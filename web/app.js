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

const SAMPLES = [
  { name: "Stand-up", slug: "INT. A FLIGHT. 2AM.", cities: ["Dallas", "London", "Johannesburg", "Lagos"], text:
`I flew into Dallas at 2am and the only thing open was a Whataburger. My cousin from London said that's just Greggs in a cowboy hat. He spent the whole flight watching Coronation Street on his phone, volume up, like the plane needed to know who cheated on who.

I tried to fix the mood with some Kabza De Small. The guy in 14C asked if that was a new kind of yoga. So I put on Nickelback. Everyone hated it. Everyone knew every word.

We landed, he bought Crocs at the airport, and I knew right then: this man has given up, and he has never been happier.` },
  { name: "Launch ad", slug: "EXT. SUMMER CAMPAIGN", cities: ["Lagos", "Atlanta", "London"], text:
`This summer, trade the Starbucks run for something louder. Burna Boy on the speakers, Squid Game on the big screen, and Nando's on every table. Bring the friend who still wears Crocs. We'll forgive them.` },
  { name: "Best man", slug: "INT. RECEPTION HALL", cities: ["London", "Harare", "Toronto"], text:
`Tunde and I met at a Wetherspoons in Peckham. He was singing Oasis, badly. Ten years later he still thinks jollof rice is a personality, and he still quotes Love Actually every Christmas. Tonight we celebrate the only woman who ever made him miss an Arsenal match.` },
];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const store = {
  get(k, d) { try { const v = localStorage.getItem("room:" + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("room:" + k, JSON.stringify(v)); } catch { /* storage off */ } },
};

const state = {
  text: store.get("text", SAMPLES[0].text),
  slug: store.get("slug", SAMPLES[0].slug),
  cities: store.get("cities", SAMPLES[0].cities),
  age: store.get("age", ""),
  mode: "compose",
  refs: [],
  scores: {},      // ref id -> { key, data }
  swaps: {},       // ref id + city -> { loading, list, error }
  focus: null,
  selected: null,
  math: false,
  gen: 0,
  lens: "qloo",    // "qloo": measured by Qloo; "gemini": Gemini's guess from memory
  guess: null,     // { key, data: { refId: { city: { known, loved } } }, loading, error }
};
state.focus = state.cities[0];

async function api(path, body) {
  const res = await fetch(API + path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : undefined);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data;
}

const roomKey = () => state.cities.join("|") + "#" + state.age;
const scoreOf = (ref) => {
  if (ref.score) return ref.score;            // references inside an agent draft carry their own score
  const s = state.scores[ref.id];
  return s && s.key === roomKey() ? s.data : null;
};
const scorable = (ref) => ref.match && !ref.outside;

// Same thresholds as the engine, for Gemini's numbers.
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

function verdictFor(ref, city) {
  if (state.lens === "gemini" && !state.agent && !ref.outside && ref.match) return guessVerdict(ref, city);
  return measuredVerdict(ref, city);
}

function measuredVerdict(ref, city) {
  if (ref.outside) return "outside";
  if (!ref.match) return "unscored";
  const s = scoreOf(ref);
  if (!s) return null;
  return s.cities[city]?.verdict ?? "unscored";
}

function status(msg) { $("status").textContent = msg || ""; }

// ---------- audience ----------

function renderChips() {
  $("chips").innerHTML = state.cities.map((c) => `
    <span class="chip ${c === state.focus ? "focus" : ""}">
      <button class="name" data-focus="${esc(c)}" type="button" title="Underline the script for ${esc(c)}">${esc(c)}</button>
      <button class="x" data-remove="${esc(c)}" type="button" aria-label="Remove ${esc(c)}">×</button>
    </span>`).join("");
  $("cityInput").disabled = state.cities.length >= MAX_CITIES;
  $("cityInput").placeholder = state.cities.length >= MAX_CITIES ? "Four cities max" : "Add a city";
}

function renderAges() {
  $("ages").innerHTML = AGES.map(([v, l]) =>
    `<button type="button" role="radio" aria-checked="${v === state.age}" data-age="${v}">${l}</button>`).join("");
}

function setCities(cities) {
  state.agent = null;
  state.cities = cities;
  if (!cities.includes(state.focus)) state.focus = cities[0];
  store.set("cities", cities);
  renderChips();
  if (state.mode === "read") { scoreAll(); render(); }
}

$("chips").addEventListener("click", (e) => {
  const r = e.target.closest("[data-remove]");
  if (r) {
    if (state.cities.length > 1) setCities(state.cities.filter((c) => c !== r.dataset.remove));
    return;
  }
  const f = e.target.closest("[data-focus]");
  if (f) { state.focus = f.dataset.focus; renderChips(); render(); }
});

$("addCity").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("cityInput").value.trim();
  if (!q || state.cities.length >= MAX_CITIES) return;
  $("cityInput").value = "";
  try {
    const c = await api(`/city?q=${encodeURIComponent(q)}`);
    if (!state.cities.includes(c.name)) setCities([...state.cities, c.name]);
  } catch (err) { status(err.message); }
});

