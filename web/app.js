import { applyProposal, swapSpan } from "./js/edits.js";
import { runReview } from "./js/review.js";
import { MAX_STOPS, runTour, stopVersion } from "./js/tour.js";
import { accepts, blockStarts, downloadText, exportFile, joinBlocks, KINDS, parseFile } from "./js/docs.js";
import { ticks, transition } from "./js/motion.js";
import { initPalette, openPalette } from "./js/palette.js";

const API = "/api";
const MAX_CITIES = 4;
const PRESETS = ["Dallas", "Atlanta", "Houston", "Chicago", "New York", "Los Angeles", "Philadelphia", "Miami",
  "Toronto", "London", "Manchester", "Paris", "Johannesburg", "Cape Town", "Lagos", "Accra", "Nairobi",
  "Harare", "Mumbai", "Sydney"];
const AGES = [["", "Everyone"], ["24_and_younger", "Under 25"], ["25_to_29,30_to_34", "25 to 34"],
  ["35_to_44,45_to_54", "35 to 54"], ["55_and_older", "55+"]];
const WORD = { lands: "Lands", roast: "Roast", inside: "Inside", dies: "Dies", famous: "Famous",
  global: "Famous", unscored: "Unscored", outside: "Off graph" };
const VALUE = { lands: 1, roast: 0.8, famous: 0.7, global: 0.7, inside: 0.4, dies: 0 };
const LEGEND = {
  lands: "They know it and they love it.",
  roast: "They know it and keep their distance. Good for a jab.",
  inside: "A slice of the room knows it. The ones who do, love it.",
  dies: "A blank for most of the room.",
  famous: "Famous everywhere, with a thin fan base here. Expect recognition and little love.",
  outside: "Foods, slang, holidays and events sit outside Qloo's graph. Room leaves them unscored.",
};
const ACT = { swap: "Swap", drop: "Drop", keep: "Keep" };
const SHORT = { lands: "lands", roast: "roast", inside: "inside", dies: "dies", famous: "famous", global: "famous",
  unscored: "n/a", outside: "off" };
const APPLE = /mac|iphone|ipad/i.test(navigator.userAgentData?.platform || navigator.platform || "");
const MOD = APPLE ? "⌘" : "Ctrl";
const WHO = { you: "You", gemini: "Gemini", qloo: "Qloo", room: "Room" };

const SAMPLES = [
  { name: "Launch ad", slug: "EXT. SUMMER CAMPAIGN", cities: ["Atlanta", "Lagos", "London"],
    stops: ["Atlanta", "Dallas", "London", "Lagos", "Nairobi"], text:
`This summer, trade the Starbucks run for something louder. Burna Boy on the speakers, Squid Game on the big screen, and Nando's on every table. Bring the friend who still wears Crocs. We'll forgive them.` },
  { name: "Stand-up", slug: "INT. A FLIGHT. 2AM.", cities: ["Dallas", "London", "Johannesburg", "Lagos"],
    stops: ["Dallas", "Atlanta", "Toronto", "London", "Johannesburg", "Lagos"], text:
`I flew into Dallas at 2am and the only thing open was a Whataburger. My cousin from London said that's just Greggs in a cowboy hat. He spent the whole flight watching Coronation Street on his phone, volume up, like the plane needed to know who cheated on who.

I tried to fix the mood with some Kabza De Small. The guy in 14C asked if that was a new kind of yoga. So I put on Nickelback. Everyone hated it. Everyone knew every word.

We landed, he bought Crocs at the airport, and I knew right then: this man has given up, and he has never been happier.` },
  { name: "Best man", slug: "INT. RECEPTION HALL", cities: ["London", "Harare", "Toronto"],
    stops: ["London", "Manchester", "Toronto", "Harare"], text:
`Tunde and I met at a Wetherspoons in Peckham. He was singing Oasis, badly. Ten years later he still thinks jollof rice is a personality, and he still quotes Love Actually every Christmas. Tonight we celebrate the only woman who ever made him miss an Arsenal match.` },
];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

