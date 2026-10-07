# API

Role is supplied by the `X-Role` header (`viewer` default, `admin`). This is trial-grade
authentication, chosen so permission paths can be tested without an identity provider.

| Method | Path | Behavior |
|---|---|---|
| GET | `/healthz` | `{"status": "ok", "version": ...}` |
| GET | `/api/reports` | Reports visible to the role. Restricted reports are admin-only. |
| GET | `/api/reports/{id}` | One report, or 404 if missing or not visible to the role. |
| GET | `/api/exports/reports.csv` | CSV of the reports visible to the role — see **CSV export** below. |

## CSV export

`GET /api/exports/reports.csv` streams no data: it is buffered and returns a **plain UTF-8** CSV
body with **no BOM** (per the final board answers, register `4833d53b` Q3; the BOM belongs only to
the browser download path). Columns are `id,title,owner,rows` for **both** roles (identical schema;
Q1) — `restricted` is never a column, so the CSV is a field-subset of `GET /api/reports` and roles
differ only in row membership. `id` and `rows` are plain integers. Records are CRLF-terminated; a
CR/LF inside a field value is preserved byte-for-byte inside a quoted field. String values that
begin with `=`, `+`, `-`, `@`, TAB, CR or LF are prefixed with a single `'` so a spreadsheet treats
them as inert text rather than a formula. The row set uses the same permission filter as
`GET /api/reports` (`X-Role` header only; anything not exactly `admin` is a viewer), so a download
never contains a restricted report the requester may not see. Because the role header is never
rejected, a request for this route always gets a `200`; non-GET methods get `405` and unknown
query parameters are ignored. A successful response is `text/csv; charset=utf-8` carrying
`Content-Disposition: attachment; filename="reports-YYYY-MM-DD.csv"` (Q2 — the server's UTC date at
response time, never steerable by the request), `Content-Length` equal to the body (the response is
buffered, not streamed), `Cache-Control: no-store`, `Vary: X-Role` — so a permission-filtered body
is never served from a cache to a different role — and `X-Content-Type-Options: nosniff`. An empty
permitted set returns 200 with the header row only.

To read the API response from another consumer, decode the bytes as UTF-8 — the API response is
UTF-8 with no BOM. Open the text with `newline=""` so embedded newlines are not translated:

```python
import csv, io, urllib.request

raw = urllib.request.urlopen(url).read()
rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline="")))
# pandas: pandas.read_csv(path_to_saved_csv, encoding="utf-8")
```

A file saved from the browser download contains byte-identical data preceded by the three-byte
UTF-8 BOM (`EF BB BF`), which the page's export script adds so spreadsheets auto-detect UTF-8.
Strip or account for that prefix when diffing a saved download against the API bytes.

## Accepted user journeys

Journey IDs follow the accepted test plan; brief IDs are kept in parentheses.

| ID | Journey | Test |
|---|---|---|
| J-01 | Viewer opens the reports page and sees permitted reports; admin sees the restricted one too | `tests/e2e/test_journey.py` |
| J-02 | A viewer exports from the page; the downloaded rows are exactly the rows shown on the page | (brief J1, AC1) `tests/e2e/test_export_control.py` |
| J-03 | An admin exports from the page and gets one extra row — the restricted report; columns are identical to the viewer file | (brief J2, AC1) `tests/e2e/test_export_control.py` |
| J-04 | The role select is read at click time: switching admin→viewer without a reload exports the viewer file, and clicking never navigates | (brief J5) `tests/e2e/test_export_control.py` |
| J-05 | For every role the CSV rows equal the JSON rows projected onto `id,title,owner,rows` (set equality; the CSV is a four-column subset of the JSON fields) | (brief J3, AC2) `tests/integration/test_export_api.py` |
| J-06 | No viewer-classified request or artifact on any export path contains restricted data | (brief J4a, AC3) `tests/integration/test_export_api.py` |
| J-08 | Cell classes round-trip a spreadsheet intact: commas, quotes, embedded newlines, accents/emoji/RTL, and formula-like text stays inert (`'`-prefixed) | (AC4) `tests/integration/test_export_api.py`, plus manual proof in Excel (Windows/macOS) and Google Sheets before release |
| J-09 | The permission model and the existing endpoints are untouched by the export | (AC5) existing suites, unmodified: `tests/unit/test_data.py`, `tests/integration/test_api.py`, `tests/e2e/test_journey.py` |
