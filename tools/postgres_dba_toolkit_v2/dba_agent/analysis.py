from __future__ import annotations

from datetime import timedelta
from typing import Any


def build_findings(report: dict[str, Any], long_txn_seconds: int = 300,
                   dead_tuple_pct: float = 20.0, dead_tuple_min: int = 100) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    perms = report.get("permissions", [])
    if perms and isinstance(perms, list):
        p = perms[0]
        if not p.get("is_superuser") and not p.get("has_pg_read_all_stats") and not p.get("has_pg_monitor"):
            findings.append({
                "severity": "INFO", "category": "visibility", "title": "Monitoring visibility may be limited",
                "evidence": "The connected role is not a member of pg_read_all_stats or pg_monitor.",
                "impact": "Some cross-session query text and detailed activity information may be hidden. Empty results should not be interpreted as proof that no activity exists.",
                "recommendation": "Keep least privilege. Grant additional monitoring access only if the operational requirement justifies its cluster-wide scope.",
            })

    for row in report.get("blocking", []) if isinstance(report.get("blocking"), list) else []:
        blocked_pid = row.get("blocked_pid")
        blocker_pid = row.get("blocker_pid")

        evidence_parts = [
          f"Blocked PID {blocked_pid} ({row.get('blocked_user')})"
        ]

        if blocker_pid is not None:
          evidence_parts.append(f"is blocked by PID {blocker_pid}")
        else:
          evidence_parts.append("has a reported lock wait, but blocker PID is unavailable")

        wait_type = row.get("wait_event_type")
        wait_event = row.get("wait_event")
        if wait_type or wait_event:
          evidence_parts.append(f"wait event={wait_type}/{wait_event}")

        blocker_state = row.get("blocker_state")
        if blocker_state:
          evidence_parts.append(f"blocker state={blocker_state}")

        blocked_age = row.get("blocked_query_age")
        blocker_age = row.get("blocker_transaction_age")

        if isinstance(blocked_age, timedelta):
          evidence_parts.append(
              f"blocked query age={int(blocked_age.total_seconds())}s"
          )

        if isinstance(blocker_age, timedelta):
          evidence_parts.append(
              f"blocker transaction age={int(blocker_age.total_seconds())}s"
          )

        if row.get("blocker_state") == "idle in transaction":
          state_age = row.get("blocker_state_age")
          if state_age is not None:
              evidence_parts.append(f"blocker idle-state age={state_age}")

        for lock_key, label in (
          ("waiting_locks", "waiting locks"),
          ("blocker_granted_locks", "blocker granted locks"),
        ):
          locks = row.get(lock_key)
          if locks:
              lock_details = []
              for lock in locks:
                  if isinstance(lock, dict):
                      detail = ", ".join(
                          f"{key}={lock.get(key)}"
                          for key in ("locktype", "mode", "transactionid")
                          if lock.get(key) is not None
                      )
                      if detail:
                          lock_details.append(detail)
              if lock_details:
                  evidence_parts.append(f"{label}: {'; '.join(lock_details)}")

        chain = row.get("blocker_upstream_pids")
        if chain:
          evidence_parts.append(f"blocker is itself waiting on PID(s) {chain}")

        if not row.get("wait_event_type") and not row.get("wait_event"):
          evidence_parts.append(
              "wait-event details are unavailable to the monitoring role"
          )

        if not row.get("blocked_query") or not row.get("blocker_query"):
          evidence_parts.append(
              "query text may be hidden due to monitoring permissions"
          )

        findings.append({
          "severity": "CRITICAL",
          "category": "locking",
          "title": "Blocked session detected",
          "evidence": "; ".join(evidence_parts),
          "impact": (
              "The blocked transaction may be delaying application work and "
              "can contribute to request timeouts. An idle-in-transaction "
              "blocker may retain locks until its transaction ends."
          ),
          "recommendation": (
              "Inspect the blocker query, application, transaction age and "
              "full blocker chain. Ask the owning application/team to complete "
              "or safely roll back the transaction. Consider cancellation or "
              "termination only with explicit operational approval; never "
              "terminate automatically."
          ),
          "confidence": "HIGH" if blocker_pid is not None else "MEDIUM",
        })

    for txn in report.get("transactions", []) if isinstance(report.get("transactions"), list) else []:
        age = txn.get("transaction_age")
        seconds = age.total_seconds() if isinstance(age, timedelta) else None
        if seconds is not None and seconds >= long_txn_seconds:
            severity = "CRITICAL" if seconds >= max(long_txn_seconds * 4, 1800) else "WARNING"
            findings.append({
                "severity": severity, "category": "transactions", "title": "Long-running transaction",
                "evidence": f"PID {txn.get('pid')} transaction age is {int(seconds)} seconds; state={txn.get('state')}; backend_xmin={txn.get('backend_xmin')}.",
                "impact": "An old snapshot can delay cleanup of dead row versions and increase table/index maintenance pressure.",
                "recommendation": "Check whether the transaction is idle in transaction, inspect its owner and application, and assess its snapshot horizon before intervention.",
                "confidence": "HIGH",
            })

    for table in report.get("tables", []) if isinstance(report.get("tables"), list) else []:
        name = f"{table.get('schemaname')}.{table.get('table_name')}"
        estimate = table.get("planner_row_estimate")
        if estimate is not None and estimate < 0:
            findings.append({
                "severity": "WARNING", "category": "statistics", "title": f"Planner statistics missing for {name}",
                "evidence": f"pg_class.reltuples={estimate}; estimated live rows={table.get('estimated_live_rows')}.",
                "impact": "The planner may have a poor cardinality estimate and choose a suboptimal plan.",
                "recommendation": f"Review ANALYZE freshness and table modifications. If appropriate, schedule ANALYZE {name}; do not run maintenance automatically.",
                "confidence": "HIGH",
            })
        dead = table.get("estimated_dead_rows") or 0
        pct = table.get("estimated_dead_tuple_pct")
        if pct is not None and pct >= dead_tuple_pct and dead >= dead_tuple_min:
            findings.append({
                "severity": "WARNING", "category": "vacuum", "title": f"Elevated estimated dead tuples: {name}",
                "evidence": f"Estimated dead tuples={dead}; estimated dead tuple percentage={pct}%.",
                "impact": "If persistent, dead tuples can increase scans and maintenance work. This is not a physical bloat measurement.",
                "recommendation": "Correlate with write rate, long transactions, autovacuum logs/settings and stats reset time before planning VACUUM.",
                "confidence": "MEDIUM",
            })
        if table.get("last_analyze") is None and table.get("last_autoanalyze") is None:
            # Avoid alarming on tiny, static tables: only flag when modifications are material.
            modified = table.get("n_mod_since_analyze") or 0
            live = table.get("estimated_live_rows") or 0
            if modified >= max(50, int(live * 0.1)):
                findings.append({
                    "severity": "INFO", "category": "statistics", "title": f"No recorded ANALYZE for modified table {name}",
                    "evidence": f"No manual/automatic analyze timestamp; modifications since analyze={modified}.",
                    "impact": "Planner statistics may be stale after a material number of modifications.",
                    "recommendation": f"Consider ANALYZE {name} during an appropriate maintenance window.",
                    "confidence": "MEDIUM",
                })

    for idx in report.get("indexes", []) if isinstance(report.get("indexes"), list) else []:
        if idx.get("is_valid") is False:
            findings.append({
                "severity": "CRITICAL", "category": "indexes", "title": f"Invalid index: {idx.get('index_name')}",
                "evidence": f"Index on {idx.get('table_name')} has indisvalid=false.",
                "impact": "The planner will not use an invalid index; concurrent index build failures can leave invalid indexes behind.",
                "recommendation": "Inspect index build history and dependencies. Plan a controlled REINDEX or DROP/CREATE only after impact review.",
                "confidence": "HIGH",
            })
        if (idx.get("idx_scan") == 0 and not idx.get("backs_constraint")
                and not idx.get("is_primary") and not idx.get("is_unique")):
            findings.append({
                "severity": "INFO", "category": "indexes", "title": f"Index has zero recorded scans: {idx.get('index_name')}",
                "evidence": f"Index size={idx.get('index_size')}; idx_scan=0; constraint-backed=false.",
                "impact": "The index may add write and storage overhead, but a short or reset statistics window can hide infrequent use.",
                "recommendation": "Observe across a representative workload and check query plans and dependencies before considering removal. Never drop from this signal alone.",
                "confidence": "LOW",
            })

    if not findings:
        findings.append({
            "severity": "INFO", "category": "summary", "title": "No configured threshold findings",
            "evidence": "No blocking sessions, threshold-exceeding transactions, missing planner estimates, or configured dead-tuple thresholds were detected.",
            "impact": "This is a point-in-time diagnostic, not a guarantee of database health.",
            "recommendation": "Compare against workload baselines and historical trends; investigate slow statements and execution plans when users report latency.",
            "confidence": "MEDIUM",
        })
    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    return sorted(findings, key=lambda x: order.get(x["severity"], 9))


