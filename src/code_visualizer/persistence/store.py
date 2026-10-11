"""Atomic native-project storage with an append-only recovery journal."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from code_visualizer.config import PRODUCT
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.project import Project
from code_visualizer.persistence.decoding import (
    ProjectDecodeError,
    project_from_data,
    project_from_json,
)
from code_visualizer.persistence.invocation import migrate_legacy_invocation_operation
from code_visualizer.persistence.serialization import normalized_project_json, project_to_data


class ProjectStoreError(RuntimeError):
    pass


MAX_PROJECT_JSON_BYTES = 64 * 1024 * 1024
MAX_JOURNAL_LINE_BYTES = 64 * 1024 * 1024
MAX_JOURNAL_TOTAL_BYTES = 128 * 1024 * 1024
MAX_RECOVERY_SNAPSHOTS = 200
MAX_RETAINED_JOURNAL_RECORDS = 2_000


@dataclass(frozen=True, slots=True)
class JournalRecord:
    revision: int
    actor_id: str
    operation_id: str
    command_type: str
    project: Project
    affected_ids: tuple[str, ...] = ()
    history_action: str = "commit"
    target_operation_id: str | None = None
    forward_type: str | None = None
    forward_payload: dict[str, JsonValue] | None = None
    inverse_type: str | None = None
    inverse_payload: dict[str, JsonValue] | None = None
    occurred_at: str = ""

    def to_data(self) -> dict[str, JsonValue]:
        return {
            "affected_ids": list(self.affected_ids),
            "actor_id": self.actor_id,
            "command_type": self.command_type,
            "forward_payload": self.forward_payload,
            "forward_type": self.forward_type,
            "history_action": self.history_action,
            "inverse_payload": self.inverse_payload,
            "inverse_type": self.inverse_type,
            "occurred_at": self.occurred_at,
            "operation_id": self.operation_id,
            "project": project_to_data(self.project),
            "revision": self.revision,
            "target_operation_id": self.target_operation_id,
        }

    @classmethod
    def from_data(cls, value: object) -> JournalRecord:
        if not isinstance(value, dict):
            raise ProjectStoreError("Journal record must be a JSON object")
        data: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProjectStoreError("Journal keys must be strings")
            data[key] = item

        def required_string(key: str) -> str:
            result = data.get(key)
            if not isinstance(result, str):
                raise ProjectStoreError(f"Journal field {key!r} must be a string")
            return result

        def optional_string(key: str) -> str | None:
            result = data.get(key)
            if result is None:
                return None
            if not isinstance(result, str):
                raise ProjectStoreError(f"Journal field {key!r} must be a string or null")
            return result

        def optional_payload(key: str) -> dict[str, JsonValue] | None:
            result = data.get(key)
            if result is None:
                return None
            if not isinstance(result, dict) or not all(
                isinstance(item_key, str) for item_key in result
            ):
                raise ProjectStoreError(f"Journal field {key!r} must be an object or null")
            payload = {str(item_key): item for item_key, item in result.items()}
            raw_project = data.get("project")
            version = raw_project.get("format_revision") if isinstance(raw_project, dict) else None
            if type(version) is int and version < 8:
                prefix = key.removesuffix("_payload")
                try:
                    payload = migrate_legacy_invocation_operation(
                        data.get(f"{prefix}_type"), payload
                    )
                except ValueError as exc:
                    raise ProjectStoreError(str(exc)) from exc
            return payload

        raw_project = data.get("project")
        version = raw_project.get("format_revision") if isinstance(raw_project, dict) else None
        migrated_program_header = False
        if type(version) is int and version < 11 and isinstance(raw_project, dict):
            from code_visualizer.persistence.program_migration import (
                migrate_legacy_module_kind_operation,
                migrate_legacy_program_operation,
            )

            for prefix in ("forward", "inverse"):
                operation_type = optional_string(f"{prefix}_type")
                operation_payload = optional_payload(f"{prefix}_payload")
                if operation_type is not None and operation_payload is not None:
                    try:
                        migrated_type, migrated_payload = (
                            migrate_legacy_program_operation(
                                operation_type,
                                operation_payload,
                                raw_project,
                            )
                            if version < 10
                            else (operation_type, operation_payload)
                        )
                        migrated_type, migrated_payload = migrate_legacy_module_kind_operation(
                            migrated_type, migrated_payload
                        )
                    except ValueError as exc:
                        raise ProjectStoreError(str(exc)) from exc
                    data[f"{prefix}_type"] = migrated_type
                    data[f"{prefix}_payload"] = migrated_payload
                    nested = migrated_payload.get("operations")
                    nested_operations = nested if isinstance(nested, list) else []
                    migrated_program_header = migrated_program_header or (
                        migrated_type == "program.configure"
                        or "program_header" in migrated_payload
                        or any(
                            isinstance(item, dict)
                            and (
                                item.get("command_type") == "program.configure"
                                or (
                                    isinstance(inner_payload := item.get("payload"), dict)
                                    and "program_header" in inner_payload
                                )
                            )
                            for item in nested_operations
                        )
                    )

        raw_revision = data.get("revision")
        if isinstance(raw_revision, bool) or not isinstance(raw_revision, int):
            raise ProjectStoreError("Journal revision must be an integer")
        raw_affected = data.get("affected_ids", [])
        if not isinstance(raw_affected, list) or not all(
            isinstance(item, str) for item in raw_affected
        ):
            raise ProjectStoreError("Journal affected_ids must be an array of strings")
        if migrated_program_header and isinstance(raw_project, dict):
            project_id = raw_project.get("project_id")
            if isinstance(project_id, str) and project_id not in raw_affected:
                raw_affected = [*raw_affected, project_id]
        return cls(
            revision=raw_revision,
            actor_id=required_string("actor_id"),
            operation_id=required_string("operation_id"),
            command_type=required_string("command_type"),
            project=project_from_data(data.get("project")),
            affected_ids=tuple(raw_affected),
            history_action=required_string("history_action"),
            target_operation_id=optional_string("target_operation_id"),
            forward_type=optional_string("forward_type"),
            forward_payload=optional_payload("forward_payload"),
            inverse_type=optional_string("inverse_type"),
            inverse_payload=optional_payload("inverse_payload"),
            occurred_at=required_string("occurred_at"),
        )


class ProjectStore:
    """Owns one explicit project directory and never writes outside it."""

    def __init__(self, root: Path, *, snapshot_interval: int = 20) -> None:
        if snapshot_interval < 1:
            raise ValueError("snapshot_interval must be positive")
        self.root = root.resolve()
        self.snapshot_interval = snapshot_interval

    @property
    def project_file(self) -> Path:
        return self.root / "project.json"

    @property
    def state_root(self) -> Path:
        return self.root / PRODUCT.state_directory

    @property
    def journal_file(self) -> Path:
        return self.state_root / "journal.jsonl"

    @property
    def snapshots_root(self) -> Path:
        return self.state_root / "snapshots"

    def initialize(self, project: Project) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.project_file.exists():
            raise FileExistsError(f"Project already exists at {self.project_file}")
        self._ensure_state_directories()
        self.save(project)
        self.write_snapshot(project)

    def save(self, project: Project) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.project_file, normalized_project_json(project))

    def load(self) -> Project:
        try:
            source = self._bounded_read(self.project_file, MAX_PROJECT_JSON_BYTES)
        except (OSError, UnicodeDecodeError) as exc:
            raise ProjectStoreError(f"Cannot read {self.project_file}: {exc}") from exc
        try:
            return project_from_json(source)
        except ProjectDecodeError as exc:
            raise ProjectStoreError(str(exc)) from exc

    def append(self, record: JournalRecord) -> None:
        self._ensure_state_directories()
        line = json.dumps(
            record.to_data(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        payload = (line + "\n").encode("utf-8")
        if len(payload) - 1 > MAX_JOURNAL_LINE_BYTES:
            raise ProjectStoreError("Project journal record exceeds the 64 MiB safety limit")
        try:
            with self.journal_file.open("a+b") as stream:
                stream.seek(0, os.SEEK_END)
                original_size = stream.tell()
                try:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                except OSError:
                    # A command is not committed until its journal record is
                    # durable. Remove a possibly buffered partial/full record
                    # so recovery cannot resurrect a command we rejected.
                    stream.truncate(original_size)
                    stream.flush()
                    with suppress(OSError):
                        os.fsync(stream.fileno())
                    raise
        except OSError as exc:
            raise ProjectStoreError(f"Cannot append project journal: {exc}") from exc

    def read_journal(self) -> tuple[JournalRecord, ...]:
        if not self.journal_file.exists():
            return ()
        try:
            source = self._bounded_read(self.journal_file, MAX_JOURNAL_TOTAL_BYTES)
        except (OSError, UnicodeDecodeError) as exc:
            raise ProjectStoreError(f"Cannot read project journal: {exc}") from exc
        lines = source.splitlines()
        records: list[JournalRecord] = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            if len(line.encode("utf-8")) > MAX_JOURNAL_LINE_BYTES:
                raise ProjectStoreError(
                    f"Journal record {index + 1} exceeds the 64 MiB safety limit"
                )
            try:
                raw: object = json.loads(
                    line,
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ProjectStoreError(f"Invalid numeric constant {value}")
                    ),
                )
                records.append(JournalRecord.from_data(raw))
            except (json.JSONDecodeError, ProjectDecodeError, ProjectStoreError) as exc:
                if index == len(lines) - 1:
                    break
                raise ProjectStoreError(f"Journal record {index + 1} is invalid: {exc}") from exc
        return tuple(records)

    def write_snapshot(self, project: Project) -> None:
        self._ensure_state_directories()
        target = self.snapshots_root / f"{project.revision:020d}.json"
        self._atomic_write(target, normalized_project_json(project))

    def record_commit(self, record: JournalRecord) -> None:
        self.append(record)
        self.save(record.project)
        if record.revision % self.snapshot_interval == 0:
            self.write_snapshot(record.project)
            self._compact_journal()

    def recover(self, *, promote: bool = True) -> Project:
        decoded_projects: dict[str, Project] = {}
        cached_source_bytes = 0

        def read_project(path: Path) -> Project:
            nonlocal cached_source_bytes
            # Always reread bounded bytes: a concurrent writer can replace even
            # project.json between its initial candidate and final revision check.
            source = self._bounded_read(path, MAX_PROJECT_JSON_BYTES)
            if source in decoded_projects:
                return decoded_projects[source]
            project = project_from_json(source)
            source_bytes = len(source.encode("utf-8"))
            # Retain at most one input envelope of source text, independently of
            # the number of snapshots. This memo lasts only for this recovery.
            if cached_source_bytes + source_bytes > MAX_PROJECT_JSON_BYTES:
                decoded_projects.clear()
                cached_source_bytes = 0
            decoded_projects[source] = project
            cached_source_bytes += source_bytes
            return project

        candidates: list[Project] = []
        if self.project_file.exists():
            with suppress(OSError, UnicodeDecodeError, ProjectDecodeError, ProjectStoreError):
                candidates.append(read_project(self.project_file))
        snapshots = (
            sorted(self.snapshots_root.glob("*.json"))[-MAX_RECOVERY_SNAPSHOTS:]
            if self.snapshots_root.exists()
            else ()
        )
        for snapshot in snapshots:
            try:
                candidates.append(read_project(snapshot))
            except (OSError, UnicodeDecodeError, ProjectDecodeError, ProjectStoreError):
                continue
        candidates.extend(record.project for record in self.read_journal())
        if not candidates:
            raise ProjectStoreError(f"No recoverable project exists in {self.root}")
        project_ids = {project.id for project in candidates}
        if len(project_ids) != 1:
            raise ProjectStoreError("Recovery data contains more than one project identity")
        latest = max(candidates, key=lambda project: project.revision)
        durable_revision = -1
        if self.project_file.exists():
            with suppress(OSError, UnicodeDecodeError, ProjectDecodeError, ProjectStoreError):
                durable_revision = read_project(self.project_file).revision
        if promote and durable_revision < latest.revision:
            self.save(latest)
        return latest

    def _ensure_state_directories(self) -> None:
        self.snapshots_root.mkdir(parents=True, exist_ok=True)

    def _compact_journal(self) -> None:
        records = self.read_journal()
        retained = records[-MAX_RETAINED_JOURNAL_RECORDS:]
        content = "".join(
            json.dumps(
                record.to_data(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
            for record in retained
        )
        self._atomic_write(
            self.journal_file,
            content,
            max_bytes=MAX_JOURNAL_TOTAL_BYTES,
        )

    @staticmethod
    def _bounded_read(path: Path, limit: int) -> str:
        with path.open("rb") as stream:
            source = stream.read(limit + 1)
        if len(source) > limit:
            raise ProjectStoreError(f"{path.name} exceeds its {limit}-byte safety limit")
        return source.decode("utf-8")

    def _atomic_write(
        self,
        target: Path,
        content: str,
        *,
        max_bytes: int = MAX_PROJECT_JSON_BYTES,
    ) -> None:
        if len(content.encode("utf-8")) > max_bytes:
            raise ProjectStoreError(f"{target.name} exceeds its {max_bytes}-byte safety limit")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink()
            raise ProjectStoreError(f"Cannot atomically write {target}: {exc}") from exc
