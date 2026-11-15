"""
frontend_mount.py -- serve the built React frontend (frontend/dist) from the FastAPI app.

  /          -> frontend/dist/index.html   (the new UI)   [falls back to static/index.html if the frontend was never built]
  /assets/*  -> frontend/dist/assets/*
  /legacy    -> static/index.html          (the old single-file UI, kept as a safety net)

Optional: to host the frontend on another origin (Vercel/Netlify), build it with VITE_BACKEND_URL=https://<backend>
and start the backend with CORS_ORIGINS=https://<frontend>  (comma-separated list). Same-origin needs neither.
PITFALL: routes are matched in the order they are registered, so mount_frontend(app) must run BEFORE app.py defines its own "/".
"""
import os
import pathlib

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

HERE = pathlib.Path(__file__).resolve().parent
DIST = HERE / "frontend" / "dist"
LEGACY = HERE / "static" / "index.html"


def mount_frontend(app: FastAPI) -> None:
    origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"])

    if (DIST / "index.html").exists():
        if (DIST / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def _index():
            return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})

    if LEGACY.exists():
        @app.get("/legacy", include_in_schema=False)
        def _legacy():
            return FileResponse(LEGACY)
