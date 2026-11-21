
import hashlib
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = ROOT / "data/chunks/chunks_20261120T074258Z.jsonl"
OUTPUT_FILE = ROOT / "data/embeddings/embeddings_20261120T074258Z.jsonl"

OLLAMA_URL = "http://172.29.48.1:11434/api/embeddings"
MODEL = "nomic-embed-text"
DIMENSIONS = 768

MAX_CHARS = 1800
OVERLAP_CHARS = 150


def split_content(content):
    parts = []
    start = 0

    while start < len(content):
        end = min(start + MAX_CHARS, len(content))

        if end < len(content):
            boundary = max(
                content.rfind("\n", start + 1200, end),
                content.rfind(" ", start + 1200, end)
            )
            if boundary > start:
                end = boundary

        piece = content[start:end].strip()

        if piece:
            parts.append(piece)

        if end >= len(content):
            break

        start = max(end - OVERLAP_CHARS, start + 1)

    return parts


def embed(content):
    payload = {
        "model": MODEL,
        "prompt": content
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )

    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode())

            vector = result.get("embedding", [])

            if len(vector) != DIMENSIONS:
                raise ValueError(
                    f"Expected {DIMENSIONS} dimensions, got {len(vector)}"
                )

            return vector

        except Exception as error:
            print(f"Attempt {attempt}/3: {error}", flush=True)
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def main():
    chunks = [
        json.loads(line)
        for line in INPUT_FILE.open(encoding="utf-8")
        if line.strip()
    ]

    represented = set()

    if OUTPUT_FILE.exists():
        with OUTPUT_FILE.open(encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    record = json.loads(line)
                    represented.add(
                        record.get("parent_chunk_id", record["chunk_id"])
                    )

    missing = [
        chunk for chunk in chunks
        if chunk["chunk_id"] not in represented
    ]

    print(f"Original chunks: {len(chunks)}")
    print(f"Already represented: {len(represented)}")
    print(f"Chunks requiring repair: {len(missing)}")

    repaired = 0
    failed = 0

    with OUTPUT_FILE.open("a", encoding="utf-8") as output:
        for chunk in missing:
            parent_id = chunk["chunk_id"]
            segments = split_content(chunk["content"])

            print(
                f"Repairing {parent_id}: {len(segments)} segments",
                flush=True
            )

            try:
                for index, content in enumerate(segments, start=1):
                    vector = embed(content)

                    child_id = hashlib.sha256(
                        f"{parent_id}:{index}".encode()
                    ).hexdigest()[:20]

                    record = {
                        **chunk,
                        "chunk_id": child_id,
                        "parent_chunk_id": parent_id,
                        "segment_index": index,
                        "segment_count": len(segments),
                        "content": content,
                        "word_count": len(content.split()),
                        "embedding_model": MODEL,
                        "embedding_dimensions": DIMENSIONS,
                        "embedding": vector
                    }

                    output.write(
                        json.dumps(record, ensure_ascii=False) + "\n"
                    )
                    output.flush()

                repaired += 1

            except Exception as error:
                failed += 1
                print(f"FAILED {parent_id}: {error}", flush=True)

    print("\nRepair completed.")
    print(f"Original chunks repaired: {repaired}")
    print(f"Failed original chunks: {failed}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
