
-- ============================================================
-- PostgreSQL Performance Diagnosis for public.employees table
-- Query: SELECT * FROM public.employees WHERE department_id = 10;
-- PostgreSQL 18 - Read-Only Diagnostic Queries Only
-- ============================================================

-- ----------------------------------------------------------------------------
-- 1. TABLE SIZE AND ROW ESTIMATES
-- ----------------------------------------------------------------------------
/*
WHY: Inspect table storage and PostgreSQL's row estimates.

INTERPRETATION:
- reltuples: Planner row estimate from table statistics.
- n_live_tup and n_dead_tup: Estimated live and dead tuples.
- pg_relation_size(): Table storage excluding indexes.
- pg_total_relation_size(): Total storage including indexes.
- last_analyze / last_autoanalyze: Statistics collection timestamps.

NOTE: Tuple counts are estimates, not exact row counts.
*/

SELECT
    s.schemaname AS schema_name,
    s.relname AS table_name,
    c.reltuples::bigint AS estimated_row_count,
    pg_size_pretty(pg_relation_size(s.relid)) AS table_size,
    pg_size_pretty(pg_total_relation_size(s.relid)) AS total_size_with_indexes,
    s.n_live_tup AS estimated_live_rows,
    s.n_dead_tup AS estimated_dead_rows,
    s.last_analyze,
    s.last_autoanalyze,
    GREATEST(s.last_analyze, s.last_autoanalyze) AS last_statistics_update
FROM pg_stat_user_tables s
JOIN pg_class c ON c.oid = s.relid
WHERE s.schemaname = 'public'
  AND s.relname = 'employees';


-- ----------------------------------------------------------------------------
-- 2. EXISTING INDEXES ON EMPLOYEES TABLE
-- ----------------------------------------------------------------------------
/*
WHY: Inspect indexes available on public.employees.

INTERPRETATION:
- index_type: B-tree, GIN, BRIN, etc.
- is_valid / is_ready: Index usability state.
- index_scans: Cumulative index scan counter.
- index_definition: Indexed columns and index options.

NOTE: An existing index does not guarantee that the planner
will choose it. Review the execution plan and query selectivity.
*/

SELECT
    s.schemaname AS schema_name,
    s.relname AS table_name,
    s.indexrelname AS index_name,
    am.amname AS index_type,
    pg_size_pretty(pg_relation_size(i.indexrelid)) AS index_size,
    i.indisprimary AS is_primary,
    i.indisunique AS is_unique,
    i.indisvalid AS is_valid,
    i.indisready AS is_ready,
    s.idx_scan AS index_scans,
    s.idx_tup_read AS index_tuples_read,
    s.idx_tup_fetch AS index_tuples_fetched,
    pg_get_indexdef(i.indexrelid) AS index_definition
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
JOIN pg_class idx ON idx.oid = i.indexrelid
JOIN pg_am am ON am.oid = idx.relam
WHERE s.schemaname = 'public'
  AND s.relname = 'employees'
ORDER BY s.indexrelname;


-- ----------------------------------------------------------------------------
-- 3. DEPARTMENT ID DISTRIBUTION ANALYSIS
-- ----------------------------------------------------------------------------
/*
WHY: Understand department distribution and the proportion
of employees belonging to each department.

INTERPRETATION:
- row_count: Exact count for each department.
- total_rows: Exact total rows in the table.
- percentage_of_total: Department share of all rows.
- total_unique_departments: Number of non-NULL departments.
- rows_for_department_10: Exact count for department 10.

NOTE: This query performs an exact aggregation and may be
expensive on large production tables.
*/

WITH department_counts AS (
    SELECT
        department_id,
        COUNT(*) AS row_count
    FROM public.employees
    GROUP BY department_id
)
SELECT
    department_id,
    row_count,
    SUM(row_count) OVER () AS total_rows,
    ROUND(
        row_count * 100.0 /
        NULLIF(SUM(row_count) OVER (), 0),
        2
    ) AS percentage_of_total,
    COUNT(*) FILTER (WHERE department_id IS NOT NULL)
        OVER () AS total_unique_departments,
    COALESCE(
        SUM(row_count) FILTER (WHERE department_id = 10) OVER (),
        0
    ) AS rows_for_department_10
FROM department_counts
ORDER BY row_count DESC
LIMIT 10;

