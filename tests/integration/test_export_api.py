"""Integration tests for ``GET /api/exports/reports.csv`` (contract v1.1 §§1-5, as amended by the
final board answers in register ``4833d53b``: Q1 four columns, Q2 dated filename, Q3 no BOM).

Role parity (field-subset), cache/security headers (H-1..H-6), error matrix (E1/E2/E3/E9/E10),
query-param ignored, the J-06 leak scan pinned to report 3's title/whole-row/id (DUA-19 F1) and
the F2 single-permission-path pin. Seeded rows come only from the ``app.data._REPORTS`` test
seam; no production switch."""

from __future__ import annotations

import ast
import csv
import inspect
import io
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import data, exports, main
from app.data import Report
from app.exports import CSV_HEADER
from app.main import app

client = TestClient(app)

EXPORT = "/api/exports/reports.csv"
VIEWER_IDS = {"1", "2", "4"}
# DUA-19 F1: report 3 is pinned by its DISCRIMINATING content — title, whole emitted row and id —
# never by non-unique field values (the old ``finance``/``310``): owner and row-count recur in
# legitimate data, so scanning them false-fails as soon as the dataset grows. Only the ROW is
# restricted (v2/Q1: ``restricted`` is not a column) — the id is the authoritative absence check.
RESTRICTED_ID = "3"
RESTRICTED_TITLE = next(r.title for r in data._REPORTS if str(r.id) == RESTRICTED_ID)
RESTRICTED_TITLE_BYTES = RESTRICTED_TITLE.encode("utf-8")
DATED_DISPOSITION = re.compile(r'attachment; filename="reports-(\d{4}-\d{2}-\d{2})\.csv"')


def restricted_row() -> tuple[str, str, str, str]:
    """Report 3's whole row exactly as the server emits it (read from the admin artifact)."""
    admin = client.get(EXPORT, headers={"X-Role": "admin"}).content
    hits = [tuple(row) for row in data_rows(admin) if row[0] == RESTRICTED_ID]
    assert len(hits) == 1  # the id is unique in the admin artifact
    return hits[0]


# Matrix M1, viewer-classified rows (E1/E2/E3): reused by the row-set sweep and the J-06 Part B
# artifact sweep (test-plan v2 C3 -- every 200 artifact of a viewer-classified request passes both).
M1_VIEWER_HEADERS = [
    pytest.param({}, id="E1-absent"),
    pytest.param({"X-Role": "viewer"}, id="viewer"),
    pytest.param({"X-Role": "root"}, id="E2-root"),
    pytest.param({"X-Role": "Admin"}, id="E2-Admin"),
    pytest.param({"X-Role": "ADMIN"}, id="E2-ADMIN"),
    pytest.param({"X-Role": ""}, id="E2-empty"),
    pytest.param({"X-Role": " admin"}, id="E2-padded"),
]


def boundary_field_encodings(raw: bytes) -> list[bytes]:
    """RFC 4180 field encodings split on bytes with quote-state tracking (BOF/EOF boundaries).

    Deliberately NOT the ``csv`` parser: Part B exists to cross-check bytes a broken parser
    might hide (test-plan v2 C3 -- bad quoting, stray bytes outside records)."""
    fields: list[bytes] = []
    buf = bytearray()
    in_q = False
    i = 0
    while i < len(raw):
        c = raw[i]
        if in_q:
            buf.append(c)
            if c == 0x22:  # closing quote, or a doubled one that stays inside
                if raw[i + 1 : i + 2] == b'"':
                    buf.append(0x22)
                    i += 1
                else:
                    in_q = False
        elif c == 0x22:
            in_q = True
            buf.append(c)
        elif c in (0x2C, 0x0D):  # field separator, or CR of the CRLF record separator
            fields.append(bytes(buf))
            buf = bytearray()
            if c == 0x0D:
                i += 1  # consume the LF as part of the boundary
        else:
            buf.append(c)
        i += 1
    if buf:
        fields.append(bytes(buf))
    return fields


def assert_part_b_no_boundary_occurrence(raw: bytes) -> None:
    """Part B (v2 C3): neither C-2 encoding of the restricted TITLE occurs whole between field
    boundaries. A value inside a longer field is NOT a failure -- anywhere-substring scanning is
    explicitly not the verdict (the false-positive surface the gate corrected). DUA-19 F1: the
    scan targets only the row-discriminating title, never owner/rows values of the restricted
    row, since those recur in legitimate data and false-fail on dataset growth."""
    encodings = {RESTRICTED_TITLE_BYTES} | {
        b'"' + RESTRICTED_TITLE_BYTES.replace(b'"', b'""') + b'"'
    }
    assert not encodings & set(boundary_field_encodings(raw))


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


