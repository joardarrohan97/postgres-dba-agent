
import json
import subprocess
import sys
import urllib.request

OLLAMA_URL = "http://172.29.48.1:11434/api/embeddings"
MODEL = "nomic-embed-text"

def generate_query_embedding(question):
    payload = {
        "model": MODEL,
        "prompt": question
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode())

    embedding = result["embedding"]

    if len(embedding) != 768:
        raise ValueError("Unexpected embedding dimensions")

    return embedding

def search(question, limit=5):
    embedding = generate_query_embedding(question)

    vector = "[" + ",".join(
        f"{value:.8f}" for value in embedding
    ) + "]"

    sql = f"""
    SELECT
        topic,
        ROUND((1 - (embedding <=> '{vector}'::vector))::numeric, 4)
            AS similarity,
        LEFT(content, 500) AS content_preview
    FROM dba_agent.knowledge_chunks
    ORDER BY embedding <=> '{vector}'::vector
    LIMIT {int(limit)};
    """

    command = [
        "sudo", "-u", "postgres",
        "psql", "-d", "postgres_dba_lab",
        "-X", "-P", "pager=off",
        "-c", sql
    ]

    subprocess.run(command, check=True)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python semantic_search.py "Your DBA question"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])

    print(f"\nQuestion: {question}\n")
    search(question)
