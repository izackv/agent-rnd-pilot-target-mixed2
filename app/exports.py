"""CSV rendering for the report export endpoints.

Implements contract v1.1 §3 (clauses C-1..C-11) for ``app``-level exports. No HTTP, no data
access: callers pass the already-permission-filtered rows that ``app.data.list_reports`` returned.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from io import StringIO

from app.data import Report

# C-4: the BOM is a single module-level constant and is never request-controllable.
CSV_BOM = "\ufeff"

# C-7: identical columns for every role (parity with Report.to_dict()).
CSV_HEADER = ("id", "title", "owner", "rows", "restricted")

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
    """Build the export body as one ``str``: BOM + header + one record per report (C-6).

    ``csv.writer`` emits CRLF records and quotes a field iff it contains the delimiter, a quote,
    CR or LF (C-1/C-2). The buffer is opened ``newline=""`` so embedded CR/LF/CRLF pass through
    unchanged, and this function returns a ``str`` for the caller to encode exactly once (C-5).
    """
    buffer = StringIO(newline="")  # C-5: forbid newline translation in the text buffer
    writer = csv.writer(buffer, lineterminator="\r\n")  # C-1: stdlib writer, CRLF terminator

    writer.writerow([_field(cell) for cell in CSV_HEADER])
    for report in reports:
        cells = (
            report.id,
            report.title,
            report.owner,
            report.rows,
            "true" if report.restricted else "false",  # C-8: lowercase, JSON parity
        )
        writer.writerow([_field(cell) for cell in cells])

    return CSV_BOM + buffer.getvalue()
