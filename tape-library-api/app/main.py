"""FastAPI application entrypoint."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.audit.audit import AuditChain
from app.audit.storage import AuditStorage
from app.commands.runner import CommandRunner
from app.config import settings
from app.jobs import JobManager
from app.models.common import fail
def create_app(audit_dir=None, timeout=None, runner=None):
    app = FastAPI(
        title="Tape Library API",
        version="1.4.0",
        description="REST API for Linux Tape Library management: discovery, library/drive/media "
                    "operations, SCSI diagnostics, read/write tests, full audit trail. "
                    "Safety model: LEVEL_1 read-only, LEVEL_2 device ops, LEVEL_3 write/erase. "
                    "Long-running operations run as async jobs (202 + job_id, poll /api/v1/jobs/{id}).",
    )
    storage = AuditStorage(audit_dir or settings.audit_dir)
    chain = AuditChain(storage)
    app.state.storage = storage
    app.state.chain = chain
    app.state.runner = runner or CommandRunner(storage, timeout=timeout or settings.command_timeout)
    try:
        app.state.runner.audit = storage  # works for MockCommandRunner too
    except Exception:
        pass
    app.state.jobs = JobManager(audit_dir or settings.audit_dir,
                                runner=app.state.runner)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = chain.new_request_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    app.include_router(router)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        if isinstance(exc, JSONResponse):
            return exc
        return JSONResponse(status_code=500, content=fail("INTERNAL_ERROR", str(exc),
                                                          request_id=getattr(request.state, "request_id", "")).model_dump())

    # ---- archive gateway: config API always mounted (gw-config usable before
    # the gateway is running); worker threads only start when enabled+PG healthy ----
    app.state.gateway = None
    try:
        from app.gateway import GatewayConfig, GatewayManager
        from app.gateway.api import router as gateway_api_router
        app.include_router(gateway_api_router)
        gw_cfg = GatewayConfig()
        if gw_cfg.enabled:
            gw = GatewayManager(gw_cfg, runner=app.state.runner, chain=chain)
            gw.start()
            app.state.gateway = gw
    except Exception as e:  # PG down etc: keep the core API up
        print("[gateway] startup failed, continuing without gateway:", e,
              file=sys.stderr)

    @app.get("/", tags=["Meta"])
    def root():
        return {"service": "tape-library-api", "docs": "/docs", "openapi": "/openapi.json"}

    @app.get("/api/v1/safety", tags=["Meta"])
    def safety():
        return {"api_mode": settings.tape_api_mode,
                "allow_device_operation": settings.allow_device_operation,
                "allow_write": settings.allow_write,
                "levels": {"LEVEL_1": True, "LEVEL_2": settings.level_allowed("LEVEL_2"),
                           "LEVEL_3": settings.level_allowed("LEVEL_3")}}

    return app


app = create_app()
