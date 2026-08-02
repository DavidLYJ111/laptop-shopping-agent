"""FastAPI entry point serving both the product page and JSON API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse

from shopping_agent.api.routes import router
from shopping_agent.config import WEB_DIR


def create_app() -> FastAPI:
    app = FastAPI(
        title="笔记本智能导购 Agent",
        version="0.2.0",
        description="OpenAI Structured Outputs + deterministic search + local evidence RAG",
    )
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        path = WEB_DIR / "index.html"
        if not path.is_file():
            raise RuntimeError("web/index.html 不存在")
        return FileResponse(path)

    return app


app = create_app()

