// Pitch: say what you are launching. Qloo reads who loves it, what else they love and where they gather; Gemini
// pitches ideas built only from that; Room reads them back and keeps a receipt for every name.
// Ink is Qloo. Pencil is Gemini.

import { ticks } from "./motion.js";

export const PITCH_SAMPLES = [
  { name: "Sparkling tea", slug: "INT. A BRAND LAUNCH", text: "Liquid Death launches a sparkling tea. Austin, London, Atlanta." },
  { name: "Debut album", slug: "INT. A RECORD ROLLOUT", text: "A debut album for fans of SZA and Daniel Caesar. Out in March. London, Atlanta, Lagos." },
  { name: "Horror film", slug: "INT. AN OPENING WEEKEND", text: "A horror film for fans of Midsommar and The Lighthouse. Opens 30 October. Austin, Toronto, London." },
];

const LANES = [["artist", "They listen to"], ["tv_show", "They watch"], ["movie", "At the cinema"], ["podcast", "In their ears"],
  ["brand", "They buy"], ["person", "They follow"], ["videogame", "They play"], ["book", "They read"], ["destination", "They go to"]];
const LABEL = Object.fromEntries(LANES);
const SLOT = { partner: "With", venue: "Where", media: "On", sound: "Sound", look: "Look" };
const ROLE = { Open: "role-open", Build: "role-build", Inside: "role-inside", Wait: "role-wait", Thin: "role-thin" };
const VERD = { lands: "lands", roast: "roast", inside: "inside", dies: "dies", famous: "famous", global: "famous", unscored: "n/a" };
const KILL = ["Taken", "One city", "Thin", "Obvious", "Off-brief"];
const WHO = { you: "You", gemini: "Gemini", qloo: "Qloo", room: "Room" };
const COUNT = ["No ideas", "One idea", "Two ideas", "Three ideas"];
const LIVE = new Set(["brief", "lanes", "where", "venues", "write", "readback", "whatif", "rollout", "draw"]);

