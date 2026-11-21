from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import API_TITLE, API_VERSION, CORS_ORIGINS
from api.routes.health import router as health_router
from api.routes.diagnosis import router as diagnosis_router

app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=(
        "A PostgreSQL DBA platform for read-only diagnostics, "
        "incident analysis and historical learning."
    )
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.include_router(health_router)
app.include_router(diagnosis_router)


@app.get("/")
def root():
    return {
        "application": API_TITLE,
        "version": API_VERSION,
        "docs": "/docs",
        "health": "/health"
    }
