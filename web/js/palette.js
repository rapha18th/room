// ⌘K: every action in one list, filtered as you type, driven by the keyboard.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let list = [], shown = [], at = 0;

function score(label, q) {
  if (!q) return 1;
  const l = label.toLowerCase();
  if (l.startsWith(q)) return 3;
  if (l.includes(q)) return 2;
  let i = 0;
  for (const ch of q) { i = l.indexOf(ch, i); if (i < 0) return 0; i++; }
  return 1;
}

function draw() {
  const q = $("paletteInput").value.trim().toLowerCase();
  shown = list.map((c) => ({ c, s: score(c.label, q) })).filter((x) => x.s > 0).sort((a, b) => b.s - a.s).map((x) => x.c);
  at = Math.min(at, Math.max(0, shown.length - 1));
  $("paletteList").innerHTML = shown.map((c, i) =>
    `<li role="option" data-i="${i}" aria-selected="${i === at}">${esc(c.label)}${c.hint ? `<small>${esc(c.hint)}</small>` : ""}</li>`).join("")
    || `<li aria-disabled="true">Nothing matches</li>`;
  $("paletteList").querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
}

function run(i) {
  const c = shown[i];
  $("palette").close();
  if (c) c.run();
}

export function openPalette(commands) {
  list = commands;
  at = 0;
  $("paletteInput").value = "";
  draw();
  $("palette").showModal();
  $("paletteInput").focus();
}

export function initPalette() {
  $("paletteInput").addEventListener("input", () => { at = 0; draw(); });
  $("paletteInput").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); at = Math.min(at + 1, shown.length - 1); draw(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); at = Math.max(at - 1, 0); draw(); }
    else if (e.key === "Enter") { e.preventDefault(); run(at); }
  });
  $("paletteList").addEventListener("click", (e) => {
    const li = e.target.closest("[data-i]");
    if (li) run(+li.dataset.i);
  });
  $("palette").addEventListener("click", (e) => { if (e.target === $("palette")) $("palette").close(); });
}