const store = {
  get(k, d) { try { const v = localStorage.getItem("room:" + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("room:" + k, JSON.stringify(v)); } catch { /* storage off */ } },
};

async function api(path, body) {
  const res = await fetch(API + path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}

// ---------- state ----------

const state = {
  text: store.get("text", SAMPLES[0].text),
  slug: store.get("slug", SAMPLES[0].slug),
  cities: store.get("cities", SAMPLES[0].cities),
  age: store.get("age", ""),
  tab: store.get("tab", "room"),           // "room" or "tour"
  mode: "compose",                          // "compose" or "read"
  refs: [],
  scores: {},          // ref id -> { key, data } for the room's cities
  swaps: {},           // ref id + city -> { loading, list, error }
  focus: null,
  selected: null,
  math: false,
  gen: 0,
  lens: "qloo",
  guess: null,
  review: null,        // { city, running, items, trace, before, current }
  doc: null,           // { file, name, kind, blocks }
  tour: {
    stops: store.get("stops", SAMPLES[0].stops),
    scores: {},        // ref id -> { key, data } across the stops
    run: null,         // { key, stops: [...], running, scoring }
    active: null,      // city whose set list is open
    versions: {},      // city -> { text, refs, applied }
  },
};
state.focus = state.cities[0];

const roomKey = () => state.cities.join("|") + "#" + state.age;
const tourKey = () => state.tour.stops.join("|") + "#" + state.age;
const scorable = (ref) => ref.match && !ref.outside;
const scoreOf = (ref) => {
  if (ref.score) return ref.score;
  const s = state.scores[ref.id];
  return s && s.key === roomKey() ? s.data : null;
};
const tourScoreOf = (ref) => {
  const s = state.tour.scores[ref.id];
  return s && s.key === tourKey() ? s.data : null;
};
// The tour starts from the script as it stands: earlier swaps are history, not changes on this tour.
const tourRefs = () => state.refs.map(({ swapped_from, ...r }) => ({ ...r, score: tourScoreOf(r) }));

function verdictFromNumbers(known, loved, popularity = 0) {
  if (known < 0.45 && popularity >= 0.995) return "famous";
  if (known < 0.15) return "dies";
  if (known < 0.45) return "inside";
  if (loved != null && loved < 0.45) return "roast";
  return "lands";
}

function guessVerdict(ref, city) {
  const g = state.guess;
  if (!g || g.key !== roomKey() || !g.data) return null;
  const d = g.data[ref.id]?.[city];
  if (!d) return "unscored";
  return verdictFromNumbers(d.known, d.loved, ref.match?.popularity || 0);
}

function measuredVerdict(ref, city, score = scoreOf(ref)) {
  if (ref.outside) return "outside";
  if (!ref.match) return "unscored";
  if (!score) return null;
  return score.cities?.[city]?.verdict ?? "unscored";
}

function verdictFor(ref, city) {
  if (state.lens === "gemini" && !state.review && !ref.outside && ref.match) return guessVerdict(ref, city);
  return measuredVerdict(ref, city);
}

function roomScore(city, refs = state.refs, verdict = verdictFor) {
  const vals = refs.map((r) => verdict(r, city)).filter((v) => v in VALUE);
  if (!vals.length) return null;
  return Math.round(100 * vals.reduce((a, v) => a + VALUE[v], 0) / vals.length);
}

function status(msg) { $("status").textContent = msg || ""; }

const FOCUS_KEYS = ["data-item", "data-card", "data-ref", "data-age", "data-focus", "data-remove", "data-stop", "data-unstop", "data-mode"];
function focusKey(el) {
  if (!el || el === document.body || !el.getAttribute) return null;
  if (el.id) return `#${CSS.escape(el.id)}`;
  for (const a of FOCUS_KEYS) if (el.hasAttribute(a)) return `[${a}="${CSS.escape(el.getAttribute(a))}"]`;
  if (el.dataset?.act) return `[data-act="${CSS.escape(el.dataset.act)}"]` + (el.dataset.arg != null ? `[data-arg="${CSS.escape(el.dataset.arg)}"]` : "");
  return null;
}
// Run a DOM update; if it replaced the focused element, focus its twin in the new DOM.
function keepFocus(update) {
  const el = document.activeElement;
  const key = focusKey(el);
  update();
  if (key && el && !el.isConnected) document.querySelector(key)?.focus({ preventScroll: true });
}
function focusSoon(selector) {
  requestAnimationFrame(() => document.querySelector(selector)?.focus({ preventScroll: true }));
  setTimeout(() => { const el = document.querySelector(selector); if (el && document.activeElement !== el) el.focus({ preventScroll: true }); }, 350);
}

// ---------- undo: every accepted edit can be taken back ----------
const history = [];
function snapshot() {
  return { text: state.text, refs: state.refs.map((r) => ({ ...r })), scores: { ...state.scores }, review: state.review ? state.review.items.map((it) => it.status) : null };
}
function undo() {
  const h = history.pop();
  if (!h) return;
  state.text = h.text;
  state.refs = h.refs;
  state.scores = h.scores;
  if (state.review && h.review) {
    state.review.items.forEach((it, i) => { if (h.review[i]) it.status = h.review[i]; });
    state.review.lastAccepted = null;
  }
  state.tour.run = null;
  state.tour.versions = {};
  state.guess = null;
  store.set("text", state.text);
  $("script").value = state.text;
  render();
  status("Undone.");
}

// ---------- controls ----------

function renderControls() { keepFocus(renderControlsNow); }
function renderControlsNow() {
  document.querySelectorAll("#modes [data-mode]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.mode === state.tab)));
  $("roomGroup").hidden = state.tab !== "room";
  $("tourGroup").hidden = state.tab !== "tour";
  $("chips").innerHTML = state.cities.map((c) => `
    <span class="chip ${c === state.focus ? "focus" : ""}">
      <button class="name" data-focus="${esc(c)}" type="button" aria-pressed="${c === state.focus}" title="Underline the script for ${esc(c)}">${esc(c)}</button>
      <button class="x" data-remove="${esc(c)}" type="button" aria-label="Remove ${esc(c)}">×</button>
    </span>`).join("");
  const full = state.cities.length >= MAX_CITIES;
  $("cityInput").disabled = full;
  $("cityInput").placeholder = full ? "Room full" : "Add a city";
  $("route").innerHTML = state.tour.stops.map((c, i) => `
    <li><span class="chip ${c === state.tour.active ? "focus" : ""}"><span class="n">${i + 1}</span>
      <button class="name" data-stop="${esc(c)}" type="button">${esc(c)}</button>
      <button class="x" data-unstop="${esc(c)}" type="button" aria-label="Remove ${esc(c)}">×</button></span></li>`).join("");
  const tourFull = state.tour.stops.length >= MAX_STOPS;
  $("stopInput").disabled = tourFull;
  $("stopInput").placeholder = tourFull ? "Tour full" : "Add a stop";
  $("ages").innerHTML = AGES.map(([v, l]) =>
    `<button type="button" aria-pressed="${v === state.age}" data-age="${v}">${l}</button>`).join("");
}

function setTab(tab) {
  if (state.tab === tab) return;
  state.tab = tab;
  store.set("tab", tab);
  state.selected = null;
  closePop();
  transition(() => { renderControls(); render(); });
}

function setCities(cities) {
  state.cities = cities;
  state.review = null;
  if (!cities.includes(state.focus)) state.focus = cities[0];
  store.set("cities", cities);
  renderControls();
  if (state.mode === "read") { scoreAll(); render(); }
}

function setStops(stops) {
  state.tour.stops = stops;
  state.tour.active = null;
  state.tour.versions = {};
  store.set("stops", stops);
  renderControls();
  render();
}

async function resolveCity(q) {
  const c = await api(`/city?q=${encodeURIComponent(q)}`);
  return c.name;
}

$("modes").addEventListener("click", (e) => {
  const b = e.target.closest("[data-mode]");
  if (b) setTab(b.dataset.mode);
});

$("chips").addEventListener("click", (e) => {
  const r = e.target.closest("[data-remove]");
  if (r) { if (state.cities.length > 1) setCities(state.cities.filter((c) => c !== r.dataset.remove)); return; }
  const f = e.target.closest("[data-focus]");
  if (f) { state.focus = f.dataset.focus; renderControls(); render(); summarise(); }
});

$("route").addEventListener("click", (e) => {
  const r = e.target.closest("[data-unstop]");
  if (r) { if (state.tour.stops.length > 1) setStops(state.tour.stops.filter((c) => c !== r.dataset.unstop)); return; }
  const s = e.target.closest("[data-stop]");
  if (s) openStop(s.dataset.stop);
});

$("addCity").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("cityInput").value.trim();
  if (!q || state.cities.length >= MAX_CITIES) return;
  $("cityInput").value = "";
  try {
    const name = await resolveCity(q);
    if (!state.cities.includes(name)) setCities([...state.cities, name]);
  } catch (err) { status(err.message); }
});

$("addStop").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("stopInput").value.trim();
  if (!q || state.tour.stops.length >= MAX_STOPS) return;
  $("stopInput").value = "";
  try {
    const name = await resolveCity(q);
    if (!state.tour.stops.includes(name)) setStops([...state.tour.stops, name]);
  } catch (err) { status(err.message); }
});

$("ages").addEventListener("click", (e) => {
  const b = e.target.closest("[data-age]");
  if (!b) return;
  state.age = b.dataset.age;
  state.review = null;
  store.set("age", state.age);
  renderControls();
  if (state.mode === "read") { scoreAll(); render(); }
});

// ---------- reading ----------

async function readRoom() {
  const text = $("script").value.trim();
  if (!text) { status("Write or paste something first, or drop a file on the page."); return; }
  if (state.doc && text !== joinBlocks(state.doc.blocks) && !blockStarts(state.doc, text)) state.doc = null;
  state.text = text;
  store.set("text", text);
  state.mode = "read";
  state.refs = [];
  state.scores = {};
  state.swaps = {};
  state.guess = null;
  state.review = null;
  state.selected = null;
  state.tour.scores = {};
  state.tour.run = null;
  state.tour.versions = {};
  state.tour.active = null;
  $("readBtn").disabled = true;
  status("Reading…");
  render();
  try {
    // Only the built-in samples go to the shared cache; pasted text stays in server memory.
    const { references } = await api("/read", { text, keep: SAMPLES.some((x) => x.text === text) });
    state.refs = references;
    if (!references.length) status("No references found. Room reads brands, artists, shows, films, books, people, teams and places.");
    render();
    await scoreAll();
  } catch (err) {
    status(err.message);
  } finally {
    $("readBtn").disabled = false;
  }
}

async function pool(items, n, fn) {
  const queue = [...items];
  await Promise.all(Array.from({ length: n }, async () => { while (queue.length) await fn(queue.shift()); }));
}

async function scoreAll() {
  if (state.lens === "gemini") loadGuess();
  const gen = ++state.gen;
  const key = roomKey();
  const todo = state.refs.filter((r) => scorable(r) && !scoreOf(r));
  if (!todo.length) { summarise(); render(); return; }
  let done = 0;
  status(`Scoring ${plural(todo.length, "reference")} across ${plural(state.cities.length, "city").replace("citys", "cities")}…`);
  await pool(todo, 3, async (ref) => {
    if (gen !== state.gen) return;
    try {
      const data = await api("/score", { entity: ref.match, type: ref.type, cities: state.cities, age: state.age || null });
      if (gen === state.gen) state.scores[ref.id] = { key, data };
    } catch (err) {
      if (gen === state.gen) state.scores[ref.id] = { key, data: { cities: {}, error: err.message } };
    }
    done += 1;
    if (gen === state.gen) { if (done < todo.length) status(`Scored ${done} of ${todo.length}…`); render(); }
  });
  if (gen === state.gen) summarise();
}

function summarise() {
  if (state.mode !== "read" || !state.refs.length || state.review) return;
  const f = state.focus;
  const dead = state.refs.filter((r) => verdictFor(r, f) === "dies").length;
  status(dead === 1 ? `1 reference dies in ${f}. Review it, or tap it for a local swap.`
    : dead ? `${dead} references die in ${f}. Review for ${f} to fix them.`
    : `Everything here has a pulse in ${f}.`);
}

// Commit an edited view to the script: carried scores move into the room's score table.
function commit(view) {
  const key = roomKey();
  state.text = view.text;
  state.refs = view.refs.map((r) => {
    const { score, ...rest } = r;
    if (score && state.cities.every((c) => score.cities?.[c])) state.scores[r.id] = { key, data: score };
    else if (score) delete state.scores[r.id];
    return rest;
  });
  state.guess = null;
  state.swaps = {};
  state.tour.run = null;
  state.tour.versions = {};
  store.set("text", state.text);
  $("script").value = state.text;
}

