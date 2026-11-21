"""PostgreSQL catalog/statistics queries. Keep queries version-conscious."""
QUERIES: dict[str, str] = {
    "health": """
        SELECT current_database() AS database_name, current_user AS connected_user,
               current_setting('server_version') AS server_version,
               current_setting('server_version_num')::int AS server_version_num,
               pg_postmaster_start_time() AS server_started_at,
               clock_timestamp() AS checked_at,
               pg_size_pretty(pg_database_size(current_database())) AS database_size,
               pg_database_size(current_database()) AS database_size_bytes,
               pg_postmaster_start_time() AS postmaster_start_time
    """,
    "permissions": """
        SELECT current_user AS connected_user,
               COALESCE(r.rolsuper, false) AS is_superuser,
               pg_has_role(current_user, 'pg_read_all_stats', 'MEMBER') AS has_pg_read_all_stats,
               pg_has_role(current_user, 'pg_monitor', 'MEMBER') AS has_pg_monitor,
               has_database_privilege(current_user, current_database(), 'CONNECT') AS can_connect
        FROM pg_roles r WHERE r.rolname = current_user
    """,
    "connections": """
        SELECT state, COALESCE(wait_event_type, 'none') AS wait_event_type,
               count(*)::int AS connection_count
        FROM pg_stat_activity
        WHERE datname = current_database() AND backend_type = 'client backend'
        GROUP BY state, wait_event_type
        ORDER BY connection_count DESC, state
    """,
    "connection_details": """
        SELECT pid, usename AS username, application_name, client_addr::text AS client_address,
               state, wait_event_type, wait_event,
               clock_timestamp() - xact_start AS transaction_age,
               clock_timestamp() - query_start AS query_age,
               left(regexp_replace(COALESCE(query, ''), E'[\\n\\r\\t]+', ' ', 'g'), 350) AS query
        FROM pg_stat_activity
        WHERE datname = current_database() AND backend_type = 'client backend'
          AND pid <> pg_backend_pid()
        ORDER BY xact_start NULLS LAST, query_start NULLS LAST
    """,
    "transactions": """
        SELECT pid, usename AS username, application_name, client_addr::text AS client_address,
               state, xact_start, clock_timestamp() - xact_start AS transaction_age,
               backend_xmin::text AS backend_xmin, wait_event_type, wait_event,
               left(regexp_replace(COALESCE(query, ''), E'[\\n\\r\\t]+', ' ', 'g'), 500) AS query
        FROM pg_stat_activity
        WHERE datname = current_database() AND pid <> pg_backend_pid() AND xact_start IS NOT NULL
        ORDER BY xact_start
    """,
    "blocking": """
        WITH activity AS (
            SELECT pid, datname, usename, application_name, client_addr,
                   state, wait_event_type, wait_event, xact_start, query_start,
                   state_change, backend_xmin,
                   left(regexp_replace(COALESCE(query, ''), E'[\\n\\r\\t]+', ' ', 'g'), 500) AS query
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
        ), blocked AS (
            SELECT a.*, p.blocker_pid
            FROM activity AS a
            CROSS JOIN LATERAL unnest(pg_blocking_pids(a.pid)) AS p(blocker_pid)
        )
        SELECT blocked.pid AS blocked_pid,
               blocked.usename AS blocked_user,
               blocked.application_name AS blocked_application,
               blocked.client_addr::text AS blocked_client_address,
               blocked.state AS blocked_state,
               blocked.xact_start AS blocked_xact_start,
               clock_timestamp() - blocked.xact_start AS blocked_transaction_age,
               blocked.query_start AS blocked_query_start,
               clock_timestamp() - blocked.query_start AS blocked_query_age,
               blocked.wait_event_type,
               blocked.wait_event,
               blocked.query AS blocked_query,
               blocker.pid AS blocker_pid,
               blocker.usename AS blocker_user,
               blocker.application_name AS blocker_application,
               blocker.client_addr::text AS blocker_client_address,
               blocker.state AS blocker_state,
               blocker.state_change AS blocker_state_change,
               clock_timestamp() - blocker.state_change AS blocker_state_age,
               blocker.xact_start AS blocker_xact_start,
               clock_timestamp() - blocker.xact_start AS blocker_transaction_age,
               blocker.wait_event_type AS blocker_wait_event_type,
               blocker.wait_event AS blocker_wait_event,
               blocker.query AS blocker_query,
               CASE WHEN blocker.pid IS NULL THEN NULL
                    ELSE pg_blocking_pids(blocker.pid) END AS blocker_upstream_pids,
               COALESCE((
                   SELECT array_agg(a2.pid ORDER BY a2.pid)
                   FROM activity AS a2
                   WHERE blocker.pid = ANY(pg_blocking_pids(a2.pid))
               ), ARRAY[]::integer[]) AS blocker_blocked_pids,
               COALESCE(waiting_locks.lock_details, '[]'::jsonb) AS waiting_locks,
               COALESCE(granted_locks.lock_details, '[]'::jsonb) AS blocker_granted_locks
        FROM blocked
        LEFT JOIN activity AS blocker ON blocker.pid = blocked.blocker_pid
        LEFT JOIN LATERAL (
            SELECT jsonb_agg(jsonb_build_object(
                'locktype', l.locktype, 'mode', l.mode,
                'relation', CASE WHEN l.relation IS NULL THEN NULL ELSE l.relation::regclass::text END,
                'page', l.page, 'tuple', l.tuple,
                'transactionid', l.transactionid::text,
                'virtualxid', l.virtualxid, 'waitstart', l.waitstart
            )) AS lock_details
            FROM pg_locks AS l
            WHERE l.pid = blocked.pid AND NOT l.granted
        ) AS waiting_locks ON true
        LEFT JOIN LATERAL (
            SELECT jsonb_agg(jsonb_build_object(
                'locktype', bl.locktype, 'mode', bl.mode,
                'relation', CASE WHEN bl.relation IS NULL THEN NULL ELSE bl.relation::regclass::text END,
                'page', bl.page, 'tuple', bl.tuple,
                'transactionid', bl.transactionid::text,
                'virtualxid', bl.virtualxid
            )) AS lock_details
            FROM pg_locks AS bl
            JOIN pg_locks AS wl
              ON wl.pid = blocked.pid AND NOT wl.granted
             AND bl.pid = blocker.pid AND bl.granted
             AND bl.locktype = wl.locktype
             AND bl.database IS NOT DISTINCT FROM wl.database
             AND bl.relation IS NOT DISTINCT FROM wl.relation
             AND bl.page IS NOT DISTINCT FROM wl.page
             AND bl.tuple IS NOT DISTINCT FROM wl.tuple
             AND bl.virtualxid IS NOT DISTINCT FROM wl.virtualxid
             AND bl.transactionid IS NOT DISTINCT FROM wl.transactionid
             AND bl.classid IS NOT DISTINCT FROM wl.classid
             AND bl.objid IS NOT DISTINCT FROM wl.objid
             AND bl.objsubid IS NOT DISTINCT FROM wl.objsubid
        ) AS granted_locks ON true
        ORDER BY blocked.pid, blocker.pid
    """,
    "tables": """
        SELECT s.schemaname, s.relname AS table_name, c.reltuples::bigint AS planner_row_estimate,
               s.n_live_tup AS estimated_live_rows, s.n_dead_tup AS estimated_dead_rows,
               round(100.0 * s.n_dead_tup / NULLIF(s.n_live_tup + s.n_dead_tup, 0), 2) AS estimated_dead_tuple_pct,
               pg_relation_size(s.relid) AS heap_size_bytes,
               pg_size_pretty(pg_relation_size(s.relid)) AS heap_size,
               pg_total_relation_size(s.relid) AS total_size_bytes,
               pg_size_pretty(pg_total_relation_size(s.relid)) AS total_size,
               s.seq_scan, s.seq_tup_read, s.idx_scan, s.idx_tup_fetch,
               s.n_tup_ins, s.n_tup_upd, s.n_tup_del, s.n_tup_hot_upd,
               s.n_mod_since_analyze, s.last_vacuum, s.last_autovacuum,
               s.last_analyze, s.last_autoanalyze
        FROM pg_stat_user_tables AS s JOIN pg_class AS c ON c.oid = s.relid
        ORDER BY pg_total_relation_size(s.relid) DESC
    """,
    "indexes": """
        SELECT st.schemaname, st.relname AS table_name, st.indexrelname AS index_name,
               am.amname AS access_method, i.indisprimary AS is_primary,
               i.indisunique AS is_unique, i.indisvalid AS is_valid,
               (con.conindid IS NOT NULL) AS backs_constraint,
               con.contype AS constraint_type,
               st.idx_scan, st.idx_tup_read, st.idx_tup_fetch,
               pg_relation_size(st.indexrelid) AS index_size_bytes,
               pg_size_pretty(pg_relation_size(st.indexrelid)) AS index_size,
               pg_get_indexdef(st.indexrelid) AS index_definition
        FROM pg_stat_user_indexes AS st
        JOIN pg_index AS i ON i.indexrelid = st.indexrelid
        JOIN pg_class AS ic ON ic.oid = st.indexrelid
        JOIN pg_am AS am ON am.oid = ic.relam
        LEFT JOIN pg_constraint AS con ON con.conindid = st.indexrelid
        ORDER BY pg_relation_size(st.indexrelid) DESC
    """,
    "replication": """
        SELECT pid, usename AS username, application_name, client_addr::text AS client_address,
               state, sync_state, sent_lsn::text AS sent_lsn, write_lsn::text AS write_lsn,
               flush_lsn::text AS flush_lsn, replay_lsn::text AS replay_lsn,
               write_lag, flush_lag, replay_lag
        FROM pg_stat_replication ORDER BY application_name, pid
    """,
    "wal_receiver": """
        SELECT status, receive_start_lsn::text AS receive_start_lsn,
               written_lsn::text AS written_lsn, flushed_lsn::text AS flushed_lsn,
               latest_end_lsn::text AS latest_end_lsn, last_msg_send_time,
               last_msg_receipt_time, sender_host, sender_port, slot_name
        FROM pg_stat_wal_receiver
    """,
    "replication_slots": """
        SELECT slot_name, slot_type, database, active, restart_lsn::text AS restart_lsn,
               confirmed_flush_lsn::text AS confirmed_flush_lsn
        FROM pg_replication_slots ORDER BY slot_name
    """,
    "database_stats": """
        SELECT datname, numbackends, xact_commit, xact_rollback, blks_read, blks_hit,
               round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2) AS cache_hit_pct,
               tup_returned, tup_fetched, conflicts, temp_files, temp_bytes,
               deadlocks, blk_read_time, blk_write_time, stats_reset
        FROM pg_stat_database WHERE datname = current_database()
    """,
    "config": """
        SELECT name, setting, unit, source, pending_restart
        FROM pg_settings
        WHERE name = ANY (ARRAY[
          'max_connections','shared_buffers','work_mem','maintenance_work_mem',
          'effective_cache_size','autovacuum','autovacuum_work_mem',
          'autovacuum_vacuum_scale_factor','autovacuum_analyze_scale_factor',
          'max_wal_size','checkpoint_timeout','wal_level','track_counts',
          'track_io_timing','random_page_cost','effective_io_concurrency'
        ])
        ORDER BY name
    """,
    "statements": """
        SELECT queryid, calls, rows, round(total_exec_time::numeric, 2) AS total_exec_ms,
               round(mean_exec_time::numeric, 2) AS mean_exec_ms,
               round(max_exec_time::numeric, 2) AS max_exec_ms,
               shared_blks_hit, shared_blks_read, temp_blks_written,
               left(regexp_replace(query, E'[\\n\\r\\t]+', ' ', 'g'), 500) AS query
        FROM pg_stat_statements
        WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
        ORDER BY total_exec_time DESC LIMIT 20
    """,
}

SECTION_MAP = {
    "health": ["health", "permissions"],
    "connections": ["connections", "connection_details", "permissions"],
    "transactions": ["transactions", "permissions"],
    "blocking": ["blocking", "permissions"],
    "tables": ["tables", "database_stats", "permissions"],
    "indexes": ["indexes", "permissions"],
    "replication": ["replication", "wal_receiver", "replication_slots", "permissions"],
    "config": ["config", "permissions"],
    "statements": ["statements", "permissions"],
    "all": list(QUERIES.keys()),
}
