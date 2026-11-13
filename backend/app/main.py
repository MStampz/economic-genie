import importlib
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import auth_routes, finance_routes, group_routes
from app.core.categories import ensure_default_categories
from app.core.deps import require_client_header
from app.db import get_engine
from app.ingestion import routes as import_routes
from app.modules import MODULES


@asynccontextmanager
async def lifespan(app: FastAPI):
    with Session(get_engine()) as db:
        ensure_default_categories(db)
    yield


def create_app(seed: bool = True) -> FastAPI:
    app = FastAPI(
        title="Economic Genie",
        lifespan=lifespan if seed else None,
        dependencies=[Depends(require_client_header)],
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    for r in (auth_routes.router, group_routes.router, finance_routes.router, import_routes.router):
        app.include_router(r)
    for name in MODULES:
        module = importlib.import_module(f"app.modules.{name}")
        flag = getattr(module, "FEATURE_FLAG", None)
        if flag is None or getattr(get_settings(), flag, False):
            app.include_router(module.router)

    @app.get("/api/health")
    def health():
        s = get_settings()
        return {"ok": True, "features": {"coach": s.feature_coach}}

    return app


app = create_app()
