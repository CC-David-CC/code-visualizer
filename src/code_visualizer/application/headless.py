"""Headless composition root for a project authority and native store."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.program_model import canonicalize_project
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.application.session import ProjectSession
from code_visualizer.persistence import ProjectLease, ProjectStore
from code_visualizer.sdk.client import CodeVisualizerClient


@dataclass(slots=True)
class HeadlessService:
    store: ProjectStore
    authority: ProjectAuthority
    lease: ProjectLease | None = None
    session: ProjectSession | None = None

    @classmethod
    def create(cls, root: Path, *, title: str = "Untitled Project") -> HeadlessService:
        store = ProjectStore(root)
        lease = ProjectLease.acquire(store.root, owner_id="headless")
        try:
            project = canonicalize_project(create_default_project(title=title))
            store.initialize(project)
            authority = ProjectAuthority(project, store=store)
            session = ProjectSession(
                authority,
                CodeVisualizerClient(authority, actor_id="headless"),
                store.root,
                project.revision,
                lease,
            )
            return cls(store, authority, lease, session)
        except BaseException:
            lease.release()
            raise

    @classmethod
    def open(cls, root: Path, *, read_only: bool = False) -> HeadlessService:
        session = ProjectSession.open(root, actor_id="headless", read_only=read_only)
        return cls(ProjectStore(root), session.authority, session.lease, session)

    def client(self, actor_id: str) -> CodeVisualizerClient:
        return CodeVisualizerClient(self.authority, actor_id=actor_id)

    def close(self) -> None:
        if self.session is not None:
            self.session.close()
            self.session = None
            self.lease = None
        if self.lease is not None:
            self.lease.release()
            self.lease = None

    def update_authority_endpoint(self, endpoint: str | None) -> None:
        if self.session is not None:
            self.session.update_authority_endpoint(endpoint)
            return
        if self.lease is not None:
            self.lease.update_endpoint(endpoint)

    def __del__(self) -> None:
        self.close()
