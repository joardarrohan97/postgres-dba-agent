import os
from fastapi import APIRouter
from api.config import API_MODE, API_VERSION

router = APIRouter(tags=["Health"])


@router.get("/health")
def health():
    return {"status": "healthy"}


@router.get("/api/v1/status")
def service_status():
    return {
        "status": "operational",
        "api_version": API_VERSION,
        "mode": API_MODE,
        "database_dsn_configured": bool(os.getenv("DBA_AGENT_DSN")),
        "ollama_url_configured": bool(os.getenv("OLLAMA_BASE_URL")),
        "live_diagnosis_enabled": API_MODE == "live",
    }
