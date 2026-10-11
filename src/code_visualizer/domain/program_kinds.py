"""Semantic categories shared by canonical programs and their projections."""

from enum import StrEnum


class ProgramModuleKind(StrEnum):
    MODULE = "module"
    PACKAGE = "package"


class CallableKind(StrEnum):
    SYNC = "sync"
    ASYNC = "async"
    GENERATOR = "generator"
    ASYNC_GENERATOR = "async_generator"


class ParameterKind(StrEnum):
    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"


class MethodKind(StrEnum):
    INSTANCE = "instance"
    CLASS = "class"
    STATIC = "static"


class TransferKind(StrEnum):
    RETURN = "return"
    RAISE = "raise"
    YIELD = "yield"
    YIELD_FROM = "yield_from"
    BREAK = "break"
    CONTINUE = "continue"


class SimpleKind(StrEnum):
    PASS = "pass"
    DELETE = "delete"
    GLOBAL = "global"
    NONLOCAL = "nonlocal"
    ASSERT = "assert"
    EXPRESSION = "expression"


class NotePlacement(StrEnum):
    RICH = "rich"
    LEFT = "left"
    RIGHT = "right"


class SelectMode(StrEnum):
    CONDITIONS = "conditions"
    MATCH = "match"


class LoopKind(StrEnum):
    WHILE = "while"
    DO_FIRST = "do_first"
    FOR = "for"
    ASYNC_FOR = "async_for"
    WAIT = "wait"
    TREE_DFS = "tree_dfs"
    TREE_BFS = "tree_bfs"


class ParallelMode(StrEnum):
    SYNC = "sync"
    ASYNC = "async"