def analyze_plan(plan_doc: Any) -> dict[str, Any]:
    """Extract plan nodes and cautious, evidence-backed plan observations."""
    if isinstance(plan_doc, list) and plan_doc:
        root = plan_doc[0].get("Plan", {})
        planning_time = plan_doc[0].get("Planning Time")
        execution_time = plan_doc[0].get("Execution Time")
    elif isinstance(plan_doc, dict):
        root = plan_doc.get("Plan", plan_doc)
        planning_time = plan_doc.get("Planning Time")
        execution_time = plan_doc.get("Execution Time")
    else:
        raise ValueError("Unexpected EXPLAIN JSON structure")
    nodes: list[dict[str, Any]] = []
    observations: list[dict[str, str]] = []

    def walk(node: dict[str, Any], depth: int = 0) -> None:
        item = {
            "depth": depth, "node_type": node.get("Node Type"), "relation": node.get("Relation Name"),
            "schema": node.get("Schema"), "index": node.get("Index Name"),
            "estimated_rows": node.get("Plan Rows"), "actual_rows": node.get("Actual Rows"),
            "loops": node.get("Actual Loops"), "startup_cost": node.get("Startup Cost"),
            "total_cost": node.get("Total Cost"), "actual_total_ms": node.get("Actual Total Time"),
            "shared_hit_blocks": node.get("Shared Hit Blocks"), "shared_read_blocks": node.get("Shared Read Blocks"),
            "filter": node.get("Filter"), "index_condition": node.get("Index Cond"),
            "join_type": node.get("Join Type"),
        }
        nodes.append(item)
        if node.get("Node Type") == "Seq Scan":
            observations.append({"severity": "INFO", "title": f"Sequential scan on {node.get('Relation Name', 'unknown relation')}",
                                 "evidence": f"Plan rows={node.get('Plan Rows')}; actual rows={node.get('Actual Rows')}; filter={node.get('Filter')}.",
                                 "interpretation": "A sequential scan is not inherently bad. It can be optimal for small tables or when a large fraction of rows is needed."})
        est, actual = node.get("Plan Rows"), node.get("Actual Rows")
        if isinstance(est, (int, float)) and isinstance(actual, (int, float)) and est > 0:
            ratio = max(actual / est, est / max(actual, 1))
            if ratio >= 10:
                observations.append({"severity": "WARNING", "title": "Large cardinality estimation error",
                                     "evidence": f"Node {node.get('Node Type')} on {node.get('Relation Name', 'n/a')}: estimated {est} rows vs actual {actual} rows; factor about {ratio:.1f}x.",
                                     "interpretation": "Investigate stale statistics, skew, correlated predicates, parameter sensitivity, or missing extended statistics. This is a hypothesis, not a confirmed root cause."})
        if node.get("Node Type") == "Nested Loop" and isinstance(node.get("Actual Loops"), (int, float)) and node.get("Actual Loops", 0) > 1000:
            observations.append({"severity": "WARNING", "title": "High-loop nested loop", "evidence": f"Nested Loop executed {node.get('Actual Loops')} loops.",
                                 "interpretation": "Check outer row count, inner access path, join selectivity and whether a hash/merge strategy is more appropriate for this workload."})
        for child in node.get("Plans", []) or []:
            walk(child, depth + 1)

    walk(root)
    return {"planning_time_ms": planning_time, "execution_time_ms": execution_time,
            "root_node": root.get("Node Type"), "nodes": nodes, "observations": observations}