$("ages").addEventListener("click", (e) => {
  const b = e.target.closest("[data-age]");
  if (!b) return;
  state.age = b.dataset.age;
  store.set("age", state.age);
  renderAges();
  if (state.mode === "read") { scoreAll(); render(); }
});

// ---------- reading ----------

async function readRoom() {
  const text = $("script").value.trim();
  if (!text) { status("Write or paste something first."); return; }
  state.text = text;
  store.set("text", text);
  state.mode = "read";
  state.refs = [];
  state.scores = {};
  state.swaps = {};
  state.guess = null;
  state.selected = null;
  $("readBtn").disabled = true;
  status("Reading the script…");
  render();
  try {
    const { references } = await api("/read", { text });
    state.refs = references;
    if (!references.length) status("No references found. Room reads brands, artists, shows, films, books, people and places.");
    render();
    await scoreAll();
  } catch (err) {
    status(err.message);
  } finally {
    $("readBtn").disabled = false;
  }
}

async function scoreAll() {
  if (state.lens === "gemini") loadGuess();
  const gen = ++state.gen;
  const key = roomKey();
  const todo = state.refs.filter((r) => scorable(r) && !(state.scores[r.id]?.key === key));
  let done = 0;
  const total = todo.length;
  if (!total) { summarise(); return; }
  status(`Scoring ${total} reference${total > 1 ? "s" : ""} across ${state.cities.length} cities…`);
  const queue = [...todo];
  const worker = async () => {
    while (queue.length) {
      const ref = queue.shift();
      try {
        const data = await api("/score", { entity: ref.match, type: ref.type, cities: state.cities, age: state.age || null });
        if (gen !== state.gen) return;
        state.scores[ref.id] = { key, data };
      } catch (err) {
        if (gen !== state.gen) return;
        state.scores[ref.id] = { key, data: { cities: {}, error: err.message } };
      }
      done += 1;
      if (done < total) status(`Scored ${done} of ${total}…`);
      render();
    }
  };
  await Promise.all([worker(), worker(), worker()]);
  if (gen === state.gen) summarise();
}

function summarise() {
  if (state.mode !== "read" || !state.refs.length) return;
  const f = state.focus;
  const counts = {};
  state.refs.forEach((r) => { const v = verdictFor(r, f); if (v) counts[v] = (counts[v] || 0) + 1; });
  const dead = (counts.dies || 0);
  status(dead === 1 ? `1 reference dies in ${f}. Tap it for a local swap.`
    : dead ? `${dead} references die in ${f}. Tap one for a local swap.`
    : `Everything here has a pulse in ${f}.`);
}

// ---------- render ----------

function render() {
  const reading = state.mode === "read";
  $("script").hidden = reading;
  $("read").hidden = !reading;
  $("editBtn").hidden = !reading;
  $("readBtn").textContent = reading ? "Read again" : "Read the room";
  $("slug").textContent = state.slug;
  const a = state.agent;
  if (reading) renderPaper(a ? a : state);
  $("agent").hidden = !a;
  if (a) {
    $("board").hidden = true;
    $("detail").hidden = true;
    renderAgent();
    return;
  }
  renderBoard();
  renderDetail();
}

