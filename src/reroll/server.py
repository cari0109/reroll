"""HTTP transport for the Observatory (`life serve`). The logic lives in observatory.py."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from reroll.narrator import Narrator
from reroll.observatory import (
    CheckoutRequest,
    CommitRequest,
    DecisionRequest,
    Observatory,
    ObservatoryError,
    WhatifRequest,
)
from reroll.params import Params

WEB_DIR = Path(__file__).with_name("web")


def create_app(path: Path, params: Params | None = None, narrator: Narrator | None = None) -> FastAPI:
    obs = Observatory(path, params, narrator)
    app = FastAPI(title="Reroll Observatory", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.exception_handler(ObservatoryError)
    def observatory_error(_: Request, e: ObservatoryError) -> JSONResponse:
        return JSONResponse({"detail": e.detail}, status_code=e.status)

    @app.get("/api/state")
    def state() -> dict:
        return obs.state()

    @app.post("/api/commit")
    def commit(req: CommitRequest) -> dict:
        return obs.commit(req.option)

    @app.post("/api/whatif")
    def whatif(req: WhatifRequest) -> dict:
        return obs.whatif(req.commit, req.option)

    @app.post("/api/decision")
    def decision(req: DecisionRequest) -> dict:
        return obs.set_decision(req)

    @app.post("/api/decision/reset")
    def reset_decision() -> dict:
        return obs.reset_decision()

    @app.post("/api/checkout")
    def checkout(req: CheckoutRequest) -> dict:
        return obs.checkout(req.branch)

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
