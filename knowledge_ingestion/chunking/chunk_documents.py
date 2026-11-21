import json
import re
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INPUT_DIR = ROOT / "data" / "normalized"
OUTPUT_DIR = ROOT / "data" / "chunks"
MANIFEST_PATH = ROOT / "metadata" / "normalized_manifest_20261120T074258Z.json"

RUN_ID = "20261120T074258Z"

TARGET_WORDS = 800
MAX_WORDS = 1000
OVERLAP_WORDS = 120

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def estimate_tokens(text):
    # Conservative initial approximation.
    return int(len(text.split()) * 1.35)


def split_blocks(text):
    return re.split(r"\n\s*\n", text.strip())


def split_large_block(block):
    words = block.split()
    if len(words) <= MAX_WORDS:
        return [block]

    parts = []
    start = 0
    while start < len(words):
        end = min(start + MAX_WORDS, len(words))
        parts.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - OVERLAP_WORDS

    return parts


def build_chunks(text):
    blocks = split_blocks(text)
    chunks = []
    current = []
    current_words = 0
    heading_context = []

    def flush():
        nonlocal current, current_words

        if not current:
            return

        body = "\n\n".join(current)
        context = " > ".join(heading_context)

        chunks.append({
            "heading_context": context,
            "content": body,
            "word_count": len(body.split()),
            "estimated_tokens": estimate_tokens(body),
        })

        current = []
        current_words = 0

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        if re.match(r"^#{1,6}\s+", block):
            flush()
            heading_context.append(
                re.sub(r"^#{1,6}\s+", "", block).strip()
            )
            continue

        for part in split_large_block(block):
            count = len(part.split())

            if current_words + count > TARGET_WORDS and current:
                flush()

            current.append(part)
            current_words += count

    flush()
    return chunks


def main():
    manifest = json.loads(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )

    output_file = OUTPUT_DIR / f"chunks_{RUN_ID}.jsonl"
    total_chunks = 0

    with output_file.open("w", encoding="utf-8") as writer:

        for document in manifest["documents"]:
            source = ROOT / document["normalized_file"]

            if not source.exists():
                print("SKIPPED:", source)
                continue

            text = source.read_text(encoding="utf-8")
            chunks = build_chunks(text)

            for index, chunk in enumerate(chunks):
                chunk_id = hashlib.sha256(
                    f'{document["key"]}:{index}:{chunk["content"]}'.encode()
                ).hexdigest()[:20]

                record = {
                    "chunk_id": chunk_id,
                    "document_key": document["key"],
                    "topic": document["topic"],
                    "source_url": document["source_url"],
                    "source_file": document["normalized_file"],
                    "chunk_index": index,
                    "heading_context": chunk["heading_context"],
                    "content": chunk["content"],
                    "word_count": chunk["word_count"],
                    "estimated_tokens": chunk["estimated_tokens"],
                    "postgresql_version": "18",
                }

                writer.write(json.dumps(record, ensure_ascii=False) + "\n")
                total_chunks += 1

    print("\nCHUNKING COMPLETED")
    print("Documents:", len(manifest["documents"]))
    print("Chunks:", total_chunks)
    print("Output:", output_file)


if __name__ == "__main__":
    main()
