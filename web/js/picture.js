// The picture check: a frame is a script whose references are boxes. Gemini reads what is on the TV, in hand and on
// the wall; Qloo scores each element for the brand and each city; a flagged element is redrawn in place and read back.

import { ticks } from "./motion.js";

export const PICTURE_SAMPLES = [
  { name: "Lagos bar", slug: "EXT. LAGOS BAR. NIGHT.", src: "samples/scene_lagos.jpg", brand: "Heineken",
    cities: ["Lagos", "London", "Dallas", "New York"] },
  { name: "Dallas backyard", slug: "EXT. DALLAS BACKYARD. SUNDAY.", src: "samples/scene_dallas.jpg", brand: "Bud Light",
    cities: ["Dallas", "New York", "London", "Lagos"] },
];

const IMAGE = /^image\/(jpeg|png|webp)$/;
const VIDEO = /^video\/(mp4|quicktime|webm)$/;
const isVideo = (f) => VIDEO.test(f.type) || /\.(mp4|mov|webm)$/i.test(f.name || "");
export const acceptsPicture = (f) => IMAGE.test(f.type) || isVideo(f) || /\.(jpe?g|png|webp)$/i.test(f.name || "");

const KIND = { fits: "v-lands", rival: "v-roast", off_market: "v-inside", off_brand: "v-dies" };
const SHORTV = { fits: "fits", rival: "rival's", off_market: "off-market", off_brand: "off-brand" };

