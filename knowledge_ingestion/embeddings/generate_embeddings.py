
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = ROOT / "data/chunks/chunks_20261120T074258Z.jsonl"
OUTPUT_FILE = ROOT / "data/embeddings/embeddings_20261120T074258Z.jsonl"

OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://172.29.48.1:11434"
).rstrip("/")

MODEL = "nomic-embed-text"
EXPECTED_DIMENSIONS = 768
TIMEOUT = 180
MAX_RETRIES = 3
PROGRESS_INTERVAL = 10


def load_completed_ids():
    completed = set()

    if OUTPUT_FILE.exists():
        with OUTPUT_FILE.open("r", encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    record = json.loads(line)
                    completed.add(record["chunk_id"])

    return completed


def generate_embedding(content):
    url = f"{OLLAMA_BASE_URL}/api/embeddings"

    payload = {
        "model": MODEL,
        "prompt": content
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(
                request,
                timeout=TIMEOUT
            ) as response:
                result = json.loads(response.read().decode("utf-8"))

            embedding = result.get("embedding")

            if not embedding:
                raise ValueError("Ollama returned an empty embedding")

            if len(embedding) != EXPECTED_DIMENSIONS:
                raise ValueError(
                    f"Expected {EXPECTED_DIMENSIONS} dimensions, "
                    f"received {len(embedding)}"
                )

            return embedding

        except Exception as error:
            print(
                f"Attempt {attempt}/{MAX_RETRIES} failed: {error}",
                flush=True
            )

            if attempt == MAX_RETRIES:
                raise

            time.sleep(2 ** attempt)


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Chunk file not found: {INPUT_FILE}"
        )

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    completed = load_completed_ids()

    with INPUT_FILE.open("r", encoding="utf-8") as source:
        chunks = [
            json.loads(line)
            for line in source
            if line.strip()
        ]

    pending = [
        chunk for chunk in chunks
        if chunk["chunk_id"] not in completed
    ]

    print(f"Total chunks: {len(chunks)}")
    print(f"Already embedded: {len(completed)}")
    print(f"Remaining: {len(pending)}")
    print(f"Embedding model: {MODEL}")
    print(f"Output: {OUTPUT_FILE}")

    if not pending:
        print("All chunks already have embeddings.")
        return

    successful = 0
    failed = 0

    with OUTPUT_FILE.open("a", encoding="utf-8") as output:
        for index, chunk in enumerate(pending, start=1):
            try:
                embedding = generate_embedding(chunk["content"])

                record = {
                    **chunk,
                    "embedding_model": MODEL,
                    "embedding_dimensions": len(embedding),
                    "embedding": embedding
                }

                output.write(
                    json.dumps(record, ensure_ascii=False) + "\n"
                )
                output.flush()

                successful += 1

                if index % PROGRESS_INTERVAL == 0:
                    print(
                        f"Progress: {index}/{len(pending)} "
                        f"| Successful: {successful} "
                        f"| Failed: {failed}",
                        flush=True
                    )

            except Exception as error:
                failed += 1
                print(
                    f"FAILED chunk {chunk.get('chunk_id')}: {error}",
                    flush=True
                )

    print("\nEmbedding generation finished.")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Output file: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