const fmt = (x) => (x == null ? "" : `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(3)}`);
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const cities = (n) => plural(n, "city").replace("citys", "cities");
const listing = (xs) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`);
const cap = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
const verb = (xs, one, many) => (xs.length > 1 ? many : one);

async function pool(items, n, fn) {
  const queue = [...items];
  await Promise.all(Array.from({ length: n }, async () => { while (queue.length) await fn(queue.shift()); }));
}

export function createPitch(ctx) {
  const { $, esc, api } = ctx;
  const P = {
    text: "", briefText: "", slug: "", busy: "", gen: 0, error: "", sample: "", seed: 0, statusLine: "",
    brief: null, subjects: [], picking: null, lanes: {}, threads: [], marks: {}, where: null, venues: {}, age: null,
    ideas: [], kept: [], killed: [], launch: "", strips: {}, rollout: null, rolloutFor: null, rolling: null,
    trace: [], traceOpen: null, answer: null, tone: "", pins: [], pinNames: {}, raw: false, receipt: null,
    killing: null, stale: "", note: "", visuals: {}, drawing: null,
  };

  const status = (m) => { P.statusLine = m || ""; ctx.status(m); };
  const trace = (who, text, ms) => { P.trace.push({ who, text, ms }); };
  const since = (t0) => Math.round(performance.now() - t0);
  const resolved = () => P.subjects.filter((s) => s.match);
  const subjectName = () => listing(resolved().map((s) => s.match.name));
  const control = () => Object.values(P.lanes).find((l) => l?.control)?.control;
  const working = () => LIVE.has(P.busy);
  const launchIsName = () => resolved().some((s) => s.role !== "comp");

  function params() {
    const b = P.brief || {};
    return {
      subjects: resolved().map((s) => ({ id: s.match.entity_id, type: s.type, name: s.match.name, role: s.role })),
      cities: ctx.cities(), age: ctx.age() || null, categories: b.categories || [], kind: b.kind || "campaign",
      news: b.news || "", when: b.when || "", avoid: b.avoid || [], alcohol: !!b.alcohol,
    };
  }

  function clearResults() {
    Object.assign(P, { lanes: {}, threads: [], marks: {}, where: null, venues: {}, ideas: [], kept: [], killed: [],
      launch: "", strips: {}, rollout: null, rolloutFor: null, rolling: null, answer: null, tone: "", pins: [],
      pinNames: {}, receipt: null, killing: null, error: "", stale: "", note: "", traceOpen: null, drawing: null });
    for (const v of Object.values(P.visuals)) URL.revokeObjectURL(v.url);
    P.visuals = {};
  }

  // The footer's one button: Again for the brief already read, Pitch it for a new one.
  const fresh = () => ($("briefInput")?.value ?? P.text).trim() !== P.briefText;
  function primary() {
    if (P.brief && resolved().length && !fresh()) { again(); return; }
    go();
  }
  const primaryLabel = () => (P.brief && resolved().length && !fresh() && P.ideas.length ? "Again" : "Pitch it");

  // ---------- the run ----------

  async function go(text, opts = {}) {
    text = (text ?? $("briefInput")?.value ?? "").trim();
    if (!text) { status("Name what you are launching. One line is enough."); $("briefInput")?.focus(); return; }
    const gen = ++P.gen;
    const newBrief = text !== P.briefText;
    clearResults();
    Object.assign(P, { text, sample: "", seed: 0, brief: null, subjects: [], trace: [], busy: "brief", picking: null });
    P.slug = opts.slug || P.slug;
    ctx.saveBrief(text);
    trace("you", text);
    status("Reading the brief…");
    ctx.render();
    try {
      const t0 = performance.now();
      const b = await api("/pitch/brief", { text });
      if (gen !== P.gen) return;
      Object.assign(P, { brief: b.brief, subjects: b.subjects, sample: b.sample || "", briefText: text });
      trace("gemini", `Read the brief: ${b.brief.news || "a launch"}${b.brief.when ? `, ${b.brief.when}` : ""}. Kind: ${b.brief.kind}.`, since(t0));
      for (const s of b.subjects) {
        if (s.match) trace("qloo", `Found ${s.match.name}, ${s.type.replace("_", " ")}${s.role === "comp" ? ", a comp for the audience" : s.role === "parent" ? ", the name behind the launch" : ""}.`);
        else trace("room", `${s.name} is new to Qloo.`);
      }
      if (b.brief.note) trace("room", b.brief.note);
      // The brief's own cities and age apply to a new brief only; Again keeps the room the person set.
      if (newBrief && b.brief.cities?.length) ctx.setCities(b.brief.cities);
      if (newBrief && b.brief.age && !b.brief.alcohol) ctx.setAge(b.brief.age);
      if (!opts.slug) P.slug = `INT. ${(b.brief.news || "a launch").toUpperCase()}`;
      if (!resolved().length) {
        P.busy = "";
        P.error = `${b.subjects[0]?.name || "Every name"} is new to Qloo. Name what its people already love: "for fans of …".`;
        status(P.error);
        ctx.render();
        return;
      }
      ctx.render();
      await research(gen);
      if (gen !== P.gen) return;
      await write(gen);
    } catch (err) {
      if (gen !== P.gen) return;
      P.busy = "";
      P.error = err.message;
      status(err.message);
      ctx.render();
    }
  }

  async function research(gen, { lanes = true } = {}) {
    const p = params();
    P.age = p.age;
    const missing = LANES.map((l) => l[0]).filter((k) => lanes || !P.lanes[k] || P.lanes[k].fold === "error");
    if (missing.length) {
      P.busy = "lanes";
      status(`Reading who loves ${subjectName()}…`);
      ctx.render();
      await pool(missing, 3, async (lane) => {
        if (gen !== P.gen) return;
        const t0 = performance.now();
        try {
          const l = await api("/pitch/lane", { ...p, lane });
          if (gen !== P.gen) return;
          P.lanes[lane] = l;
          const top = l.rows.find((r) => r.lift != null);
          trace("qloo", `${LABEL[lane]}: ${plural(l.rows.length, "name")}, against ${l.control.name}'s fans.`, since(t0));
          if (l.fold) trace("room", `${LABEL[lane]} folds: Qloo's signal runs thin here.`);
          else if (top) trace("room", `${top.name} leads at ${fmt(top.lift)}.`);
        } catch (err) {
          if (gen !== P.gen) return;
          P.lanes[lane] = { lane, label: LABEL[lane], rows: [], fold: "error", error: err.message };
          trace("room", `${LABEL[lane]} failed to load: ${err.message}`);
        }
        ctx.render();
      });
    }
    if (gen !== P.gen) return;
    P.busy = "where";
    status(`Mapping the fans across ${listing(p.cities)}…`);
    ctx.render();
    const t0 = performance.now();
    const [w, th] = await Promise.all([api("/pitch/where", p), lanes || !P.threads.length ? api("/pitch/threads", p) : null]);
    if (gen !== P.gen) return;
    P.where = w;
    if (th) { P.threads = th.threads; P.marks = th.marks || {}; }
    trace("room", `Mapped ${listing(w.mapped)} over ${cities(w.order.length)}: Known from Gemini with a Qloo floor, Loved from Qloo's heatmap.`, since(t0));
    const by = (r) => w.order.filter((c) => w.cities[c].role === r);
    const o = by("Open"), b = by("Build"), i = by("Inside"), wt = by("Wait");
    trace("room", [o.length && `${listing(o)} ${verb(o, "opens", "open")}.`, b.length && `${listing(b)} ${verb(b, "builds", "build")}.`,
      i.length && `${listing(i)} ${verb(i, "starts", "start")} small.`, wt.length && `${listing(wt)} ${verb(wt, "waits", "wait")}.`].filter(Boolean).join(" "));
    if (th && P.threads.length) trace("room", `Threads: ${listing(P.threads.slice(0, 5).map((t) => t.word))}.`);
    P.busy = "venues";
    status("Finding the rooms these fans gather in…");
    ctx.render();
    await pool(w.order, 3, async (city) => {
      if (gen !== P.gen) return;
      const t1 = performance.now();
      try {
        const v = await api("/pitch/venues", { ...p, city });
        if (gen !== P.gen) return;
        P.venues[city] = v;
        const first = v.rows[0];
        trace("qloo", first ? `${city} ${first.label} for these fans: ${listing(first.venues.map((x) => x.name))}.` : `${city}: few rooms on record.`, since(t1));
      } catch (err) {
        if (gen === P.gen) trace("room", `${city}: ${err.message}`);
      }
      ctx.render();
    });
  }

  async function write(gen, extra = {}) {
    const p = params();
    const keepN = P.kept.length;
    Object.assign(P, { busy: "write", rollout: null, rolloutFor: null, error: "", note: "", stale: "" });
    if (keepN >= 3) { P.busy = ""; status("All three are kept. Unkeep or kill one to make room."); ctx.render(); return; }
    status(`Writing ideas from what fans of ${subjectName()} love…`);
    ctx.render();
    const t0 = performance.now();
    const w = await api("/pitch/write", {
      ...p, kept: P.kept.map((i) => `${i.title}: ${i.line}`).slice(0, 3), killed: P.killed.map((k) => `${k.title}: ${k.reason}`).slice(-6),
      answer: extra.answer || "", tone: extra.tone || P.tone || "", pins: P.pins.slice(0, 4), sample: P.sample, seed: P.seed,
    });
    if (gen !== P.gen) return;
    const names = Object.values(P.lanes).reduce((n, l) => n + (l.fold ? 0 : Math.min(8, l.rows.length)), 0);
    const rooms = Object.values(P.venues).reduce((n, v) => n + v.rows.reduce((m, r) => m + r.venues.length, 0), 0);
    if (w.note) { P.note = w.note; trace("room", w.note); }
    else trace("gemini", `Wrote ${plural(w.ideas.length, "idea")} from ${names} names and ${rooms} rooms.`, since(t0));
    if (w.struck.length) trace("room", `Struck ${plural(w.struck.length, "draft line")}: names outside the pack, numbers, rankings, claimed deals or empty slots.`);
    P.launch = w.launch;
    const newOnes = w.ideas.slice(0, 3 - keepN).map((i) => ({ ...i, id: `${P.seed}-${i.id}`, unread: true }));
    P.ideas = [...P.kept, ...newOnes];
    if (newOnes.length) await readBack(gen, newOnes);
    if (gen !== P.gen) return;
    await strips(gen);
    if (gen !== P.gen) return;
    P.busy = "";
    status(P.ideas.length ? `${COUNT[P.ideas.length] || plural(P.ideas.length, "idea")} for ${P.launch || subjectName()}. Keep, kill, roll one out, or ask what if.`
      : P.note || "Every draft broke a rule: a name outside the pack, a number or a claimed deal. Press Again to write new ones.");
    ctx.render();
  }

  async function readBack(gen, ideas) {
    P.busy = "readback";
    status("Reading the ideas back…");
    ctx.render();
    const t1 = performance.now();
    try {
      const rb = await api("/pitch/readback", { ...params(), ideas, sample: P.sample, seed: P.seed, pins: P.pins.slice(0, 4) });
      if (gen !== P.gen) return;
      const byId = Object.fromEntries(rb.ideas.map((i) => [i.id, i]));
      const ids = new Set(ideas.map((i) => i.id));
      P.ideas = P.ideas.map((i) => ids.has(i.id) ? (byId[i.id] ? { ...i, ...byId[i.id], unread: rb.tally.stalled } : null) : i).filter(Boolean);
      if (rb.tally.stalled) trace("room", "The read-back stalled. These ideas carry the first check only.", since(t1));
      else trace("room", `Read the ideas back: ${plural(rb.tally.read, "name")}, ${rb.tally.in_pack} from Qloo's lists${rb.tally.struck ? `, ${plural(rb.tally.struck, "line")} struck` : ""}.`, since(t1));
    } catch (err) {
      if (gen === P.gen) trace("room", `The read-back stalled: ${err.message}. These ideas carry the first check only.`);
    }
  }

  // City strips: the anchor of each idea, scored in the room. An entry counts only when it covers every current city.
  async function strips(gen) {
    const need = P.ideas.filter((i) => { const a = anchorOf(i); const s = a && P.strips[a.id]; return a && (!s?.cities || ctx.cities().some((c) => !s.cities[c])); });
    if (!need.length) return;
    P.busy = "strips";
    status("Checking each idea in the room…");
    ctx.render();
    const p = params();
    await pool(need, 3, async (idea) => {
      const a = anchorOf(idea);
      if (!a || gen !== P.gen) return;
      const t2 = performance.now();
      try {
        const s = await api("/pitch/strip", { ...p, id: a.id, pins: P.pins.slice(0, 4) });
        if (gen !== P.gen) return;
        P.strips[a.id] = s;
        trace("room", `Scored ${a.name} in ${cities(Object.keys(s.cities).length)}.`, since(t2));
      } catch { /* the card shows its strip as pending */ }
      ctx.render();
    });
  }

  const anchorOf = (idea) => idea.slots.partner || idea.slots.media || idea.slots.sound || idea.slots.look;

  async function again(text = "") {
    if (!P.brief || !resolved().length || working()) return;
    const gen = ++P.gen;
    P.seed += 1;
    P.traceOpen = null;
    try {
      if (!text) { trace("you", "Again."); await write(gen); return; }
      trace("you", `What if ${text.replace(/^what if\s*/i, "")}`);
      P.busy = "whatif";
      status("Asking Qloo…");
      ctx.render();
      const t0 = performance.now();
      const x = await api("/pitch/whatif", { ...params(), text });
      if (gen !== P.gen) return;
      P.answer = x;
      if (x.ink) trace(x.who || "qloo", x.ink, since(t0));
      if (x.pencil) trace(x.who || "gemini", x.pencil, since(t0));
      const u = x.update || {};
      if (u.categories && P.brief) P.brief.categories = u.categories;
      if (u.add_city && !ctx.cities().includes(u.add_city)) ctx.setCities([...ctx.cities(), u.add_city].slice(-4), { quiet: true });
      if (u.age) ctx.setAge(u.age, { quiet: true });
      if (x.pins?.length) {
        if (x.record) P.pinNames[x.record.id] = x.record.name;
        for (const pin of x.pins) P.pinNames[pin.id] ??= nameOf(pin.id) || x.term;
        P.pins = [...x.pins, ...P.pins.filter((p) => !x.pins.some((q) => q.id === p.id))].slice(0, 4);
      }
      if (x.kind === "tone") P.tone = text.slice(0, 160);
      if (u.age) await research(gen);
      else if (u.add_city || u.categories) await research(gen, { lanes: false });
      if (gen !== P.gen) return;
      await write(gen, { answer: x.ink || x.pencil || text, tone: x.kind === "tone" ? text : "" });
    } catch (err) {
      if (gen !== P.gen) return;
      P.busy = "";
      status(err.message);
      ctx.render();
    }
  }

  async function rereadIdea(id) {
    const idea = P.ideas.find((i) => i.id === id);
    if (!idea || working()) return;
    const gen = P.gen;
    await readBack(gen, [idea]);
    if (gen !== P.gen) return;
    P.busy = "";
    status(P.ideas.find((i) => i.id === id && !i.unread) ? "Read back." : "The read-back stalled again. The idea carries the first check only.");
    ctx.render();
  }

  async function rollOut(id) {
    const idea = P.ideas.find((i) => i.id === id);
    if (!idea || working()) return;
    const gen = P.gen;
    Object.assign(P, { busy: "rollout", rolloutFor: id, rollout: null, rolling: id });
    status(`Rolling out ${plainText(idea.title, idea)} city by city…`);
    ctx.render();
    requestAnimationFrame(() => document.getElementById("rollout")?.scrollIntoView({ behavior: "smooth", block: "nearest" }));
    try {
      const t0 = performance.now();
      const r = await api("/pitch/rollout", { ...params(), idea, sample: P.sample, pins: P.pins.slice(0, 4) });
      if (gen !== P.gen) return;
      P.rollout = r;
      trace("gemini", `Rolled out ${plainText(idea.title, idea)}: ${plural(r.beats.length, "beat")} across ${listing(r.cities)}.`, since(t0));
      status("The rollout sits under the ideas. Take it on tour, or print the pitch.");
    } catch (err) {
      if (gen === P.gen) { status(err.message); P.rolloutFor = null; }
    }
    if (gen === P.gen) { P.busy = ""; P.rolling = null; }
    ctx.render();
    requestAnimationFrame(() => document.getElementById("rollout")?.focus({ preventScroll: false }));
  }

  // Draw it: a key visual for the idea, described only in Room's words, then read back by the picture check.
  async function drawIt(id) {
    const idea = P.ideas.find((i) => i.id === id);
    if (!idea || working()) return;
    const gen = P.gen;
    Object.assign(P, { busy: "draw", drawing: id });
    status(`Drawing ${plainText(idea.title, idea)}…`);
    ctx.render();
    try {
      const t0 = performance.now();
      const take = P.visuals[id] ? (P.visuals[id].take || 0) + 1 : 0;
      const r = await api("/pitch/draw", { ...params(), idea, sample: P.sample, pins: P.pins.slice(0, 4), take });
      if (gen !== P.gen) return;
      const blob = await (await fetch(`data:${r.mime};base64,${r.image}`)).blob();
      if (P.visuals[id]) URL.revokeObjectURL(P.visuals[id].url);
      P.visuals[id] = { url: URL.createObjectURL(blob), blob, prompt: r.prompt, read: r.read, flag: r.flag || [], take };
      trace("gemini", `Drew ${plainText(idea.title, idea)} from Room's description: rooms and roles, no names.`, since(t0));
      if (r.read) {
        trace("room", `The picture check reads: ${r.read.join("; ") || "a quiet frame"}.`);
        if (r.flag?.length) trace("room", `It found a mark in the frame: ${r.flag[0]}. Draw again before using it.`);
        status(r.flag?.length ? "Room found a mark in the frame. Draw again before you use it." : brandName() ? `Drawn and read back. Check it in Picture to score it for ${brandName()} city by city.` : "Drawn and read back.");
        P.busy = "";
        P.drawing = null;
        ctx.render();
        return;
      }
      status("Reading the key visual back…");
      ctx.render();
      const f = new FormData();
      f.append("file", blob, "key-visual.jpg");
      f.append("keep", "false");
      const t1 = performance.now();
      const res = await fetch("/api/scene/read", { method: "POST", body: f });
      const data = await res.json().catch(() => ({}));
      if (gen !== P.gen || !P.visuals[id]) return;
      if (res.ok) {
        const els = data.scene?.elements || [];
        const seen = els.map((e) => e.what).filter(Boolean).slice(0, 5);
        // A drawing must carry no marks: anything the reader names as a brand or a logo flags the frame.
        const marked = els.filter((e) => e.kind === "brand" || e.name || /\b(logos?|branded|brand name|swoosh|emblem|lettering|handwritten|printed text|readable text)\b|['"“‘][^'"”’]{2,}['"”’]/i.test(`${e.what} ${e.cue || ""}`));
        P.visuals[id].read = seen;
        P.visuals[id].flag = marked.map((e) => e.what).slice(0, 2);
        trace("room", `The picture check reads: ${seen.join("; ") || "a quiet frame"}.`, since(t1));
        if (marked.length) trace("room", `It found a mark in the frame: ${marked[0].what}. Draw again before using it.`);
      }
      status(brandName() ? `Drawn. Check it in Picture to score it for ${brandName()} city by city.` : "Drawn and read back.");
    } catch (err) {
      if (gen === P.gen) status(err.message);
    }
    if (gen === P.gen) { P.busy = ""; P.drawing = null; }
    ctx.render();
  }

  const brandName = () => resolved().find((s) => s.type === "brand" && s.role !== "comp")?.match.name || "";

  // The room changed (cities or age). A first run carries on into the room as it stands; ideas wait for Again.
  async function roomChanged({ age = false } = {}) {
    if (!P.brief || !resolved().length) return;
    const firstRun = !!P.busy && !P.ideas.length;
    const gen = ++P.gen;
    try {
      await research(gen, { lanes: age });
      if (gen !== P.gen) return;
      if (firstRun) { await write(gen); return; }
      if (P.ideas.length) {
        P.stale = "The room changed. Again writes for it.";
        P.rollout = null;
        P.rolloutFor = null;
        await strips(gen);
        if (gen !== P.gen) return;
      }
      P.busy = "";
      status(P.stale || "The room changed.");
    } catch (err) {
      if (gen === P.gen) { P.busy = ""; status(err.message); }
    }
    ctx.render();
  }

  // Entering the tab with a different age band than the lanes were read for: re-rank.
  function entered() {
    ctx.status(P.statusLine);
    if (P.brief && resolved().length && !P.busy && (ctx.age() || null) !== P.age && P.where) roomChanged({ age: true });
  }

  // A wrong match on the brief's subject: pick another of Qloo's candidates and read again from there.
  async function pickSubject(i, id) {
    const s = P.subjects[i];
    const c = s?.candidates?.find((x) => x.entity_id === id);
    if (!c) return;
    const gen = ++P.gen;
    const keepBrief = { brief: P.brief, subjects: P.subjects, briefText: P.briefText, text: P.text, sample: "" };
    clearResults();
    Object.assign(P, keepBrief, { picking: null, seed: 0 });
    s.match = c;
    s.certain = true;
    if (c.type && c.type !== s.type && LABEL[c.type] !== undefined) s.type = c.type;
    trace("you", `Read ${c.name} for ${s.name}.`);
    try {
      await research(gen);
      if (gen !== P.gen) return;
      await write(gen);
    } catch (err) {
      if (gen !== P.gen) return;
      P.busy = "";
      status(err.message);
      ctx.render();
    }
  }

  // ---------- receipts ----------

  function nameOf(id) {
    for (const l of Object.values(P.lanes)) { const r = l.rows?.find((x) => x.id === id); if (r) return r.name; }
    return "";
  }

  function item(id) {
    for (const l of Object.values(P.lanes)) {
      const r = l.rows?.find((x) => x.id === id);
      if (r) return { ...r, laneLabel: l.label, ctrl: l.control, requests: l.requests, fold: l.fold };
    }
    for (const i of P.ideas) for (const s of Object.values(i.slots)) {
      if (s.id === id) return { ...s, laneLabel: s.lane === "venue" ? s.label : LABEL[s.lane], request: s.request, requests: s.requests };
    }
    for (const v of Object.values(P.venues)) for (const row of v.rows) {
      const x = row.venues.find((y) => y.id === id);
      if (x) return { ...x, lane: "venue", city: v.city, laneLabel: row.label, one: row.one, request: row.request };
    }
    return null;
  }

  async function checkItem(id) {
    if (P.strips[id]) return;
    const gen = P.gen;
    try {
      P.strips[id] = { pending: true };
      ctx.render();
      const t0 = performance.now();
      const s = await api("/pitch/strip", { ...params(), id, pins: P.pins.slice(0, 4) });
      if (gen !== P.gen) { if (P.strips[id]?.pending) delete P.strips[id]; return; }
      P.strips[id] = s;
      trace("room", `Scored ${s.name} in ${cities(Object.keys(s.cities).length)}.`, since(t0));
    } catch (err) {
      if (gen === P.gen) { delete P.strips[id]; status(err.message); }
    }
    ctx.render();
  }

  // ---------- drawing: the paper ----------

  const ink = (s) => s ? `<button type="button" class="ink${s.mark?.who === "yours" ? " yours" : ""}" data-item="${esc(s.id)}">${esc(s.name)}</button>` : "";

  // Pencil is Gemini; every name inside it is a Qloo record, in ink. Case changes touch only Gemini's words.
  function prose(text, idea) {
    const label = P.launch || subjectName();
    const t = (text || "").replace(/(^|[.!?]\s+)([a-z])/g, (m, a, b) => a + b.toUpperCase());
    return esc(t).replace(/(^|[.!?]\s+)?\{(\w+)\}/g, (m, lead, k, at) => {
      const pre = lead || "";
      if (k === "subject") {
        const shown = lead !== undefined || at === 0 ? cap(label) : label;
        return pre + (launchIsName() ? `<b class="ink subj">${esc(shown)}</b>` : esc(shown));
      }
      if (k === "city") return pre + esc(idea.lead_city || "");
      return pre + (idea.slots[k] ? ink(idea.slots[k]) : "");
    });
  }

  function plainText(text, idea) {
    const label = P.launch || subjectName();
    return (text || "").replace(/(^|[.!?]\s+)([a-z])/g, (m, a, b) => a + b.toUpperCase())
      .replace(/(^|[.!?]\s+)\{subject\}/g, (m, a) => a + cap(label))
      .replace(/\{(\w+)\}/g, (m, k) => k === "subject" ? label : k === "city" ? (idea.lead_city || "") : idea.slots[k]?.name || "");
  }

  function slotRow(k, s, ctrl) {
    if (!s) return "";
    const why = s.lane === "venue"
      ? `${esc(s.city || "")} · ${esc(s.one || (s.label || "").replace(/s$/, ""))}`
      : s.lift != null ? `${fmt(s.lift)} against ${esc(ctrl?.name || "the control")}'s fans` : "";
    const mark = s.mark?.who === "yours" ? `<span class="mk yours" title="Qloo lists it among ${esc(subjectName())}'s partnerships">Yours</span>` : "";
    return `<dt>${SLOT[k]}</dt><dd>${ink(s)}${mark}<span class="swhy2">${why}</span></dd>`;
  }

  function stripHtml(idea) {
    const a = anchorOf(idea);
    if (!a) return "";
    const s = P.strips[a.id];
    const cells = ctx.cities().map((c) => {
      const v = s?.cities?.[c];
      if (!v) return `<span class="sd wait"><i></i>${esc(c)}<span class="sr">: scoring</span></span>`;
      const word = VERD[v.verdict] || v.verdict;
      return `<span class="sd v-${v.verdict}" title="${esc(c)}: ${esc(word)}${v.loved != null ? `, loved ${v.loved.toFixed(2)}` : ""}"><i></i>${esc(c)} <em>${esc(word)}</em></span>`;
    }).join("");
    return `<div class="cstrip" role="group" aria-label="${esc(a.name)} in each city"><span class="sl">${esc(a.name)} in the room</span>${cells}</div>`;
  }

  function ideaHtml(idea, n) {
    const ctrl = control();
    const kept = P.kept.some((k) => k.id === idea.id);
    const killing = P.killing === idea.id;
    const busy = working();
    const id = esc(idea.id);
    return `<article class="idea${kept ? " is-kept" : ""}${idea.unread ? " unread" : ""}" data-idea="${id}">
      <p class="idea-k">Idea ${n}${idea.threads?.length ? ` · ${esc(idea.threads.join(", "))}` : ""}${kept ? ` · <span class="kepttag">Kept</span>` : ""}${idea.unread ? ` · <span class="unreadtag">Unread</span>` : ""}</p>
      ${visualHtml(idea)}
      <h3 class="idea-t">${prose(idea.title, idea)}</h3>
      <p class="idea-line">${prose(idea.line, idea)}</p>
      ${idea.insight ? `<p class="idea-ins"><span>The truth</span>${prose(idea.insight, idea)}</p>` : ""}
      <p class="idea-body">${prose(idea.idea, idea)}</p>
      <dl class="slots">${Object.keys(SLOT).map((k) => slotRow(k, idea.slots[k], ctrl)).join("")}</dl>
      ${stripHtml(idea)}
      ${idea.unread ? `<p class="unreadnote">Room's script reader has yet to read this one back. <button type="button" class="linkbtn" id="reread-${id}" data-act="reread" ${busy ? "disabled" : ""}>Read back again</button></p>` : ""}
      ${killing ? `<div class="killwhy" role="group" aria-label="Why kill it"><span>Why?</span>${KILL.map((r, k) => `<button type="button" id="why-${k}-${id}" data-act="kill-why" data-arg="${esc(r)}">${r}</button>`).join("")}<button type="button" class="x" id="cancel-${id}" data-act="kill-cancel" aria-label="Keep it on the wall">×</button></div>`
        : `<div class="idea-actions">
        <button type="button" class="ghost dark" id="keep-${id}" data-act="${kept ? "unkeep" : "keep"}" aria-pressed="${kept}">${kept ? "Kept" : "Keep"}</button>
        <button type="button" class="ghost dark" id="kill-${id}" data-act="kill">Kill</button>
        <button type="button" class="ghost dark" id="roll-${id}" data-act="roll" ${busy ? "disabled" : ""}>${P.rolling === idea.id ? "Rolling out…" : "Roll it out"}</button>
        <button type="button" class="ghost dark" id="draw-${id}" data-act="draw" ${busy ? "disabled" : ""}>${P.drawing === idea.id ? "Drawing…" : P.visuals[idea.id] ? "Draw again" : "Draw it"}</button>
        <button type="button" class="ghost dark" id="use-${id}" data-act="use" ${busy ? "disabled" : ""} title="Send the idea to the paper and check every reference city by city">Check the copy</button>
      </div>`}
    </article>`;
  }

  function visualHtml(idea) {
    const v = P.visuals[idea.id];
    if (!v) return P.drawing === idea.id ? `<div class="kv wait"><p class="pwork"><span class="dot"></span>Drawing the key visual…</p></div>` : "";
    const id = esc(idea.id);
    return `<figure class="kv"><img src="${v.url}" alt="Key visual for ${esc(plainText(idea.title, idea))}">
      <figcaption>${v.read ? `<span class="who">Room reads</span> ${esc(v.read.join("; ") || "a quiet frame")}` : `<span class="pwork"><span class="dot"></span>Reading it back…</span>`}
        ${v.flag?.length ? `<span class="kvflag">Room found a mark in the frame: ${esc(v.flag.join("; "))}. Draw again before you use it.</span>` : ""}
        <span class="kvacts">${brandName() ? `<button type="button" class="linkbtn" id="pic-${id}" data-act="topicture">Check it in Picture</button>` : ""}
        <button type="button" class="linkbtn" id="dl-${id}" data-act="kvdownload">Download</button>
        <details class="kvwhy"><summary>What Room asked for</summary><p>${esc(v.prompt)}</p></details></span></figcaption></figure>`;
  }

  function rolloutHtml() {
    const idea = P.ideas.find((i) => i.id === P.rolloutFor);
    if (!idea) return "";
    const title = plainText(idea.title, idea).toUpperCase();
    const head = `<p class="slugline">ROLLOUT. ${esc((P.launch || subjectName()).toUpperCase())}. ${esc(title)}.</p>`;
    const r = P.rollout;
    if (!r) return P.busy === "rollout" ? `<section class="rollout" id="rollout" tabindex="-1" aria-label="Rollout">${head}<p class="pwork"><span class="dot"></span>Rolling it out city by city…</p></section>` : "";
    const phases = ["Tease", "Drop", "Live"];
    const cell = (b) => {
      if (!b) return `<td class="empty-beat"></td>`;
      const fake = { slots: b.slots, lead_city: b.city };
      const move = b.move ? prose(b.move, fake) : `${b.phase} at ${ink(b.slots.venue)}.`;
      return `<td><p>${move}</p><span class="bv">${ink(b.slots.venue)}</span></td>`;
    };
    const rows = r.cities.map((c) => `<tr><th scope="row"><b>${esc(c)}</b><span class="role ${ROLE[r.roles[c]] || ""}">${esc(r.roles[c] || "")}</span></th>${phases.map((ph) => cell(r.beats.find((b) => b.city === c && b.phase === ph))).join("")}</tr>`).join("");
    return `<section class="rollout" id="rollout" tabindex="-1" aria-label="Rollout">${head}
      <div class="rollwrap"><table class="rolltable"><thead><tr><th></th>${phases.map((ph) => `<th scope="col">${ph}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>
      ${r.stalled ? `<p class="unreadnote">The read-back stalled on these moves. They carry the first check only.</p>` : ""}
      <div class="rollactions"><button type="button" class="ghost dark" id="tourBtn" data-act="tour">Take it on tour</button><button type="button" class="ghost dark" id="printRoll" data-act="print">Print the pitch</button></div>
    </section>`;
  }

  function chipsHtml() {
    if (!P.brief) return "";
    const b = P.brief;
    const subs = P.subjects.map((s, i) => {
      const label = s.match ? `${s.match.image ? `<img src="${esc(s.match.image)}" alt="" loading="lazy">` : ""}<b>${esc(s.match.name)}</b><small>${s.role === "comp" ? "comp" : esc(s.type.replace("_", " "))}${s.certain ? "" : " · check"}</small>`
        : `<b>${esc(s.name)}</b><small>new to Qloo</small>`;
      const has = (s.candidates || []).length > (s.match ? 1 : 0);
      return has ? `<button type="button" class="bc subj${s.match ? "" : " miss"}${s.certain ? "" : " unsure"}" id="subj-${i}" data-act="pick" data-arg="${i}" aria-expanded="${P.picking === i}" title="Qloo's match for ${esc(s.name)}. Pick another">${label}</button>`
        : `<span class="bc subj${s.match ? "" : " miss"}">${label}</span>`;
    }).join("");
    const pk = P.picking != null && P.subjects[P.picking];
    const picker = pk ? `<div class="picker" role="group" aria-label="Qloo's matches for ${esc(pk.name)}"><span>Qloo's matches for ${esc(pk.name)}:</span>${(pk.candidates || []).map((c) =>
      `<button type="button" data-act="pick-one" data-arg="${esc(c.entity_id)}" class="${pk.match?.entity_id === c.entity_id ? "on" : ""}">${esc(c.name)} <small>${esc((c.type || "").replace("_", " "))}</small></button>`).join("")}</div>` : "";
    return `<div class="bchips">${subs}<span class="bc">${esc(b.news || "a launch")}</span>${b.when ? `<span class="bc">${esc(b.when)}</span>` : ""}<span class="bc kind">${esc(b.kind)}</span>${b.alcohol ? `<span class="bc">25 and over</span>` : ""}</div>${picker}`;
  }

  function steersHtml() {
    const chips = [
      ...P.pins.map((p) => ({ k: "pin", id: p.id, label: `With ${P.pinNames[p.id] || nameOf(p.id) || "a pinned name"}` })),
      ...(P.tone ? [{ k: "tone", id: "tone", label: `Tone: ${P.tone}` }] : []),
      ...P.killed.map((x, i) => ({ k: "killed", id: String(i), label: `Away from ${x.reason.toLowerCase()}: ${x.title}` })),
    ];
    if (!chips.length) return "";
    return `<div class="steers" role="group" aria-label="What the next round steers by"><span>Steering by</span>${chips.map((c) =>
      `<span class="steer">${esc(c.label)}<button type="button" class="x" data-act="unsteer" data-arg="${c.k}:${esc(c.id)}" aria-label="Drop ${esc(c.label)}">×</button></span>`).join("")}</div>`;
  }

  function answerHtml() {
    const x = P.answer;
    if (!x || (!x.ink && !x.pencil)) return "";
    return `<p class="answer"><span class="who who-${esc(x.who || "qloo")}">${WHO[x.who] || "Qloo"}</span>${x.ink ? `<b>${esc(x.ink)}</b>` : ""}${x.pencil ? ` <span class="pencilline">${esc(x.pencil)}</span>` : ""}</p>`;
  }

  function renderPaper() {
    const el = $("pitch");
    // The brief box and the what-if line are built once and never re-rendered, so drafts and the caret survive.
    if (!$("briefInput")) {
      el.innerHTML = `<label class="brief-l" for="briefInput">What are you launching?</label>
        <textarea id="briefInput" class="brief-in" rows="2" maxlength="2000" spellcheck="false"
          placeholder="A debut album for fans of SZA and Daniel Caesar. London, Atlanta, Lagos."></textarea>
        <div id="pitchBody"></div>
        <form class="whatif" id="whatifForm" autocomplete="off" hidden>
          <input id="whatifInput" maxlength="200" placeholder="What if… with Frank Ocean, in record stores, darker, add Toronto, for over 35s" aria-label="What if">
          <button type="submit" class="primary" id="againBtn">Again</button>
        </form>
        <div id="pitchTail"></div>`;
      $("briefInput").dataset.shown = "";
    }
    const box = $("briefInput");
    if (box.dataset.shown !== P.text) { box.value = P.text; box.dataset.shown = P.text; }
    const busy = working();
    const wait = { brief: "Reading the brief", lanes: "Reading who loves it", where: "Mapping the fans", venues: "Finding their rooms",
      write: "Writing the ideas", readback: "Reading the ideas back", whatif: "Asking Qloo", draw: "Drawing the key visual" }[P.busy];
    const n = P.ideas.length;
    $("pitchBody").innerHTML = `
      ${chipsHtml()}
      ${P.error && !P.busy ? `<p class="perr">${esc(P.error)}</p>` : ""}
      ${P.stale ? `<p class="perr soft">${esc(P.stale)}</p>` : ""}
      ${n ? `<p class="ideas-k">${COUNT[n] || plural(n, "idea")}<span>Underlined names come from Qloo and open their receipts. The words around them are Gemini's.</span></p>
        <div class="ideas">${P.ideas.map((i, k) => ideaHtml(i, k + 1)).join("")}</div>`
        : P.brief && resolved().length && !busy && P.briefText ? `<p class="perr soft">${esc(P.note || (P.killed.length ? "Every idea is killed. Again writes new ones away from them." : "The wall is empty. Press Again."))}</p>` : ""}`;
    const form = $("whatifForm");
    form.hidden = !(P.brief && resolved().length && !P.error);
    const allKept = P.kept.length >= 3;
    $("whatifInput").disabled = busy || allKept;
    $("againBtn").disabled = busy || allKept;
    $("againBtn").textContent = allKept ? "All three kept" : "Again";
    $("pitchTail").innerHTML = `${answerHtml()}${steersHtml()}
      ${busy && wait ? `<p class="pwork"><span class="dot"></span>${wait}…</p>` : ""}
      ${rolloutHtml()}`;
  }

  // ---------- drawing: the panel ----------

  function laneHtml(lane, label) {
    const l = P.lanes[lane];
    if (!l) return P.busy === "brief" || P.busy === "lanes" ? `<div class="lrow wait"><span class="lab">${label}</span><span class="lchips"><span class="lc ghost-chip"></span><span class="lc ghost-chip"></span><span class="lc ghost-chip"></span></span></div>` : "";
    if (l.fold) return "";
    const rows = [...l.rows].filter((r) => P.raw || r.lift != null).sort((a, b) => P.raw ? a.raw_rank - b.raw_rank : (b.lift ?? -9) - (a.lift ?? -9)).slice(0, 5);
    return `<div class="lrow"><span class="lab">${label}</span><span class="lchips">${rows.map((r) => {
      const m = P.marks[r.id];
      const t = m?.who === "rival" ? `Qloo's brand records list it under ${m.brand}` : m?.who === "yours" ? `Qloo lists it among ${subjectName()}'s partnerships` : "";
      return `<button type="button" class="lc${P.receipt === r.id ? " on" : ""}${m ? ` mk-${m.who}` : ""}" data-item="${esc(r.id)}"${t ? ` title="${esc(t)}"` : ""} aria-label="${esc(r.name)}${t ? `. ${esc(t)}` : ""}">${esc(r.name)}<i>${P.raw ? `#${r.raw_rank}` : fmt(r.lift)}</i></button>`;
    }).join("")}</span></div>`;
  }

  function whereHtml() {
    const w = P.where;
    if (!w) return P.busy === "where" || P.busy === "lanes" ? `<p class="working"><span class="dot"></span>Mapping the fans city by city…</p>` : "";
    return w.order.map((c) => {
      const x = w.cities[c];
      const v = P.venues[c];
      return `<div class="wrow"><div class="wtop"><b>${esc(c)}</b><span class="role ${ROLE[x.role] || ""}">${esc(x.role)}</span>
        <span class="kl"><span class="pencil">Known ${x.known.toFixed(2)}</span> · <span>Loved ${x.loved == null ? "n/a" : x.loved.toFixed(2)}</span>${x.confidence === "low" ? " · low confidence" : ""}</span></div>
        <p class="wline">${esc(x.line)}</p>
        ${v ? v.rows.map((r) => `<p class="rooms"><span>${esc(cap(r.label))}</span>${r.venues.map((y) => `<button type="button" class="vn${P.receipt === y.id ? " on" : ""}" data-item="${esc(y.id)}">${esc(y.name)}</button>`).join("")}</p>`).join("")
          : P.busy === "venues" ? `<p class="rooms wait"><span>Rooms</span>·  ·  ·</p>` : ""}</div>`;
    }).join("");
  }

  function traceHtml() {
    if (!P.trace.length) return "";
    const open = P.traceOpen ?? !!P.busy;
    return `<details class="work" id="pitchTrace" ${open ? "open" : ""}><summary data-act="p-trace">How Room pitched it</summary>
      <ol class="trace">${P.trace.map((e) => `<li class="t-${e.who}"><span class="who">${WHO[e.who] || e.who}</span><span class="what">${esc(e.text)}</span>${e.ms >= 100 ? `<span class="ms">${(e.ms / 1000).toFixed(1)} s</span>` : "<span></span>"}</li>`).join("")}</ol></details>`;
  }

  function receiptHtml(id) {
    const r = item(id);
    if (!r) return "";
    const s = P.strips[id];
    const ctrl = r.ctrl || control();
    const req = r.requests?.[0] || r.request;
    const reqText = req ? `GET ${req.path}?` + Object.entries(req.params).map(([k, v]) => `${k}=${String(v).replace(/[0-9A-F]{8}-[0-9A-F-]{27}/gi, (x) => x.slice(0, 8) + "…")}`).join("&") : "";
    const m = P.marks[id] || r.mark;
    const own = m ? `<p class="rwhy">${m.who === "yours" ? `Qloo lists it among ${esc(subjectName())}'s partnerships.` : `Qloo's brand records list it under ${esc(m.brand)}, a competitor. Room keeps it out of the ideas.`}</p>` : "";
    const numbers = r.lane === "venue"
      ? `<div class="rc"><span>City</span><b>${esc(r.city || "")}</b></div><div class="rc"><span>Kind of room</span><b>${esc(cap(r.one || r.laneLabel || ""))}</b></div>
         ${r.raw_rank ? `<div class="rc"><span>Qloo's order for these fans</span><b>#${r.raw_rank}</b></div>` : ""}
         ${r.address ? `<p class="rnote">${esc(r.address)}</p>` : ""}`
      : `<div class="rc"><span>Fans of ${esc(subjectName())}</span><b>${typeof r.affinity === "number" ? r.affinity.toFixed(3) : "n/a"}</b></div>
         <div class="rc"><span>${esc(ctrl?.name || "Control")}'s fans</span><b>${typeof r.control === "number" ? r.control.toFixed(3) : "n/a"}</b></div>
         <div class="rc lift"><span>Lift</span><b>${fmt(r.lift)}</b></div>
         <p class="rnote">${r.lift_rank ? `${ordinal(r.lift_rank)} by lift in ${esc(r.laneLabel || "")}` : r.pinned ? "Asked for by name" : ""}${r.raw_rank ? ` · ${ordinal(r.raw_rank)} in Qloo's own order` : ""}${r.popularity != null ? ` · popularity ${r.popularity.toFixed(2)}` : ""}</p>`;
    const strip = s?.cities ? `<div class="rstrip">${Object.entries(s.cities).map(([c, v]) => `<div class="rsc"><b>${esc(c)}</b><span class="cell v-${v.verdict}">${esc(VERD[v.verdict] || v.verdict)}</span><span class="kl"><span class="pencil">Known ${v.known.toFixed(2)}</span> · Loved ${v.loved == null ? "n/a" : v.loved.toFixed(2)}</span></div>`).join("")}</div>`
      : s?.pending ? `<p class="working"><span class="dot"></span>Scoring it in the room…</p>` : "";
    return `<button class="back" data-act="p-back" type="button">← Their people</button>
      <p class="kicker">${esc(r.laneLabel || "")}</p><h2 class="dname" id="pitchReceipt" tabindex="-1">${esc(r.name)}</h2>
      <div class="receipt">${numbers}</div>
      ${r.lane !== "venue" ? `<p class="rwhy">Lift is how much more fans of ${esc(subjectName())} love it than ${esc(ctrl?.name || "the control")}'s fans do. Qloo measures both on the same list.</p>` : ""}
      ${own}
      ${reqText ? `<pre class="req">${esc(reqText)}</pre>` : ""}
      ${strip}
      <div class="callout">${r.lane !== "venue" && !s ? `<button class="primary" type="button" data-act="p-strip" data-arg="${esc(id)}">Check it in the room</button>` : ""}
        ${P.brief && r.lane !== "venue" && m?.who !== "rival" && (r.lift ?? 0) > 0 ? `<button class="ghost" type="button" data-act="p-build" data-arg="${esc(id)}" ${working() ? "disabled" : ""}>Build an idea around it</button>` : ""}</div>`;
  }

  const ordinal = (n) => `${n}${["th", "st", "nd", "rd"][(n % 100 > 10 && n % 100 < 14) || n % 10 > 3 ? 0 : n % 10]}`;

  function panelHtml() {
    if (P.receipt && item(P.receipt)) return receiptHtml(P.receipt);
    if (!P.brief) {
      return `<p class="kicker">Pitch</p><h2 class="dname">Who loves it, and what else they love.</h2>
        <p class="plede">Name what you are launching. Qloo reads its audience across music, shows, film, podcasts, brands, people, games, books and travel, ranked by how much more they love each thing than fans of a household name of the same kind do. Room maps where they are and the rooms they gather in, city by city, and pitches ideas built only from that.</p>
        ${P.busy === "brief" ? `<p class="working"><span class="dot"></span>Gemini is reading the brief…</p>` : `<div class="callout"><p>Pick a sample at the top of the paper, or write one line. "A debut album for fans of SZA and Daniel Caesar" works as well as a brand.</p></div>`}
        ${traceHtml()}`;
    }
    if (!resolved().length) {
      const cands = P.subjects.flatMap((s, i) => (s.candidates || []).slice(0, 4).map((c) => ({ i, c })));
      return `<p class="kicker">Pitch</p><h2 class="dname">New to Qloo.</h2>
        <p class="plede">${esc(P.error || "Every name in this brief is new to Qloo.")}</p>
        ${cands.length ? `<p class="boardnote">Qloo's nearest names:</p><div class="lchips">${cands.map(({ i, c }) => `<button type="button" class="lc" data-act="pick-cand" data-arg="${i}:${esc(c.entity_id)}">${esc(c.name)}<i>${esc((c.type || "").replace("_", " "))}</i></button>`).join("")}</div>` : ""}
        ${traceHtml()}`;
    }
    const ctrl = control();
    const words = P.threads.slice(0, 3).map((t, i) => (i ? t.word : cap(t.word)));
    const head = words.length ? `${listing(words)}.` : `Fans of ${subjectName()}.`;
    const folded = LANES.filter(([k]) => ["thin", "noise"].includes(P.lanes[k]?.fold)).map(([, l]) => l);
    const failed = LANES.filter(([k]) => P.lanes[k]?.fold === "error").map(([, l]) => l);
    return `<p class="kicker">Their people · ${esc(subjectName())}</p>
      <h2 class="dname">${esc(head)}</h2>
      ${ctrl ? `<p class="plede">What fans of ${esc(subjectName())} love more than ${esc(ctrl.name)}'s fans do, ranked by lift and measured by Qloo.</p>` : ""}
      ${P.threads.length ? `<div class="threads">${P.threads.slice(0, 6).map((t) => `<span class="tw" title="${esc(t.lanes.join(", "))}: ${t.count} names">${esc(t.word)}<i>${t.count}</i></span>`).join("")}</div>` : ""}
      <div class="lanes">${LANES.map(([k, l]) => laneHtml(k, l)).join("")}</div>
      ${folded.length ? `<p class="boardnote">Folded: ${esc(listing(folded))}. Qloo's signal runs thin there for these fans.</p>` : ""}
      ${failed.length ? `<p class="boardnote">${esc(listing(failed))} failed to load. Again retries.</p>` : ""}
      <div class="lens rawlift" role="group" aria-label="Order"><button type="button" data-act="p-order" data-arg="lift" aria-pressed="${!P.raw}">By lift</button><button type="button" data-act="p-order" data-arg="raw" aria-pressed="${P.raw}">Qloo's order</button></div>
      <h3 class="subh">Where they gather</h3>
      ${whereHtml()}
      ${traceHtml()}
      <p class="src">Ink is Qloo · pencil is Gemini · every underlined name opens its receipt</p>`;
  }

  // ---------- events ----------

  function select(id) {
    P.receipt = id;
    ctx.render();
    requestAnimationFrame(() => {
      // The receipt opens at the top of the panel: bring it into view when the page sits below it.
      const pan = $("panel");
      if (pan && (matchMedia("(max-width: 960px)").matches || pan.getBoundingClientRect().top < 0)) {
        pan.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      $("pitchReceipt")?.focus({ preventScroll: true });
    });
  }

  function back() {
    const was = P.receipt;
    P.receipt = null;
    ctx.render();
    if (was) requestAnimationFrame(() => {
      const el = document.querySelector(`#panel [data-item="${CSS.escape(was)}"]`);
      el?.scrollIntoView({ block: "nearest" });
      el?.focus({ preventScroll: true });
    });
  }

  function onPanel(e) {
    const b = e.target.closest("[data-act], [data-item]");
    if (!b) return;
    switch (b.dataset.act) {
      case "p-back": back(); return;
      case "p-order": P.raw = b.dataset.arg === "raw"; ctx.render(); return;
      case "p-strip": checkItem(b.dataset.arg); return;
      case "p-trace": P.traceOpen = !document.getElementById("pitchTrace")?.open; return;
      case "pick-cand": { const [i, id] = b.dataset.arg.split(":"); pickSubject(+i, id); return; }
      case "p-build": {
        const r = item(b.dataset.arg);
        if (r) {
          P.pins = [{ id: r.id, lane: r.lane }, ...P.pins.filter((p) => p.id !== r.id)].slice(0, 4);
          P.pinNames[r.id] = r.name;
          P.receipt = null;
          again(`with ${r.name}`);
        }
        return;
      }
    }
    if (b.dataset.item) select(b.dataset.item);
  }

  function focusSoon(sel) {
    requestAnimationFrame(() => document.querySelector(sel)?.focus({ preventScroll: true }));
  }

  function onPaper(e) {
    if (e.type === "submit") {
      e.preventDefault();
      const t = $("whatifInput")?.value.trim() || "";
      $("whatifInput").value = "";
      again(t);
      return;
    }
    const b = e.target.closest("[data-act], [data-item]");
    if (!b) return;
    if (b.dataset.item && !b.dataset.act) { select(b.dataset.item); return; }
    const card = b.closest("[data-idea]");
    const idea = card && P.ideas.find((i) => i.id === card.dataset.idea);
    const id = idea && CSS.escape(idea.id);
    switch (b.dataset.act) {
      case "pick": P.picking = P.picking === +b.dataset.arg ? null : +b.dataset.arg; ctx.render(); return;
      case "pick-one": if (P.picking != null) pickSubject(P.picking, b.dataset.arg); return;
      case "keep": if (idea && !P.kept.some((k) => k.id === idea.id)) { P.kept = [...P.kept, idea].slice(-3); trace("you", `Kept ${plainText(idea.title, idea)}.`); } ctx.render(); return;
      case "unkeep": if (idea) P.kept = P.kept.filter((k) => k.id !== idea.id); ctx.render(); return;
      case "kill": if (idea) { P.killing = idea.id; ctx.render(); focusSoon(`#why-0-${id}`); } return;
      case "kill-cancel": P.killing = null; ctx.render(); if (idea) focusSoon(`#kill-${id}`); return;
      case "kill-why":
        if (idea) {
          const i = P.ideas.indexOf(idea);
          P.killed = [...P.killed, { title: plainText(idea.title, idea), reason: b.dataset.arg }].slice(-6);
          P.kept = P.kept.filter((k) => k.id !== idea.id);
          P.ideas = P.ideas.filter((x) => x.id !== idea.id);
          if (P.rolloutFor === idea.id) { P.rollout = null; P.rolloutFor = null; }
          P.killing = null;
          trace("you", `Killed ${plainText(idea.title, idea)}: ${b.dataset.arg}.`);
          status(`Killed: ${b.dataset.arg}. Again keeps what you kept and writes the rest new.`);
          ctx.render();
          const next = P.ideas[i] || P.ideas[i - 1];
          focusSoon(next ? `#kill-${CSS.escape(next.id)}` : "#whatifInput");
        }
        return;
      case "reread": if (idea) rereadIdea(idea.id); return;
      case "draw": if (idea) drawIt(idea.id); return;
      case "topicture": if (idea && P.visuals[idea.id]) ctx.toPicture(P.visuals[idea.id].blob, brandName(), ctx.cities()); return;
      case "kvdownload": {
        const v = idea && P.visuals[idea.id];
        if (!v) return;
        const a = document.createElement("a");
        a.href = v.url;
        a.download = `${plainText(idea.title, idea).replace(/[^\w .-]+/g, "").trim() || "key visual"} (Room).jpg`;
        a.click();
        return;
      }
      case "roll": if (idea) rollOut(idea.id); return;
      case "use": if (idea) ctx.useText(idea.text || plainText(`${idea.title}. ${idea.line}\n${idea.insight} ${idea.idea}`, idea), P.slug, { cities: ctx.cities() }); return;
      case "tour": {
        const i = P.ideas.find((x) => x.id === P.rolloutFor);
        if (!P.rollout || !i) { status("Roll an idea out first."); return; }
        ctx.useText(i.text || "", P.slug, { stops: P.rollout.cities, tour: true });
        return;
      }
      case "print": print(); return;
      case "unsteer": {
        const [k, v] = b.dataset.arg.split(":");
        if (k === "pin") P.pins = P.pins.filter((p) => p.id !== v);
        if (k === "tone") P.tone = "";
        if (k === "killed") P.killed = P.killed.filter((_, i) => String(i) !== v);
        ctx.render();
        return;
      }
    }
  }

  function print() {
    if (!P.ideas.length) { status("Pitch something first."); return; }
    const ctrl = control();
    const lanes = LANES.filter(([k]) => P.lanes[k] && !P.lanes[k].fold).map(([k, l]) =>
      `<li><b>${esc(l)}:</b> ${P.lanes[k].rows.filter((r) => r.lift != null).slice(0, 4).map((r) => `${esc(r.name)} (${fmt(r.lift)})`).join(", ")}</li>`).join("");
    const ideas = P.ideas.map((i, n) => `<h2>${n + 1}. ${esc(plainText(i.title, i))}</h2><p class="text">${esc(plainText(i.line, i))}</p>
      <p>${esc(plainText(i.insight, i))} ${esc(plainText(i.idea, i))}</p>
      <ul>${Object.entries(i.slots).map(([k, s]) => `<li><b>${SLOT[k]}:</b> ${esc(s.name)}${s.lift != null ? ` (${fmt(s.lift)} against ${esc(ctrl?.name || "")}'s fans)` : s.city ? ` (${esc(s.city)}${s.address ? `, ${esc(s.address)}` : ""})` : ""}</li>`).join("")}</ul>`).join("");
    const roll = P.rollout && P.ideas.some((i) => i.id === P.rolloutFor)
      ? `<h2>Rollout</h2><ul>${P.rollout.beats.map((b) => `<li><b>${esc(b.phase)}, ${esc(b.city)}:</b> ${esc(b.move ? plainText(b.move, { slots: b.slots, lead_city: b.city }) : `${b.phase} at ${b.slots.venue?.name || ""}`)}</li>`).join("")}</ul>` : "";
    ctx.print(`<section><h1>${esc(cap(P.launch || subjectName()))}</h1><p class="meta">${esc(P.briefText || P.text)} · ${esc(ctx.cities().join(", "))}${ctx.age() ? ` · ${esc(ctx.age().replace(/_/g, " "))}` : ""}</p>
      <h2>Their people</h2><p class="meta">What fans of ${esc(subjectName())} love more than ${esc(ctrl?.name || "a household name")}'s fans do, ranked by lift. Source: Qloo.</p><ul>${lanes}</ul>
      ${ideas}${roll}<p class="meta">Room's proposals, built from audience signals. Names and numbers from Qloo; words from Gemini.</p></section>`);
  }

  function onInput(e) {
    if (e.target.id === "briefInput") ctx.saveBrief(e.target.value);
  }

  return { state: P, go, again, primary, primaryLabel, roomChanged, entered, renderPaper, panelHtml, onPanel, onPaper,
    onInput, back, print, ticks, activeSample: () => PITCH_SAMPLES.findIndex((s) => s.text === P.briefText) };
}
