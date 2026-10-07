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
never contains a restricted report the requester may not see. Responses carry
`Content-Disposition: attachment; filename="reports-YYYY-MM-DD.csv"` (Q2 — the server's UTC date at
response time, never steerable by the request), plus `Cache-Control: no-store` and `Vary: X-Role` so
a permission-filtered body is never served from a cache to a different role. An empty permitted set
returns 200 with the header row only.

To read the API response from another consumer, decode as `utf-8` and open with `newline=""` so
embedded newlines are not translated (`utf-8-sig` also works and is the right choice for
BOM-prefixed browser downloads — it is a no-op on these BOM-free bytes):

```python
import csv, io, urllib.request

raw = urllib.request.urlopen(url).read()
rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
# pandas: pandas.read_csv("reports.csv", encoding="utf-8-sig")
```

## Accepted user journeys

| ID | Journey | Test |
|---|---|---|
| J-01 | Viewer opens the reports page and sees permitted reports; admin sees the restricted one too | `tests/e2e/test_journey.py` |
| J-05 | API list export matches the JSON endpoint for the same role (per role; set equality) | (brief J3) `tests/integration/test_export_api.py` |
| J-06 | A viewer-classified CSV download never contains restricted data | (brief J4a) `tests/integration/test_export_api.py` |
| UI export control | "Export CSV" button on `/` fetches the export route with the current role in `X-Role`, then downloads it as a CSV file (BOM prepended client-side only; API bytes stay BOM-free); non-200 shows `Error <status>` in the status region | `tests/e2e/test_export_control.py` |
