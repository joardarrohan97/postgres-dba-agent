POSTGRES_FACTS = {
    "pg_monitor": "Predefined PostgreSQL role, not an extension.",
    "pg_read_all_stats": "Predefined PostgreSQL role, not an extension. Grants cluster-wide statistics visibility.",
    "pg_stat_activity": "Some activity information is visible to ordinary users; sensitive details such as other users query text are restricted.",
    "pg_stat_user_tables": "Table statistics view. Do not assume it is entirely inaccessible because pg_monitor membership is absent.",
    "pg_statio_user_tables": "Table I/O statistics view. Do not assume it is entirely inaccessible because pg_monitor membership is absent.",
    "pg_settings": "Configuration view available to ordinary users, with some columns subject to privilege restrictions.",
    "explain": "EXPLAIN without ANALYZE plans a statement without executing it.",
    "explain_analyze": "EXPLAIN ANALYZE executes the underlying statement and can have operational side effects.",
    "track_activities": "PostgreSQL activity tracking setting; inspect its actual value rather than assuming it is disabled.",
}
