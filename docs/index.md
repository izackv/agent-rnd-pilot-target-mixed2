# pilot-target

A deliberately small reports web app. It exists so that an agent team can be evaluated on a
realistic delivery loop: plan → small tickets → PRs → protected merge → release to a real host.

- Browser UI at `/` lists reports visible to the selected role.
- CSV export of what the selected role can see (see **Export CSV** below).
- JSON API under `/api` (see `api.md`).
- Health endpoint `/healthz`.

## Run locally

```
uv sync
uv run uvicorn app.main:app --reload
```

## Export CSV

The **Export CSV** button on `/` downloads `reports-YYYY-MM-DD.csv` containing exactly the reports
the selected role can see, as `id,title,owner,rows` columns. The role is read at click time, so an
admin who switches the select back to viewer gets the viewer's file without reloading the page. A
viewer can never receive a restricted report through any export.

The file opens directly in Excel and Google Sheets — no import dialog — because it is UTF-8 with a
leading BOM, and text that could be mistaken for a spreadsheet formula (`=`, `+`, `-`, `@` leading
characters) is prefixed with `'` so it displays as typed. Real numbers (`id`, `rows`) stay numbers.

The same data is available over HTTP without the button; the API bytes are plain UTF-8 with no BOM
(the download's BOM is added in the browser):

```
curl -H "X-Role: admin" http://localhost:8000/api/exports/reports.csv -o report-copy.csv
```

Encoding mechanics, headers and programmatic read recipes: `api.md`.

## Tests

```
uv run ruff check .
uv run pytest tests/unit tests/integration
uv run playwright install chromium && uv run pytest tests/e2e
```

## Documentation policy

Any change under `app/` must touch `docs/` in the same PR, or the PR description must contain
the line `docs-impact: none` with a one-line reason. The `docs` CI check enforces this.
