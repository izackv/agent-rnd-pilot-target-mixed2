"""Integration tests for ``GET /api/exports/reports.csv`` (contract v1.1 R1, §§1-5).

Role parity, cache/security headers (H-1..H-6), error matrix (E1/E2/E3/E9/E10) and query-param
ignored, per the DUA-8 test plan tiers I-1..I-11 / I-14. Seeded rows come only from the
``app.data._REPORTS`` test seam; no production switch."""

from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient

from app import data
from app.data import Report
from app.exports import CSV_BOM, CSV_HEADER
from app.main import app

client = TestClient(app)

EXPORT = "/api/exports/reports.csv"
VIEWER_IDS = {"1", "2", "4"}
RESTRICTED_VALUES = (b"Payroll", b"summary", b"finance", b"310")


def parse_bytes(raw: bytes) -> list[list[str]]:
    assert raw.startswith(b"\xef\xbb\xbf") and raw.count(b"\xef\xbb\xbf") == 1  # R-6 / BOM once
    return list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))


def data_rows(raw: bytes) -> list[list[str]]:
    return parse_bytes(raw)[1:]


def tuples_from_json(items: list[dict]) -> set[tuple[str, str, str, str, str]]:
    return {
        (
            str(x["id"]),
            x["title"],
            x["owner"],
            str(x["rows"]),
            "true" if x["restricted"] else "false",
        )
        for x in items
    }


# --- I-1: every 200 carries H-1..H-6 ------------------------------------------------------------
def test_export_headers_present_both_roles():
    for headers in ({}, {"X-Role": "admin"}):
        r = client.get(EXPORT, headers=headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/csv; charset=utf-8"  # H-1
        assert r.headers["content-disposition"] == 'attachment; filename="reports.csv"'  # H-2
        assert r.headers["cache-control"] == "no-store"  # H-3
        assert r.headers["vary"] == "X-Role"  # H-4
        assert r.headers["x-content-type-options"] == "nosniff"  # H-5
        assert r.headers["content-length"] == str(len(r.content))  # H-6


# --- I-2: CSV row set == JSON row set for the same role (SET equality, order unasserted) --------
def test_role_parity_vs_json_endpoint():
    for role_headers in ({}, {}, {"X-Role": "admin"}, {"X-Role": "viewer"}):
        export = client.get(EXPORT, headers=role_headers).content
        csv_set = {tuple(row) for row in data_rows(export)}
        json_set = tuples_from_json(client.get("/api/reports", headers=role_headers).json())
        assert csv_set == json_set


def test_admin_includes_restricted_row_viewer_does_not():
    admin = {row[0] for row in data_rows(client.get(EXPORT, headers={"X-Role": "admin"}).content)}
    viewer = {row[0] for row in data_rows(client.get(EXPORT).content)}
    assert admin == VIEWER_IDS | {"3"} and viewer == VIEWER_IDS
    admin_rows = data_rows(client.get(EXPORT, headers={"X-Role": "admin"}).content)
    assert sum(1 for row in admin_rows if row[4] == "true") == 1  # exactly one restricted=true


# --- I-3 / J-06: a viewer artifact leaks no restricted data (parsed + raw bytes) -----------------
def test_viewer_export_leaks_no_restricted_values():
    r = client.get(EXPORT)
    for row in data_rows(r.content):
        assert row[0] != "3"
        assert row[4] == "false"  # N3: no truthy restricted for a viewer
    for value in RESTRICTED_VALUES:  # supplementary raw-byte scan (never the sole check)
        assert value not in r.content


# --- I-5: full M1 role sweep, all viewer-classified (E1/E2/E3, fail-closed) ---------------------
def test_viewer_classified_roles_all_yield_viewer_rows():
    cases = [
        {},  # E1 absent
        {"X-Role": "viewer"},
        {"X-Role": "root"},  # E2
        {"X-Role": "Admin"},  # E2 wrong case
        {"X-Role": "ADMIN"},
        {"X-Role": ""},  # E2 empty
        {"X-Role": " admin"},  # E2 padded
    ]
    for headers in cases:
        rows = data_rows(client.get(EXPORT, headers=headers).content)
        assert {row[0] for row in rows} == VIEWER_IDS, headers


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
        assert b"\xef\xbb\xbf" not in r.content  # error responses emit no CSV bytes


# --- I-11: unknown query params ignored (a second permission input must not exist) --------------
def test_unknown_query_param_ignored():
    rows = data_rows(client.get(EXPORT + "?role=admin").content)
    assert {row[0] for row in rows} == VIEWER_IDS


# --- I-7 / E9: empty permitted set returns header-only bytes (order exact) -----------------------
def test_empty_set_header_only(monkeypatch):
    monkeypatch.setattr(data, "_REPORTS", [])
    r = client.get(EXPORT)
    assert r.status_code == 200
    assert r.content == CSV_BOM.encode("utf-8") + ",".join(CSV_HEADER).encode("utf-8") + b"\r\n"


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
