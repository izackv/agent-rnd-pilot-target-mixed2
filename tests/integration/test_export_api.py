"""Integration tests for ``GET /api/exports/reports.csv`` (contract v1.1 §§1-5, as amended by the
final board answers in register ``4833d53b``: Q1 four columns, Q2 dated filename, Q3 no BOM).

Role parity (field-subset), cache/security headers (H-1..H-6), error matrix (E1/E2/E3/E9/E10),
query-param ignored, the F1 whole-field J-06 scan and the F2 single-permission-path pin. Seeded
rows come only from the ``app.data._REPORTS`` test seam; no production switch."""

from __future__ import annotations

import ast
import csv
import inspect
import io
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import data, main
from app.data import Report
from app.exports import CSV_HEADER
from app.main import app

client = TestClient(app)

EXPORT = "/api/exports/reports.csv"
VIEWER_IDS = {"1", "2", "4"}
# Report 3's whole field values (v2/Q1: ``restricted`` is not a column, so only these can leak).
RESTRICTED_VALUES = (b"Payroll summary", b"finance", b"310")
DATED_DISPOSITION = re.compile(r'attachment; filename="reports-(\d{4}-\d{2}-\d{2})\.csv"')


def parse_bytes(raw: bytes) -> list[list[str]]:
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\xef\xbb\xbf" not in raw  # v2/Q3: no BOM
    return list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))


def data_rows(raw: bytes) -> list[list[str]]:
    return parse_bytes(raw)[1:]


def tuples_from_json(items: list[dict]) -> set[tuple[str, str, str, str]]:
    return {(str(x["id"]), x["title"], x["owner"], str(x["rows"])) for x in items}


def utc_filename_date() -> str:
    return datetime.now(UTC).date().isoformat()


