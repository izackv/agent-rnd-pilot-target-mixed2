async function load() {
  const role = document.getElementById("role").value;
  const status = document.getElementById("status");
  status.textContent = "Loading…";
  const res = await fetch("/api/reports", { headers: { "X-Role": role } });
  const tbody = document.querySelector("#reports tbody");
  tbody.innerHTML = "";
  if (!res.ok) { status.textContent = `Error ${res.status}`; return; }
  const rows = await res.json();
  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.dataset.id = r.id;
    tr.innerHTML = `<td>${r.id}</td><td>${r.title}</td><td>${r.owner}</td><td>${r.rows}</td>`;
    tbody.appendChild(tr);
  }
  status.textContent = rows.length ? `${rows.length} reports` : "No reports";
}
document.getElementById("role").addEventListener("change", load);

// C-4 (contract v2 D3): the BOM lives ONLY on the browser download path, prepended client-side
// as the last step of blob assembly, from one constant — never request-derived, never server-side.
const CSV_BOM = new Uint8Array([0xef, 0xbb, 0xbf]);

function downloadFilename(disposition) {
  // §6: the Content-Disposition filename when parseable (H-2/D4: quoted, ASCII, no filename*),
  // else the literal fallback. An unparseable header (absent or malformed) takes the fallback.
  const m = /;\s*filename=(?:"([^"]*)"|([^";]+))/i.exec(disposition || "");
  const name = m ? (m[1] ?? m[2]).trim() : "";
  return name || "reports.csv";
}

async function exportCsv() {
  const role = document.getElementById("role").value; // read at click time (§6)
  const status = document.getElementById("status");
  const res = await fetch("/api/exports/reports.csv", { headers: { "X-Role": role } });
  if (!res.ok) {
    status.textContent = `Error ${res.status}`; // §6: no navigation, no new tab, no partial file
    return;
  }
  // D3(c): arrayBuffer + Blob only — byte-transforming readers are FORBIDDEN here (C-5).
  const blob = new Blob([CSV_BOM, await res.arrayBuffer()], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = downloadFilename(res.headers.get("Content-Disposition"));
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
document.getElementById("export").addEventListener("click", exportCsv);

load();
