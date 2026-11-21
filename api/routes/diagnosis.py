import asyncio
import logging
import secrets

from fastapi import APIRouter, Header, HTTPException
from api.config import API_KEY, API_MODE
from api.schemas import DiagnosisRequest, DiagnosisResponse

router = APIRouter(prefix="/api/v1", tags=["Diagnosis"])
logger = logging.getLogger(__name__)
_live_lock = asyncio.Semaphore(1)


def require_live_key(provided_key: str | None):
    if not API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Live API authentication is not configured."
        )
    if not provided_key or not secrets.compare_digest(provided_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API key.")


@router.post("/demo/diagnosis")
def demo_diagnosis(request: DiagnosisRequest):
    return DiagnosisResponse(
        status="COMPLETED",
        mode="demo",
        question=request.question,
        answer=(
            "This is sample portfolio data, not a live database diagnosis. "
            "The demonstration shows how the DBA platform presents metrics. "
            "No database connection or SQL execution was performed."
        ),
        diagnostic="demo",
        read_only=True,
        metrics={
            "connection_pressure": {
                "classification": "NORMAL",
                "utilization_percent": 1.0,
                "total_connections": 1,
                "max_connections": 100
            },
            "transaction_lock": {
                "severity": "NORMAL",
                "blocking_count": 0,
                "long_transactions": 0,
                "idle_in_transaction": 0
            },
            "incident_correlation": {
                "severity": "NORMAL",
                "confidence": "HIGH",
                "incident_count": 0
            }
        },
        evidence={
            "data_source": "synthetic_demo_data",
            "database_accessed": False,
            "sql_executed": False
        }
    )


@router.post("/diagnosis", response_model=DiagnosisResponse)
async def live_diagnosis(
    request: DiagnosisRequest,
    x_api_key: str | None = Header(default=None)
):
    require_live_key(x_api_key)

    if API_MODE != "live":
        raise HTTPException(
            status_code=403,
            detail="Live diagnosis is disabled. Configure API mode explicitly."
        )

    async with _live_lock:
        try:
            result = await asyncio.to_thread(
                _run_existing_orchestrator,
                request.question
            )
            return DiagnosisResponse(
                status="COMPLETED",
                mode="live",
                **result
            )
        except Exception as exc:
            logger.exception("Live diagnosis failed")
            raise HTTPException(
                status_code=503,
                detail="Live diagnosis failed. Check the private backend logs."
            ) from exc


def _run_existing_orchestrator(question: str) -> dict:
    from agents.orchestrator import run_orchestrator

    result = run_orchestrator(question)
    if not isinstance(result, dict):
        raise RuntimeError(
            "Orchestrator did not return a structured result."
        )
    return result