# --- I-1: every 200 carries H-1..H-6 ------------------------------------------------------------
def test_export_headers_present_both_roles():
    for headers in ({}, {"X-Role": "admin"}):
        r = client.get(EXPORT, headers=headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/csv; charset=utf-8"  # H-1
        m = DATED_DISPOSITION.fullmatch(r.headers["content-disposition"])  # H-2 (v2/Q2)
        assert m and m.group(1) == utc_filename_date()  # server UTC date, server clock only
        assert r.headers["cache-control"] == "no-store"  # H-3
        assert r.headers["vary"] == "X-Role"  # H-4
        assert r.headers["x-content-type-options"] == "nosniff"  # H-5
        assert r.headers["content-length"] == str(len(r.content))  # H-6


# --- I-2: CSV row set == JSON row set projected to four columns (SET equality) -------------------
def test_role_parity_vs_json_endpoint():
    for role_headers in ({}, {}, {"X-Role": "admin"}, {"X-Role": "viewer"}):
        export = client.get(EXPORT, headers=role_headers).content
        assert parse_bytes(export)[0] == [*CSV_HEADER] == ["id", "title", "owner", "rows"]
        csv_set = {tuple(row) for row in data_rows(export)}
        json_set = tuples_from_json(client.get("/api/reports", headers=role_headers).json())
        assert csv_set == json_set


def test_admin_includes_restricted_row_viewer_does_not():
    admin_rows = data_rows(client.get(EXPORT, headers={"X-Role": "admin"}).content)
    viewer_rows = data_rows(client.get(EXPORT).content)
    assert {row[0] for row in admin_rows} == VIEWER_IDS | {"3"}
    assert {row[0] for row in viewer_rows} == VIEWER_IDS
    # v2/Q1: identical four-column schema for both roles; no restricted column anywhere
    assert all(len(row) == 4 for row in admin_rows + viewer_rows)
    all_cells = {cell for row in admin_rows + viewer_rows for cell in row}
    assert not all_cells & {"true", "false"}


# --- F2: the single permission path is structural, not just behavioural ---------------------------
def test_export_endpoint_has_exactly_one_permission_call():
    tree = ast.parse(inspect.getsource(main))
    fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "api_export_reports_csv"
    )
    permission_calls = [
        node
        for node in ast.walk(fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "list_reports"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "data"
    ]
    assert len(permission_calls) == 1  # no second filter may exist in the endpoint
    assert "restricted" not in inspect.getsource(main.api_export_reports_csv)


def test_rendered_rows_are_what_list_reports_returns(monkeypatch):
    # A behaviour-equivalent inline ``restricted`` check would drop these rows for a viewer.
    sentinel = [Report(1, "a", "ops", 1, False), Report(9, "R", "finance", 9, True)]
    expected = {(str(r.id), r.title, r.owner, str(r.rows)) for r in sentinel}
    seen: list[str] = []

    def fake_list_reports(role: str) -> list[Report]:
        seen.append(role)
        return list(sentinel)

    monkeypatch.setattr(data, "list_reports", fake_list_reports)
    for headers, want_role in (({}, data.ROLE_VIEWER), ({"X-Role": "admin"}, data.ROLE_ADMIN)):
        seen.clear()
        rows = data_rows(client.get(EXPORT, headers=headers).content)
        assert seen == [want_role]  # exactly one call, with the resolved role
        assert {tuple(row) for row in rows} == expected  # emitted verbatim, no post-filter


# --- I-3 / J-06 (F1): a viewer artifact leaks no restricted data (whole-field scan) ---------------
def test_viewer_export_leaks_no_restricted_values():
    raw = client.get(EXPORT).content
    cells = {cell for row in data_rows(raw) for cell in row}
    assert "3" not in {row[0] for row in data_rows(raw)}
    # F1 (test-plan-v2 §22): compare whole parsed cells byte-for-byte -- a substring scan
    # false-positives on clean files (e.g. an owner "francis" or a title mentioning "310").
    cell_bytes = {cell.encode("utf-8") for cell in cells}
    for value in RESTRICTED_VALUES:
        assert value not in cell_bytes
        assert value.decode() not in cells


# --- I-5: full M1 role sweep, all viewer-classified (E1/E2/E3, fail-closed) ---------------------
@pytest.mark.parametrize(
    "headers",
    [
        {},  # E1 absent
        {"X-Role": "viewer"},
        {"X-Role": "root"},  # E2
        {"X-Role": "Admin"},  # E2 wrong case
        {"X-Role": "ADMIN"},
        {"X-Role": ""},  # E2 empty
        {"X-Role": " admin"},  # E2 padded
    ],
    ids=["E1-absent", "viewer", "E2-root", "E2-Admin", "E2-ADMIN", "E2-empty", "E2-padded"],
)
def test_viewer_classified_roles_all_yield_viewer_rows(headers):
    rows = data_rows(client.get(EXPORT, headers=headers).content)
    assert {row[0] for row in rows} == VIEWER_IDS


def test_duplicate_role_headers_first_value_wins():
    admin_first = client.get(EXPORT, headers=[("X-Role", "admin"), ("X-Role", "viewer")])
    assert {row[0] for row in data_rows(admin_first.content)} == VIEWER_IDS | {"3"}
    viewer_first = client.get(EXPORT, headers=[("X-Role", "viewer"), ("X-Role", "admin")])
    assert {row[0] for row in data_rows(viewer_first.content)} == VIEWER_IDS


# --- I-4 / E10: methods other than GET are 405, JSON, no CSV, no Content-Disposition -------------
def test_non_get_is_405():
    for method in (client.post, client.put, client.delete):
        r = method(EXPORT)
        assert r.status_code == 405
        assert r.headers["content-type"] == "application/json"
        assert "content-disposition" not in r.headers
        assert b"\xef\xbb\xbf" not in r.content  # error responses emit no CSV or BOM bytes


# --- I-11: unknown query params ignored (a second permission input must not exist) --------------
def test_unknown_query_param_ignored():
    rows = data_rows(client.get(EXPORT + "?role=admin").content)
    assert {row[0] for row in rows} == VIEWER_IDS


# --- I-7 / E9: empty permitted set returns header-only bytes (order exact) -----------------------
def test_empty_set_header_only(monkeypatch):
    monkeypatch.setattr(data, "_REPORTS", [])
    r = client.get(EXPORT)
    assert r.status_code == 200
    assert r.content == ",".join(CSV_HEADER).encode("utf-8") + b"\r\n"


# --- I-8: round-trip the cell classes through the real route via the _REPORTS seam ---------------
def test_seeded_cell_classes_round_trip_via_route(monkeypatch):
    monkeypatch.setattr(
        data,
        "_REPORTS",
        [
            Report(1, "Q1, Q2 revenue", "ops", 1, False),
            Report(2, 'She said "ship it"', "sre", 2, False),
            Report(3, '=HYPERLINK("http://x","c")', "finance", 3, True),
        ],
    )
    parsed = parse_bytes(client.get(EXPORT, headers={"X-Role": "admin"}).content)
    titles = {row[0]: row[1] for row in parsed[1:]}
    assert titles["1"] == "Q1, Q2 revenue"
    assert titles["2"] == 'She said "ship it"'
    assert titles["3"] == '\'=HYPERLINK("http://x","c")'  # active -> single-apostrophe prefix


# --- Q2 boundary: the date comes from the server clock, not the request --------------------------
def test_filename_date_ignores_request_input():
    r = client.get(EXPORT + "?date=1999-01-01", headers={"X-Role": "admin"})
    m = DATED_DISPOSITION.fullmatch(r.headers["content-disposition"])
    assert m and m.group(1) == utc_filename_date()  # query param cannot steer the filename


# --- I-10: buffered, Content-Length matches body length (no chunked streaming) -------------------
def test_buffered_content_length_matches_body():
    r = client.get(EXPORT, headers={"X-Role": "admin"})
    assert r.headers["content-length"] == str(len(r.content))
    assert "transfer-encoding" not in r.headers


# --- I-12: existing endpoints unchanged (AC5 regression) ------------------------------------------
def test_existing_json_endpoints_unaffected():
    assert [x["id"] for x in client.get("/api/reports").json()] == [1, 2, 4]
    assert [x["id"] for x in client.get("/api/reports", headers={"X-Role": "admin"}).json()] == [
        1,
        2,
        3,
        4,
    ]
    assert client.get("/api/reports/3").status_code == 404