-- ----------------------------------------------------------------------------
-- 4. TABLE STATISTICS AND LAST ANALYZE TIME
-- ----------------------------------------------------------------------------
/*
WHY: Assess PostgreSQL's table row estimates and statistics collection history.

INTERPRETATION:
- reltuples: Planner row estimate from pg_class.
- n_live_tup: Estimated live tuples from table statistics.
- estimate_divergence_pct: Relative difference between two estimates.
- last_statistics_update: Most recent manual or automatic ANALYZE timestamp.

NOTE:
Both row counts are estimates, not exact counts. Their divergence alone
does not prove that statistics are stale. Statistics age is also workload
dependent. This query only reports information; it does not run ANALYZE.
*/

WITH table_stats AS (
    SELECT
        s.schemaname,
        s.relname AS table_name,
        c.oid AS table_oid,
        c.reltuples::numeric AS planner_estimated_rows,
        s.n_live_tup::numeric AS estimated_live_rows,
        s.n_dead_tup::numeric AS estimated_dead_rows,
        s.last_analyze,
        s.last_autoanalyze,
        GREATEST(s.last_analyze, s.last_autoanalyze)
            AS last_statistics_update
    FROM pg_stat_user_tables s
    JOIN pg_class c ON c.oid = s.relid
    WHERE s.schemaname = 'public'
      AND s.relname = 'employees'
),
comparison AS (
    SELECT
        *,
        CASE
            WHEN planner_estimated_rows < 0 THEN NULL
            ELSE
                ABS(planner_estimated_rows - estimated_live_rows)
                * 100.0
                / NULLIF(
                    GREATEST(
                        ABS(planner_estimated_rows),
                        ABS(estimated_live_rows)
                    ),
                    0
                )
        END AS estimate_divergence_pct
    FROM table_stats
)
SELECT
    schemaname AS schema_name,
    table_name,
    planner_estimated_rows,
    estimated_live_rows,
    estimated_dead_rows,
    pg_size_pretty(pg_relation_size(table_oid)) AS table_size,
    ROUND(estimate_divergence_pct, 2) AS estimate_divergence_pct,
    CASE
        WHEN planner_estimated_rows < 0
            THEN 'PLANNER ESTIMATE UNAVAILABLE'
        WHEN estimate_divergence_pct IS NULL
            THEN 'NO ESTIMATE DIVERGENCE TO CALCULATE'
        WHEN estimate_divergence_pct > 50
            THEN 'HIGH ESTIMATE DIVERGENCE'
        WHEN estimate_divergence_pct > 10
            THEN 'MODERATE ESTIMATE DIVERGENCE'
        ELSE 'LOW ESTIMATE DIVERGENCE'
    END AS estimate_comparison,
    last_analyze,
    last_autoanalyze,
    last_statistics_update,
    CASE
        WHEN last_statistics_update IS NULL
            THEN 'NO ANALYZE TIMESTAMP RECORDED'
        WHEN last_statistics_update < now() - INTERVAL '24 hours'
            THEN 'STATISTICS UPDATE OLDER THAN 24 HOURS'
        ELSE 'STATISTICS UPDATE WITHIN 24 HOURS'
    END AS statistics_age_status
FROM comparison;


-- ----------------------------------------------------------------------------
-- 5. DEAD TUPLE ESTIMATES AND AUTOVACUUM HISTORY
-- ----------------------------------------------------------------------------
/*
WHY: Review estimated dead tuples and the history of VACUUM activity.

INTERPRETATION:
- n_live_tup: Estimated live tuples.
- n_dead_tup: Estimated dead tuples.
- dead_tuple_estimate_pct: Estimated dead tuples as a percentage
  of estimated live and dead tuples.
- last_vacuum / last_autovacuum: Most recent manual and automatic VACUUM.

NOTE:
Dead tuple estimates do not directly measure physical table bloat.
A high ratio is an investigation signal, not proof of bloat.
This query does not execute VACUUM or modify database objects.
*/

