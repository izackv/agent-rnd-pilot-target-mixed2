"""Contract §6 UI touchpoint + contract v2 D3/D4: the "Export CSV" control on `/`.

The export endpoint itself belongs to the backend slice (DUA-12, PR #2) and may not be merged
with this branch, so these tests stub the route in the browser (the plan pre-approved: "UI may
proceed against the approved contract plus a local stub, in parallel with backend"). What is
pinned here is the *client* contract: role in the header read at click time, never a query
parameter; BOM prepended client-side as the last step of blob assembly over byte-exact API
content (D3); filename from Content-Disposition when parseable, else `reports.csv` (§6);
non-200 writes `Error <status>` into `#status` with no navigation and no partial file.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Route, expect

CSV_BOM = b"\xef\xbb\xbf"
EXPORT_PATH = "/api/exports/reports.csv"

CD = "Content-Disposition"
DISPOSITION_OK = {CD: 'attachment; filename="reports-2026-10-07.csv"'}
CSV_HEADERS = {"Content-Type": "text/csv; charset=utf-8"}


class Captured:
    def __init__(self) -> None:
        self.requests: list = []


def stub_export(
    page: Page,
    captured: Captured,
    body: bytes,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> None:
    def handler(route: Route) -> None:
        captured.requests.append(route.request)
        route.fulfill(status=status, body=body, headers={**CSV_HEADERS, **(headers or {})})

    page.route(f"**{EXPORT_PATH}", handler)


def open_page(page: Page, base_url: str) -> None:
    page.goto(base_url + "/")
    expect(page.locator("#reports tbody tr")).to_have_count(3)
    expect(page.locator("#status")).to_have_text("3 reports")


def click_export(page: Page) -> None:
    page.get_by_role("button", name="Export CSV").click()


def exported_body(
    page: Page,
    base_url: str,
    body: bytes,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
):
    """Open the page, click the control once, return (download, captured requests)."""
    captured = Captured()
    stub_export(page, captured, body, status=status, headers=headers)
    open_page(page, base_url)
    with page.expect_download() as info:
        click_export(page)
    return info.value, captured.requests


def test_button_exists_and_page_stable(page: Page, base_url: str) -> None:
    open_page(page, base_url)
    button = page.get_by_role("button", name="Export CSV")
    expect(button).to_be_visible()
    # §6: reachable exactly the way the e2e journeys drive it; table journey J-01 unaffected.
    page.get_by_label("role").select_option("admin")
    expect(page.locator("#reports tbody tr")).to_have_count(4)


def test_normal_viewer_download_is_bom_plus_exact_bytes(page: Page, base_url: str) -> None:
    body = b'id,title,owner,rows\r\n1,Site audit,qa,12\r\n2,"Roadmap, Q3",pm,7\r\n'
    download, requests = exported_body(page, base_url, body, headers=DISPOSITION_OK)
    assert download.suggested_filename == "reports-2026-10-07.csv"  # §6: from Content-Disposition
    # D3(a/b): the API bytes carry NO BOM; the download is exactly BOM + those bytes.
    with Path(download.path()).open("rb") as f:
        assert f.read() == CSV_BOM + body
    assert len(requests) == 1
    req = requests[0]
    assert req.headers["x-role"] == "viewer"  # header, value of the current select (§6)
    parsed = urlparse(req.url)
    assert parsed.path == EXPORT_PATH
    assert parsed.query == ""  # §6 FORBIDDEN: role (or anything) as a query parameter


@pytest.mark.parametrize("disposition", [None, "attachment", 'attachment; filename="'])
def test_filename_falls_back_when_not_parseable(page: Page, base_url: str, disposition) -> None:
    body = b"id,title,owner,rows\r\n"
    headers = dict(CSV_HEADERS)
    if disposition is not None:
        headers[CD] = disposition
    download, _ = exported_body(page, base_url, body, headers=headers)
    assert download.suggested_filename == "reports.csv"  # §6 literal fallback


def test_filename_star_is_never_read(page: Page, base_url: str) -> None:
    # D4: the server must not send filename*; if some peer does, parsing it is OFF-limits.
    download, _ = exported_body(
        page,
        base_url,
        b"id,title,owner,rows\r\n",
        headers={CD: "attachment; filename*=UTF-8''weird%20name.csv"},
    )
    assert download.suggested_filename == "reports.csv"


def test_role_is_read_at_click_time(page: Page, base_url: str) -> None:
    captured = Captured()
    stub_export(page, captured, b"id,title,owner,rows\r\n", headers=DISPOSITION_OK)
    open_page(page, base_url)
    page.get_by_label("role").select_option("admin")  # no reload happens
    expect(page.locator("#reports tbody tr")).to_have_count(4)
    with page.expect_download() as info:
        click_export(page)
    assert info.value.suggested_filename == "reports-2026-10-07.csv"
    assert captured.requests[-1].headers["x-role"] == "admin"


def test_bytes_pass_through_untouched(page: Page, base_url: str) -> None:
    # D3(c)/C-5: no decode/re-encode path may transform bytes. Payload mixes multi-byte UTF-8,
    # an embedded CR LF inside a quoted field, and BOM-looking bytes mid-cell.
    body = (
        'id,title,owner,rows\r\n1,café naïf,ø,3\r\n2,"line1\r\nline2",x,4\r\n3,\ufeffmid, y ,5\r\n'
    ).encode()
    assert body.count(CSV_BOM) == 1 and not body.startswith(CSV_BOM)
    download, _ = exported_body(page, base_url, body, headers=DISPOSITION_OK)
    with Path(download.path()).open("rb") as f:
        content = f.read()
    assert content == CSV_BOM + body
    assert content.count(CSV_BOM) == 2  # signature + the mid-cell occurrence, unchanged


def test_empty_boundary_rowset_downloads_header_only(page: Page, base_url: str) -> None:
    download, _ = exported_body(page, base_url, b"id,title,owner,rows\r\n", headers=DISPOSITION_OK)
    with Path(download.path()).open("rb") as f:
        assert f.read() == CSV_BOM + b"id,title,owner,rows\r\n"


@pytest.mark.parametrize(
    ("status", "label"), [(400, "Error 400"), (404, "Error 404"), (500, "Error 500")]
)
def test_non_200_writes_status_without_download_or_navigation(
    page: Page, base_url: str, status: int, label: str
) -> None:
    captured = Captured()
    stub_export(page, captured, b"boom", status=status)
    open_page(page, base_url)
    context = page.context
    pages_before = len(context.pages)
    click_export(page)
    expect(page.locator("#status")).to_have_text(label)  # §6: existing #status pattern
    assert page.url == base_url + "/"  # no navigation
    with pytest.raises(PlaywrightError):  # expect_download times out => no file ever started
        with page.expect_download(timeout=1000):
            page.wait_for_timeout(1000)
    assert len(context.pages) == pages_before  # no new tab
    assert urlparse(captured.requests[-1].url).query == ""


def test_download_button_sends_no_body_and_stays_get(page: Page, base_url: str) -> None:
    captured = Captured()
    stub_export(page, captured, b"id,title,owner,rows\r\n")
    open_page(page, base_url)
    with page.expect_download():
        click_export(page)
    assert captured.requests[-1].method == "GET"
    assert not captured.requests[-1].post_data


def test_app_js_has_no_bypass_patterns() -> None:
    # §6/D3(c) FORBIDDEN list, checked at the source of the module the control ships in.
    source = Path(__file__).resolve().parents[2].joinpath("app/static/app.js").read_text()
    for forbidden in ("window.location", "res.text()", "TextDecoder", "role="):
        assert not re.search(re.escape(forbidden), source), forbidden
    assert re.search(r"fetch\(\"/api/exports/reports\.csv\"", source)
    assert source.count("new Blob(") == 1  # one blob assembly site, BOM prepended there
