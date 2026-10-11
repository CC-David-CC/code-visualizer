"""Real Git operations over a saved project, with explicit path and review boundaries."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from uuid import uuid4

from code_visualizer.config import PRODUCT
from code_visualizer.domain.project import Project
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.store import MAX_PROJECT_JSON_BYTES, ProjectStore
from code_visualizer.validation import Severity, validate_integrity


class GitError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class GitFile:
    path: str
    index: str
    worktree: str
    original_path: str | None = None
    in_project: bool = True

    @property
    def conflicted(self) -> bool:
        return "U" in self.index + self.worktree or self.index + self.worktree in {"AA", "DD"}

    @property
    def staged(self) -> bool:
        return self.index not in {" ", "?", "!"}


@dataclass(frozen=True, slots=True)
class GitStatus:
    root: str
    project_prefix: str
    branch: str
    head: str
    index_fingerprint: str
    files: tuple[GitFile, ...]
    merging: bool = False


@dataclass(frozen=True, slots=True)
class GitDiffLine:
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class GitDiff:
    path: str
    staged: bool
    patch: str
    lines: tuple[GitDiffLine, ...]


@dataclass(frozen=True, slots=True)
class GitCommit:
    oid: str
    parents: tuple[str, ...]
    author: str
    timestamp: str
    subject: str


@dataclass(frozen=True, slots=True)
class GitBranch:
    name: str
    oid: str
    current: bool
    upstream: str = ""


@dataclass(frozen=True, slots=True)
class GitRemote:
    name: str
    fetch_url: str
    push_url: str


@dataclass(frozen=True, slots=True)
class GitConflict:
    path: str
    base: str
    ours: str
    theirs: str
    working: str


@dataclass(frozen=True, slots=True)
class GitOperationResult:
    operation: str
    message: str
    head: str
    conflicts: tuple[str, ...] = ()
    reload_required: bool = False


@dataclass(frozen=True, slots=True)
class GitExpectedState:
    """Includes the physical index: experiment capture must not consume staged work."""

    head: str
    symbolic_head: str
    index_digest: str


def git_available() -> bool:
    return shutil.which("git") is not None


def has_git_ancestor(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in (path, *path.parents))


def validate_git_project(source: str) -> Project:
    """Git's text merge result must satisfy native integrity before model admission."""
    if len(source.encode("utf-8")) > MAX_PROJECT_JSON_BYTES:
        raise GitError("GIT_PROJECT_SIZE", "Project JSON exceeds the native size limit")
    try:
        project = project_from_json(source)
    except ValueError as exc:
        raise GitError(
            "GIT_PROJECT_INVALID", f"Git working tree is not a valid project: {exc}"
        ) from exc
    errors = tuple(item for item in validate_integrity(project) if item.severity is Severity.ERROR)
    if errors:
        raise GitError("GIT_PROJECT_INVALID", f"{errors[0].code}: {errors[0].message}")
    return project


