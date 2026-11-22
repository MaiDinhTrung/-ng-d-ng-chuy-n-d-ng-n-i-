from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config  # noqa: F401  (đặt biến môi trường trước khi import zerotts)
from .api.routes import router
from .engines import get_engines
from .services import tts_service
from .storage import db


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.conn()
    tts_service.start_worker()
    for e in get_engines().values():
        if hasattr(e, "start_loading"):
            e.start_loading()  # nạp model ở thread nền, UI hiển thị trạng thái
    yield


app = FastAPI(title="Local AI Voice Studio", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(router)

_dist = config.BACKEND_DIR.parent / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        f = (_dist / full_path).resolve()
        if full_path and _dist.resolve() in f.parents and f.is_file():
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