// ---------- the paper ----------

function render() { keepFocus(renderNow); }

// The light sits on the paper while you write and moves to the panel while you review.
function moveSpot() {
  const target = state.review || state.selected || state.tab === "tour" ? $("panel") : $("paper");
  const r = target.getBoundingClientRect();
  if (!r.width) return;
  $("spot").style.setProperty("--sx", `${Math.round(r.left + r.width / 2 - innerWidth * 0.4)}px`);
}

function renderNow() {
  const reading = state.mode === "read";
  $("script").hidden = reading;
  $("read").hidden = !reading;
  $("editBtn").hidden = !reading;
  $("downloadBtn").hidden = !reading;
  $("downloadBtn").textContent = state.doc
    ? (state.doc.kind === "pdf" ? "Download as Word" : `Download ${KINDS[state.doc.kind]}`)
    : "Download text";
  $("readBtn").textContent = reading ? "Read again" : "Read the room";
  $("undoBtn").hidden = !reading || !history.length;
  $("slug").textContent = state.slug;
  if (reading) renderPaper();
  renderPanel();
  moveSpot();
}

function paperView() {
  const v = state.tab === "tour" && state.tour.active && state.tour.versions[state.tour.active];
  return v ? { text: v.text, refs: v.refs, version: true } : { text: state.text, refs: state.refs, version: false };
}

function diffParts(a, b) {
  let p = 0;
  while (p < a.length && p < b.length && a[p] === b[p]) p++;
  let q = 0;
  while (q < a.length - p && q < b.length - p && a[a.length - 1 - q] === b[b.length - 1 - q]) q++;
  while (p > 0 && /[\p{L}\p{N}]/u.test(a[p - 1])) p--;
  while (q > 0 && /[\p{L}\p{N}]/u.test(a[a.length - q] ?? "")) q--;
  return { pre: a.slice(0, p), del: a.slice(p, a.length - q), ins: b.slice(p, b.length - q), post: a.slice(a.length - q) };
}

function diffHtml(a, b) {
  if (!b) return `<del>${esc(a)}</del>`;
  const d = diffParts(a, b);
  return `${esc(d.pre)}${d.del ? `<del>${esc(d.del)}</del>` : ""}${d.ins ? `<ins>${esc(d.ins)}</ins>` : ""}${esc(d.post)}`;
}

function renderPaper() {
  const view = paperView();
  const t = view.text;
  const pending = new Map();
  if (state.review && !view.version) {
    for (const it of state.review.items) if (it.status === "pending" && it.proposal) pending.set(it.ref_id, it);
  }
  const marks = view.refs.map((r) => ({ pos: r.start, ref: r }));
  const starts = state.doc && !view.version ? blockStarts(state.doc, t) : null;
  if (starts) {
    let prev = null;
    state.doc.blocks.forEach((b, i) => {
      if (b.where !== prev && state.doc.kind !== "txt" && state.doc.kind !== "md") marks.push({ pos: starts[i], label: b.where });
      prev = b.where;
    });
  }
  marks.sort((a, b) => a.pos - b.pos || (a.label ? -1 : 1));
  const touring = state.tab === "tour";
  const focus = touring ? (state.tour.active || state.tour.stops[0]) : state.focus;
  let html = "", at = 0, refIndex = 0;
  for (const m of marks) {
    if (m.pos < at) continue;
    if (m.label) {
      const cut = m.pos >= 2 && t.slice(m.pos - 2, m.pos) === "\n\n" ? m.pos - 2 : m.pos;
      html += esc(t.slice(at, cut)) + `<span class="where">${esc(m.label)}</span>`;
      at = m.pos;
      continue;
    }
    const r = m.ref;
    html += esc(t.slice(at, r.start));
    const word = esc(t.slice(r.start, r.end));
    const it = pending.get(r.id);
    if (it) {
      const p = it.proposal;
      const words = p.action === "swap" ? (() => { const s = swapSpan(p.sentence, p.line, p.after); return s ? p.line.substr(s.at, s.len) : p.after; })() : "";
      html += `<span class="sug ${p.action} ${state.review.current === it.id ? "active" : ""}" data-item="${esc(it.id)}" tabindex="0" role="button" aria-haspopup="dialog" aria-label="Suggestion: ${esc(ACT[p.action])} ${word}${words ? " for " + esc(words) : ""}"><span class="old">${word}</span>${words ? `<span class="new">${esc(words)}</span>` : ""}</span>`;
    } else {
      const sc = touring ? (r.score || tourScoreOf(r)) : null;
      const labelCity = sc ? focus : (touring ? state.focus : focus);
      const v = sc ? measuredVerdict(r, focus, sc) : verdictFor(r, labelCity);
      const said = `${v ? WORD[v] : "scoring"} in ${labelCity}${r.swapped_from ? `, was ${r.swapped_from}` : ""}`;
      const live = !state.review && !touring;   // only the board view opens a reference
      const cls = `ref ${v ? "v-" + v : "wait"} ${state.selected === r.id ? "sel" : ""} ${r.swapped_from ? "swapped" : ""} ${live ? "" : "static"}`;
      const n = refIndex++;
      html += live
        ? `<span class="${cls}" style="--i:${n}" ${r.swapped_from ? `title="Was ${esc(r.swapped_from)}"` : ""} data-ref="${esc(r.id)}" tabindex="0" role="button" aria-label="${word}: ${esc(said)}">${word}</span>`
        : `<span class="${cls}" style="--i:${n}">${word}<span class="sr"> (${esc(said)})</span></span>`;
    }
    at = r.end;
  }
  $("read").innerHTML = html + esc(t.slice(at));
}

// ---------- the panel ----------

function renderPanel() { keepFocus(renderPanelNow); }
function renderPanelNow() {
  const panel = $("panel");
  if (state.tab === "tour") panel.innerHTML = state.tour.active ? stopHtml() : tourHtml();
  else if (state.review) panel.innerHTML = reviewHtml();
  else if (state.selected && state.refs.some((r) => r.id === state.selected)) panel.innerHTML = detailHtml();
  else panel.innerHTML = boardHtml();
  ticks(panel);
  const list = panel.querySelector(".trace");
  if (list && state.review?.running) list.scrollTop = list.scrollHeight;
}

function cell(ref, city) {
  const v = verdictFor(ref, city);
  if (!v) return `<span class="cell wait" aria-label="scoring"></span>`;
  const low = state.lens === "qloo" && scoreOf(ref)?.cities?.[city]?.confidence === "low";
  const other = state.lens === "gemini" ? measuredVerdict(ref, city) : guessVerdict(ref, city);
  const differs = other && other !== v && !["outside", "unscored"].includes(v);
  const tip = differs ? `${state.lens === "gemini" ? "Room says" : "Gemini alone says"}: ${WORD[other]}` : (LEGEND[v] || "");
  return `<span class="cell v-${v} ${low ? "low" : ""} ${differs ? "differs" : ""}" title="${esc(tip)}"><span class="long">${WORD[v]}</span><span class="short" aria-hidden="true">${SHORT[v] || v}</span>${low ? `<span class="sr">, low confidence</span>` : ""}${differs ? `<span class="sr">, ${esc(tip)}</span>` : ""}</span>`;
}

const pct = (n, key) => (n == null ? `<span class="n">··</span>` : `<span class="n"><span data-tick="${n}" data-key="${esc(key)}">${n}</span><i>%</i></span>`);

