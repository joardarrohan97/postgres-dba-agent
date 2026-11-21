import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator


# --------------------------------------------------
# PROJECT PATHS
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
CLEANED_DIR = BASE_DIR / "data" / "cleaned"
METADATA_DIR = BASE_DIR / "metadata"
REPORT_DIR = BASE_DIR / "reports"

DOC_BASE = "https://www.postgresql.org/docs/18/"

# --------------------------------------------------
# INITIAL DOCUMENTATION COLLECTION
# --------------------------------------------------

DOCUMENTS = [
    # Original documentation collection
    ("architecture", "Architectural Fundamentals", "tutorial-arch.html"),
    ("monitoring", "Monitoring Database Activity", "monitoring.html"),
    ("memory", "Resource Consumption", "runtime-config-resource.html"),
    ("connections", "Connection Settings", "runtime-config-connection.html"),
    ("wal", "Write Ahead Log", "wal.html"),
    ("wal-config", "WAL Configuration", "runtime-config-wal.html"),
    ("vacuum", "Routine Vacuuming", "routine-vacuuming.html"),
    ("indexes", "Indexes", "indexes.html"),
    ("explain", "Using EXPLAIN", "using-explain.html"),
    ("backup", "Backup and Restore", "backup.html"),

    # Architecture and fundamentals
    ("tutorial-install", "Installation and Setup", "tutorial-install.html"),
    ("tutorial-start", "Getting Started", "tutorial-start.html"),
    ("tutorial-createdb", "Creating a Database", "tutorial-createdb.html"),

    # Monitoring and observability
    ("monitoring-ps", "Monitoring Server Processes", "monitoring-ps.html"),
    ("monitoring-stats", "Monitoring Statistics", "monitoring-stats.html"),
    ("monitoring-locks", "Monitoring Locks", "monitoring-locks.html"),
    ("progress-reporting", "Progress Reporting", "progress-reporting.html"),
    ("diskusage", "Database Disk Usage", "diskusage.html"),

    # WAL, reliability and recovery
    ("wal-reliability", "WAL Reliability", "wal-reliability.html"),
    ("wal-intro", "WAL Introduction", "wal-intro.html"),
    ("wal-async-commit", "Asynchronous Commit", "wal-async-commit.html"),
    ("wal-configuration", "WAL Configuration and Management", "wal-configuration.html"),
    ("wal-internals", "WAL Internals", "wal-internals.html"),

    # Indexing
    ("indexes-intro", "Introduction to Indexes", "indexes-intro.html"),
    ("indexes-types", "Index Types", "indexes-types.html"),
    ("indexes-multicolumn", "Multicolumn Indexes", "indexes-multicolumn.html"),
    ("indexes-ordering", "Indexes and ORDER BY", "indexes-ordering.html"),
    ("indexes-bitmap-scans", "Combining Multiple Indexes", "indexes-bitmap-scans.html"),
    ("indexes-unique", "Unique Indexes", "indexes-unique.html"),
    ("indexes-expressional", "Indexes on Expressions", "indexes-expressional.html"),
    ("indexes-partial", "Partial Indexes", "indexes-partial.html"),
    ("indexes-index-only-scans", "Index-Only Scans", "indexes-index-only-scans.html"),
    ("indexes-examine", "Examining Index Usage", "indexes-examine.html"),

    # Backup and recovery
    ("backup-dump", "SQL Dump and Restore", "backup-dump.html"),
    ("backup-file", "File System Level Backup", "backup-file.html"),
    ("continuous-archiving", "Continuous Archiving and PITR", "continuous-archiving.html"),
]


# --------------------------------------------------
# CONTENT CLEANING CONFIGURATION
# --------------------------------------------------

# PostgreSQL documentation content extraction.
# Select the documentation container instead of using aggressive pruning.
markdown_generator = DefaultMarkdownGenerator()

crawl_config = CrawlerRunConfig(
    css_selector="#docContent",
    excluded_tags=["script", "style", "nav"],
    markdown_generator=markdown_generator,
    word_count_threshold=1,
    page_timeout=60000,
    remove_overlay_elements=True,
)


# --------------------------------------------------
# UTILITY FUNCTIONS
# --------------------------------------------------