export function createPicture(ctx) {
  const { $, esc, status } = ctx;
  const pic = {
    brand: "Heineken", name: "", slug: "", kind: null, src: null, blob: null, keep: false, frames: [],
    scene: null, fit: null, fitKey: "", selected: null, busy: "", error: "", fixed: null, wipe: 100, view: "before",
    frame: 0, gen: 0, pending: false,
  };
  let sweepId = 0;

  // ---------- loading ----------

  async function toJpeg(source, longest) {
    const bmp = source instanceof Blob ? await createImageBitmap(source) : source;
    const w = bmp.width || bmp.videoWidth, h = bmp.height || bmp.videoHeight;
    const s = Math.min(1, longest / Math.max(w, h));
    const c = document.createElement("canvas");
    c.width = Math.round(w * s);
    c.height = Math.round(h * s);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    return new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.88));
  }

  // A media event, or a clear error after a few seconds: some clips never fire one.
  const when = (v, ev, ms, msg) => new Promise((ok, no) => {
    const t = setTimeout(() => no(new Error(msg)), ms);
    v.addEventListener(ev, () => { clearTimeout(t); ok(); }, { once: true });
    v.addEventListener("error", () => { clearTimeout(t); no(new Error(msg)); }, { once: true });
  });

  async function sampleClip(file) {
    const v = document.createElement("video");
    v.muted = true;
    v.playsInline = true;
    v.preload = "auto";
    const url = URL.createObjectURL(file);
    v.src = url;
    try {
      await when(v, "loadeddata", 15000, "Room could not open that clip.");
      // Some WebM files report an endless duration until the player seeks to the end.
      if (!Number.isFinite(v.duration)) {
        v.currentTime = 1e7;
        await when(v, "seeked", 8000, "Room could not find the length of that clip.");
      }
      const dur = Math.min(Number.isFinite(v.duration) ? v.duration : 0, 60);
      if (!dur) throw new Error("Room could not find the length of that clip.");
      const step = Math.max(1, dur / 16);
      const frames = [];
      for (let t = 0; t < dur && frames.length < 16; t += step) {
        v.currentTime = t;
        await when(v, "seeked", 8000, "Room lost its place in that clip.");
        const blob = await toJpeg(v, 768);
        const mm = String(Math.floor(t / 60)).padStart(2, "0"), ss = String(Math.floor(t % 60)).padStart(2, "0");
        frames.push({ blob, t: `${mm}:${ss}`, url: URL.createObjectURL(blob) });
      }
      if (!frames.length) throw new Error("Room found no frames in that clip.");
      return frames;
    } finally {
      URL.revokeObjectURL(url);
      v.removeAttribute("src");
      v.load();
    }
  }

  function revoke() {
    const urls = new Set([pic.src, pic.fixed?.url, ...pic.frames.map((f) => f.url)].filter(Boolean));
    setTimeout(() => urls.forEach((u) => URL.revokeObjectURL(u)), 0);
  }

  function reset() {
    revoke();
    Object.assign(pic, { src: null, blob: null, kind: null, frames: [], scene: null, fit: null, fitKey: "", selected: null,
      fixed: null, view: "before", frame: 0, busy: "", error: "", pending: false });
    pic.gen++;
    cancelSweep();
  }

  async function open(file) {
    reset();
    const gen = pic.gen;
    pic.keep = false;
    pic.name = file.name || "picture";
    pic.slug = pic.name;
    pic.busy = "load";
    ctx.render();
    try {
      let frames = [], blob;
      if (isVideo(file)) {
        status("Sampling the clip…");
        frames = await sampleClip(file);
        blob = frames[0].blob;
      } else {
        blob = await toJpeg(file, 1600);
      }
      if (gen !== pic.gen) { frames.forEach((f) => URL.revokeObjectURL(f.url)); return; }
      Object.assign(pic, { kind: frames.length ? "video" : "image", frames, blob, src: URL.createObjectURL(blob), busy: "" });
      ctx.render();
      await check();
    } catch (err) {
      if (gen !== pic.gen) return;
      reset();
      status(err.message || "Room could not open that file.");
      ctx.render();
    }
  }

  async function loadSample(i) {
    const s = PICTURE_SAMPLES[i];
    reset();
    const gen = pic.gen;
    Object.assign(pic, { keep: true, name: s.name, slug: s.slug, brand: s.brand, busy: "load" });
    ctx.setCities(s.cities);
    ctx.renderControls();
    ctx.render();
    try {
      const blob = await (await fetch(s.src)).blob();
      if (gen !== pic.gen) return;
      Object.assign(pic, { kind: "image", blob, src: URL.createObjectURL(blob), busy: "" });
      ctx.render();
      await check();
    } catch (err) {
      if (gen !== pic.gen) return;
      pic.busy = "";
      status(err.message);
      ctx.render();
    }
  }

  // ---------- reading and scoring ----------

  async function post(path, form) {
    const res = await fetch(`/api${path}`, { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status})`);
    return data;
  }

  async function readFrames(blob, frames, keep) {
    const f = new FormData();
    if (frames?.length) {
      frames.forEach((fr) => f.append("frames", fr.blob, `${fr.t}.jpg`));
      f.append("times", JSON.stringify(frames.map((fr) => fr.t)));
    } else {
      f.append("file", blob, "frame.jpg");
    }
    f.append("keep", keep ? "true" : "false");
    return (await post("/scene/read", f)).scene;
  }

  const fitKey = () => `${ctx.cities().join("|")}#${ctx.age() || ""}#${pic.brand.trim().toLowerCase()}`;

  async function score(scene) {
    const key = fitKey();
    const fit = await ctx.api("/scene/fit", { brand: pic.brand.trim(), elements: scene.elements, cities: ctx.cities(), age: ctx.age() || null });
    return { fit, key };
  }

  // The room, the age or the brand moved while Room was busy: score again once it is free.
  function settle() {
    if (pic.busy || !pic.scene) return;
    if (pic.pending || (pic.fit && pic.fitKey !== fitKey())) { pic.pending = false; refit(); }
  }

  function report(fit) {
    const flagged = fit.elements.filter((e) => Object.values(e.cities || {}).some((c) => c.verdict !== "fits"));
    status(flagged.length ? `${plural(flagged.length, "element")} to look at. Tap a box for the reason and the fix.`
      : fit.scored ? `Everything in frame fits ${pic.brand} in this room.`
      : "Room scores sport, brands, artists, shows and places. This frame holds other things.");
  }

  async function check() {
    if (!pic.blob) { status("Open a picture or a clip, or pick a sample."); return; }
    if (!pic.brand.trim()) { status("Name the brand first."); $("brandInput")?.focus(); return; }
    if (pic.busy) return;
    const gen = ++pic.gen;
    Object.assign(pic, { fit: null, fixed: null, view: "before", selected: null, error: "", busy: "read" });
    status(pic.kind === "video" ? `Reading ${pic.frames.length} frames…` : "Reading the frame…");
    ctx.render();
    try {
      const scene = await readFrames(pic.blob, pic.kind === "video" ? pic.frames : null, pic.keep);
      if (gen !== pic.gen) return;
      pic.scene = scene;
      pic.busy = "fit";
      status(`Scoring ${plural(scene.elements.length, "element")} for ${pic.brand} in ${ctx.cities().join(", ")}…`);
      ctx.render();
      const { fit, key } = await score(scene);
      if (gen !== pic.gen) return;
      Object.assign(pic, { fit, fitKey: key, busy: "" });
      report(fit);
    } catch (err) {
      if (gen !== pic.gen) return;
      Object.assign(pic, { busy: "", error: err.message });
      status(err.message);
    }
    ctx.render();
    settle();
  }

  // Cities, age or brand changed: the frame's read holds; only the scores move.
  async function refit() {
    if (!pic.scene) return;
    if (pic.busy) { pic.pending = true; return; }
    const gen = ++pic.gen;
    Object.assign(pic, { busy: "fit", error: "", fixed: null, view: "before" });
    ctx.render();
    try {
      const { fit, key } = await score(pic.scene);
      if (gen !== pic.gen) return;
      Object.assign(pic, { fit, fitKey: key });
      report(fit);
    } catch (err) {
      if (gen !== pic.gen) return;
      pic.error = err.message;
      status(err.message);
    }
    pic.busy = "";
    ctx.render();
    settle();
  }

  function setBrand(b) {
    pic.brand = b;
    if (!pic.scene) { if (pic.blob) check(); return; }
    refit();
  }

  // ---------- the fix: redraw one box, then read it back ----------

  async function redraw(elementId, city) {
    const el = pic.fit?.elements.find((e) => e.id === elementId);
    const cell = el?.cities?.[city];
    if (!el || !cell?.pick || pic.kind !== "image" || pic.busy) return;
    const gen = pic.gen;
    pic.busy = "fix";
    status(`Redrawing the ${where(el)} with ${cell.pick.display}…`);
    ctx.render();
    try {
      const f = new FormData();
      f.append("file", pic.blob, "frame.jpg");
      f.append("element_id", el.id);
      f.append("box", JSON.stringify(el.box_2d));
      f.append("pick", cell.pick.name);
      const out = await post("/scene/fix", f);
      if (gen !== pic.gen) return;
      const blob = await (await fetch(`data:${out.mime};base64,${out.image}`)).blob();
      if (pic.fixed?.url) URL.revokeObjectURL(pic.fixed.url);
      pic.fixed = { blob, url: URL.createObjectURL(blob), element_id: elementId, city, pick: cell.pick, before: pic.fit.scene_score };
      Object.assign(pic, { view: "wipe", wipe: 100, busy: "readback" });
      sweep();
      ctx.render();
      await readBack(gen);
    } catch (err) {
      if (gen !== pic.gen) return;
      pic.busy = "";
      status(err.message);
      ctx.render();
    }
  }

  async function readBack(gen = pic.gen) {
    const fixed = pic.fixed;
    if (!fixed) return;
    Object.assign(fixed, { error: "", check: null });
    pic.busy = "readback";
    status("Reading the new frame back…");
    ctx.render();
    try {
      const read = fixed.scene || await readFrames(fixed.blob, null, false);
      if (gen !== pic.gen || pic.fixed !== fixed) return;
      const ck = await ctx.api("/scene/check", { before: pic.scene, after: read, element_id: fixed.element_id, pick: fixed.pick.name });
      if (gen !== pic.gen || pic.fixed !== fixed) return;
      // The read-back confirms the sport in the redrawn slot: that slot now shows the property Room drew there.
      const after = ck.ok && ck.slot_id
        ? { ...read, elements: read.elements.map((e) => (e.id === ck.slot_id ? { ...e, name: fixed.pick.name } : e)) }
        : read;
      fixed.scene = after;
      const sc = await score(after);
      if (gen !== pic.gen || pic.fixed !== fixed) return;
      fixed.check = ck;
      fixed.fit = sc.fit;
      fixed.fitKey = sc.key;
      const slot = where(fitOf(fixed.element_id));
      status(ck.ok ? `Drew ${ck.drew}. Room reads ${ck.found} on the ${slot}.`
        : `Drew ${ck.drew}; Room reads ${ck.found || "something else"}. Redraw again or keep the original.`);
    } catch (err) {
      if (gen !== pic.gen || pic.fixed !== fixed) return;
      fixed.error = err.message;
      status(`The read-back failed: ${err.message}`);
    }
    pic.busy = "";
    ctx.render();
  }

  function discard() {
    if (!pic.fixed) return;
    URL.revokeObjectURL(pic.fixed.url);
    pic.fixed = null;
    pic.view = "before";
    pic.gen++;
    pic.busy = "";
    cancelSweep();
    status("Back to the original frame.");
    ctx.render();
    settle();
  }

  // The new frame sweeps in over the old one, then the slider is yours.
  function sweep() {
    const id = ++sweepId;
    const t0 = performance.now(), dur = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1400;
    const step = (now) => {
      if (id !== sweepId) return;
      const k = dur ? Math.min(1, (now - t0) / dur) : 1;
      setWipe(Math.round(100 * Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  function cancelSweep() { sweepId++; }

  const wipeText = (w) => `${100 - w}% of the new frame showing`;
  function setWipe(w) {
    pic.wipe = w;
    document.querySelector(".frame-stage")?.style.setProperty("--wipe", `${w}%`);
    const r = document.getElementById("wipeRange");
    if (r) { r.value = w; r.setAttribute("aria-valuetext", wipeText(w)); }
  }

  function keepFixed() {
    const f = pic.fixed;
    if (!f?.fit || pic.busy) return;
    if (pic.src) URL.revokeObjectURL(pic.src);
    Object.assign(pic, { blob: f.blob, src: f.url, scene: f.scene, fit: f.fit, fitKey: f.fitKey, keep: false, fixed: null,
      view: "before", selected: null });
    status("Kept the new frame. Download it, or check another city.");
    ctx.render();
    settle();
  }

  function download() {
    const blob = pic.fixed?.blob || (pic.kind === "video" ? pic.frames[pic.frame]?.blob : pic.blob);
    if (!blob) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    const stem = (pic.name || "frame").replace(/\.\w+$/, "");
    const at = pic.kind === "video" && !pic.fixed ? ` ${pic.frames[pic.frame].t.replace(":", "m")}s` : "";
    a.download = `${stem}${at} (Room).${blob.type.includes("png") ? "png" : "jpg"}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  // ---------- drawing ----------

  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const bn = () => pic.fit?.brand?.name || pic.brand;
  const cap = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
  const focusCity = () => (ctx.cities().includes(ctx.focus()) ? ctx.focus() : ctx.cities()[0]);
  const fitOf = (id) => pic.fit?.elements.find((e) => e.id === id);
  const where = (e) => (e?.slot || "screen").replace(/^on (the|a) /, "");
  const area = (e) => (e.box_2d[2] - e.box_2d[0]) * (e.box_2d[3] - e.box_2d[1]);
  const numberOf = (id) => (pic.scene?.elements.findIndex((x) => x.id === id) ?? -1) + 1;

  // Largest boxes first, so a small box inside a large one sits on top and stays clickable.
  function boxesHtml(scene, fit) {
    if (!scene) return "";
    const city = focusCity();
    const shown = scene.elements.filter((e) => pic.kind !== "video" || inFrame(e, pic.frame)).sort((a, b) => area(b) - area(a));
    return shown.map((e) => {
      const f = fit?.elements.find((x) => x.id === e.id);
      const cell = f?.cities?.[city];
      const [y0, x0, y1, x1] = e.box_2d;
      const style = `top:${y0 / 10}%;left:${x0 / 10}%;height:${(y1 - y0) / 10}%;width:${(x1 - x0) / 10}%`;
      const n = numberOf(e.id);
      if (f?.route === "off_graph") {
        return `<span class="box off" style="${style}" title="${esc(e.what)}: off graph" aria-hidden="true"><span class="pin">${n}</span></span>`;
      }
      const cls = cell ? KIND[cell.verdict] : "wait";
      const said = cell ? `${SHORTV[cell.verdict]} in ${city}` : f ? `unscored in ${city}` : "scoring";
      return `<button type="button" class="box ${cls} ${pic.selected === e.id ? "sel" : ""}" data-el="${esc(e.id)}" style="${style}"
        aria-label="${n}: ${esc(e.what)}, ${esc(said)}" ${f ? "" : "disabled"}><span class="pin">${n}</span></button>`;
    }).join("");
  }

  function inFrame(e, k) {
    if (!e.t || !pic.frames.length) return k === 0;
    const toS = (s) => { const [m, x] = s.split(":").map(Number); return m * 60 + x; };
    const [a, b] = e.t.split("-").map((s) => toS(s.trim()));
    const t = toS(pic.frames[k].t);
    return t >= a - 1 && t <= (Number.isFinite(b) ? b : a) + 1;
  }

  const BUSY = { load: "Opening…", read: "Reading…", fix: "Redrawing…" };

  function renderPaper() {
    const frame = $("frame");
    if (!pic.src) {
      frame.innerHTML = pic.busy ? `<div class="frame-empty"><p>${pic.busy === "load" ? "Opening the picture…" : "Reading…"}</p></div>`
        : `<div class="frame-empty"><p>Drop a picture or a short clip from an ad.</p>
        <p class="sub">Room reads what is on the TV, in hand and on the wall, and checks each one for your brand in every city in the room.</p></div>`;
      return;
    }
    const src = pic.kind === "video" ? pic.frames[pic.frame].url : pic.src;
    const showFixed = pic.fixed && pic.view === "wipe";
    const busy = BUSY[pic.busy] || "";
    frame.innerHTML = `
      <div class="frame-stage ${busy ? "busy" : ""}" style="--wipe:${pic.wipe}%">
        <img class="before" src="${src}" alt="${esc(pic.name)}">
        ${showFixed ? `<img class="after" src="${pic.fixed.url}" alt="${esc(pic.name)} redrawn for ${esc(pic.fixed.city)}">
          <div class="wipe-line" aria-hidden="true"></div>` : ""}
        <div class="boxes">${showFixed ? "" : boxesHtml(pic.scene, pic.fit)}</div>
        ${busy ? `<div class="frame-busy"><span>${busy}</span></div>` : ""}
        ${pic.busy === "readback" ? `<div class="frame-pill" role="status">Reading back…</div>` : ""}
      </div>
      ${showFixed ? `<label class="wipe"><span>Before</span><input type="range" min="0" max="100" value="${pic.wipe}" id="wipeRange"
        aria-label="Before and after" aria-valuetext="${wipeText(pic.wipe)}"><span>After</span></label>` : ""}
      ${pic.kind === "video" ? `<div class="strip" role="group" aria-label="Frames">${pic.frames.map((fr, k) =>
        `<button type="button" class="${k === pic.frame ? "on" : ""}" data-frame="${k}" aria-pressed="${k === pic.frame}" aria-label="Frame at ${fr.t}"><img src="${fr.url}" alt=""><span>${fr.t}</span></button>`).join("")}</div>` : ""}`;
  }

  function scoreHead(scores) {
    return ctx.cities().map((c) => {
      const n = scores?.[c];
      return `<th><button class="colhead ${c === focusCity() ? "focus" : ""}" data-focus="${esc(c)}" type="button" aria-pressed="${c === focusCity()}" title="${esc(c)}">
        <span class="c">${esc(c)}</span><span class="n">${n == null ? "··" : `<span data-tick="${n}" data-key="pic-${esc(c)}">${n}</span><i>%</i>`}</span></button></th>`;
    }).join("");
  }

  function panelHtml() {
    const head = `<p class="kicker">Picture · ${esc(bn())}</p>`;
    if (!pic.src) {
      if (pic.busy) return `${head}<h2 class="dname">Opening the picture</h2><p class="lede">Room samples a clip in your browser before it reads it.</p>`;
      return `<p class="kicker">Picture</p><h2 class="dname">Check a frame</h2>
        <p class="lede">Gemini reads every cultural element in the frame. Qloo scores each one for the brand: how its fans lean,
        who holds it, and how each city in the room feels about it.</p>
        <div class="callout"><p>Pick a sample above, or drop a picture or a clip from an ad.</p></div>`;
    }
    if (pic.fixed && pic.view === "wipe") return fixedHtml();
    if (pic.selected && fitOf(pic.selected)) return elementHtml(fitOf(pic.selected));
    const fit = pic.fit;
    const brand = esc(bn());
    if (!fit) {
      if (pic.error && !pic.busy) {
        return `${head}<h2 class="dname">Room hit a snag</h2><p class="lede">${esc(pic.error)}</p>
          <div class="callout"><button class="primary" type="button" data-act="pic-retry">${pic.scene ? "Score again" : "Read again"}</button></div>`;
      }
      return `${head}<h2 class="dname">${pic.busy === "fit" ? "Scoring the frame" : "Reading the frame"}</h2>
        <p class="lede working"><span class="dot"></span>${pic.busy === "fit" ? `Qloo is ranking every element for ${brand}'s audience and mapping it for each city.` : "Gemini is finding every cultural element in the frame."}</p>`;
    }
    const scored = fit.elements.filter((e) => e.route !== "off_graph");
    const off = fit.elements.filter((e) => e.route === "off_graph");
    const rows = scored.map((e) => {
      const own = e.ownership;
      return `<tr><td><button class="rowname" type="button" data-el="${esc(e.id)}"><b><span class="pin small">${numberOf(e.id)}</span>${esc(e.what)}</b>
          <span>${esc(e.slot)} · ${esc(e.read_as.display || e.read_as.name)}${own ? ` · ${own.who === "yours" ? "yours" : own.who === "rival" ? esc(own.brand) + "'s" : "near " + esc(own.brand)}` : ""}</span></button></td>
        ${ctx.cities().map((c) => {
          const cell = e.cities?.[c];
          return `<td>${cell ? `<span class="cell ${KIND[cell.verdict]}">${SHORTV[cell.verdict]}</span>` : `<span class="cell wait" title="Qloo holds too little on this one in ${esc(c)}"></span>`}</td>`;
        }).join("")}</tr>`;
    }).join("");
    const stale = pic.busy === "fit" ? `<p class="boardnote working"><span class="dot"></span>Scoring for the new room…</p>` : "";
    return `${head}${stale}
      ${scored.length ? `<table class="board"><thead><tr><th></th>${scoreHead(fit.scene_score)}</tr></thead><tbody>${rows}</tbody></table>`
        : `<p class="lede">Room scores sport, brands, artists, shows and places. Everything in this frame sits outside that graph.</p>`}
      ${off.length ? `<p class="boardnote">Also in frame: ${off.map((e) => esc(e.what)).join("; ")}.</p>` : ""}
      ${scored.length ? `<p class="boardnote">The number under each city is how much of the frame works for ${brand} there. Tap a box or a row for the reason and the fix.</p>` : ""}
      ${ownershipNote(fit)}`;
  }

  function ownershipNote(fit) {
    const mine = fit.brand.partnership?.length ? `${esc(fit.brand.name)} partners with ${fit.brand.partnership.map(esc).join(", ")}.` : "";
    const riv = Object.entries(fit.brand.rivals || {}).slice(0, 4).map(([b, ps]) => `${esc(b)}: ${ps.map(esc).join(", ")}`).join(" · ");
    return mine || riv ? `<div class="callout"><p><b>From Qloo's brand records.</b> ${mine}${riv ? ` Competitors hold ${riv}.` : ""}</p></div>` : "";
  }

  function ownLine(e) {
    const o = e.ownership;
    if (!o) return "";
    const prop = esc(o.display || o.property || "");
    if (o.who === "yours") {
      return `<p class="own yours">${esc(bn())} partners with ${prop}.${o.shared?.length ? ` Qloo lists it for ${o.shared.map(esc).join(" and ")} too.` : ""}</p>`;
    }
    if (o.product) return `<p class="own ${o.who}">${esc(o.brand)} is ${o.who === "rival" ? "a competitor" : "a similar brand"} in Qloo's records for ${esc(bn())}.</p>`;
    return `<p class="own ${o.who}">Qloo lists ${prop} among ${esc(o.brand)}'s partnerships${o.who === "near" ? " (a similar brand)" : ""}.</p>`;
  }

  function elementHtml(e) {
    const city = focusCity();
    const control = esc(pic.fit?.brand?.control || "Coca-Cola");
    const lift = e.lift == null ? "" : `${esc(bn())}'s fans lean ${e.lift >= 0 ? "+" : ""}${e.lift.toFixed(3)} against ${control}'s fans${e.lift_rank ? `, ${ordinal(e.lift_rank)} of ${e.lift_of} properties Room scores` : ""}.`;
    const rows = ctx.cities().map((c) => {
      const cell = e.cities?.[c];
      if (!cell) return `<div class="sc"><div class="schead"><span class="cell wait"></span><b>${esc(c)}</b></div><p class="swhy">Qloo holds too little on this one in ${esc(c)}.</p></div>`;
      const here = c === city;
      let act = "";
      if (here && cell.verdict !== "fits" && e.route === "sport") {
        if (!cell.pick) act = `<p class="shot">Every sport Room scores either misses ${esc(c)} or pulls ${esc(bn())}'s fans away. Cut away from the screen for ${esc(c)}.</p>`;
        else if (pic.kind === "image") act = `<button class="primary" type="button" data-act="pic-fix" data-el="${esc(e.id)}" data-city="${esc(c)}" ${pic.busy ? "disabled" : ""}>Redraw for ${esc(c)}: ${esc(cell.pick.display)}</button>`;
        else act = `<p class="shot">Shot note${e.t ? ` ${esc(e.t)}` : ""}: show ${esc(cell.pick.visual)} for ${esc(c)}.</p>`;
      }
      return `<div class="sc ${here ? "here" : ""}"><div class="schead"><span class="cell ${KIND[cell.verdict]}">${SHORTV[cell.verdict]}</span>
        <b>${esc(c)}</b>${cell.yours ? `<span class="badge">yours</span>` : ""}</div><p class="swhy">${esc(cell.why)}</p>${act}</div>`;
    }).join("");
    return `<button class="back" data-act="pic-back" type="button">← The whole frame</button>
      <p class="kicker">${esc(e.slot)}</p><h2 class="dname" id="picTitle" tabindex="-1">${esc(e.what)}</h2>
      <p class="lede">Read as <b>${esc(e.read_as.display || e.read_as.name)}</b>${e.evokes ? `, evoking ${esc(e.evokes)}` : ""}. ${lift}</p>
      ${ownLine(e)}
      <div class="scs">${rows}</div>
      <p class="src">Gemini saw it · Qloo ranked it for ${esc(bn())} · Qloo mapped it for each city</p>`;
  }

  function fixedHtml() {
    const f = pic.fixed;
    const ck = f.check;
    const after = f.fit?.scene_score?.[f.city];
    const before = f.before?.[f.city];
    const product = ck?.product === true ? ", and so did the product" : ck?.product === false ? ". The product moved" : "";
    const held = !ck ? "" : ck.kept === ck.of ? (ck.of === 1 ? "The other element held" : `All ${ck.of} other elements held`)
      : `${ck.kept} of ${ck.of} other elements held`;
    const readback = ck ? `<div class="card readback ${ck.ok ? "ok" : "miss"}"><p class="kicker">Read back</p>
        <p>Drew <b>${esc(ck.drew)}</b>. Room reads <b>${esc(ck.found || "something else")}</b>${ck.slot_now ? ` (${esc(ck.slot_now)})` : ""}.</p>
        <p class="swhy">${held}${product}.</p></div>`
      : f.error ? `<div class="card readback miss"><p class="kicker">Read back</p><p class="swhy">${esc(f.error)}</p>
        <button class="ghost" type="button" data-act="pic-readback" ${pic.busy ? "disabled" : ""}>Read it back again</button></div>`
      : `<div class="card readback"><p class="kicker">Read back</p><p class="swhy working"><span class="dot"></span>Reading the new frame…</p></div>`;
    return `<p class="kicker">Redrawn for ${esc(f.city)}</p><h2 class="dname" id="picTitle" tabindex="-1">${esc(cap(f.pick.display || f.pick.name))}</h2>
      <div class="score"><span class="from">${before ?? "··"}% →</span> <span class="n">${after == null ? "··" : `<span data-tick="${after}" data-key="fixed-${esc(f.city)}">${after}</span><i>%</i>`}</span></div>
      <p class="lede">Room drew ${esc(f.pick.visual)} on the ${esc(where(fitOf(f.element_id)))} and kept the rest of the frame.</p>
      ${readback}
      <div class="callout"><button class="primary" type="button" data-act="pic-keep" ${f.fit && !pic.busy ? "" : "disabled"}>Keep it</button>
        <button class="ghost" type="button" data-act="pic-download">Download</button>
        <button class="ghost" type="button" data-act="pic-discard">Back to the original</button></div>
      <p class="src">Redrawn by Gemini image · read back by Gemini · scored by Qloo</p>`;
  }

  const ordinal = (n) => `${n}${["th", "st", "nd", "rd"][(n % 100 > 10 && n % 100 < 14) || n % 10 > 3 ? 0 : n % 10]}`;

  // ---------- events ----------

  const narrow = () => matchMedia("(max-width: 900px)").matches;

  // After the next paint, with a timer behind it for tabs that hold their frames.
  function soon(fn) {
    let done = false;
    const once = () => { if (!done) { done = true; fn(); } };
    requestAnimationFrame(once);
    setTimeout(once, 250);
  }

  function select(id) {
    pic.selected = id;
    ctx.render();
    soon(() => {
      if (narrow()) $("panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
      $("picTitle")?.focus({ preventScroll: true });
    });
  }

  function back() {
    const was = pic.selected;
    pic.selected = null;
    ctx.render();
    if (was) soon(() => document.querySelector(`#panel [data-el="${CSS.escape(was)}"]`)?.focus({ preventScroll: true }));
  }

  function onPanel(e) {
    const b = e.target.closest("[data-act], [data-el], [data-focus]");
    if (!b) return;
    if (b.dataset.focus) { ctx.setFocus(b.dataset.focus); return; }
    switch (b.dataset.act) {
      case "pic-back": back(); return;
      case "pic-fix": redraw(b.dataset.el, b.dataset.city); return;
      case "pic-keep": keepFixed(); return;
      case "pic-download": download(); return;
      case "pic-discard": discard(); return;
      case "pic-readback": readBack(); return;
      case "pic-retry": if (pic.scene) refit(); else check(); return;
    }
    if (b.dataset.el) select(b.dataset.el);
  }

  function onFrame(e) {
    const box = e.target.closest("button[data-el]");
    if (box) { select(box.dataset.el); return; }
    const fr = e.target.closest("[data-frame]");
    if (fr) { pic.frame = +fr.dataset.frame; ctx.render(); }
  }

  function onWipe(e) {
    if (e.target.id !== "wipeRange") return;
    cancelSweep();
    setWipe(+e.target.value);
  }

  return { state: pic, open, loadSample, check, refit, setBrand, back, renderPaper, panelHtml, onPanel, onFrame, onWipe,
    download, ticks };
}