function boardHtml() {
  if (state.mode !== "read") {
    return `<p class="empty">Put a script under the light. Room checks every reference against the people in the seats.
      <small>Pick up to four cities and an age. Paste a set, or drop a PDF, deck or document on the page. Then review it for any city, or take it on tour.</small></p>`;
  }
  if (!state.refs.length) return `<p class="empty">Reading…</p>`;
  const scoring = state.refs.some((r) => scorable(r) && !scoreOf(r));
  const head = state.cities.map((c) => `<th><button class="colhead ${c === state.focus ? "focus" : ""}" data-focus="${esc(c)}" type="button" aria-pressed="${c === state.focus}" title="${esc(c)}">
      <span class="c">${esc(c)}</span>${pct(roomScore(c), "room:" + c)}</button></th>`).join("");
  const rows = state.refs.map((r) => `
    <tr><td><button class="rowname" data-ref="${esc(r.id)}" type="button"><b>${esc(r.surface)}</b>
      <span>${esc(r.outside ? "outside the graph" : (r.match?.type || r.type || "").replace("_", " "))}</span></button></td>
      ${state.cities.map((c) => `<td>${cell(r, c)}</td>`).join("")}</tr>`).join("");
  const g = state.guess;
  const lensNote = state.lens === "gemini"
    ? (g?.loading ? "Asking Gemini to guess from memory…" : g?.error ? esc(g.error)
      : "Gemini guessing everything from memory, Loved included. Outlined cells are where it disagrees with Room.")
    : (g?.key === roomKey() && g.data ? "Outlined cells are where Gemini alone disagrees with Room." : "");
  return `<div class="lens" role="group" aria-label="Whose verdicts">
      <button type="button" aria-pressed="${state.lens === "qloo"}" data-act="lens" data-arg="qloo">Room</button>
      <button type="button" aria-pressed="${state.lens === "gemini"}" data-act="lens" data-arg="gemini">Gemini alone</button>
    </div>${lensNote ? `<p class="lensnote">${lensNote}</p>` : ""}
    <table class="board"><thead><tr><th></th>${head}</tr></thead><tbody>${rows}</tbody></table>
    <p class="boardnote">The number under each city is how much of the script lands there. Tap a city to underline the script for it.</p>
    <div class="callout">
      <button class="primary" data-act="review" type="button" ${scoring ? "disabled" : ""}>Review for ${esc(state.focus)}</button>
      <p>An agent decides what to swap, drop or keep for ${esc(state.focus)}. You accept or ignore each suggestion.</p>
    </div>`;
}

function bar(label, cls, v) {
  const w = v == null ? 0 : Math.round(v * 100);
  return `<span>${label}</span><span class="bar ${cls}"><i style="width:${w}%"></i></span><span>${v == null ? "n/a" : v.toFixed(2)}</span>`;
}

function detailHtml() {
  const ref = state.refs.find((r) => r.id === state.selected);
  const s = scoreOf(ref);
  const m = ref.match;
  const meta = ref.outside
    ? `<span>Outside Qloo's graph. ${esc(LEGEND.outside)}</span>`
    : m ? `<span>Matched to</span>
        <select data-rematch="${esc(ref.id)}" aria-label="Qloo match">
          ${(ref.candidates || [m]).map((c) => `<option value="${esc(c.entity_id)}" ${c.entity_id === m.entity_id ? "selected" : ""}>${esc(c.name)}${c.disambiguation && c.disambiguation !== c.name ? " · " + esc(c.disambiguation) : ""}</option>`).join("")}
        </select>${ref.certain ? "" : `<span class="warn">Check this match.</span>`}`
      : ref.candidates?.length
        ? `<span class="warn">Qloo holds no clear match.</span>
          <select data-rematch="${esc(ref.id)}" aria-label="Pick a Qloo match">
            <option value="" selected>Pick the closest</option>
            ${ref.candidates.map((c) => `<option value="${esc(c.entity_id)}">${esc(c.name)} · ${esc((c.type || "").replace("_", " "))}${c.disambiguation && c.disambiguation !== c.name ? " · " + esc(c.disambiguation) : ""}</option>`).join("")}
          </select>`
        : `<span class="warn">Qloo found no match.</span>`;
  const rows = !scorable(ref) ? "" : state.cities.map((c) => {
    const d = s?.cities?.[c];
    const v = d?.verdict;
    const sw = state.swaps[ref.id + "|" + c];
    const weak = v && ["dies", "inside", "unscored"].includes(v);
    return `<div class="crow">
      <div class="crow-top"><span class="city">${esc(c)}</span><span class="vw v-${v || ""}">${v ? WORD[v] : "…"}</span></div>
      ${d ? `<p class="why">${esc(d.why)}${d.confidence === "low" ? " Qloo holds thin data for this city." : ""}</p>
      <div class="bars">${bar("Known", "k", d.known)}${bar("Loved", "l", d.loved)}</div>
      ${state.math ? `<div class="math">recognition (Gemini) ${d.recognition ?? "n/a"} · fan presence (Qloo) ${d.presence ?? "n/a"} = ${d.cells} cells against ${d.base_cells ?? "n/a"} for a household name · median affinity (Qloo) ${d.loved ?? "n/a"}${s.mode === "memory" ? " · Qloo holds no map for this one" : ""}</div>` : ""}` : ""}
      ${weak && !sw ? `<button class="ghost" data-act="swap" data-arg="${esc(ref.id)}" data-city="${esc(c)}" type="button" style="margin-top:12px">Find a ${esc(c)} swap</button>` : ""}
      ${sw ? swapsHtml(ref, c, sw) : ""}
    </div>`;
  }).join("");
  const home = s?.elsewhere && !state.cities.includes(s.elsewhere.city)
    ? `<p class="elsewhere">Its fans cluster hardest in <b>${esc(s.elsewhere.city)}</b> across Room's anchor cities.</p>` : "";
  return `<button class="back" data-act="back" type="button">← The whole room</button>
    <h2 class="dname" tabindex="-1" id="detailTitle">${esc(ref.surface)}</h2>
    <div class="dmeta">${meta}</div>
    <p class="job"><span>Its job in the line</span>${esc(ref.role)}</p>
    ${s?.error ? `<p class="why warn">${esc(s.error)}</p>` : ""}
    ${rows}${home}
    ${scorable(ref) ? `<button class="ghost" data-act="math" type="button" style="margin-top:18px">${state.math ? "Hide" : "Show"} the math</button>` : ""}`;
}

function swapsHtml(ref, city, sw) {
  if (sw.loading) return `<p class="working"><span class="dot"></span>Asking Qloo what ${esc(city)} loves, then keeping what does the same job…</p>`;
  if (sw.error) return `<p class="why warn">${esc(sw.error)}</p>`;
  if (!sw.list.length) return `<p class="why">Qloo offered nothing close enough for ${esc(city)}.</p>`;
  return `<div class="cards" style="margin-top:12px">${sw.list.map((x, i) => {
    const d = x.score?.cities?.[city];
    const v = x.score ? (d?.verdict || "unscored") : null;
    return `<div class="card">
      <div class="card-top"><b>${esc(x.candidate.name)}</b>${v ? `<span class="cell v-${v}">${WORD[v]}</span>` : `<span class="cell wait" aria-label="scoring"></span>`}</div>
      <p class="diff">${diffHtml(ref.sentence, x.line)}</p>
      <p class="swhy">${esc(x.why)}</p>
      <div class="card-actions"><button class="ghost" ${x.score ? "" : "disabled"} data-act="use-swap" data-arg="${esc(ref.id)}" data-city="${esc(city)}" data-i="${i}" type="button">Use this line</button></div>
    </div>`;
  }).join("")}</div>`;
}

// ---------- review: Grammarly for culture ----------

function cardHtml(it, inPop = false) {
  const ref = state.refs.find((r) => r.id === it.ref_id);
  const p = it.proposal;
  const city = state.review.city;
  const name = esc(p?.before || ref?.surface || "");
  if (it.status === "working") {
    return `<div class="card"><div class="card-top"><span class="act ${it.action}">${ACT[it.action]}</span></div>
      <p class="pair">${name}</p><p class="working" style="margin:6px 0 0"><span class="dot"></span>${it.action === "swap" ? `Finding what ${esc(city)} loves…` : "Rewriting the line…"}</p></div>`;
  }
  if (it.status === "error") {
    return `<div class="card"><p class="pair">${name}</p><p class="swhy warn">${esc(it.error)}</p></div>`;
  }
  const cur = state.review.current === it.id;
  const pair = p.action === "swap"
    ? `<s>${name}</s><span class="arrow">→</span>${esc(p.after)}`
    : `<s>${name}</s><span class="arrow">→</span>${p.line ? "cut from the line" : "the line goes"}`;
  const vb = p.verdict_before ? WORD[p.verdict_before] || p.verdict_before : "";
  const va = p.action === "swap" ? WORD[p.verdict_after] || p.verdict_after : "cut";
  const done = it.status === "accepted" ? "Accepted" : it.status === "ignored" ? "Ignored" : "";
  return `<div class="card ${cur ? "current" : ""} ${it.status}" data-card="${esc(it.id)}">
    <div class="card-top"><span class="act ${p.action}">${ACT[p.action]}${it.fallback ? " · no local swap lands" : ""}</span><span class="vchange">${esc(vb)} → ${esc(va)} in ${esc(city)}</span></div>
    <p class="pair">${pair}</p>
    <p class="diff">${diffHtml(p.sentence, p.line)}</p>
    ${p.why || it.why ? `<p class="swhy">${esc(p.why || it.why)}</p>` : ""}
    ${done ? `<p class="done-line">${done === "Accepted" ? "✓ " : ""}${done}.${done === "Accepted" && state.review.lastAccepted === it.id && history.length ? ` <button class="ghost" data-act="undo" type="button" style="padding:3px 10px;font-size:12px;margin-left:6px">Undo</button>` : ""}</p>` : `<div class="card-actions">
      <button class="primary" data-act="accept" data-arg="${esc(it.id)}" type="button">Accept${cur && !inPop ? " <kbd>A</kbd>" : ""}</button>
      <button class="ghost" data-act="ignore" data-arg="${esc(it.id)}" type="button">Ignore${cur && !inPop ? " <kbd>I</kbd>" : ""}</button></div>`}
  </div>`;
}

