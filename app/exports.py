"""CSV rendering for the report export endpoints.

Implements contract v1.1 §3 (clauses C-1..C-11) as amended by the final board answers
(register ``4833d53b``, contract v2 Q1/Q3): the server emits **no BOM** and the columns are
exactly ``id,title,owner,rows`` for both roles. No HTTP, no data access: callers pass the
already-permission-filtered rows that ``app.data.list_reports`` returned.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from io import StringIO

from app.data import Report

# C-7 (v2/Q1): identical columns for every role; ``restricted`` is never emitted, so roles differ
# only in row membership, never in schema (a field-subset of the JSON endpoint).
CSV_HEADER = ("id", "title", "owner", "rows")

# C-11: a string field is "active" iff its first character is one of these.
ACTIVE_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def neutralise(value: str) -> str:
    """Prepend one apostrophe to formula-active text (C-11). Pure; no CSV/formatting logic.

    Spreadsheets evaluate a cell that *starts* with an active character, so only the first
    character is tested; prose that merely contains one (e.g. ``Q1 - Q2 delta``) is untouched.
    Integers are never routed here (see ``_field``), so real negatives stay real.
    """
    if value[:1] in ACTIVE_PREFIXES:
        return "'" + value
    return value


def _field(value: object) -> object:
    """The single call site of :func:`neutralise`, applied to every string field (C-11)."""
    return neutralise(value) if isinstance(value, str) else value


def render_reports_csv(reports: Iterable[Report]) -> str:
    """Build the export body as one ``str``: header + one record per report (C-6).

    ``csv.writer`` emits CRLF records and quotes a field iff it contains the delimiter, a quote,
    CR or LF (C-1/C-2). The buffer is opened ``newline=""`` so embedded CR/LF/CRLF pass through
    unchanged, and this function returns a ``str`` for the caller to encode exactly once (C-5).
    V2/Q3: no BOM here -- the server response is plain UTF-8; the BOM belongs to the browser
    download path only.
    """
    buffer = StringIO(newline="")  # C-5: forbid newline translation in the text buffer
    writer = csv.writer(buffer, lineterminator="\r\n")  # C-1: stdlib writer, CRLF terminator

    writer.writerow([_field(cell) for cell in CSV_HEADER])
    for report in reports:
        cells = (report.id, report.title, report.owner, report.rows)
        writer.writerow([_field(cell) for cell in cells])

    return buffer.getvalue()