function renderPaper(view) {
  const t = view.text;
  if (!view.refs.length) { $("read").innerHTML = esc(t); return; }
  let html = "", at = 0;
  for (const r of [...view.refs].sort((a, b) => a.start - b.start)) {
    if (r.start < at) continue;
    const v = verdictFor(r, state.focus);
    html += esc(t.slice(at, r.start));
    html += `<span class="ref ${v ? "v-" + v : "wait"} ${state.selected === r.id ? "sel" : ""} ${r.swapped_from ? "swapped" : ""}" title="${r.swapped_from ? "Was " + esc(r.swapped_from) : ""}" data-ref="${r.id}" tabindex="0" role="button" aria-label="${esc(r.surface)}: ${v ? WORD[v] : "scoring"} in ${esc(state.focus)}">${esc(t.slice(r.start, r.end))}</span>`;
    at = r.end;
  }
  $("read").innerHTML = html + esc(t.slice(at));
}

function roomScore(city, refs = state.refs) {
  const vals = refs.map((r) => verdictFor(r, city)).filter((v) => v in VALUE);
  if (!vals.length) return null;
  return Math.round(100 * vals.reduce((a, v) => a + VALUE[v], 0) / vals.length);
}

function cell(ref, city) {
  const v = verdictFor(ref, city);
  if (!v) return `<span class="cell wait" aria-label="scoring"></span>`;
  const low = state.lens === "qloo" && scoreOf(ref)?.cities?.[city]?.confidence === "low";
  const other = state.lens === "gemini" ? measuredVerdict(ref, city) : guessVerdict(ref, city);
  const differs = other && other !== v && !["outside", "unscored"].includes(v);
  const tip = differs ? `${state.lens === "gemini" ? "Room says" : "Gemini alone says"}: ${WORD[other]}` : (LEGEND[v] || "");
  return `<span class="cell v-${v} ${low ? "low" : ""} ${differs ? "differs" : ""}" title="${esc(tip)}">${WORD[v]}</span>`;
}

function renderBoard() {
  const board = $("board");
  $("board").hidden = !!state.selected;
  if (state.mode !== "read") {
    board.innerHTML = `<p class="empty">Put a script under the light. Room checks every reference against the people in the seats.
      <small>Pick up to four cities and an age. Tap a reference to see why it lands, and get a swap that does the same job for that crowd.</small></p>`;
    return;
  }
  if (!state.refs.length) {
    board.innerHTML = `<p class="empty">Reading…</p>`;
    return;
  }
  const scoring = state.refs.some((r) => scorable(r) && !scoreOf(r));
  const head = state.cities.map((c) => {
    const n = roomScore(c);
    return `<th><button class="colhead ${c === state.focus ? "focus" : ""}" data-focus="${esc(c)}" type="button">
      <span class="c">${esc(c)}</span><span class="n">${n == null ? "··" : n}<i>${n == null ? "" : "%"}</i></span></button></th>`;
  }).join("");
  const rows = state.refs.map((r) => `
    <tr><td><button class="rowname" data-ref="${r.id}" type="button"><b>${esc(r.surface)}</b>
      <span>${esc(r.outside ? "outside the graph" : (r.match?.type || r.type).replace("_", " "))}</span></button></td>
      ${state.cities.map((c) => `<td>${cell(r, c)}</td>`).join("")}</tr>`).join("");
  const lens = `<div class="lens" role="radiogroup" aria-label="Whose verdicts">
      <button type="button" role="radio" aria-checked="${state.lens === "qloo"}" data-lens="qloo">Room</button>
      <button type="button" role="radio" aria-checked="${state.lens === "gemini"}" data-lens="gemini">Gemini alone</button>
    </div>`;
  const g = state.guess;
  const lensNote = state.lens === "gemini"
    ? (g?.loading ? "Asking Gemini to guess from memory…" : g?.error ? esc(g.error)
      : "Gemini guessing everything from memory, Loved included. Outlined cells are where it disagrees with Room.")
    : (g?.key === roomKey() && g.data ? "Outlined cells are where Gemini alone disagrees with Room." : "");
  board.innerHTML = `${lens}${lensNote ? `<p class="lensnote">${lensNote}</p>` : ""}<table class="board"><thead><tr><th></th>${head}</tr></thead><tbody>${rows}</tbody></table>
    <p class="boardnote">The number under each city is how much of the script lands there. Tap a city to underline the script for it.</p>
    <div class="agentcall">
      <button class="primary" data-agent type="button" ${scoring ? "disabled" : ""}>Rewrite for ${esc(state.focus)}</button>
      <p>An agent swaps what dies in ${esc(state.focus)}, keeps what the line needs, and shows every step.</p>
    </div>`;
}

