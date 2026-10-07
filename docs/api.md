# API

Role is supplied by the `X-Role` header (`viewer` default, `admin`). This is trial-grade
authentication, chosen so permission paths can be tested without an identity provider.

| Method | Path | Behavior |
|---|---|---|
| GET | `/healthz` | `{"status": "ok", "version": ...}` |
| GET | `/api/reports` | Reports visible to the role. Restricted reports are admin-only. |
| GET | `/api/reports/{id}` | One report, or 404 if missing or not visible to the role. |

## Accepted user journeys

| ID | Journey | Test |
|---|---|---|
| J-01 | Viewer opens the reports page and sees permitted reports; admin sees the restricted one too | `tests/e2e/test_journey.py` |
| UI export control | "Export CSV" button on `/` fetches the export route with the current role in `X-Role`, then downloads it as a CSV file (BOM prepended client-side only; API bytes stay BOM-free); non-200 shows `Error <status>` in the status region | `tests/e2e/test_export_control.py` |
