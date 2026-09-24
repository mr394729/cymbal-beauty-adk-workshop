"""SELECT-only guard applied to every raw SQL statement, on every backend, before it runs.

The guard is deterministic code, not a prompt. It rejects multi-statement input, anything that is
not a SELECT/WITH query, a deny-list of statement keywords, INFORMATION_SCHEMA (metadata goes
through the metadata tools), and any table reference outside the allowed prefix.
"""
from __future__ import annotations

import re

DENY = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE", "GRANT", "REVOKE",
    "COPY", "SET", "USE", "CALL", "REFRESH", "OPTIMIZE", "VACUUM", "DECLARE", "BEGIN", "EXECUTE",
    "EXPLAIN", "DESCRIBE", "SHOW", "LOAD", "EXPORT", "IMPORT",
}
_COMMENT = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.S)
_STRING = re.compile(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")")
_QUALIFIED = re.compile(r"`?\b([A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z_][A-Za-z0-9_\-]*){1,2})\b`?")  # dataset.table or project.dataset.table, anywhere


class SqlGuardError(ValueError):
    """Raised when a statement is not a read-only query inside the allowed dataset."""


def assert_select_only(sql: str, allowed_prefixes: tuple[str, ...] | list[str]) -> str:
    """Return the statement if it is a single read-only query on allowed tables; raise otherwise."""
    if not sql or not sql.strip():
        raise SqlGuardError("empty statement")
    stripped = _STRING.sub("''", _COMMENT.sub(" ", sql)).strip().rstrip(";").strip()
    if ";" in stripped:
        raise SqlGuardError("multiple statements are not allowed")
    first = re.split(r"\s+", stripped, maxsplit=1)[0].upper()
    if first not in ("SELECT", "WITH"):
        raise SqlGuardError(f"only SELECT/WITH queries are allowed (statement starts with {first})")
    words = {w.upper() for w in re.findall(r"[A-Za-z_]+", stripped)}
    hit = sorted(words & DENY)
    if hit:
        raise SqlGuardError(f"statement contains disallowed keyword(s): {', '.join(hit)}")
    if "INFORMATION_SCHEMA" in stripped.upper():
        raise SqlGuardError("INFORMATION_SCHEMA is not queryable here; use the metadata tools")
    if {"ASSOCIATES", "COACHING_SIGNALS", "OPERATIONS_CONTEXT"} & {w.upper() for w in re.findall(r"[A-Za-z_]+", stripped)}:
        raise SqlGuardError("people data (associates, coaching signals) is not available to raw SQL; use the domain tools")
    prefixes = tuple(p.rstrip(".") for p in allowed_prefixes)
    bare = stripped.replace("`", "")
    in_from = {m.group(1) for m in re.finditer(r"(?:\bFROM|\bJOIN|,)\s+([A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z_][A-Za-z0-9_\-]*){1,2})\b", bare, re.I)}
    for ref in _QUALIFIED.findall(bare):
        if ref not in in_from and ref.count(".") == 1 and ref.split(".")[0].lower() in _ALIAS_LIKE(stripped):
            continue  # alias.column, e.g. p.price_usd (a table reference after FROM/JOIN/comma is never an alias)
        if not any(ref == p or ref.startswith(p + ".") or p.endswith("." + ref) for p in prefixes):
            raise SqlGuardError(f"table {ref!r} is outside the allowed dataset(s) {prefixes}")
    return sql.strip().rstrip(";")


def _ALIAS_LIKE(stripped: str) -> set[str]:
    """Names that appear as table aliases or CTE names, so alias.column references are not mistaken for tables."""
    names = set(re.findall(r"(?:\bAS\s+|\)\s*|\b[A-Za-z0-9_\-\.]+`?\s+)([A-Za-z_][A-Za-z0-9_]*)\b(?=\s*(?:,|ON|USING|WHERE|JOIN|LEFT|RIGHT|INNER|CROSS|GROUP|ORDER|LIMIT|$))", stripped, re.I))
    names |= set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+AS\s*\(", stripped, re.I))
    return {n.lower() for n in names}
