"""FastAPI app: JSON API under /api plus a small browser UI at /."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import data, exports

BASE = Path(__file__).parent
app = FastAPI(title="pilot-target", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def _role(x_role: str | None) -> str:
    """Trial-grade auth: the role comes from a header. Good enough to test permission paths."""
    return data.ROLE_ADMIN if x_role == data.ROLE_ADMIN else data.ROLE_VIEWER


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/api/reports")
def api_reports(x_role: str | None = Header(default=None)) -> list[dict]:
    return [r.to_dict() for r in data.list_reports(_role(x_role))]


@app.get("/api/reports/{report_id}")
def api_report(report_id: int, x_role: str | None = Header(default=None)) -> dict:
    r = data.get_report(report_id, _role(x_role))
    if r is None:
        raise HTTPException(status_code=404, detail="report not found")
    return r.to_dict()


# H-2..H-5 (contract §4). Content-Type is set via media_type below.
_EXPORT_HEADERS = {
    "Content-Disposition": 'attachment; filename="reports.csv"',
    "Cache-Control": "no-store",
    "Vary": "X-Role",
    "X-Content-Type-Options": "nosniff",
}


@app.get("/api/exports/reports.csv")
def api_export_reports_csv(x_role: str | None = Header(default=None)) -> Response:
    # R1 (§1): GET-only list export, no query params (§2/§5: any that arrive are ignored).
    # One permission path, reused verbatim: data.list_reports(_role(x_role)) is the only filter.
    body = exports.render_reports_csv(data.list_reports(_role(x_role)))
    # C-5: encode the str body exactly once and hand bytes to Response; no newline translation.
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers=dict(_EXPORT_HEADERS),
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"title": "Reports"})