WITH tuple_stats AS (
    SELECT
        s.schemaname,
        s.relname AS table_name,
        s.relid AS table_oid,
        s.n_live_tup::numeric AS estimated_live_tuples,
        s.n_dead_tup::numeric AS estimated_dead_tuples,
        s.last_vacuum,
        s.last_autovacuum,
        GREATEST(s.last_vacuum, s.last_autovacuum)
            AS last_vacuum_activity
    FROM pg_stat_user_tables s
    WHERE s.schemaname = 'public'
      AND s.relname = 'employees'
),
calculated AS (
    SELECT
        *,
        CASE
            WHEN estimated_live_tuples + estimated_dead_tuples = 0
                THEN NULL
            ELSE
                estimated_dead_tuples * 100.0
                / NULLIF(
                    estimated_live_tuples + estimated_dead_tuples,
                    0
                )
        END AS dead_tuple_estimate_pct
    FROM tuple_stats
)
SELECT
    schemaname AS schema_name,
    table_name,
    estimated_live_tuples,
    estimated_dead_tuples,
    ROUND(dead_tuple_estimate_pct, 2) AS dead_tuple_estimate_pct,
    pg_size_pretty(pg_relation_size(table_oid)) AS table_size,
    last_vacuum,
    last_autovacuum,
    last_vacuum_activity,
    CASE
        WHEN dead_tuple_estimate_pct IS NULL
            THEN 'NO TUPLE ESTIMATE AVAILABLE'
        WHEN dead_tuple_estimate_pct >= 70
            THEN 'HIGH ESTIMATED DEAD-TUPLE RATIO - INVESTIGATE'
        WHEN dead_tuple_estimate_pct >= 50
            THEN 'ELEVATED ESTIMATED DEAD-TUPLE RATIO'
        WHEN dead_tuple_estimate_pct >= 20
            THEN 'MODERATE ESTIMATED DEAD-TUPLE RATIO'
        ELSE 'LOW ESTIMATED DEAD-TUPLE RATIO'
    END AS dead_tuple_assessment
FROM calculated;


-- ----------------------------------------------------------------------------
-- 6. QUERY EXECUTION PLAN WITH EXPLAIN
-- ----------------------------------------------------------------------------
/*
WHY: Inspect the PostgreSQL planner's proposed execution strategy.

INTERPRETATION:
- Index Scan: Reads matching rows through an index.
- Sequential Scan: Reads the table; this can be optimal for low selectivity.
- Bitmap Heap Scan: Uses an index bitmap to locate heap pages.
- Estimated Rows: Planner estimate, not actual execution row count.
- Cost: Planner cost units, not elapsed milliseconds.

SAFETY:
The EXPLAIN statement below does not execute the SELECT query.
It reports the estimated plan only.

NOTE:
Actual execution time and buffer activity require EXPLAIN ANALYZE.
That executes the query and can consume production resources.
It is intentionally excluded from this read-only diagnostic script.
*/

EXPLAIN (VERBOSE, COSTS, SETTINGS)
SELECT *
FROM public.employees
WHERE department_id = 10;


-- ----------------------------------------------------------------------------
-- ADDITIONAL DIAGNOSTIC QUERIES FOR COMMON PERFORMANCE ISSUES
-- ----------------------------------------------------------------------------
/*
WHY: Identify blocked sessions and long-running transactions.

NOTE:
These queries inspect PostgreSQL activity views only.
They do not terminate sessions or modify transactions.
Query text may contain sensitive application information.
*/


-- Identify sessions waiting on other PostgreSQL sessions.
WITH blocked_sessions AS (
    SELECT
        a.*,
        pg_blocking_pids(a.pid) AS blocking_pids
    FROM pg_stat_activity a
    WHERE a.datname = current_database()
      AND a.pid <> pg_backend_pid()
)
SELECT
    blocked.pid AS blocked_pid,
    blocked.usename AS blocked_user,
    blocked.application_name AS blocked_application,
    blocked.state AS blocked_state,
    blocked.wait_event_type,
    blocked.wait_event,
    clock_timestamp() - blocked.query_start AS blocked_query_duration,
    blocker.pid AS blocker_pid,
    blocker.usename AS blocker_user,
    blocker.application_name AS blocker_application,
    blocker.state AS blocker_state,
    LEFT(blocked.query, 200) AS blocked_query,
    LEFT(blocker.query, 200) AS blocker_query
FROM blocked_sessions blocked
CROSS JOIN LATERAL
    unnest(blocked.blocking_pids) AS blocker_pid(pid)
LEFT JOIN pg_stat_activity blocker
    ON blocker.pid = blocker_pid.pid
ORDER BY blocked.query_start;


-- Identify long-running transactions in the current database.
SELECT
    pid AS backend_pid,
    usename AS database_user,
    application_name,
    state,
    clock_timestamp() - xact_start AS transaction_duration,
    wait_event_type,
    wait_event,
    LEFT(query, 200) AS query_preview
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
  AND xact_start IS NOT NULL
  AND state IN (
      'active',
      'idle in transaction',
      'idle in transaction (aborted)'
  )
  AND xact_start < clock_timestamp() - INTERVAL '1 minute'
ORDER BY xact_start;


-- ----------------------------------------------------------------------------
-- DIAGNOSTIC SUMMARY METRICS
-- ----------------------------------------------------------------------------
/*
PURPOSE:
Combine table estimates, index availability, dead-tuple estimates,
and statistics collection timestamps.

IMPORTANT:
- Row counts and dead-tuple counts are estimates.
- An index's existence does not guarantee index usage.
- A sequential scan is not automatically a performance problem.
- Statistics age is an investigation indicator, not a universal threshold.
*/

