"""Author-owned semantic concepts and non-executable relationships.

These values preserve programmer intent that ordinary Python cannot conveniently
express.  They may describe and organize executable objects, but they never become a
second control-flow truth or emit Python by themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AuthoredRelationKind(StrEnum):
    ASSOCIATES = "associates"
    DEPENDS_ON = "depends_on"
    EXPLAINS = "explains"
    IMPLEMENTS = "implements"
    COMMUNICATES_WITH = "communicates_with"
    PRECEDES_CONCEPTUALLY = "precedes_conceptually"


@dataclass(frozen=True, slots=True)
class SemanticConcept:
    id: str
    title: str
    description: str = ""
    member_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AuthoredSemanticRelation:
    id: str
    source_id: str
    target_id: str
    kind: AuthoredRelationKind = AuthoredRelationKind.ASSOCIATES
    label: str = ""
    description: str = ""
