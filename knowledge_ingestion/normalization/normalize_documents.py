import json
import re
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]

RAW_DIR = ROOT / "data" / "raw"
OUTPUT_DIR = ROOT / "data" / "normalized"
METADATA_DIR = ROOT / "metadata"

RUN_ID = "20261120T074258Z"
MANIFEST = METADATA_DIR / f"manifest_{RUN_ID}.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def normalize_markdown(text):
    text = text.replace("\r\n", "\n")

    # Remove PostgreSQL documentation navigation links.
    text = re.sub(
        r"^\|.*\[(?:Prev|Up|Next|Home)\].*\|$",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE
    )

    # Remove standalone horizontal separators.
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # Normalize excessive blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip() + "\n"


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results = []

    for document in manifest["documents"]:
        source = ROOT / document["raw_file"]

        if not source.exists():
            print("MISSING:", source)
            continue

        original = source.read_text(encoding="utf-8")
        normalized = normalize_markdown(original)

        output = OUTPUT_DIR / source.name
        output.write_text(normalized, encoding="utf-8")

        result = {
            "key": document["key"],
            "topic": document["topic"],
            "source_url": document["url"],
            "source_file": str(source.relative_to(ROOT)),
            "normalized_file": str(output.relative_to(ROOT)),
            "original_characters": len(original),
            "normalized_characters": len(normalized),
            "word_count": len(normalized.split()),
            "normalized_at_utc": datetime.now(timezone.utc).isoformat(),
        }

        results.append(result)

    report = {
        "project": "PostgreSQL DBA Architect Agent",
        "source_run": RUN_ID,
        "normalization_version": "1.0",
        "total_documents": len(results),
        "documents": results,
    }

    report_path = METADATA_DIR / f"normalized_manifest_{RUN_ID}.json"
    report_path.write_text(
        json.dumps(report, indent=4),
        encoding="utf-8"
    )

    print("\nNORMALIZATION COMPLETED")
    print("Documents:", len(results))
    print("Output:", OUTPUT_DIR)
    print("Manifest:", report_path)


if __name__ == "__main__":
    main()