function bar(label, cls, v) {
  const pct = v == null ? 0 : Math.round(v * 100);
  return `<span>${label}</span><span class="bar ${cls}"><i style="width:${pct}%"></i></span><span>${v == null ? "n/a" : v.toFixed(2)}</span>`;
}

function renderDetail() {
  const box = $("detail");
  const ref = state.refs.find((r) => r.id === state.selected);
  box.hidden = !ref;
  if (!ref) return;
  const s = scoreOf(ref);
  const m = ref.match;
  const meta = ref.outside
    ? `<span>Outside Qloo's graph. ${esc(LEGEND.outside)}</span>`
    : m ? `<span>Matched to</span>
        <select data-rematch="${ref.id}" aria-label="Qloo match">
          ${(ref.candidates || [m]).map((c) => `<option value="${esc(c.entity_id)}" ${c.entity_id === m.entity_id ? "selected" : ""}>${esc(c.name)}${c.disambiguation && c.disambiguation !== c.name ? " · " + esc(c.disambiguation) : ""}</option>`).join("")}
        </select>${ref.certain ? "" : `<span class="warn">Check this match.</span>`}`
      : ref.candidates?.length
        ? `<span class="warn">Qloo holds no clear match.</span>
          <select data-rematch="${ref.id}" aria-label="Pick a Qloo match">
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
      ${weak && !sw ? `<button class="swapbtn" data-swap="${ref.id}" data-city="${esc(c)}" type="button">Find a ${esc(c)} swap</button>` : ""}
      ${sw ? renderSwaps(ref, c, sw) : ""}
    </div>`;
  }).join("");

  const home = s?.elsewhere && !state.cities.includes(s.elsewhere.city)
    ? `<p class="elsewhere">Lands hardest in <b>${esc(s.elsewhere.city)}</b> across Room's anchor cities.</p>` : "";

  box.innerHTML = `
    <button class="back" data-back type="button">← The whole room</button>
    <h2 class="dname">${esc(ref.surface)}</h2>
    <div class="dmeta">${meta}</div>
    <p class="job"><span>Its job in the line</span>${esc(ref.role)}</p>
    ${s?.error ? `<p class="why warn">${esc(s.error)}</p>` : ""}
    ${rows}
    ${home}
    ${scorable(ref) ? `<button class="ghost mathtoggle" data-math type="button">${state.math ? "Hide" : "Show"} the math</button>` : ""}`;
}

// Where the new reference sits in a swapped line: the candidate's name if Gemini kept it,
// otherwise the words that changed between the old line and the new one.
function swapSpan(oldLine, newLine, name) {
  const byName = newLine.toLowerCase().indexOf(name.toLowerCase());
  if (byName >= 0) return { at: byName, len: name.length };
  const a = oldLine, b = newLine;
  let p = 0;
  while (p < a.length && p < b.length && a[p] === b[p]) p++;
  let q = 0;
  while (q < a.length - p && q < b.length - p && a[a.length - 1 - q] === b[b.length - 1 - q]) q++;
  while (p > 0 && /\w/.test(b[p - 1])) p--;
  while (q > 0 && /\w/.test(b[b.length - q])) q--;
  const changed = b.slice(p, b.length - q).trim();
  if (!changed) return null;
  return { at: b.indexOf(changed, p), len: changed.length };
}