function reviewHtml() {
  const rv = state.review;
  const after = roomScore(rv.city);
  const d = after != null && rv.before != null ? after - rv.before : 0;
  const shown = rv.items.filter((it) => it.status !== "kept");
  const kept = rv.items.filter((it) => it.status === "kept");
  const pending = rv.items.filter((it) => it.status === "pending").length;
  return `<button class="back" data-act="close-review" type="button">← The whole room</button>
    <div class="rhead">
      <div><p class="kicker">Review</p><h2 class="dname" tabindex="-1" id="reviewTitle">For ${esc(rv.city)}</h2></div>
      <div class="score"><span class="from">${rv.before ?? "··"}% →</span> ${pct(after, "review:" + rv.city)}
        ${d ? `<span class="d ${d > 0 ? "up" : "down"}">${d > 0 ? "+" : ""}${d}</span>` : ""}</div>
    </div>
    ${rv.running && !rv.items.length ? `<p class="working"><span class="dot"></span>Gemini is reading the room for ${esc(rv.city)}…</p>` : ""}
    ${!rv.running && !shown.length ? `<p class="empty" style="padding:8px 0">${kept.length ? `Room keeps every weak reference here on purpose.` : `Everything already has a pulse in ${esc(rv.city)}.`}</p>` : ""}
    <div class="cards">${shown.map((it) => cardHtml(it)).join("")}</div>
    ${kept.length ? `<details class="kept" ${shown.length ? "" : "open"}><summary>Kept on purpose (${kept.length})</summary><ul>${kept.map((it) => {
      const ref = state.refs.find((r) => r.id === it.ref_id);
      return `<li><b>${esc(ref?.surface || "")}</b>: ${esc(it.why || "")}</li>`;
    }).join("")}</ul></details>` : ""}
    <details class="work"><summary>How the agent decided (${rv.trace.length} steps)</summary>
      <ol class="trace">${rv.trace.map((e) => `<li class="t-${e.who}"><span class="who">${WHO[e.who] || e.who}</span><span class="what">${esc(e.text)}</span>${e.ms >= 100 ? `<span class="ms">${(e.ms / 1000).toFixed(1)} s</span>` : "<span></span>"}</li>`).join("")}</ol>
    </details>
    <div class="sticky">
      ${pending ? `<button class="primary" data-act="accept-all" type="button">Accept all ${pending}</button>` : ""}
      <button class="ghost" data-act="close-review" type="button">${rv.running ? "Stop" : "Done"}</button>
      ${rv.running ? `<span class="working" style="margin:0 0 0 6px"><span class="dot"></span>Working</span>` : ""}
    </div>`;
}

async function startReview(city = state.focus) {
  if (state.mode !== "read" || !state.refs.length) return;
  const refs = state.refs.map((r) => ({ ...r, score: scoreOf(r) }));
  if (refs.some((r) => scorable(r) && !r.score)) { status("Still scoring. Give it a moment."); return; }
  const rv = { city, running: true, items: [], trace: [{ who: "you", text: `Review this for ${city}.` }], before: roomScore(city), current: null };
  state.lens = "qloo";
  state.selected = null;
  state.review = rv;
  transition(render);
  focusSoon("#reviewTitle");
  status(`Reviewing for ${city}…`);
  const live = () => state.review === rv;
  try {
    const r = await runReview({
      api, text: state.text, refs, city, cities: state.cities, age: state.age || null, live,
      onTrace: (entries) => { rv.trace.push(...entries); if (live()) renderPanel(); },
      onItem: (it) => {
        if (!rv.items.includes(it)) rv.items.push(it);
        if (!rv.current && it.status === "pending") rv.current = it.id;
        if (live()) {
          render();
          if (it.status === "pending") {
            const n = rv.items.filter((x) => x.status === "pending").length;
            status(`${plural(n, "suggestion")} ready for ${city}.`);
          }
        }
      },
    });
    rv.before = r.before ?? rv.before;
  } catch (err) {
    rv.trace.push({ who: "room", text: err.message });
    status(err.message);
  }
  if (!live()) return;
  rv.running = false;
  const pending = rv.items.filter((it) => it.status === "pending").length;
  status(pending ? `${plural(pending, "suggestion")} for ${city}. Accept or ignore each, or accept them all.` : `Nothing to change for ${city}.`);
  render();
}

async function recut(view, ref) {
  const c = await api("/agent/cut", { text: view.text, refs: view.refs, ref_id: ref.id, city: state.review?.city || state.focus, apply: false });
  return c.proposal?.line ?? null;
}

function nextPending(fromId) {
  const items = state.review.items.filter((it) => it.status === "pending");
  if (!items.length) return null;
  const i = state.review.items.findIndex((it) => it.id === fromId);
  return (state.review.items.slice(i + 1).find((it) => it.status === "pending") || items[0]).id;
}

// Accepts run one at a time: a cut that waits on a fresh rewrite must see every edit committed before it,
// or it would write the old line back over them.
let acceptQueue = Promise.resolve();
function accept(id, from = "panel") {
  const it = state.review?.items.find((x) => x.id === id);
  if (!it || it.status !== "pending") return acceptQueue;
  it.status = "queued";
  acceptQueue = acceptQueue.then(() => acceptNow(id, from)).catch(() => {});
  return acceptQueue;
}

async function acceptNow(id, from) {
  const rv = state.review;
  const it = rv?.items.find((x) => x.id === id);
  if (!it || it.status !== "queued") return;
  const before = snapshot();
  it.status = "busy";
  const view = { text: state.text, refs: state.refs.map((r) => ({ ...r, score: scoreOf(r) })) };
  const next = await applyProposal(view, it.proposal, recut).catch(() => null);
  if (!next) { it.status = "error"; it.error = "That line changed. Read the room again."; render(); return; }
  before.review[rv.items.indexOf(it)] = "pending";
  history.push(before);
  if (state.doc) {
    state.doc.notes.push({ before: it.proposal.sentence, after: it.proposal.line, why: it.proposal.why || it.why || "" });
    state.doc.audience = rv.city;
  }
  it.status = "accepted";
  rv.lastAccepted = id;
  commit(next);
  rv.current = nextPending(id);
  closePop();
  render();
  const left = rv.items.filter((x) => x.status === "pending").length;
  status(left ? `Accepted. ${left} left.` : `Accepted. That was the last one.`);
  focusNext(from);
}

function focusNext(from) {
  const id = state.review?.current;
  if (!id) { focusSoon("#reviewTitle"); return; }
  focusSoon(from === "paper" ? `.sug[data-item="${CSS.escape(id)}"]` : `[data-act="accept"][data-arg="${CSS.escape(id)}"]`);
}

function ignore(id, from = "panel") {
  const it = state.review?.items.find((x) => x.id === id);
  if (!it || it.status !== "pending") return;
  it.status = "ignored";
  state.review.current = nextPending(id);
  closePop();
  render();
  const left = state.review.items.filter((x) => x.status === "pending").length;
  status(left ? `Ignored. ${left} left.` : "Ignored. That was the last one.");
  focusNext(from);
}

async function acceptAll() {
  for (const it of [...state.review.items]) if (it.status === "pending") await accept(it.id);
}

