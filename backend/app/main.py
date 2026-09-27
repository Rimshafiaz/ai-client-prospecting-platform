import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger, request_id_contextvar
from app.api.routes.users import router as user_router
from app.api.routes.companies import router as company_router
from app.api.routes.research_requests import router as research_requests_router
from app.api.routes.reports import router as reports_router
from app.api.routes.company_discovery import router as company_discovery_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.campaigns import router as campaigns_router
from app.api.routes.outreach_attempts import router as outreach_attempts_router
from app.api.routes.gmail_connections import router as gmail_connections_router

configure_logging()
logger = get_logger(__name__)

app = FastAPI(
    title = settings.app_name,
    version = settings.app_version,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(user_router)
app.include_router(company_router)
app.include_router(research_requests_router)
app.include_router(reports_router)
app.include_router(company_discovery_router)
app.include_router(dashboard_router)
app.include_router(campaigns_router)
app.include_router(outreach_attempts_router)
app.include_router(gmail_connections_router)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = uuid.uuid4().hex
    request_id_contextvar.set(request_id)

    started = time.perf_counter()
    status_code = "-"
    try:
        response = await call_next(request)
        status_code = response.status_code
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "%s %s -> %s (%.0f ms)",
            request.method,
            request.url.path,
            status_code,
            duration_ms,
        )

    response.headers["X-Request-ID"] = request_id
    return response


register_exception_handlers(app)


@app.on_event("startup")
def warm_database_connection() -> None:

    from app.db.session import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        db.execute(text("select 1"))
    finally:
        db.close()


@app.get("/", summary="Welcome message")
def root():
    return {"message" : "Welcome to AI Sales Intelligence Platform"}

@app.get("/health", summary="Health check", tags=["Health"])
def health():
    return {"status" : "healthy"}


@app.get("/ready", summary="Readiness check", tags=["Health"])
def ready():
    from app.db.session import SessionLocal
    from sqlalchemy import text
    from sqlalchemy.exc import SQLAlchemyError

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except SQLAlchemyError as error:
        logger.exception("Database readiness check failed")
        raise HTTPException(status_code=503, detail="Database is not ready.") from error
    finally:
        db.close()
