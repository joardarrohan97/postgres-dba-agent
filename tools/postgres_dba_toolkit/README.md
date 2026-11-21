# PostgreSQL DBA Toolkit (read-only starter)

A local Python CLI for PostgreSQL diagnostics. The first version focuses on safe inspection:
- server/database identity and database size
- connection counts
- long-running transactions and transaction snapshots
- blocking/blocker relationships using `pg_blocking_pids()`
- user-table statistics, relation sizes, vacuum/analyze timestamps
- index usage statistics
- primary-side replication status and standby WAL receiver status
- basic evidence-based findings

## Safety model

- Every run uses a PostgreSQL `READ ONLY` transaction.
- No DDL, DML, `VACUUM`, `ANALYZE`, `EXPLAIN ANALYZE`, session termination, or configuration changes.
- Each query has a statement timeout.
- Credentials are supplied through `PG_DSN`, never stored in this project.
- Statistics such as `n_live_tup`, `n_dead_tup`, and index scan counts are estimates/cumulative counters. Interpret them with workload and stats-reset context.
- A NULL vacuum timestamp alone is not proof of a vacuum problem.
- Low `idx_scan` alone is not proof that an index is unused; consider constraints, workload, and stats reset time.

## Requirements

- Python 3.10+
- PostgreSQL 12+ recommended (tested query design targets modern PostgreSQL; your PostgreSQL 18 lab is suitable)
- A database login with permission to connect and read the relevant statistics views.
- `psycopg` 3

## Install

### WSL Ubuntu

From the toolkit directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Configure the connection

Set `PG_DSN` in the same terminal where you run the tool.

Example format (replace the placeholders with a login role and password you already configured):

```bash
export PG_DSN="host=127.0.0.1 port=5432 dbname=postgres_dba_lab user=YOUR_LOGIN_ROLE password=YOUR_PASSWORD"
```

Do not use a superuser for routine monitoring. Prefer a dedicated monitoring login with only the privileges needed for the views you inspect. Do not commit real credentials to Git.

If you use a password file (`.pgpass`), you can omit `password` from the DSN. On Linux, protect it with `chmod 600 ~/.pgpass`.

## Run

```bash
python pg_dba.py health
python pg_dba.py connections
python pg_dba.py transactions
python pg_dba.py blocking
python pg_dba.py tables
python pg_dba.py indexes
python pg_dba.py replication
python pg_dba.py all
```

JSON output for agent ingestion:

```bash
python pg_dba.py all --format json
```

Tune thresholds:

```bash
python pg_dba.py all --long-txn-seconds 180 --timeout-ms 15000
```

## Suggested first validation

Start with the least invasive command:

```bash
python pg_dba.py health
```

Then:

```bash
python pg_dba.py transactions
python pg_dba.py blocking
```

The `blocking` report uses `pg_blocking_pids()` and reports both sides of a blocking relationship. It does not terminate sessions or claim that every idle transaction is blocking.

## Known limitations in v1

- No automatic remediation.
- No SQL execution supplied by the LLM.
- No `EXPLAIN ANALYZE` (it executes the statement being explained).
- No physical bloat measurement; dead-tuple estimates are not bloat measurements.
- Replication sections may be empty on a standalone instance.
- Some statistics are restricted or filtered depending on PostgreSQL privileges and server configuration.
- Query statistics from `pg_stat_statements` will be added as a separate optional module after the core checks are validated.

## Project integration

Keep this toolkit separate from your existing `CLAUDE.md`, agents, and skills initially. After the commands are validated against `postgres_dba_lab`, we can add a small agent-facing contract describing each command, its output schema, safety guarantees, and known limitations.