WITH table_stats AS (
    SELECT
        s.schemaname,
        s.relname AS table_name,
        s.relid AS table_oid,
        c.reltuples::numeric AS planner_estimated_rows,
        s.n_live_tup::numeric AS estimated_live_rows,
        s.n_dead_tup::numeric AS estimated_dead_rows,
        s.last_analyze,
        s.last_autoanalyze,
        GREATEST(s.last_analyze, s.last_autoanalyze)
            AS last_statistics_update
    FROM pg_stat_user_tables s
    JOIN pg_class c ON c.oid = s.relid
    WHERE s.schemaname = 'public'
      AND s.relname = 'employees'
),
metrics AS (
    SELECT
        *,
        CASE
            WHEN planner_estimated_rows < 0 THEN NULL
            ELSE
                ABS(planner_estimated_rows - estimated_live_rows)
                * 100.0
                / NULLIF(
                    GREATEST(
                        ABS(planner_estimated_rows),
                        ABS(estimated_live_rows)
                    ),
                    0
                )
        END AS estimate_divergence_pct,
        CASE
            WHEN estimated_live_rows + estimated_dead_rows = 0
                THEN NULL
            ELSE
                estimated_dead_rows * 100.0
                / NULLIF(
                    estimated_live_rows + estimated_dead_rows,
                    0
                )
        END AS dead_tuple_estimate_pct
    FROM table_stats
)
SELECT
    m.schemaname AS schema_name,
    m.table_name,
    m.planner_estimated_rows,
    m.estimated_live_rows,
    m.estimated_dead_rows,
    pg_size_pretty(pg_relation_size(m.table_oid)) AS table_size,

    CASE
        WHEN m.planner_estimated_rows < 0 THEN 'UNKNOWN'
        WHEN m.planner_estimated_rows > 1000000 THEN 'LARGE TABLE'
        ELSE 'SMALL OR MEDIUM TABLE'
    END AS table_category,

    ROUND(m.estimate_divergence_pct, 2)
        AS estimate_divergence_pct,

    ROUND(m.dead_tuple_estimate_pct, 2)
        AS dead_tuple_estimate_pct,

    CASE
        WHEN EXISTS (
            SELECT 1
            FROM pg_index i
            JOIN pg_attribute a
              ON a.attrelid = i.indrelid
             AND a.attnum = i.indkey[0]
            WHERE i.indrelid = m.table_oid
              AND a.attname = 'department_id'
              AND i.indisvalid
              AND i.indisready
              AND i.indpred IS NULL
        )
        THEN 'VALID LEADING DEPARTMENT_ID INDEX EXISTS'
        ELSE 'NO VALID NON-PARTIAL LEADING INDEX FOUND'
    END AS department_index_status,

    m.last_analyze,
    m.last_autoanalyze,
    m.last_statistics_update,

    CASE
        WHEN m.last_statistics_update IS NULL
            THEN 'NO ANALYZE TIMESTAMP RECORDED'
        WHEN m.last_statistics_update < now() - INTERVAL '24 hours'
            THEN 'STATISTICS UPDATE OLDER THAN 24 HOURS'
        ELSE 'STATISTICS UPDATE WITHIN 24 HOURS'
    END AS statistics_age_status

FROM metrics m;


-- ----------------------------------------------------------------------------

-- ----------------------------------------------------------------------------
-- DOCUMENTATION FOR EACH QUERY SECTION
-- ----------------------------------------------------------------------------