def test_render_path_never_reads_or_strips_restricted():
    # DUA-19 F4: the emit-then-strip tuple (id,title,owner,rows,restricted)[:4] is BEHAVIOUR-
    # EQUIVALENT to correct code, so no behavioural test can see it (round-2 mutation survivor).
    # Pin it structurally, mirroring the endpoint's single-filter spy above. Same documented
    # caveat as that spy: the literal token may only occur in prose comments (reword those).
    tree = ast.parse(inspect.getsource(exports.render_reports_csv))
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "restricted"
    ]
    assert "restricted" not in inspect.getsource(exports.render_reports_csv)


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


# --- I-3 / J-06 (DUA-19 F1): a viewer artifact leaks no restricted ROW (id/row/title scan) --------
def test_viewer_export_leaks_no_restricted_row():
    raw = client.get(EXPORT).content
    rows = data_rows(raw)
    cells = {cell for row in rows for cell in row}
    # Part A (DUA-19 F1, oracle of record): whole-row-scoped absence, not value-by-value.
    # The id is the authoritative check; title and whole emitted row join it because they are
    # THIS row's content. Non-unique values (an owner like "finance", a 10-bit "310") are NOT
    # scanned -- they legitimately recur and the old scan false-failed the moment data grew.
    assert RESTRICTED_ID not in {row[0] for row in rows}
    assert restricted_row() not in {tuple(row) for row in rows}
    assert RESTRICTED_TITLE not in cells
    assert RESTRICTED_TITLE_BYTES not in {cell.encode("utf-8") for cell in cells}
    # Part B (v2 C3, supplementary, run additive after A): boundary raw-byte scan of the title.
    assert_part_b_no_boundary_occurrence(raw)


def test_part_b_precondition_dataset_has_no_colliding_value():
    # v2 C3 soundness, dataset-anchored: no NON-RESTRICTED report may share the restricted row's
    # TITLE as a whole value, else the title scan cannot name report 3. DUA-19 F1: this is the
    # only collision guard needed -- owner/rows values are no longer scanned, so they may collide
    # with legitimate reports freely (the old three-value guard false-failed as data grew).
    titles = {row[1] for row in data_rows(client.get(EXPORT).content) if row[0] != RESTRICTED_ID}
    assert RESTRICTED_TITLE not in titles


@pytest.mark.parametrize("headers", M1_VIEWER_HEADERS)
def test_viewer_classified_roles_all_yield_viewer_rows(headers):
    rows = data_rows(client.get(EXPORT, headers=headers).content)
    assert {row[0] for row in rows} == VIEWER_IDS


@pytest.mark.parametrize("headers", M1_VIEWER_HEADERS)
def test_every_viewer_artifact_passes_part_a_and_part_b(headers):
    # J-06: EVERY 200 artifact of a viewer-classified request, not just the default one. Part A
    # is row-scoped (DUA-19 F1): no id-3 row, no whole restricted row, no title as a bare cell.
    raw = client.get(EXPORT, headers=headers).content
    assert raw  # a 200 with CSV bytes (fail-closed classification asserted in the sweep above)
    assert_part_b_no_boundary_occurrence(raw)
    rows = data_rows(raw)
    assert RESTRICTED_ID not in {row[0] for row in rows}
    assert restricted_row() not in {tuple(row) for row in rows}
    assert RESTRICTED_TITLE not in {c for row in rows for c in row}


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
    for headers in ({}, {"X-Role": "admin"}):  # v3 Δ2: the dated name is asserted for E9 too
        r = client.get(EXPORT, headers=headers)
        assert r.status_code == 200
        m = DATED_DISPOSITION.fullmatch(r.headers["content-disposition"])
        assert m and m.group(1) == utc_filename_date()  # H-2 applies to every 200, empty included
        assert r.content == ",".join(CSV_HEADER).encode("utf-8") + b"\r\n"


# --- v3 Δ3 / D3(a): a BOM switch must not exist; ?bom= (or any switch) is request-inert ----------
def test_bom_switch_is_request_inert():
    plain = client.get(EXPORT, headers={"X-Role": "admin"})
    for url in (EXPORT + "?bom=true", EXPORT + "?bom=1", EXPORT + "?BOM=true"):
        r = client.get(url, headers={"X-Role": "admin"})
        assert r.status_code == plain.status_code  # ignored, not a second behaviour (D3(a))
        assert r.content == plain.content  # identical bytes -- no server-side BOM path
        assert b"\xef\xbb\xbf" not in r.content


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
