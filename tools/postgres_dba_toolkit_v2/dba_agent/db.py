from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row


@contextmanager
def connect(dsn: str, timeout_ms: int = 10000) -> Iterator[psycopg.Connection]:
    """Open a bounded connection and a read-only transaction."""
    if timeout_ms < 1:
        raise ValueError("timeout_ms must be positive")
    with psycopg.connect(
        dsn,
        connect_timeout=5,
        application_name="postgres_dba_toolkit_v2",
        row_factory=dict_row,
        options=f"-c statement_timeout={int(timeout_ms)} -c lock_timeout=2000",
    ) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            yield conn
