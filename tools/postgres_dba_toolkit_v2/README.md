# PostgreSQL DBA Toolkit v2

An evidence-first PostgreSQL diagnostic and plan-analysis toolkit designed to feed a local Ollama model. It is a diagnostic assistant, not an autonomous DBA with permission to make production changes.

## Safety model

- All database connections run inside a PostgreSQL `READ ONLY` transaction.
- Diagnostics do not run DDL, DML, `VACUUM`, `ANALYZE`, `REINDEX`, session termination, or configuration changes.
- Each connection has a connect timeout, statement timeout and lock timeout.
- Credentials come from `PG_DSN` / `.pgpass`; never commit credentials.
- `EXPLAIN` is non-executing by default.
- `EXPLAIN ANALYZE` executes the statement. It requires BOTH `--analyze` and `--allow-execution`, and is limited to a single SELECT/WITH statement inside a read-only transaction. Read-only mode does not prevent external side effects from user-defined functions: only use trusted SQL.
- The LLM receives evidence and produces advice only. It cannot execute SQL through this toolkit.
- Empty monitoring results can reflect permissions, scope, or an idle system. Findings distinguish evidence from hypotheses.

## Requirements

- Python 3.10+
- PostgreSQL 12+ (some optional statistics columns/extensions vary by server version)
- PostgreSQL role with CONNECT and SELECT/monitor visibility as appropriate
- `psycopg` 3
- Optional: Ollama running locally with a chat model such as `qwen3.5:4b`

## Install in WSL Ubuntu

```bash
python3 -m venv ~/.venvs/postgres-dba-toolkit-v2
source ~/.venvs/postgres-dba-toolkit-v2/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Configure credentials

Use a protected `~/.pgpass` file (chmod 600). Example line:

```text
127.0.0.1:5432:postgres_dba_lab:dba_monitor:YOUR_PASSWORD
```

Then in the same terminal:

```bash
export PG_DSN="host=127.0.0.1 port=5432 dbname=postgres_dba_lab user=dba_monitor"
```

Do not paste passwords into chat or store them in project files. The toolkit deliberately does not grant roles or alter privileges.

## Diagnostics

```bash
python pg_dba.py health
python pg_dba.py connections
python pg_dba.py transactions
python pg_dba.py blocking
python pg_dba.py blocking --format json
python pg_dba.py tables
python pg_dba.py indexes
python pg_dba.py replication
python pg_dba.py config
python pg_dba.py statements
python pg_dba.py all
python pg_dba.py all --format json
python pg_dba.py all --format markdown
```

`statements` uses `pg_stat_statements`. If the extension is not installed or visible, the report records the error instead of pretending query statistics were collected. The toolkit does not install the extension.

The `blocking` section reports each blocked PID and direct blocker PID, wait event, query/transaction ages, blocker state, upstream blocker PIDs, sessions blocked by the blocker, and lock details where visible. `pg_blocking_pids()` is the source of the blocker relationship. Monitoring permissions can hide query text; an empty result is only a point-in-time observation. The toolkit never cancels or terminates a backend.

## Execution plan analysis

Non-executing plan:

```bash
python pg_dba.py explain --sql "SELECT * FROM public.employees WHERE department_id = 1"
```

Analyze actual runtime and buffers (executes the query):

```bash
python pg_dba.py explain --sql "SELECT * FROM public.employees WHERE department_id = 1" --analyze --allow-execution
```

Prefer `--sql-file plan_query.sql` for longer statements. Review SQL yourself first. Never use untrusted SQL or statements that call user-defined functions with external side effects. `EXPLAIN ANALYZE` executes the statement; even SELECT may invoke functions.

The plan analyzer extracts node types, estimates, actual rows, loops, timing and buffer metrics where available. It flags large estimate/actual mismatches as investigation leads, not proof of a specific cause. A sequential scan is not automatically a problem.

## Local Ollama DBA assessment

```bash
export OLLAMA_MODEL="qwen3.5:4b"
python pg_dba.py ask --question "Why might this database be slow? Give evidence, hypotheses, validation steps and safe recommendations."
```

The `ask` command collects the full report and sends a bounded JSON evidence payload to Ollama's `/api/chat`. The model's answer is advisory and must be validated. The toolkit does not expose an LLM tool for arbitrary SQL execution.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Important limitations / next validation

- The package has passed local Python syntax and unit tests, but its SQL still needs live validation against your PostgreSQL 18.6 lab, one section at a time.
- `pg_stat_statements` may require DBA installation/configuration and a restart; this toolkit will not do that.
- `pg_read_all_stats` and `pg_monitor` are cluster-wide privileges. Do not grant them casually just to make a dashboard look complete. The report surfaces limited visibility.
- `n_live_tup`, `n_dead_tup`, scan counts and query statistics are estimates/cumulative counters, not exact current truth. Always consider `stats_reset` and workload window.
- Unused-index candidates are low-confidence signals. Unique/primary/constraint-backed indexes are excluded from the zero-scan suggestion.
- No automatic remediation is included. Remediation SQL is a proposal for human review only.
