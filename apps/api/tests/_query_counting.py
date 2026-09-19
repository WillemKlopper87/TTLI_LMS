"""A tiny, reusable SQL statement counter for N+1 regression tests
(BACKLOG.md F3/F4: "batched query shape; query count asserted").

Not a fixture — a plain context manager, since what it needs to attach
to (the shared engine `tenant_session_factory` already opened) differs
by call site, and forcing every caller through one more fixture layer
buys nothing a four-line `with` block doesn't already give directly.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine


@contextmanager
def count_queries(engine: AsyncEngine) -> Iterator[list[str]]:
    """Yields a list that grows by one entry (the statement text) per
    real round-trip to the database for the block's duration — a plain
    `len(...)` after the `with` exits is the count. A list rather than
    an int counter so a failing assertion's message can show exactly
    which statements ran, not just how many."""
    statements: list[str] = []

    def _before_cursor_execute(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    sync_engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)


__all__ = ["count_queries"]