def create_directories():
    for directory in (
        RAW_DIR,
        CLEANED_DIR,
        METADATA_DIR,
        REPORT_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def extract_title(markdown):
    match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    return match.group(1).strip() if match else "Title not detected"


def extract_markdown(result):
    markdown_result = result.markdown

    if isinstance(markdown_result, str):
        content = markdown_result
    else:
        content = getattr(markdown_result, "raw_markdown", "") or ""
        if not content:
            content = getattr(markdown_result, "fit_markdown", "") or ""

    # CSS selection already restricts extraction to PostgreSQL documentation.
    # Do not apply the lossy pruning filter.
    return content, content, False


def safe_slug(value):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", value)


# --------------------------------------------------
# CRAWL ONE DOCUMENT
# --------------------------------------------------

async def crawl_document(crawler, document, run_id):
    key, topic, filename = document
    url = DOC_BASE + filename

    print(f"\n{'=' * 65}")
    print(f"Topic: {topic}")
    print(f"URL: {url}")

    record = {
        "key": key,
        "topic": topic,
        "url": url,
        "version": "18",
        "status": "failed",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = await crawler.arun(
            url=url,
            config=crawl_config,
        )

        if not result.success:
            record["error"] = getattr(
                result, "error_message", "Unknown crawl error"
            )
            print("FAILED:", record["error"])
            return record

        raw, cleaned, fallback = extract_markdown(result)

        if not raw.strip():
            record["error"] = "No Markdown content extracted"
            print("FAILED: Empty Markdown")
            return record

        slug = safe_slug(key)

        raw_path = RAW_DIR / f"{run_id}_{slug}.md"
        cleaned_path = CLEANED_DIR / f"{run_id}_{slug}.md"

        raw_path.write_text(raw, encoding="utf-8")
        cleaned_path.write_text(cleaned, encoding="utf-8")

        record.update({
            "status": "success",
            "title": extract_title(raw),
            "raw_file": str(raw_path.relative_to(BASE_DIR)),
            "cleaned_file": str(cleaned_path.relative_to(BASE_DIR)),
            "raw_characters": len(raw),
            "cleaned_characters": len(cleaned),
            "extraction_method": "css_selector:#docContent",
            "fallback_used": False,
            "cleaning_reduction_percent": round(
                (1 - len(cleaned) / len(raw)) * 100, 2
            ) if raw else 0,
        })

        print("SUCCESS")
        print("Raw characters:", len(raw))
        print("Cleaned characters:", len(cleaned))
        print("Extraction method: CSS #docContent")

    except Exception as exc:
        record["error"] = str(exc)
        print("ERROR:", exc)

    return record


# --------------------------------------------------
# MAIN INGESTION PIPELINE
# --------------------------------------------------

async def main():
    create_directories()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    records = []

    print("POSTGRESQL DOCUMENTATION INGESTION")
    print("Version: PostgreSQL 18")
    print("Documents:", len(DOCUMENTS))
    print("Run ID:", run_id)

    async with AsyncWebCrawler() as crawler:
        for document in DOCUMENTS:
            record = await crawl_document(
                crawler,
                document,
                run_id,
            )
            records.append(record)

            # Be respectful to the documentation server.
            await asyncio.sleep(1.5)

    successful = sum(
        record["status"] == "success" for record in records
    )

    failed = len(records) - successful

    manifest = {
        "project": "PostgreSQL DBA Architect Agent",
        "source": "Official PostgreSQL Documentation",
        "postgresql_version": "18",
        "crawler": "Crawl4AI 0.9.5",
        "run_id": run_id,
        "total_documents": len(records),
        "successful_documents": successful,
        "failed_documents": failed,
        "documents": records,
    }

    manifest_path = METADATA_DIR / f"manifest_{run_id}.json"

    manifest_path.write_text(
        json.dumps(manifest, indent=4),
        encoding="utf-8",
    )

    report_path = REPORT_DIR / f"summary_{run_id}.md"

    report = [
        "# PostgreSQL Documentation Ingestion Report",
        "",
        f"- Run ID: {run_id}",
        "- Documentation version: PostgreSQL 18",
        f"- Total documents: {len(records)}",
        f"- Successful: {successful}",
        f"- Failed: {failed}",
        "",
        "## Document Results",
        "",
        "| Topic | Status | Raw chars | Cleaned chars |",
        "|---|---|---:|---:|",
    ]

    for record in records:
        report.append(
            f"| {record['topic']} "
            f"| {record['status']} "
            f"| {record.get('raw_characters', 0)} "
            f"| {record.get('cleaned_characters', 0)} |"
        )

    report_path.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    print("\n" + "=" * 65)
    print("INGESTION COMPLETED")
    print("Successful:", successful)
    print("Failed:", failed)
    print("Manifest:", manifest_path)
    print("Report:", report_path)


if __name__ == "__main__":
    asyncio.run(main())