function closeReview() {
  state.review = null;
  transition(() => { render(); summarise(); });
  focusSoon('[data-act="review"]');
  scoreAll();
}

function move(step) {
  const rv = state.review;
  const items = rv.items.filter((it) => it.status === "pending");
  if (!items.length) return;
  const i = Math.max(0, items.findIndex((it) => it.id === rv.current));
  rv.current = items[(i + step + items.length) % items.length].id;
  render();
  $("panel").querySelector(`[data-card="${CSS.escape(rv.current)}"]`)?.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  focusSoon(`[data-act="accept"][data-arg="${CSS.escape(rv.current)}"]`);
}

// The suggestion on the page opens its card right next to the word.
let popFrom = null;
function openPop(el, id) {
  const it = state.review?.items.find((x) => x.id === id);
  const pop = $("pop");
  if (!it || !pop.showPopover) { state.review && (state.review.current = id, render()); return; }
  state.review.current = id;
  popFrom = id;
  pop.innerHTML = cardHtml(it, true);
  pop.setAttribute("aria-label", `Suggestion for ${it.proposal?.before || "this reference"}`);
  document.querySelectorAll(".anchor").forEach((x) => x.classList.remove("anchor"));
  el.classList.add("anchor");
  const anchored = CSS.supports("position-area: block-end");
  pop.classList.toggle("anchored", anchored);
  try { pop.showPopover({ source: el }); } catch { pop.showPopover(); }
  if (!anchored) {
    const r = el.getBoundingClientRect();
    const w = pop.offsetWidth, h = pop.offsetHeight;
    pop.style.left = `${Math.min(Math.max(12, r.left + r.width / 2 - w / 2), innerWidth - w - 12)}px`;
    pop.style.top = `${r.bottom + 10 + h < innerHeight ? r.bottom + 10 : Math.max(12, r.top - h - 10)}px`;
  }
  renderPanel();
  pop.querySelector('[data-act="accept"]')?.focus({ preventScroll: true });
}
function closePop(restore = false) {
  const pop = $("pop");
  const open = pop.matches?.(":popover-open");
  try { pop.hidePopover?.(); } catch { /* not open */ }
  if (open && restore && popFrom) focusSoon(`.sug[data-item="${CSS.escape(popFrom)}"]`);
}

// ---------- tour ----------

function stopAfter(stop) {
  const refs = tourRefs();
  const vals = [];
  for (const r of refs) {
    const it = stop.items.find((x) => x.ref_id === r.id && x.proposal);
    if (it?.proposal.action === "drop") continue;
    const v = it?.proposal.action === "swap" ? it.proposal.verdict_after : measuredVerdict(r, stop.city, r.score);
    if (v in VALUE) vals.push(VALUE[v]);
  }
  return vals.length ? Math.round(100 * vals.reduce((a, b) => a + b, 0) / vals.length) : null;
}

function tourCell(ref, stop) {
  if (!scorable(ref)) return `<span class="tcell fine">off graph</span>`;
  const v = measuredVerdict(ref, stop.city, tourScoreOf(ref));
  const it = stop.items.find((x) => x.ref_id === ref.id);
  if (!v) return `<span class="cell wait" aria-label="scoring"></span>`;
  if (it?.status === "working") return `<span class="cell wait" aria-label="working"></span>`;
  if (it?.proposal?.action === "swap") return `<span class="tcell swap" title="${esc(it.proposal.why || "")}">→ ${esc(it.proposal.after)}</span>`;
  if (it?.proposal?.action === "drop") return `<span class="tcell drop" title="${esc(it.proposal.why || "")}">cut</span>`;
  if (it?.status === "kept") return `<span class="tcell keep" title="${esc(it.why || "")}">keeps</span>`;
  return `<span class="tcell fine v-${v}">${WORD[v]?.toLowerCase() || v}</span>`;
}

function tourHtml() {
  const t = state.tour;
  if (state.mode !== "read" || !state.refs.length) {
    return `<p class="empty">One set, many rooms. Read a set first, then route the tour.
      <small>Add up to eight stops above. Room reviews the set for each city and prints a set list per stop: what stays, what swaps, what goes.</small></p>`;
  }
  const run = t.run && t.run.key === tourKey() ? t.run : null;
  const stops = run ? run.stops : t.stops.map((city) => ({ city, status: "waiting", items: [] }));
  const head = stops.map((s) => {
    const before = roomScore(s.city, tourRefs(), (r, c) => measuredVerdict(r, c, r.score));
    const after = s.status === "done" ? stopAfter(s) : null;
    return `<th><button class="stophead" data-act="stop" data-arg="${esc(s.city)}" type="button" ${s.status === "done" ? "" : "disabled"}>
      <span class="c">${esc(s.city)}</span>
      ${after != null ? `<span class="from">${before ?? "··"}% →</span> <span class="n"><span data-tick="${after}" data-key="tour:${esc(s.city)}">${after}</span>%</span>`
        : `<span class="n" style="color:var(--muted)">${before != null ? before + "%" : "··"}</span>`}
      ${s.status === "working" ? `<span class="dot" style="display:inline-block;margin-left:6px"></span>` : ""}
    </button></th>`;
  }).join("");
  const rows = state.refs.map((r) => `<tr><td><b>${esc(r.surface)}</b></td>${stops.map((s) => `<td>${tourCell(r, s)}</td>`).join("")}</tr>`).join("");
  const scoring = run?.scoring;
  const doneAll = run && !run.running;
  return `<div class="rhead"><div><p class="kicker">Tour</p><h2 class="dname">${plural(t.stops.length, "stop")}</h2></div>
      ${run ? "" : `<button class="primary" data-act="route" type="button">Route the tour</button>`}</div>
    ${scoring ? `<p class="working"><span class="dot"></span>Scoring the set in every city: ${scoring.done} of ${scoring.total}…</p>` : ""}
    ${run?.running && !scoring ? `<p class="working"><span class="dot"></span>Reviewing stop by stop. Tap a finished stop for its set list.</p>` : ""}
    <div class="sheet-wrap"><table class="sheet"><thead><tr><th></th>${head}</tr></thead><tbody>${rows}</tbody></table></div>
    <p class="boardnote">Each column is the set as that city hears it: what stays, what swaps, what gets cut. The number is the room score before and after.</p>
    ${doneAll ? `<div class="callout"><button class="primary" data-act="print" type="button">Print set lists</button><p>One page per stop, with every change marked.</p></div>` : ""}`;
}

function stopHtml() {
  const t = state.tour;
  const stop = t.run?.stops.find((s) => s.city === t.active);
  if (!stop) return tourHtml();
  const v = t.versions[stop.city];
  const before = roomScore(stop.city, tourRefs(), (r, c) => measuredVerdict(r, c, r.score));
  const after = stopAfter(stop);
  const changes = stop.items.filter((it) => it.proposal);
  const kept = stop.items.filter((it) => it.status === "kept");
  return `<button class="back" data-act="sheet" type="button">← The whole tour</button>
    <div class="rhead"><div><p class="kicker">Set list</p><h2 class="dname">${esc(stop.city)}</h2></div>
      <div class="score"><span class="from">${before ?? "··"}% →</span> ${pct(after, "stop:" + stop.city)}</div></div>
    ${!v ? `<p class="working"><span class="dot"></span>Writing the ${esc(stop.city)} version…</p>` : ""}
    <div class="cards">${changes.map((it) => {
      const p = it.proposal;
      return `<div class="card"><div class="card-top"><span class="act ${p.action}">${ACT[p.action]}</span>
        <span class="vchange">${esc(WORD[p.verdict_before] || "")} → ${esc(p.action === "swap" ? WORD[p.verdict_after] || "" : "cut")}</span></div>
        <p class="pair"><s>${esc(p.before)}</s><span class="arrow">→</span>${p.action === "swap" ? esc(p.after) : "cut"}</p>
        <p class="diff">${diffHtml(p.sentence, p.line)}</p>${p.why ? `<p class="swhy">${esc(p.why)}</p>` : ""}</div>`;
    }).join("") || `<p class="why">The set plays as written in ${esc(stop.city)}.</p>`}</div>
    ${kept.length ? `<details class="kept"><summary>Kept on purpose (${kept.length})</summary><ul>${kept.map((it) => `<li><b>${esc(state.refs.find((r) => r.id === it.ref_id)?.surface || "")}</b>: ${esc(it.why || "")}</li>`).join("")}</ul></details>` : ""}
    <div class="callout"><button class="primary" data-act="print" type="button">Print set lists</button><p>The paper shows the ${esc(stop.city)} version.</p></div>`;
}