class GitRepository:
    """An argv-only Git adapter. Git owns history, branches, merges, and its index."""

    def __init__(self, project_root: Path, *, executable: str | None = None) -> None:
        self.project_root = project_root.resolve()
        self.executable = executable or shutil.which("git") or ""
        if not self.executable:
            raise GitError(
                "GIT_UNAVAILABLE", "Install Git and make its executable available on PATH"
            )
        self.root = self.project_root
        # Repository layout is fixed for this adapter, while refs and index
        # contents are read afresh at every transaction boundary. Discover the
        # paths together so repeated admission checks do not launch Git just
        # to rediscover the same physical index location.
        result = self._run(
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--git-path",
            "HEAD",
            "--git-path",
            "index",
            "--git-common-dir",
            check=False,
        )
        if result.returncode:
            raise GitError("GIT_NOT_REPOSITORY", "The saved project is not inside a Git repository")
        paths = self._text(result.stdout).splitlines()
        if len(paths) != 4 or any(not Path(value).is_absolute() for value in paths):
            raise GitError("GIT_LAYOUT", "Git did not return an unambiguous repository layout")
        self.root, self._head_file, self._index_file, self._common_directory = (
            Path(value).resolve() for value in paths
        )
        if not self.project_root.is_relative_to(self.root):
            raise GitError("GIT_SCOPE", "Git returned a repository outside the project ancestry")
        self.prefix = self.project_root.relative_to(self.root).as_posix()
        if self.prefix == ".":
            self.prefix = ""
        self.project_path = self._relative("project.json")
        self.state_prefix = self._relative(PRODUCT.state_directory)

    @classmethod
    def initialize(cls, project_root: Path) -> GitRepository:
        root = project_root.resolve()
        if has_git_ancestor(root):
            raise GitError(
                "GIT_ALREADY_REPOSITORY", "This project already belongs to a Git repository"
            )
        if not (root / "project.json").is_file():
            raise GitError("GIT_SAVE_REQUIRED", "Save the project before initializing Git")
        executable = shutil.which("git")
        if executable is None:
            raise GitError("GIT_UNAVAILABLE", "Git is not available on PATH")
        result = subprocess.run(
            [executable, "init", "--", str(root)],
            capture_output=True,
            timeout=30,
            creationflags=_creation_flags(),
            check=False,
        )
        if result.returncode:
            raise GitError("GIT_FAILED", result.stderr.decode("utf-8", errors="replace"))
        repository = cls(root, executable=executable)
        # This newly created repository has no existing exclude policy to replace.
        exclude = root / ".git" / "info" / "exclude"
        with exclude.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                "\n# Local Code Visualizer recovery and session state\n"
                f"/{PRODUCT.state_directory}/\n"
            )
        return repository

    @staticmethod
    def _text(value: bytes) -> str:
        return value.decode("utf-8", errors="replace")

    def _run(
        self,
        *arguments: str,
        input_text: str | None = None,
        input_bytes: bytes | None = None,
        environment_overrides: dict[str, str] | None = None,
        working_directory: Path | None = None,
        output_limit: int = 16 * 1024 * 1024,
        check: bool = True,
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[bytes]:
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_LITERAL_PATHSPECS": "1",
                "GIT_MERGE_AUTOEDIT": "no",
                "GIT_PAGER": "cat",
            }
        )
        if environment_overrides is not None:
            environment.update(environment_overrides)
        if input_text is not None and input_bytes is not None:
            raise ValueError("Git accepts one input encoding")
        try:
            with TemporaryFile() as output, TemporaryFile() as error:
                completed = subprocess.run(
                    [
                        self.executable,
                        "--no-pager",
                        "--no-optional-locks",
                        *(["-c", "core.longpaths=true"] if os.name == "nt" else []),
                        "-C",
                        str(working_directory or self.root),
                        *arguments,
                    ],
                    input=input_text.encode("utf-8") if input_text is not None else input_bytes,
                    stdout=output,
                    stderr=error,
                    timeout=timeout,
                    env=environment,
                    creationflags=_creation_flags(),
                    check=False,
                )
                output.seek(0)
                error.seek(0)
                result = subprocess.CompletedProcess(
                    completed.args,
                    completed.returncode,
                    output.read(output_limit + 1),
                    error.read(output_limit + 1),
                )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitError("GIT_PROCESS", str(exc)) from exc
        if len(result.stdout) + len(result.stderr) > output_limit:
            raise GitError("GIT_OUTPUT_SIZE", "Git output exceeds its bounded inspection limit")
        if check and result.returncode:
            detail = self._text(result.stderr or result.stdout).strip()
            raise GitError("GIT_FAILED", detail or f"Git returned {result.returncode}")
        return result

    @property
    def common_directory(self) -> Path:
        return self._common_directory

    def expected_state(self) -> GitExpectedState:
        index = self._index_file
        return GitExpectedState(
            self.head(),
            self._text(self._run("symbolic-ref", "-q", "HEAD", check=False).stdout).strip(),
            hashlib.sha256(index.read_bytes() if index.exists() else b"").hexdigest(),
        )

    def require_state(self, expected: GitExpectedState) -> None:
        if self.expected_state() != expected:
            raise GitError("GIT_EXPERIMENT_CONFLICT", "Git HEAD or index changed during capture")

    def input_commit(self, files: tuple[tuple[str, bytes], ...], *, parent: str) -> str:
        """Create an exact tree through Git plumbing without touching the user's index."""
        if not files or len(files) > 1002:
            raise GitError("GIT_INPUT_CLOSURE", "Input closure requires 1 to 1002 files")
        names = [path.casefold() for path, _ in files]
        if len(names) != len(set(names)):
            raise GitError("GIT_INPUT_CLOSURE", "Input paths must be unique on every platform")
        for path, _ in files:
            self.input_path(path)
        with TemporaryDirectory(prefix="cv-git-index-") as temporary:
            environment = {"GIT_INDEX_FILE": str(Path(temporary) / "index")}
            self._run("read-tree", "--empty", environment_overrides=environment)
            for path, payload in sorted(files):
                oid = self._text(
                    self._run("hash-object", "-w", "--stdin", input_bytes=payload).stdout
                ).strip()
                self._run(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    "100644",
                    oid,
                    path,
                    environment_overrides=environment,
                )
            tree = self._text(
                self._run("write-tree", environment_overrides=environment).stdout
            ).strip()
            environment.update(
                {
                    "GIT_AUTHOR_NAME": "Code Visualizer",
                    "GIT_AUTHOR_EMAIL": "local@code-visualizer.invalid",
                    "GIT_COMMITTER_NAME": "Code Visualizer",
                    "GIT_COMMITTER_EMAIL": "local@code-visualizer.invalid",
                }
            )
            parents = ("-p", parent) if parent else ()
            return self._text(
                self._run(
                    "commit-tree",
                    tree,
                    *parents,
                    input_text="Freeze declared computation inputs\n",
                    environment_overrides=environment,
                ).stdout
            ).strip()

    @staticmethod
    def input_path(path: str) -> str:
        # Git paths are portable slash-separated names, not shell/path expressions.
        parts = path.split("/")
        if (
            not path
            or "\\" in path
            or ":" in path
            or any(ord(c) < 32 for c in path)
            or any(
                part in {"", ".", ".."} or part.casefold() == ".git" or part.rstrip(" .") != part
                for part in parts
            )
        ):
            raise GitError("GIT_INPUT_PATH", "Inputs require portable repository-relative paths")
        return path

    def retain_ref(self, reference: str, commit: str, *, expected: str = "") -> None:
        self._common_run("check-ref-format", reference)
        self._common_run("update-ref", reference, commit, expected or "0" * len(commit))

    def resolve_ref(self, reference: str) -> str:
        self._common_run("check-ref-format", reference)
        return self._text(self._common_run("rev-parse", "--verify", reference).stdout).strip()

    def _common_run(self, *arguments: str) -> subprocess.CompletedProcess[bytes]:
        """Shared refs/objects must outlive the editor worktree which discovered Git."""
        return self._run(
            "--git-dir",
            str(self.common_directory),
            *arguments,
            working_directory=self.common_directory,
            output_limit=MAX_PROJECT_JSON_BYTES,
        )

    def add_input_worktree(self, path: Path, branch: str, commit: str) -> None:
        self._common_run(
            "-c", "core.autocrlf=false", "worktree", "add", "-b", branch, "--", str(path), commit
        )

    def inspect_input_worktree(self, path: Path, commit: str) -> None:
        self._common_run(
            "-c", "core.autocrlf=false", "worktree", "add", "--detach", "--", str(path), commit
        )

    def remove_input_worktree(self, path: Path, exclude_file: Path) -> None:
        # Caller verifies registered ownership and inactivity. Git still refuses
        # dirty work; no --force and no recursive filesystem substitute for Git.
        self._common_run(
            "-c", f"core.excludesFile={exclude_file}", "worktree", "remove", "--", str(path)
        )

    def read_input(self, commit: str, path: str) -> bytes:
        self.input_path(path)
        if not commit or any(c not in "0123456789abcdef" for c in commit):
            raise GitError("GIT_INPUT_COMMIT", "An input requires a full Git object identity")
        # cat-file has an unambiguous object argument. `show` also probes the
        # argument as a worktree filename, including on Windows MAX_PATH paths.
        return self._common_run("cat-file", "blob", f"{commit}:{path}").stdout

    def _relative(self, filename: str) -> str:
        return f"{self.prefix}/{filename}" if self.prefix else filename

    def _internal(self, path: str) -> bool:
        return path == self.state_prefix or path.startswith(self.state_prefix + "/")

    def _in_project(self, path: str) -> bool:
        return (not self.prefix or path.startswith(self.prefix + "/")) and not self._internal(path)

    def _path(self, path: str) -> Path:
        if not path or "\0" in path or Path(path).is_absolute() or ".." in Path(path).parts:
            raise GitError("GIT_PATH", "Choose a relative project file")
        resolved = (self.root / path).resolve()
        if not resolved.is_relative_to(self.project_root) or resolved.is_relative_to(
            (self.project_root / PRODUCT.state_directory).resolve()
        ):
            raise GitError(
                "GIT_SCOPE", "Git file edits are limited to the project, excluding local state"
            )
        if any(part.casefold() == ".git" for part in Path(path).parts) or resolved.is_dir():
            raise GitError(
                "GIT_PATH", "Select individual project files, not directories or Git state"
            )
        return resolved

    def _paths(self, paths: tuple[str, ...]) -> tuple[str, ...]:
        if not paths or len(paths) > 1000:
            raise GitError("GIT_PATH", "Select between one and 1000 project files")
        for path in paths:
            self._path(path)
        return tuple(dict.fromkeys(paths))

    def head(self) -> str:
        result = self._run("rev-parse", "--verify", "HEAD", check=False)
        return self._text(result.stdout).strip() if result.returncode == 0 else ""

    def head_token(self) -> tuple[bytes, bytes, int, int]:
        """Cheap change detector; Git remains the resolver when references change."""
        head = self._head_file.read_bytes()
        loose = b""
        if head.startswith(b"ref: "):
            reference = head[5:].decode("utf-8").strip()
            path = (self._common_directory / reference).resolve()
            if path.is_relative_to(self._common_directory) and path.is_file():
                loose = path.read_bytes()
        packed = self._common_directory / "packed-refs"
        stat = packed.stat() if packed.exists() else None
        return head, loose, stat.st_mtime_ns if stat else 0, stat.st_size if stat else 0

    def status(self) -> GitStatus:
        result = self._run("status", "--porcelain=v1", "-z", "--untracked-files=all")
        records = self._text(result.stdout).split("\0")
        files: list[GitFile] = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            if len(record) < 4:
                raise GitError("GIT_STATUS", "Git returned an invalid status record")
            staged, working, path = record[0], record[1], record[3:]
            original = None
            if staged in {"R", "C"} or working in {"R", "C"}:
                if index >= len(records):
                    raise GitError("GIT_STATUS", "Git returned an incomplete rename record")
                original = records[index]
                index += 1
            if self._internal(path) and staged == "?":
                continue
            files.append(
                GitFile(
                    path,
                    staged,
                    working,
                    original,
                    self._in_project(path) and (original is None or self._in_project(original)),
                )
            )
        head_contents = self._head_file.read_text(encoding="utf-8").strip()
        branch = (
            head_contents.removeprefix("ref: refs/heads/")
            if head_contents.startswith("ref: refs/heads/")
            else "(detached)"
        )
        fingerprint = hashlib.sha256(self._run("ls-files", "--stage", "-z").stdout).hexdigest()
        return GitStatus(
            str(self.root),
            self.prefix,
            branch,
            self.head(),
            fingerprint,
            tuple(files),
            (self._head_file.parent / "MERGE_HEAD").exists(),
        )

    def diff(self, path: str, *, staged: bool = False) -> GitDiff:
        target = self._path(path)
        arguments = ["diff", "--no-ext-diff", "--no-textconv", "--unified=3"]
        if staged:
            arguments.append("--cached")
        patch = self._text(self._run(*arguments, "--", path).stdout)
        if not staged and not patch and target.is_file():
            tracked = self._run("ls-files", "--error-unmatch", "--", path, check=False)
            if tracked.returncode:
                contents = self._read_text(target)
                patch = "".join(
                    difflib.unified_diff(
                        [], contents.splitlines(keepends=True), fromfile="/dev/null", tofile=path
                    )
                )
        lines = tuple(
            GitDiffLine(
                "added"
                if line.startswith("+") and not line.startswith("+++")
                else "removed"
                if line.startswith("-") and not line.startswith("---")
                else "hunk"
                if line.startswith("@@")
                else "context",
                line,
            )
            for line in patch.splitlines()
        )
        return GitDiff(path, staged, patch, lines)

    @staticmethod
    def _read_text(path: Path) -> str:
        with path.open("rb") as stream:
            value = stream.read(2 * 1024 * 1024 + 1)
        if len(value) > 2 * 1024 * 1024:
            raise GitError("GIT_FILE_SIZE", "File is too large for the text review panel")
        if b"\0" in value:
            raise GitError("GIT_BINARY", "This file is binary; review it with an external Git tool")
        return value.decode("utf-8", errors="replace")

    def history(self, *, limit: int = 50) -> tuple[GitCommit, ...]:
        if not 1 <= limit <= 500:
            raise GitError("GIT_LIMIT", "History limit must be between one and 500")
        if not self.head():
            return ()
        output = self._text(
            self._run(
                "log",
                f"--max-count={limit}",
                "--date=iso-strict",
                "--format=%H%x00%P%x00%an%x00%aI%x00%s%x00",
            ).stdout
        )
        values = output.split("\0")
        return tuple(
            GitCommit(
                values[index].strip(),
                tuple(values[index + 1].split()),
                values[index + 2],
                values[index + 3],
                values[index + 4],
            )
            for index in range(0, len(values) - 1, 5)
            if index + 4 < len(values)
        )

    def branches(self) -> tuple[GitBranch, ...]:
        output = self._text(
            self._run(
                "for-each-ref",
                "--sort=refname",
                "--format=%(refname:short)%00%(objectname)%00%(HEAD)%00%(upstream:short)",
                "refs/heads",
            ).stdout
        )
        return tuple(
            GitBranch(parts[0], parts[1], parts[2] == "*", parts[3])
            for line in output.splitlines()
            if len(parts := line.split("\0")) == 4
        )

    def remotes(self) -> tuple[GitRemote, ...]:
        names = self._text(self._run("remote").stdout).splitlines()
        return tuple(
            GitRemote(
                name,
                self._text(self._run("remote", "get-url", name).stdout).strip(),
                self._text(self._run("remote", "get-url", "--push", name).stdout).strip(),
            )
            for name in names
        )

    def add_remote(self, name: str, url: str) -> GitOperationResult:
        if not name or name.startswith("-") or any(character.isspace() for character in name):
            raise GitError("GIT_REMOTE", "Supply a remote name without spaces or option prefixes")
        if not url or url.startswith("-") or "\0" in url or "\n" in url:
            raise GitError("GIT_REMOTE", "Supply a remote URL or repository path")
        self._run("remote", "add", name, url)
        return GitOperationResult("add_remote", f"Configured remote {name}", self.head())

    def commit_diff(self, oid: str) -> str:
        if not 40 <= len(oid) <= 64 or any(
            character not in "0123456789abcdef" for character in oid
        ):
            raise GitError("GIT_COMMIT", "Choose a full commit identity from history")
        return self._text(
            self._run(
                "show",
                "--no-ext-diff",
                "--no-textconv",
                "--format=fuller",
                oid,
                "--",
                self.prefix or ".",
            ).stdout
        )

    def _branch(self, name: str, *, existing: bool = False) -> str:
        if not name or name.startswith("-") or "\0" in name:
            raise GitError("GIT_BRANCH", "Choose a valid branch name")
        self._run("check-ref-format", "--branch", name)
        if existing and name not in {branch.name for branch in self.branches()}:
            raise GitError("GIT_BRANCH", "Choose an existing local branch")
        return name

    def _remote(self, name: str) -> str:
        if name not in {remote.name for remote in self.remotes()}:
            raise GitError("GIT_REMOTE", "Choose a configured remote")
        return name

    def ensure_head(self, expected_head: str) -> None:
        if self.head() != expected_head:
            raise GitError(
                "GIT_HEAD_CHANGED", "Git HEAD changed; refresh the review before proceeding"
            )

    def ensure_clean(self) -> None:
        status = self.status()
        if status.files or status.merging:
            raise GitError(
                "GIT_DIRTY",
                "Commit or resolve repository changes before changing branches or merging",
            )

    def ensure_untracked_recovery(self, *, target: str | None = None) -> None:
        tracked = self._run("ls-files", "--", self.state_prefix).stdout
        if target is not None:
            tracked += self._run(
                "ls-tree", "-r", "--name-only", target, "--", self.state_prefix
            ).stdout
        if tracked:
            raise GitError(
                "GIT_TRACKED_RECOVERY",
                "Local recovery state is tracked by Git; "
                "untrack it explicitly before branch operations",
            )

    def stage(self, paths: tuple[str, ...]) -> GitOperationResult:
        selected = self._paths(paths)
        if self.project_path in selected and (self.root / self.project_path).exists():
            validate_git_project((self.root / self.project_path).read_text(encoding="utf-8"))
        self._run("add", "--", *selected)
        return GitOperationResult("stage", "Selected files staged", self.head())

    def unstage(self, paths: tuple[str, ...]) -> GitOperationResult:
        selected = self._paths(paths)
        if self.head():
            self._run("restore", "--staged", "--", *selected)
        else:
            self._run("rm", "--cached", "--ignore-unmatch", "--", *selected)
        return GitOperationResult(
            "unstage", "Selected files unstaged; working files preserved", self.head()
        )

    def commit(self, message: str, *, expected_index: str) -> GitOperationResult:
        if not message.strip() or len(message) > 100_000:
            raise GitError("GIT_MESSAGE", "Supply a commit message under 100000 characters")
        status = self.status()
        if status.index_fingerprint != expected_index:
            raise GitError("GIT_INDEX_CHANGED", "The staged files changed; refresh the staged diff")
        if any(item.conflicted for item in status.files):
            raise GitError("GIT_CONFLICT", "Resolve every Git conflict before committing")
        staged = tuple(item for item in status.files if item.staged)
        if any(not item.in_project for item in staged):
            raise GitError(
                "GIT_SCOPE",
                "The index contains changes outside this project; commit them separately",
            )
        if not staged and not status.merging:
            raise GitError("GIT_NOTHING_STAGED", "Stage the files you intend to commit")
        indexed = self._run("show", f":{self.project_path}", check=False)
        if indexed.returncode == 0:
            validate_git_project(self._text(indexed.stdout))
        else:
            raise GitError(
                "GIT_PROJECT_REQUIRED", "A project commit must retain a valid project.json"
            )
        result = self._run("commit", "--file=-", input_text=message)
        return GitOperationResult("commit", self._text(result.stdout).strip(), self.head())

    def create_branch(self, name: str) -> GitOperationResult:
        self._run("branch", self._branch(name), "HEAD")
        return GitOperationResult("branch", f"Created branch {name}", self.head())

    def switch(self, name: str) -> GitOperationResult:
        branch = self._branch(name, existing=True)
        self.ensure_clean()
        self.ensure_untracked_recovery(target=branch)
        self._run("switch", branch)
        return GitOperationResult(
            "switch", f"Switched to {branch}", self.head(), reload_required=True
        )

    def merge(self, name: str) -> GitOperationResult:
        branch = self._branch(name, existing=True)
        self.ensure_clean()
        self.ensure_untracked_recovery(target=branch)
        result = self._run("merge", "--no-ff", "--no-commit", branch, check=False)
        conflicts = tuple(item.path for item in self.status().files if item.conflicted)
        if result.returncode and not conflicts:
            raise GitError("GIT_FAILED", self._text(result.stderr or result.stdout).strip())
        return GitOperationResult(
            "merge",
            self._text(result.stdout or result.stderr).strip(),
            self.head(),
            conflicts,
            True,
        )

    def abort_merge(self) -> GitOperationResult:
        if not self.status().merging:
            raise GitError("GIT_NO_MERGE", "There is no Git merge to abort")
        self._run("merge", "--abort")
        return GitOperationResult(
            "abort_merge", "Merge aborted by Git", self.head(), reload_required=True
        )

    def conflict(self, path: str) -> GitConflict:
        target = self._path(path)
        if path not in {item.path for item in self.status().files if item.conflicted}:
            raise GitError("GIT_CONFLICT", "This file has no unresolved Git conflict")
        versions = [
            self._text(self._run("show", f":{stage}:{path}", check=False).stdout)
            for stage in (1, 2, 3)
        ]
        return GitConflict(
            path,
            versions[0],
            versions[1],
            versions[2],
            self._read_text(target) if target.exists() else "",
        )

    def resolve_conflict(
        self, path: str, choice: str, *, text: str | None = None
    ) -> GitOperationResult:
        conflict = self.conflict(path)
        if choice not in {"ours", "theirs", "edited", "delete"}:
            raise GitError("GIT_RESOLUTION", "Choose ours, theirs, edited, or delete")
        if choice == "delete":
            if path == self.project_path:
                raise GitError("GIT_PROJECT_REQUIRED", "The open project must retain project.json")
            self._path(path).unlink(missing_ok=True)
            return self.stage((path,))
        content = (
            conflict.ours if choice == "ours" else conflict.theirs if choice == "theirs" else text
        )
        if content is None:
            raise GitError("GIT_RESOLUTION", "Supply the edited merge result")
        if path == self.project_path:
            validate_git_project(content)
        target = self._path(path)
        target.write_text(content, encoding="utf-8", newline="\n")
        return self.stage((path,))

    def fetch(self, remote: str) -> GitOperationResult:
        result = self._run("fetch", self._remote(remote), timeout=120)
        return GitOperationResult(
            "fetch",
            self._text(result.stdout or result.stderr).strip() or "Fetch complete",
            self.head(),
        )

    def pull(self, remote: str, branch: str) -> GitOperationResult:
        self.ensure_clean()
        self.ensure_untracked_recovery()
        self._run("fetch", self._remote(remote), self._branch(branch), timeout=120)
        self.ensure_untracked_recovery(target="FETCH_HEAD")
        result = self._run("merge", "--ff-only", "FETCH_HEAD", timeout=120)
        return GitOperationResult(
            "pull",
            self._text(result.stdout or result.stderr).strip(),
            self.head(),
            reload_required=True,
        )

    def push(self, remote: str, branch: str) -> GitOperationResult:
        local = self._branch(branch, existing=True)
        result = self._run(
            "push", self._remote(remote), f"refs/heads/{local}:refs/heads/{local}", timeout=120
        )
        return GitOperationResult(
            "push",
            self._text(result.stdout or result.stderr).strip() or "Push complete",
            self.head(),
        )

    def load_project(self) -> Project:
        if any(item.conflicted for item in self.status().files):
            raise GitError("GIT_CONFLICT", "Resolve Git conflicts before loading their model")
        path = self.project_root / "project.json"
        with path.open("rb") as stream:
            content = stream.read(MAX_PROJECT_JSON_BYTES + 1)
        if len(content) > MAX_PROJECT_JSON_BYTES:
            raise GitError("GIT_PROJECT_SIZE", "Project JSON exceeds the native size limit")
        return validate_git_project(content.decode("utf-8"))

    def require_saved(self, project: Project) -> None:
        saved = ProjectStore(self.project_root).load()
        if saved != project:
            raise GitError(
                "GIT_SAVE_REQUIRED",
                "Save the displayed project revision before changing the Git working tree",
            )

    def tracks_project(self) -> bool:
        return (
            self._run(
                "ls-files", "--error-unmatch", "--", self.project_path, check=False
            ).returncode
            == 0
        )


