from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any


def _default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _markdown(report: dict[str, Any]) -> str:
    lines = ["# PostgreSQL DBA Diagnostic Report", ""]
    for section, data in report.items():
        lines += [f"## {section.replace('_', ' ').title()}", ""]
        if isinstance(data, list):
            if not data:
                lines += ["No rows.", ""]
            elif isinstance(data[0], dict):
                keys = list(data[0].keys())
                lines.append("| " + " | ".join(keys) + " |")
                lines.append("| " + " | ".join(["---"] * len(keys)) + " |")
                for row in data:
                    lines.append("| " + " | ".join(str(row.get(k, "")).replace("|", "\\|") for k in keys) + " |")
                lines.append("")
            else:
                lines += ["```text", str(data), "```", ""]
        elif isinstance(data, dict):
            lines += ["```json", json.dumps(data, default=_default, indent=2), "```", ""]
        else:
            lines += [str(data), ""]
    return "\n".join(lines)


def render_report(report: dict[str, Any], output_format: str = "text") -> str:
    if output_format == "json":
        return json.dumps(report, default=_default, indent=2)
    if output_format == "markdown":
        return _markdown(report)
    lines: list[str] = []
    for section, data in report.items():
        lines.append(f"\n=== {section.upper()} ===")
        if isinstance(data, dict):
            if "error" in data:
                lines.append(f"ERROR: {data['error']}")
            else:
                lines.append(json.dumps(data, default=_default, indent=2))
        elif isinstance(data, list):
            if not data:
                lines.append("(no rows)")
                continue
            if section == "findings":
                for item in data:
                    lines.append(f"[{item.get('severity')}] {item.get('title')}")
                    lines.append(f"  Evidence: {item.get('evidence')}")
                    lines.append(f"  Impact: {item.get('impact')}")
                    lines.append(f"  Recommendation: {item.get('recommendation')}")
                    lines.append(f"  Confidence: {item.get('confidence')}")
            else:
                keys = list(data[0].keys())
                lines.append(" | ".join(keys))
                lines.append("-+-".join("-" * min(max(len(k), 4), 28) for k in keys))
                for row in data:
                    lines.append(" | ".join(str(row.get(k, ""))[:120] for k in keys))
        else:
            lines.append(str(data))
    return "\n".join(lines)
