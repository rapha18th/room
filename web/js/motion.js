// Motion, used sparingly: panel changes morph, numbers count, nothing moves for people who ask it not to.

export const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// Run a DOM update inside a view transition when the browser has one; otherwise just run it.
// The update runs exactly once; if the browser holds the transition back (a page that is not painting),
// it is skipped after 300 ms so the interface never waits on an animation.
export function transition(update) {
  if (!document.startViewTransition || reduced() || document.hidden) { update(); return; }
  let ran = false;
  const once = () => { if (!ran) { ran = true; update(); } };
  try {
    const vt = document.startViewTransition(once);
    setTimeout(() => { if (!ran) { try { vt.skipTransition(); } catch { /* already done */ } once(); } }, 300);
  } catch { once(); }
}

// Count numbers from what the viewer last saw to their new value. Elements carry data-tick (target)
// and data-key (identity across renders).
const shown = new Map();
const easeOut = (t) => 1 - Math.pow(1 - t, 3);

export function ticks(root) {
  root.querySelectorAll("[data-tick]").forEach((el) => {
    const key = el.dataset.key || "";
    const to = Number(el.dataset.tick);
    const from = shown.has(key) ? shown.get(key) : to;
    shown.set(key, to);
    const node = el.firstChild;
    if (!node || node.nodeType !== 3) return;
    if (from === to || reduced()) { node.nodeValue = String(to); return; }
    const t0 = performance.now(), dur = 650;
    node.nodeValue = String(from);
    const step = (now) => {
      if (!el.isConnected) return;
      const k = Math.min(1, (now - t0) / dur);
      node.nodeValue = String(Math.round(from + (to - from) * easeOut(k)));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}