def _creation_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def archive_git_recovery(repository: GitRepository) -> None:
    """Retain old local undo history without letting it resurrect another Git branch."""
    repository.ensure_untracked_recovery()
    store = ProjectStore(repository.project_root)
    state = store.state_root.resolve()
    if not state.is_relative_to(repository.project_root) or store.state_root.is_symlink():
        raise GitError("GIT_STATE_PATH", "Local recovery state must stay inside the project")
    candidates = (store.journal_file, store.snapshots_root)
    for candidate in candidates:
        if not candidate.resolve().is_relative_to(state) or candidate.is_symlink():
            raise GitError("GIT_STATE_PATH", "Recovery history contains a redirected path")
    destination = state / "git-history" / uuid4().hex
    if not destination.resolve().is_relative_to(state):
        raise GitError("GIT_STATE_PATH", "Recovery archive must stay inside local state")
    present = tuple(item for item in candidates if item.exists())
    if present:
        destination.mkdir(parents=True)
        for candidate in present:
            candidate.rename(destination / candidate.name)


def git_checkpoint(repository: GitRepository, *, prepare: bool = False) -> None:
    """A host checkpoint distinguishes local recovery from a checked-out Git revision."""
    store = ProjectStore(repository.project_root)
    path = store.state_root / "git-checkpoint.json"
    repository.ensure_untracked_recovery()
    if prepare and first_untracked_adoption(repository):
        # Git has never owned this native file; retain ordinary journal recovery.
        # The session records its first checkpoint after that recovery is published.
        return
    if not path.resolve().is_relative_to(repository.project_root):
        raise GitError("GIT_STATE_PATH", "Git checkpoint must stay inside the project")
    head = repository.head()
    current = _git_checkpoint_data(repository, head)
    previous: object = None
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            previous = None
    if prepare and previous != current:
        repository.load_project()
        archive_git_recovery(repository)
    record_git_checkpoint(repository, head)


def _git_checkpoint_data(repository: GitRepository, head: str) -> dict[str, str]:
    with (repository.project_root / "project.json").open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"head": head, "project_digest": digest}


def record_git_checkpoint(repository: GitRepository, head: str) -> None:
    """Record a successfully published native file without accepting an external restore."""
    path = ProjectStore(repository.project_root).state_root / "git-checkpoint.json"
    if not path.resolve().is_relative_to(repository.project_root):
        raise GitError("GIT_STATE_PATH", "Git checkpoint must stay inside the project")
    data = _git_checkpoint_data(repository, head)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".git-checkpoint-{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(data, sort_keys=True))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def first_untracked_adoption(repository: GitRepository) -> bool:
    """An ancestor repository does not supersede an untracked project's recovery journal."""
    checkpoint = ProjectStore(repository.project_root).state_root / "git-checkpoint.json"
    return not checkpoint.exists() and not repository.tracks_project()
