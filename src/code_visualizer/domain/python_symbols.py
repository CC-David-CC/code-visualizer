"""Deterministic allocation of derived Python bindings, separate from authored names."""

from __future__ import annotations

import io
import keyword
import tokenize
from collections.abc import Iterable
from unicodedata import normalize


def python_identifiers(source: str) -> frozenset[str]:
    """Collect lexical identifiers, including loads, without treating text as code.

    Fragments may be expressions, argument lists or suites; no execution or complete
    statement context is required. String literals and comments cannot reserve names.
    Python normalizes identifiers before resolving their bindings.
    """
    names: set[str] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.NAME:
                names.add(normalize("NFKC", token.string))
    except (tokenize.TokenError, IndentationError):
        # Incomplete source remains the validation layer's responsibility. Retain
        # every identifier recognized before the incomplete token.
        pass
    return frozenset(names)


class PythonSymbolAllocator:
    """Allocate bindings against the complete visible authored-name closure.

    A caller may conservatively include descendant scopes as well as its own scope:
    generated ancestors then cannot capture a descendant's free reference, and a
    generated module dependency cannot be shadowed by an authored parameter/local.
    Generated roles share this allocator rather than maintaining separate counters.
    """

    def __init__(self, occupied: Iterable[str] = ()) -> None:
        self._occupied = {normalize("NFKC", item) for item in occupied}

    def reserve(self, identifiers: Iterable[str]) -> None:
        self._occupied.update(normalize("NFKC", item) for item in identifiers)

    def allocate(self, preferred: str) -> str:
        preferred = normalize("NFKC", preferred)
        if not preferred.isidentifier() or keyword.iskeyword(preferred):
            raise ValueError("A generated binding requires a Python identifier")
        candidate = preferred
        suffix = 2
        while candidate in self._occupied:
            candidate = f"{preferred}_{suffix}"
            suffix += 1
        self._occupied.add(candidate)
        return candidate