async function routeTour() {
  const t = state.tour;
  if (state.mode !== "read" || !state.refs.length) return;
  const key = tourKey();
  const run = { key, stops: t.stops.map((city) => ({ city, status: "waiting", items: [], trace: [] })), running: true, scoring: null };
  t.run = run;
  t.active = null;
  t.versions = {};
  const live = () => t.run === run;
  const todo = state.refs.filter((r) => scorable(r) && !tourScoreOf(r));
  run.scoring = { done: 0, total: todo.length };
  render();
  await pool(todo, 3, async (ref) => {
    if (!live()) return;
    try {
      const data = await api("/score", { entity: ref.match, type: ref.type, cities: t.stops, age: state.age || null });
      t.scores[ref.id] = { key, data };
    } catch (err) {
      t.scores[ref.id] = { key, data: { cities: {}, error: err.message } };
    }
    run.scoring.done += 1;
    if (live()) renderPanel();
  });
  if (!live()) return;
  run.scoring = null;
  status(`Reviewing the set for ${plural(t.stops.length, "stop")}…`);
  render();
  await runTour({
    api, text: state.text, refs: tourRefs(), stops: t.stops,
    age: state.age || null, live,
    onStop: (stop) => {
      const i = run.stops.findIndex((s) => s.city === stop.city);
      if (i >= 0) run.stops[i] = stop;
      if (live()) render();
    },
  });
  if (!live()) return;
  run.running = false;
  status(`The tour is routed. Tap a stop for its set list, or print them all.`);
  render();
}

async function openStop(city) {
  const t = state.tour;
  if (state.tab !== "tour") setTab("tour");
  const stop = t.run?.stops.find((s) => s.city === city && s.status === "done");
  if (!stop) return;
  t.active = city;
  transition(() => { renderControls(); render(); });
  if (!t.versions[city]) {
    const refs = tourRefs();
    t.versions[city] = await stopVersion(state.text, refs, stop, async (view, ref) => {
      const c = await api("/agent/cut", { text: view.text, refs: view.refs, ref_id: ref.id, city, apply: false });
      return c.proposal?.line ?? null;
    });
    if (t.active === city) render();
  }
}

async function printSetLists() {
  const t = state.tour;
  const done = t.run?.stops.filter((s) => s.status === "done") || [];
  status("Preparing the set lists…");
  for (const s of done) {
    if (!t.versions[s.city]) {
      const refs = tourRefs();
      t.versions[s.city] = await stopVersion(state.text, refs, s, async (view, ref) => {
        const c = await api("/agent/cut", { text: view.text, refs: view.refs, ref_id: ref.id, city: s.city, apply: false });
        return c.proposal?.line ?? null;
      });
    }
  }
  $("print").innerHTML = done.map((s) => {
    const v = t.versions[s.city];
    const before = roomScore(s.city, tourRefs(), (r, c) => measuredVerdict(r, c, r.score));
    let html = "", at = 0;
    for (const r of [...v.refs].sort((a, b) => a.start - b.start)) {
      if (!r.swapped_from || r.start < at) continue;
      html += esc(v.text.slice(at, r.start)) + `<ins>${esc(v.text.slice(r.start, r.end))}</ins>`;
      at = r.end;
    }
    html += esc(v.text.slice(at));
    const changes = s.items.filter((it) => it.proposal).map((it) => `<li>${it.proposal.action === "swap" ? `${esc(it.proposal.before)} → ${esc(it.proposal.after)}` : `cut ${esc(it.proposal.before)}`}</li>`).join("");
    return `<section><h1>${esc(s.city)}</h1><p class="meta">${esc(state.slug)} · room score ${before ?? "··"}% → ${stopAfter(s) ?? "··"}%</p>
      <div class="text">${html}</div>${changes ? `<ul>${changes}</ul>` : ""}</section>`;
  }).join("");
  status("");
  window.print();
}

// ---------- second opinion ----------

async function loadGuess() {
  const key = roomKey();
  if (state.guess?.key === key && (state.guess.data || state.guess.loading)) return;
  const refs = state.refs.filter((r) => r.match && !r.outside).map((r) => ({ id: r.id, name: r.match.name, type: r.type }));
  if (!refs.length) return;
  state.guess = { key, loading: true };
  render();
  try {
    const { guess } = await api("/guess", { refs, cities: state.cities, age: state.age || null });
    if (state.guess?.key === key) state.guess = { key, data: guess };
  } catch (err) {
    if (state.guess?.key === key) state.guess = { key, error: err.message };
  }
  render();
}

// ---------- swaps from the detail view ----------

async function findSwap(refId, city) {
  const ref = state.refs.find((r) => r.id === refId);
  const k = refId + "|" + city;
  state.swaps[k] = { loading: true };
  renderPanel();
  try {
    const { swaps } = await api("/swap", {
      entity: ref.match, type: ref.type, surface: ref.surface, role: ref.role, sentence: ref.sentence,
      city, cities: state.cities, age: state.age || null,
      exclude: state.refs.filter((r) => r.match).map((r) => r.match.entity_id),
    });
    state.swaps[k] = { list: swaps };
  } catch (err) {
    state.swaps[k] = { error: err.message };
  }
  renderPanel();
  await Promise.all((state.swaps[k].list || []).map(async (x) => {
    try { x.score = await api("/score", { entity: x.candidate, type: ref.type, cities: state.cities, age: state.age || null }); }
    catch (err) { x.score = { cities: {}, error: err.message }; }
    if (state.swaps[k]?.list?.includes(x)) renderPanel();
  }));
}

async function useSwap(refId, city, i) {
  const ref = state.refs.find((r) => r.id === refId);
  const x = state.swaps[refId + "|" + city]?.list?.[i];
  if (!ref || !x) return;
  const view = { text: state.text, refs: state.refs.map((r) => ({ ...r, score: scoreOf(r) })) };
  const next = await applyProposal(view, { action: "swap", ref_id: refId, sentence: ref.sentence, line: x.line,
    after: x.candidate.name, candidate: x.candidate, score: x.score }, null);
  if (!next) { status("That line changed. Read the room again."); return; }
  history.push(snapshot());
  if (state.doc) { state.doc.notes.push({ before: ref.sentence, after: x.line, why: x.why || "" }); state.doc.audience = city; }
  commit(next);
  render();
  status(`Swapped in ${x.candidate.name}. ${MOD}+Z undoes it.`);
  scoreAll();
}

// ---------- files ----------

async function openFile(file) {
  if (!accepts(file)) { status("Room reads PDF, PowerPoint (.pptx), Word (.docx), text and Markdown files."); return; }
  status(`Opening ${file.name}…`);
  try {
    const doc = await parseFile(file);
    state.doc = { file, name: doc.name, kind: doc.kind, blocks: doc.blocks, notes: [], audience: "" };
    state.slug = doc.name;
    store.set("slug", doc.name);
    $("script").value = joinBlocks(doc.blocks);
    state.mode = "compose";
    if (doc.truncated) status("A long file: Room reads its first 40,000 characters.");
    await readRoom();
  } catch (err) {
    status(err.message);
  }
}

async function download() {
  try {
    if (state.doc) {
      const r = await exportFile(state.doc, state.text, state.doc.notes, state.doc.audience || state.focus);
      const how = state.doc.kind === "docx" || state.doc.kind === "pdf" ? " as tracked changes, each with its reason"
        : state.doc.kind === "pptx" ? ", logged in the speaker notes" : "";
      status(`Saved ${r.name} with ${plural(r.changed, "change")}${how}.`);
    } else {
      downloadText(`${(state.slug || "room").replace(/[^\w .-]+/g, "").trim() || "room"}.txt`, state.text);
    }
  } catch (err) {
    status(err.message);
    if (state.doc) downloadText(`${state.doc.name.replace(/\.\w+$/, "")} (Room).txt`, state.text);
  }
}

$("openBtn").addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", () => { const f = $("fileInput").files[0]; $("fileInput").value = ""; if (f) openFile(f); });
$("downloadBtn").addEventListener("click", download);