function renderSwaps(ref, city, sw) {
  if (sw.loading) return `<p class="why">Asking Qloo what ${esc(city)} loves, then keeping what does the same job…</p>`;
  if (sw.error) return `<p class="why warn">${esc(sw.error)}</p>`;
  if (!sw.list.length) return `<p class="why">Qloo offered nothing close enough for ${esc(city)}.</p>`;
  return `<div class="swaps">${sw.list.map((x, i) => {
    const d = x.score?.cities?.[city];
    const v = x.score ? (d?.verdict || "unscored") : null;
    const name = x.candidate.name;
    const span = swapSpan(ref.sentence, x.line, name);
    const line = span
      ? esc(x.line.slice(0, span.at)) + `<mark>${esc(x.line.substr(span.at, span.len))}</mark>` + esc(x.line.slice(span.at + span.len))
      : esc(x.line);
    return `<div class="swap">
      <div class="swap-top"><b>${esc(name)}</b>${v ? `<span class="cell v-${v}">${WORD[v]}${d ? " · known " + d.known.toFixed(2) : ""}</span>` : `<span class="cell wait" aria-label="scoring"></span>`}</div>
      <p class="line">${line}</p>
      <p class="swhy">${esc(x.why)}</p>
      <button class="ghost use" ${x.score ? "" : "disabled"} data-use="${ref.id}" data-city="${esc(city)}" data-i="${i}" type="button">Use this line</button>
    </div>`;
  }).join("")}</div>`;
}

// ---------- second opinion ----------

