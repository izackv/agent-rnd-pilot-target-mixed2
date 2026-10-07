"""Unit tests for the pure CSV writer (contract v1.1 §3), with no HTTP layer.

Covers: header-once (U-1), the six brief cell classes round-tripped (U-2), C-11 neutralisation
matrix (U-3), lowercase ``restricted`` (U-4) and single-BOM emission (U-5)."""

from __future__ import annotations

import ast
import csv
import inspect
import io
from pathlib import Path

import pytest

from app import exports
from app.data import Report

CSV_PATH = Path(exports.__file__)
ORACLE_HEADER = ["id", "title", "owner", "rows", "restricted"]


def parse(body: str) -> list[list[str]]:
    """The RFC 4180 oracle from the test plan §3 (utf-8-sig, newline='')."""
    return list(csv.reader(io.StringIO(body.encode("utf-8").decode("utf-8-sig"), newline="")))


def render_one(title: str) -> str:
    return exports.render_reports_csv([Report(1, title, "owner", 42, False)])


# --- the brief's six cell classes + QA additions (SP-1..SP-20) ------------------------------------
SP_FIXTURES: list[tuple[str, str]] = [
    ("SP-1 comma", "Q1, Q2 revenue"),
    ("SP-2 quote", 'She said "ship it"'),
    ("SP-3 quote-at-end", '5" monitor'),
    ("SP-4 LF in cell", "line1\nline2\n"),
    ("SP-5 CRLF in cell", "a\r\nb"),
    ("SP-6 unicode", "Üniverse — 東京 🚀 דף"),
    ("SP-7 leading zeros", "0012"),
    ("SP-8 thousands", "1,234.56"),
    ("SP-9 sci-notation", "12E50"),
    ("SP-10 big int", "12345678901234567890"),
    ("SP-11 equals", "=SUM(1,2)"),
    ("SP-12 plus", "+1-2"),
    ("SP-13 minus", "-2+3"),
    ("SP-14 at+comma", "@SUM(1,2)*cmd"),
    ("SP-15 leading TAB", "\t=1+1"),
    ("SP-16 leading LF", "\nhi"),
    ("SP-17 leading CR", "\rhi"),
    ("SP-18 over-neutralise detector", "Q1 - Q2 delta"),
    ("SP-19 empty", ""),
]


# --- U-1: header emitted exactly once ----------------------------------------------------------
def test_header_only_for_zero_rows():
    body = exports.render_reports_csv([])
    parsed = parse(body)
    assert parsed == [ORACLE_HEADER]


def test_header_is_first_record_and_constant_columns():
    parsed = parse(exports.render_reports_csv([Report(9, "t", "o", 1, True)]))
    assert parsed[0] == ORACLE_HEADER
    assert all(len(row) == 5 for row in parsed)


# --- U-2: byte-exact round-trip over the cell classes (parsed-cell equality) -------------------
@pytest.mark.parametrize(("name", "value"), SP_FIXTURES, ids=[n for n, _ in SP_FIXTURES])
def test_cell_class_round_trip(name, value):
    parsed = parse(render_one(value))
    assert len(parsed) == 2
    active = value[:1] in exports.ACTIVE_PREFIXES
    expected = "'" + value if active else value
    assert parsed[1][1] == expected


def test_crlf_inside_field_is_byte_preserved():
    # C-5/D1: an embedded CRLF stays CRLF inside the quoted field; records stay CRLF-delimited.
    body = render_one("a\r\nb").encode("utf-8")
    assert b'"a\r\nb"' in body  # field bytes preserved verbatim
    records = body[len(exports.CSV_BOM.encode("utf-8")) :].split(b"\r\n")
    assert records[0] == ",".join(ORACLE_HEADER).encode()


# --- U-3: C-11 neutralisation matrix -----------------------------------------------------------
ACTIVE_LEADERS = ["=", "+", "-", "@", "\t", "\r", "\n"]


@pytest.mark.parametrize("lead", ACTIVE_LEADERS)
def test_every_active_char_is_neutralised(lead):
    assert exports.neutralise(lead + "text") == "'" + lead + "text"


def test_neutralise_is_prefix_only():
    # containment-only and empty must NOT be mutated (over-neutralisation guard).
    assert exports.neutralise("Q1 - Q2 delta") == "Q1 - Q2 delta"
    assert exports.neutralise("a=b") == "a=b"
    assert exports.neutralise("1=on") == "1=on"
    assert exports.neutralise("") == ""


def test_double_active_prefix_uses_single_apostrophe():
    assert exports.neutralise("=+1") == "'=+1"


def test_field_helper_only_touches_strings():
    assert exports._field(123) == 123  # ints pass through untouched, never neutralised
    assert exports._field(-5) == -5  # a legitimately negative integer is unchanged
    assert exports._field("=x") == "'=x"


def test_integer_columns_never_neutralised():
    parsed = parse(exports.render_reports_csv([Report(-7, "ok", "o", -3, False)]))
    assert parsed[1][0] == "-7"  # negative id emitted as plain digits, no apostrophe
    assert parsed[1][3] == "-3"


def test_single_call_site_of_neutralise():
    tree = ast.parse(CSV_PATH.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "neutralise"
    ]
    # exactly one call site (inside _field); the def itself is not a Call.
    assert len(calls) == 1
    assert "neutralise" in inspect.getsource(exports._field)


# --- U-4: restricted rendered lowercase (parity with JSON) ----------------------------------------
def test_restricted_lowercase_boolean():
    for flag, word in ((True, "true"), (False, "false")):
        parsed = parse(exports.render_reports_csv([Report(1, "t", "o", 5, flag)]))
        assert parsed[1][4] == word


# --- U-5: BOM emitted once from the module constant ----------------------------------------------
def test_bom_prefix_once_and_matches_constant():
    body = render_one("plain")
    raw = body.encode("utf-8")
    assert raw.startswith(b"\xef\xbb\xbf")
    assert body.startswith(exports.CSV_BOM)
    assert exports.CSV_BOM == "\ufeff"
    # no BOM reappears anywhere after the single prefix
    assert body.count(exports.CSV_BOM) == 1
    assert raw.count(b"\xef\xbb\xbf") == 1