/*
SECTION 1: TABLE SIZE AND ROW ESTIMATES
---------------------------------------
PURPOSE:
Shows table storage, planner row estimates, estimated live/dead tuples,
and the latest recorded ANALYZE or auto-ANALYZE timestamp.

INTERPRETATION:
- reltuples is the planner's estimated row count.
- n_live_tup and n_dead_tup are statistics estimates, not exact counts.
- pg_relation_size reports the table relation size.
- pg_total_relation_size includes associated indexes and other relation
  storage.
- A missing ANALYZE timestamp does not by itself prove statistics are stale.

Do not treat a fixed 24-hour threshold as a universal rule. Consider table
activity, data changes, and query-plan quality when assessing freshness.


SECTION 2: EXISTING INDEXES
---------------------------
PURPOSE:
Lists indexes on public.employees, their access method, size, validity,
readiness, usage counters, and index definitions.

INTERPRETATION:
- index_type identifies the access method, such as btree.
- is_valid and is_ready describe index usability/readiness.
- index_scans, index_tuples_read, and index_tuples_fetched are cumulative
  statistics since the relevant statistics reset.
- A zero scan count does not automatically mean an index is unnecessary.
  Consider workload history, query patterns, and statistics reset time.

An index on department_id may help some filters, but PostgreSQL can
correctly choose a sequential scan depending on table size, selectivity,
cost estimates, and available cache.


SECTION 3: DEPARTMENT ID DISTRIBUTION
-------------------------------------
PURPOSE:
Counts rows grouped by department_id and reports each group's percentage
of the total grouped rows.

INTERPRETATION:
- row_count is the count for that department_id group.
- total_rows is the total represented by the grouped result.
- percentage_of_total is that group's share of the total.
- total_unique_departments counts non-NULL department groups.
- rows_for_department_10 reports the count for department 10.

This query performs an exact aggregation over public.employees. Its cost
depends on table size and available resources. Selectivity alone does not
guarantee that an index will improve performance.


SECTION 4: TABLE STATISTICS AND ESTIMATE COMPARISON
---------------------------------------------------
PURPOSE:
Compares the planner's row estimate with PostgreSQL's estimated live-row
statistics and reports the latest recorded statistics timestamps.

INTERPRETATION:
- planner_estimated_rows comes from pg_class.reltuples.
- estimated_live_rows comes from pg_stat_user_tables.n_live_tup.
- estimate_divergence_pct is a comparison between two estimates, not a
  comparison against an exact COUNT(*).
- A NULL divergence can occur when a meaningful percentage cannot be
  calculated.
- Statistics timestamps provide context but do not alone establish that
  statistics are inaccurate.

Investigate significant divergence alongside representative query plans
and workload changes. There is no universal 12-hour or 24-hour threshold
that applies to every PostgreSQL table.


SECTION 5: DEAD-TUPLE ESTIMATES AND VACUUM HISTORY
--------------------------------------------------
PURPOSE:
Reports estimated dead tuples, their estimated proportion, and recorded
VACUUM/autovacuum activity.

INTERPRETATION:
- n_dead_tup is an estimate, not an exact physical count of dead tuples.
- dead_tuple_estimate_pct is an estimated tuple ratio.
- VACUUM timestamps show recorded maintenance activity.
- A high estimated dead-tuple ratio is a reason to investigate, not proof
  of physical table bloat.

Dead tuples and physical bloat are related but are not interchangeable.
Assess table size, workload, vacuum behaviour, and suitable bloat
measurements before recommending maintenance.


SECTION 6: SAFE QUERY PLAN INSPECTION
-------------------------------------
PURPOSE:
Uses EXPLAIN (VERBOSE, COSTS, SETTINGS) to display the planner's proposed
execution plan and relevant settings for the sample query.

SAFETY:
Plain EXPLAIN does not execute the SELECT statement. This diagnostic
intentionally does not use EXPLAIN ANALYZE.

INTERPRETATION:
- Seq Scan means PostgreSQL plans to scan the table.
- Index Scan and Index Only Scan indicate index-based access.
- Bitmap Heap Scan combines bitmap index access with heap access.
- Estimated cost and row counts are planner estimates, not measured
  execution time or actual row counts.

A sequential scan is not automatically a problem. Judge the plan against
the query, table size, selectivity, and workload.


ADDITIONAL DIAGNOSTIC QUERIES
-----------------------------
LOCK CONTENTION:
Uses pg_blocking_pids() to identify sessions reported as blockers of
other sessions in the current database. Visibility of other sessions
and their query text depends on the executing role's privileges.

LONG TRANSACTIONS:
Lists other sessions in the current database with transactions older
than the query's one-minute inspection threshold. This is a diagnostic
filter, not a universal definition of a problematic transaction.

DIAGNOSTIC SUMMARY
------------------
PURPOSE:
Combines table statistics, estimated row-count divergence, estimated
dead-tuple ratio, statistics timestamps, and an index-presence check.

INTERPRETATION:
- Row-count and dead-tuple values are estimates.
- The department index check looks for a valid, ready, non-partial index
  whose leading key is department_id.
- A partial index or an index with department_id in a later key position
  is not counted by that specific check.
- The 24-hour statistics-age label is informational, not an automatic
  maintenance recommendation.

Use the summary as an initial investigation aid. Confirm findings with
the relevant individual diagnostics and representative query plans.
Do not automatically create indexes, run VACUUM, or change configuration
based only on these summary labels.


ILLUSTRATIVE OUTPUT
-------------------
Any example row counts or table sizes shown in comments are illustrative
only. They are not measurements from the current lab database.
*/