async function loadGuess() {
  const key = roomKey();
  if (state.guess?.key === key && (state.guess.data || state.guess.loading)) return;
  const refs = state.refs.filter((r) => r.match && !r.outside)
    .map((r) => ({ id: r.id, name: r.match.name, type: r.type }));
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

// ---------- the rewrite agent ----------

const TARGET = 80;
const WHO = { you: "You", gemini: "Gemini", qloo: "Qloo", room: "Room" };

async function runAgent() {
  const city = state.focus;
  const a = {
    city, running: true, trace: [], edits: 0, text: state.text,
    refs: state.refs.map((r) => ({ ...r, score: scoreOf(r) })),
  };
  a.before = Object.fromEntries(state.cities.map((c) => [c, roomScore(c, a.refs)]));
  state.agent = a;
  state.selected = null;
  const live = () => state.agent === a;
  const push = (entries) => { if (!live()) return; a.trace.push(...entries); render(); };
  push([{ who: "you", text: `Make this land in ${city}.` }]);
  try {
    const p = await api("/agent/plan", { text: a.text, refs: a.refs, city });
    push(p.trace);
    for (const step of p.plan) {
      if (!live()) return;
      if (step.action !== "swap") continue;
      const ref = a.refs.find((r) => r.id === step.ref_id);
      if (!ref) continue;
      a.step = ref.surface;
      render();
      const f = await api("/agent/find", { ref, city, exclude: a.refs.filter((r) => r.match).map((r) => r.match.entity_id) });
      push(f.trace);
      if (!f.picks.length || !live()) continue;
      const t = await api("/agent/test", {
        text: a.text, refs: a.refs, ref_id: ref.id, picks: f.picks, city,
        cities: state.cities, age: state.age || null,
      });
      if (!live()) return;
      if (t.applied) { a.text = t.text; a.refs = t.refs; a.edits += 1; }
      push(t.trace);
      if ((roomScore(city, a.refs) ?? 0) >= TARGET) {
        push([{ who: "room", text: `${city} clears ${TARGET}%. Stopping here.` }]);
        break;
      }
    }
  } catch (err) {
    push([{ who: "room", text: err.message, kind: "error" }]);
  }
  if (!live()) return;
  a.running = false;
  a.step = null;
  push([{ who: "room", kind: "done", text: a.edits
    ? `Done. ${a.edits} line${a.edits > 1 ? "s" : ""} rewritten for ${city}.`
    : `Done. The script stays as written for ${city}.` }]);
}

function renderAgent() {
  const a = state.agent;
  const scores = state.cities.map((c) => {
    const b = a.before[c], n = roomScore(c, a.refs);
    const d = n != null && b != null ? n - b : 0;
    return `<div class="ascore ${c === a.city ? "focus" : ""}"><span class="c">${esc(c)}</span>
      <span class="n">${n ?? "··"}<i>%</i></span>
      <span class="d ${d > 0 ? "up" : d < 0 ? "down" : ""}">${d > 0 ? "+" + d : d < 0 ? d : "±0"}</span></div>`;
  }).join("");
  const trace = a.trace.map((e) => `
    <li class="t-${e.who} ${e.kind ? "k-" + e.kind : ""}">
      <span class="who">${WHO[e.who] || e.who}</span>
      <span class="what">${esc(e.text)}</span>
      ${e.ms >= 100 ? `<span class="ms">${(e.ms / 1000).toFixed(1)} s</span>` : "<span></span>"}
    </li>`).join("");
  $("agent").innerHTML = `
    <button class="back" data-agent-discard type="button">← The whole room</button>
    <h2 class="dname">Rewrite for ${esc(a.city)}</h2>
    <p class="why">Target ${TARGET}% in ${esc(a.city)}. Every Qloo call and every choice is on the record.</p>
    <div class="ascores">${scores}</div>
    <ol class="trace">${trace}</ol>
    ${a.running ? `<p class="working"><span class="dot"></span>${a.step ? `Working on ${esc(a.step)}…` : "Planning…"}</p>` : `
    <div class="agentdone">
      ${a.edits ? `<button class="primary" data-agent-use type="button">Use this version</button>` : ""}
      <button class="ghost" data-agent-discard type="button">${a.edits ? "Discard" : "Back to the room"}</button>
    </div>`}`;
  status(a.running ? `The agent is rewriting for ${a.city}. The paper shows its draft.`
    : a.edits ? "The paper shows the agent's draft. Use it or discard it." : "");
  const list = $("agent").querySelector(".trace");
  if (list) list.scrollTop = list.scrollHeight;
}

function useAgent() {
  const a = state.agent;
  const key = roomKey();
  state.text = a.text;
  state.refs = a.refs.map(({ score, ...r }) => r);
  state.scores = Object.fromEntries(a.refs.filter((r) => r.score).map((r) => [r.id, { key, data: r.score }]));
  state.swaps = {};
  state.agent = null;
  store.set("text", state.text);
  $("script").value = state.text;
  render();
  summarise();
}

// ---------- detail actions ----------

async function findSwap(refId, city) {
  const ref = state.refs.find((r) => r.id === refId);
  const k = refId + "|" + city;
  state.swaps[k] = { loading: true };
  renderDetail();
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
  renderDetail();
  const key = roomKey();
  await Promise.all((state.swaps[k].list || []).map(async (x) => {
    try {
      x.score = await api("/score", { entity: x.candidate, type: ref.type, cities: state.cities, age: state.age || null });
      x.key = key;
    } catch (err) {
      x.score = { cities: {}, error: err.message };
    }
    if (state.swaps[k]?.list?.includes(x)) renderDetail();
  }));
}

function useSwap(refId, city, i) {
  const ref = state.refs.find((r) => r.id === refId);
  const x = state.swaps[refId + "|" + city].list[i];
  const t = state.text;
  const from = t.lastIndexOf(ref.sentence, ref.start);
  const at = from >= 0 ? from : t.indexOf(ref.sentence);
  if (at < 0) { status("That line changed. Read the room again."); return; }
  const next = t.slice(0, at) + x.line + t.slice(at + ref.sentence.length);
  const span = swapSpan(ref.sentence, x.line, x.candidate.name);
  const hit = span ? span.at : -1;
  const hitLen = span ? span.len : 0;

  // Re-anchor every reference in order against the new text.
  const old = [...state.refs].sort((a, b) => a.start - b.start);
  let cursor = 0;
  for (const r of old) {
    if (r.id === refId) {
      r.surface = hit >= 0 ? x.line.substr(hit, hitLen) : x.candidate.name;
      r.name = x.candidate.name;
      r.match = x.candidate;
      r.candidates = [x.candidate];
      r.certain = true;
      r.start = hit >= 0 ? at + hit : at;
      r.end = hit >= 0 ? r.start + hitLen : at;
      r.sentence = x.line;
      if (x.key === roomKey()) state.scores[r.id] = { key: x.key, data: x.score };
      else delete state.scores[r.id];
      cursor = Math.max(cursor, r.end);
      continue;
    }
    const j = next.indexOf(r.surface, r.start < at ? Math.min(cursor, r.start) : cursor);
    if (j >= 0) { r.start = j; r.end = j + r.surface.length; cursor = r.end; }
    if (r.sentence === ref.sentence) r.sentence = x.line;
  }
  state.text = next;
  store.set("text", next);
  $("script").value = next;
  state.swaps = {};
  render();
  scoreAll();
}

$("panel").addEventListener("click", (e) => {
  const t = e.target;
  if (t.closest("[data-agent]")) { runAgent(); return; }
  const lensBtn = t.closest("[data-lens]");
  if (lensBtn) {
    state.lens = lensBtn.dataset.lens;
    render();
    if (state.lens === "gemini") loadGuess();
    return;
  }
  if (t.closest("[data-agent-use]")) { useAgent(); return; }
  if (t.closest("[data-agent-discard]")) { state.agent = null; render(); summarise(); return; }
  if (t.closest("[data-back]")) { state.selected = null; render(); return; }
  if (t.closest("[data-math]")) { state.math = !state.math; renderDetail(); return; }
  const f = t.closest("[data-focus]");
  if (f) { state.focus = f.dataset.focus; renderChips(); render(); summarise(); return; }
  const row = t.closest("[data-ref]");
  if (row) { state.selected = row.dataset.ref; render(); return; }
  const sw = t.closest("[data-swap]");
  if (sw) { findSwap(sw.dataset.swap, sw.dataset.city); return; }
  const use = t.closest("[data-use]");
  if (use) useSwap(use.dataset.use, use.dataset.city, +use.dataset.i);
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
  render();
  await scoreAll();
});

function select(id) {
  if (state.agent) return;
  state.selected = id;
  render();
  if (window.innerWidth < 920) $("panel").scrollIntoView({ behavior: "smooth", block: "start" });
}
$("read").addEventListener("click", (e) => {
  const r = e.target.closest("[data-ref]");
  if (r) select(r.dataset.ref);
});
$("read").addEventListener("keydown", (e) => {
  const r = e.target.closest("[data-ref]");
  if (r && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select(r.dataset.ref); }
});

// ---------- compose ----------

$("readBtn").addEventListener("click", readRoom);
$("editBtn").addEventListener("click", () => {
  state.agent = null;
  state.mode = "compose";
  state.selected = null;
  state.gen++;
  $("script").value = state.text;
  status("");
  render();
  $("script").focus();
});
$("script").addEventListener("input", () => { store.set("text", $("script").value); });
$("script").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) readRoom(); });

$("samples").innerHTML = SAMPLES.map((s, i) => `<button type="button" data-sample="${i}">${s.name}</button>`).join("");
$("samples").addEventListener("click", (e) => {
  const b = e.target.closest("[data-sample]");
  if (!b) return;
  const s = SAMPLES[+b.dataset.sample];
  state.slug = s.slug;
  store.set("slug", s.slug);
  $("script").value = s.text;
  state.mode = "compose";
  setCities(s.cities);
  readRoom();
});

$("howBtn").addEventListener("click", () => $("how").showModal());
$("legend").innerHTML = Object.entries(LEGEND).map(([k, v]) => `<dt class="vw v-${k}">${WORD[k]}</dt><dd>${v}</dd>`).join("");
$("cityList").innerHTML = PRESETS.map((c) => `<option value="${c}">`).join("");

$("script").value = state.text;
renderChips();
renderAges();
render();
