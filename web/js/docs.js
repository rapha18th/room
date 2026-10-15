// Files in and out. The server turns a PDF, deck or document into text blocks; the paper shows them
// joined by blank lines; on the way out only the blocks the writer changed go back to the server.

export const KINDS = { pdf: "PDF", pptx: "deck", docx: "document", txt: "text", md: "Markdown" };
const OK = /\.(pdf|pptx|docx|txt|md|markdown)$/i;

export function accepts(file) {
  return file && OK.test(file.name || "");
}

export async function parseFile(file) {
  const fd = new FormData();
  fd.append("file", file, file.name);
  const res = await fetch("/api/doc/parse", { method: "POST", body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Could not open the file (${res.status})`);
  return data;
}

export const joinBlocks = (blocks) => blocks.map((b) => b.text).join("\n\n");

// Where each block starts in the joined text, or null when the text no longer splits into the same blocks.
export function blockStarts(doc, text) {
  const parts = text.split("\n\n");
  if (!doc || parts.length !== doc.blocks.length) return null;
  const starts = [];
  let at = 0;
  for (const p of parts) { starts.push(at); at += p.length + 2; }
  return starts;
}

function save(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

export function downloadText(name, text) {
  save(new Blob([text], { type: "text/plain;charset=utf-8" }), name);
}

// Returns the saved filename. Throws when the paper's text no longer maps onto the file's blocks.
// notes: accepted edits as { before, after, why }; each changed block carries the reasons that touched it.
export async function exportFile(doc, text, notes = [], audience = "") {
  const parts = text.split("\n\n");
  if (parts.length !== doc.blocks.length) {
    throw new Error("The text no longer lines up with the file's paragraphs. Use Download text instead.");
  }
  const reasons = (old, now) => [...new Set(notes
    .filter((n) => n.why && ((n.after && now.includes(n.after)) || (n.before && old.includes(n.before))))
    .map((n) => n.why))].join(" ");
  const changes = doc.blocks.map((b, i) => (parts[i] !== b.text
    ? { id: b.id, text: parts[i], why: reasons(b.text, parts[i]) } : null)).filter(Boolean);
  const fd = new FormData();
  fd.append("file", doc.file, doc.name);
  fd.append("changes", JSON.stringify(changes));
  fd.append("audience", audience);
  const res = await fetch("/api/doc/export", { method: "POST", body: fd });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `Export failed (${res.status})`);
  }
  const cd = res.headers.get("Content-Disposition") || "";
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  const name = m ? decodeURIComponent(m[1]) : doc.name;
  save(await res.blob(), name);
  return { name, changed: changes.length };
}
