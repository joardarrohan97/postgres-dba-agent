import os
from dotenv import load_dotenv

load_dotenv()

API_TITLE = "PostgreSQL DBA Incident Management Platform"
API_VERSION = "0.1.0"
API_MODE = os.getenv("DBA_AGENT_API_MODE", "demo").strip().lower()
API_KEY = os.getenv("DBA_AGENT_API_KEY", "")
CORS_ORIGINS = [
    item.strip()
    for item in os.getenv(
        "DBA_AGENT_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if item.strip()
]
