from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, Response
import time
import json
from sqlalchemy import inspect
from app.config import settings
from app.database.database import Base, sync_engine
from app.routers import (
    auth, users, repositories, pull_requests,
    analysis, security, code_quality, tests, reports, health, explorer,
    webhooks, audit_logs, chat, dead_letter_queue, insights
)

def init_db():
    try:
        inspector = inspect(sync_engine)
        tables = inspector.get_table_names()
        
        # If database is empty or missing core tables, initialize and stamp it
        if not tables or "analyses" not in tables:
            print("Database is empty or missing core tables. Initializing tables and stamping head...")
            Base.metadata.create_all(bind=sync_engine)
            try:
                import os
                from alembic.config import Config
                from alembic import command
                
                ini_path = "backend/alembic.ini" if os.path.exists("backend/alembic.ini") else "alembic.ini"
                if os.path.exists(ini_path):
                    alembic_cfg = Config(ini_path)
                    command.stamp(alembic_cfg, "head")
                    print(f"Database stamped with Alembic head version successfully using config: {ini_path}")
                else:
                    print("alembic.ini not found, skipping database stamping.")
            except Exception as stamp_err:
                print(f"Failed to stamp database: {stamp_err}")
        else:
            print("Database already initialized. Running migration upgrade head to ensure columns are synced...")
            try:
                import os
                from alembic.config import Config
                from alembic import command
                
                ini_path = "backend/alembic.ini" if os.path.exists("backend/alembic.ini") else "alembic.ini"
                if os.path.exists(ini_path):
                    alembic_cfg = Config(ini_path)
                    command.upgrade(alembic_cfg, "head")
                    print(f"Database migration upgrade head completed successfully using config: {ini_path}")
                else:
                    print("alembic.ini not found, skipping database migration upgrade.")
            except Exception as migration_err:
                print(f"Failed to run database migrations: {migration_err}")
    except Exception as e:
        print(f"Database table initialization failed: {e}")

# (FastAPI app created below after lifespan handler is defined)

# Custom Middlewares for Security Hardening
class SecureHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Build dynamic connect-src from configured CORS origins
        cors_origins = settings.BACKEND_CORS_ORIGINS
        connect_sources = "'self'"
        for origin in cors_origins.split(","):
            origin = origin.strip()
            if origin:
                connect_sources += f" {origin}"
                # Also allow WebSocket variant
                ws_origin = origin.replace("http://", "ws://").replace("https://", "wss://")
                connect_sources += f" {ws_origin}"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            f"connect-src {connect_sources}; "
            "img-src 'self' data:;"
        )
        return response

class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            allowed_origins = [origin.strip() for origin in settings.BACKEND_CORS_ORIGINS.split(",") if origin.strip()]
            
            # Origin check
            if origin and origin not in allowed_origins:
                return Response(
                    content=json.dumps({"detail": "CSRF verification failed: invalid origin."}),
                    status_code=403,
                    media_type="application/json"
                )
            # Referer check fallback
            elif referer:
                from urllib.parse import urlparse
                ref_origin = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
                if ref_origin not in allowed_origins:
                    return Response(
                        content=json.dumps({"detail": "CSRF verification failed: invalid referer."}),
                        status_code=403,
                        media_type="application/json"
                    )
        return await call_next(request)

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int = 300, window: int = 60):
        super().__init__(app)
        self.limit = limit
        self.window = window
        self.requests = {}

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
            
        if "websocket" in request.scope.get("type", "") or request.url.path in ["/docs", "/openapi.json", "/api/v1/health", "/"]:
            return await call_next(request)
            
        # Exempt authenticated dashboard polling
        if request.url.path.endswith("/users/me/dashboard") and request.headers.get("authorization", "").startswith("Bearer "):
            return await call_next(request)
            
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        
        timestamps = self.requests.get(client_ip, [])
        timestamps = [t for t in timestamps if now - t < self.window]
        
        if len(timestamps) >= self.limit:
            return Response(
                content=json.dumps({"detail": "Rate limit exceeded. Please try again later."}),
                status_code=429,
                media_type="application/json"
            )
            
        timestamps.append(now)
        self.requests[client_ip] = timestamps
        return await call_next(request)

# CORS Configuration
configured_origins = [origin.strip() for origin in settings.BACKEND_CORS_ORIGINS.split(",") if origin.strip()]

# ── Lifespan handler (replaces deprecated @app.on_event("startup")) ──
@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    init_db()
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Enterprise-grade RepoLens AI API with GitHub and multi-provider LLM integrations.",
    version="1.0.0",
    docs_url="/docs",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Secure Headers, CSRF, and Rate Limiting
app.add_middleware(SecureHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(RateLimitMiddleware, limit=300, window=60)


# Include Routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(users.router, prefix=settings.API_V1_STR)
app.include_router(repositories.router, prefix=settings.API_V1_STR)
app.include_router(pull_requests.router, prefix=settings.API_V1_STR)
app.include_router(analysis.router, prefix=settings.API_V1_STR)
app.include_router(analysis.analyses_router, prefix=settings.API_V1_STR)
app.include_router(security.router, prefix=settings.API_V1_STR)
app.include_router(code_quality.router, prefix=settings.API_V1_STR)
app.include_router(tests.router, prefix=settings.API_V1_STR)
app.include_router(reports.router, prefix=settings.API_V1_STR)
app.include_router(health.router, prefix=settings.API_V1_STR)
app.include_router(explorer.router, prefix=settings.API_V1_STR)
app.include_router(webhooks.router, prefix=settings.API_V1_STR)
app.include_router(audit_logs.router, prefix=settings.API_V1_STR)
app.include_router(chat.router, prefix=settings.API_V1_STR)
app.include_router(dead_letter_queue.router, prefix=settings.API_V1_STR)
app.include_router(insights.router, prefix=settings.API_V1_STR)

@app.get("/")
def read_root():
    return {
        "message": "Welcome to the RepoLens AI API",
        "documentation": "/docs",
        "health_check": f"{settings.API_V1_STR}/health"
    }