let dragDepth = 0;
const isFileDrag = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
addEventListener("dragenter", (e) => { if (!isFileDrag(e)) return; e.preventDefault(); dragDepth++; $("drop").hidden = false; });
addEventListener("dragover", (e) => { if (isFileDrag(e)) e.preventDefault(); });
addEventListener("dragleave", (e) => { if (!isFileDrag(e)) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("drop").hidden = true; });
addEventListener("drop", (e) => {
  if (!isFileDrag(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("drop").hidden = true;
  const f = e.dataTransfer.files[0];
  if (f) openFile(f);
});

// ---------- panel and paper events ----------

$("panel").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act], [data-focus], [data-ref]");
  if (!b) return;
  if (b.dataset.focus) { state.focus = b.dataset.focus; renderControls(); render(); summarise(); return; }
  if (b.dataset.ref && !b.dataset.act) { select(b.dataset.ref); return; }
  const arg = b.dataset.arg;
  switch (b.dataset.act) {
    case "lens": state.lens = arg; render(); if (arg === "gemini") loadGuess(); break;
    case "review": startReview(); break;
    case "accept": accept(arg); break;
    case "ignore": ignore(arg); break;
    case "undo": undo(); break;
    case "accept-all": acceptAll(); break;
    case "close-review": closeReview(); break;
    case "back": { const was = state.selected; state.selected = null; transition(render); focusSoon(`.rowname[data-ref="${CSS.escape(was || "")}"]`); break; }
    case "math": state.math = !state.math; renderPanel(); break;
    case "swap": findSwap(arg, b.dataset.city); break;
    case "use-swap": useSwap(arg, b.dataset.city, +b.dataset.i); break;
    case "route": routeTour(); break;
    case "stop": openStop(arg); break;
    case "sheet": state.tour.active = null; transition(() => { renderControls(); render(); }); break;
    case "print": printSetLists(); break;
  }
});

$("pop").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  if (b.dataset.act === "accept") accept(b.dataset.arg, "paper");
  if (b.dataset.act === "ignore") ignore(b.dataset.arg, "paper");
});

$("panel").addEventListener("change", async (e) => {
  const sel = e.target.closest("[data-rematch]");
  if (!sel) return;
  const ref = state.refs.find((r) => r.id === sel.dataset.rematch);
  const pick = (ref.candidates || []).find((c) => c.entity_id === sel.value);
  if (!pick) return;
  ref.match = pick;
  if (pick.type) ref.type = pick.type;
  ref.certain = true;
  delete state.scores[ref.id];
  delete state.tour.scores[ref.id];
  render();
  await scoreAll();
});

function select(id) {
  if (state.review || state.tab === "tour") return;
  state.selected = id;
  transition(render);
  focusSoon("#detailTitle");
  if (innerWidth < 960) $("panel").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
}

function onPaper(target) {
  const s = target.closest("[data-item]");
  if (s) { openPop(s, s.dataset.item); return true; }
  const r = target.closest("[data-ref]");
  if (r) { select(r.dataset.ref); return true; }
  return false;
}
$("read").addEventListener("click", (e) => onPaper(e.target));
$("read").addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && onPaper(e.target)) e.preventDefault();
});

// ---------- compose ----------

$("readBtn").addEventListener("click", readRoom);
$("editBtn").addEventListener("click", () => {
  state.review = null;
  state.mode = "compose";
  state.selected = null;
  state.gen++;
  $("script").value = state.text;
  status(state.doc ? "Editing a file's text works best one paragraph at a time; the download keeps its layout when the paragraphs stay put." : "");
  render();
  $("script").focus();
});
$("script").addEventListener("input", () => { store.set("text", $("script").value); });
$("script").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); readRoom(); } });

function loadSample(i) {
  const s = SAMPLES[i];
  state.doc = null;
  state.slug = s.slug;
  store.set("slug", s.slug);
  $("script").value = s.text;
  state.mode = "compose";
  state.tour.stops = s.stops;
  store.set("stops", s.stops);
  setCities(s.cities);
  readRoom();
}
$("samples").innerHTML = SAMPLES.map((s, i) => `<button type="button" data-sample="${i}">${s.name}</button>`).join("");
$("samples").addEventListener("click", (e) => { const b = e.target.closest("[data-sample]"); if (b) loadSample(+b.dataset.sample); });

// ---------- commands and keys ----------

function commands() {
  const reading = state.mode === "read" && state.refs.length;
  const list = [
    { label: "Read the room", hint: `${MOD}+Enter`, run: readRoom },
    { label: "Open a file", hint: "PDF, PPTX, DOCX", run: () => $("fileInput").click() },
  ];
  if (reading) {
    state.cities.forEach((c) => list.push({ label: `Review for ${c}`, run: () => { setTab("room"); startReview(c); } }));
    list.push({ label: "Route the tour", run: () => { setTab("tour"); routeTour(); } });
    list.push({ label: state.doc ? "Download the corrected file" : "Download the text", run: download });
    list.push({ label: state.lens === "gemini" ? "Show Room's verdicts" : "Show Gemini alone", run: () => { state.lens = state.lens === "gemini" ? "qloo" : "gemini"; render(); if (state.lens === "gemini") loadGuess(); } });
  }
  if (state.review?.items.some((it) => it.status === "pending")) list.push({ label: "Accept every suggestion", run: acceptAll });
  if (history.length) list.push({ label: "Undo the last edit", hint: `${MOD}+Z`, run: undo });
  list.push({ label: state.tab === "tour" ? "Switch to Room" : "Switch to Tour", run: () => setTab(state.tab === "tour" ? "room" : "tour") });
  SAMPLES.forEach((s, i) => list.push({ label: `Sample: ${s.name}`, run: () => loadSample(i) }));
  AGES.forEach(([v, l]) => list.push({ label: `Audience: ${l}`, run: () => { state.age = v; store.set("age", v); renderControls(); if (state.mode === "read") { scoreAll(); render(); } } }));
  list.push({ label: "How Room reads", hint: "?", run: () => $("how").showModal() });
  return list;
}

$("paletteBtn").addEventListener("click", () => openPalette(commands()));
addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(commands()); return; }
  if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === "z" && !typing && history.length) { e.preventDefault(); undo(); return; }
  if (typing || document.querySelector("dialog[open]")) return;
  if (e.key === "Escape") {
    if ($("pop").matches?.(":popover-open")) { closePop(true); return; }
    if (state.selected) { const was = state.selected; state.selected = null; transition(render); focusSoon(`.rowname[data-ref="${CSS.escape(was)}"]`); return; }
    if (state.tour.active) { state.tour.active = null; transition(() => { renderControls(); render(); }); return; }
    if (state.review) {
      // Pending suggestions are work: leaving them takes the Done button, not a stray key.
      if (state.review.running || state.review.items.some((it) => it.status === "pending")) { status("Use Done to leave the review."); return; }
      closeReview();
    }
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "?") { $("how").showModal(); return; }
  if (!state.review) return;
  // Letter keys act only while a review surface has focus: the panel, the paper or the suggestion card.
  const on = document.activeElement?.closest?.("#panel, #read, #pop");
  if (!on) return;
  const k = e.key.toLowerCase();
  const from = on.id === "panel" ? "panel" : "paper";
  if (k === "j") { e.preventDefault(); move(1); }
  else if (k === "k") { e.preventDefault(); move(-1); }
  else if (k === "a" && state.review.current) { e.preventDefault(); accept(state.review.current, from); }
  else if (k === "i" && state.review.current) { e.preventDefault(); ignore(state.review.current, from); }
});

// Paste a copied file to open it.
addEventListener("paste", (e) => {
  const f = e.clipboardData?.files?.[0];
  if (f && accepts(f)) { e.preventDefault(); openFile(f); }
});

$("howBtn").addEventListener("click", () => $("how").showModal());
$("legend").innerHTML = Object.entries(LEGEND).map(([k, v]) => `<dt class="vw v-${k}">${WORD[k]}</dt><dd>${v}</dd>`).join("");
$("cityList").innerHTML = PRESETS.map((c) => `<option value="${c}">`).join("");

document.querySelectorAll(".mod").forEach((el) => { el.textContent = MOD; });
$("paletteBtn").setAttribute("aria-keyshortcuts", APPLE ? "Meta+K" : "Control+K");
$("undoBtn").addEventListener("click", undo);
addEventListener("resize", moveSpot);

initPalette();
$("script").value = state.text;
renderControls();
render();
