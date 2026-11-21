
import json
import sys
import urllib.request
import urllib.error
import subprocess

OLLAMA_BASE_URL = "http://172.29.48.1:11434"
EMBEDDING_MODEL = "nomic-embed-text"
CHAT_MODEL = "qwen3.5:4b"

TOP_K = 5
TIMEOUT = 300


def ollama_request(endpoint, payload):
    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama HTTP {error.code}: {details}")


def generate_embedding(question):
    result = ollama_request(
        "/api/embeddings",
        {
            "model": EMBEDDING_MODEL,
            "prompt": question
        }
    )

    embedding = result.get("embedding", [])

    if len(embedding) != 768:
        raise ValueError(
            f"Expected 768 embedding dimensions, got {len(embedding)}"
        )

    return embedding


def retrieve_documents(question):
    embedding = generate_embedding(question)

    vector = "[" + ",".join(
        f"{value:.8f}" for value in embedding
    ) + "]"

    sql = f"""
    SELECT COALESCE(json_agg(result), '[]'::json)::text
    FROM (
        SELECT
            chunk_id,
            topic,
            source_url,
            content,
            ROUND(
                (1 - (embedding <=> '{vector}'::vector))::numeric,
                4
            ) AS similarity
        FROM dba_agent.knowledge_chunks
        ORDER BY embedding <=> '{vector}'::vector
        LIMIT {TOP_K}
    ) AS result;
    """

    command = [
        "sudo", "-u", "postgres",
        "psql",
        "-d", "postgres_dba_lab",
        "-X", "-qAt",
        "-c", sql
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True
    )

    return json.loads(result.stdout.strip())


def build_prompt(question, documents):
    context = []

    for index, document in enumerate(documents, start=1):
        context.append(
            f"""
SOURCE {index}
Topic: {document.get("topic")}
URL: {document.get("source_url")}
Similarity: {document.get("similarity")}

Content:
{document.get("content")}
"""
        )

    context_text = "\n".join(context)

    system_prompt = """
You are a PostgreSQL Database Administrator assistant.

Your task is to provide technically accurate, evidence-grounded
PostgreSQL DBA guidance.

RULES:

1. Use the retrieved PostgreSQL documentation as your primary evidence.
2. Never invent documentation, configuration values, SQL results,
   server metrics, or database conditions.
3. Clearly distinguish documented facts from your own recommendations
   and assumptions.
4. If retrieved evidence is insufficient, explicitly say so.
5. For troubleshooting, provide an ordered diagnostic approach.
6. Include practical SQL or Linux commands where relevant.
7. Explain what each diagnostic command checks and how to interpret it.
8. Do not claim that a command was executed.
9. Do not recommend destructive operations without explaining risks.
10. Never execute SQL or modify a database.

Structure your response using:

- Understanding the problem
- Relevant documentation findings
- Diagnostic steps
- Recommended SQL/commands
- Interpretation of possible results
- Sources

IMPORTANT:
You only have documentation context. You do not have live access to
the user's database metrics or production environment.
Request relevant diagnostic outputs when necessary.
"""

    user_prompt = f"""
DBA QUESTION:
{question}

RETRIEVED DOCUMENTATION:
{context_text}

Prepare a practical PostgreSQL DBA response using the instructions.
Cite sources using their source URLs.
"""

    return system_prompt, user_prompt


def generate_answer(question, documents):
    system_prompt, user_prompt = build_prompt(question, documents)

    result = ollama_request(
        "/api/chat",
        {
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": 8192
            }
        }
    )

    return result["message"]["content"]


def main():
    if len(sys.argv) < 2:
        print(
            'Usage: python knowledge_ingestion/embeddings/'
            'rag_answer.py "Your DBA question"'
        )
        sys.exit(1)

    question = " ".join(sys.argv[1:])

    print("\n========================================")
    print("POSTGRESQL DBA RAG ASSISTANT")
    print("========================================")
    print(f"\nQuestion: {question}")

    print("\n[1/3] Retrieving relevant documentation...")

    documents = retrieve_documents(question)

    if not documents:
        print("No relevant documentation found.")
        return

    print(f"Retrieved {len(documents)} passages.")

    print("\n[2/3] Generating DBA analysis with Qwen...")

    answer = generate_answer(question, documents)

    print("\n[3/3] DBA ASSISTANT RESPONSE")
    print("========================================\n")
    print(answer)

    print("\n========================================")
    print("RETRIEVED SOURCES")
    print("========================================")

    for index, document in enumerate(documents, start=1):
        print(
            f"{index}. {document.get('topic')} "
            f"| Similarity: {document.get('similarity')}"
        )
        print(f"   {document.get('source_url')}")


if __name__ == "__main__":
    main()
