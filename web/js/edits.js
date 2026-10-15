// Editing a script without losing track of its references.
// Mirrors apply_line in service/agent.py so the browser and the server agree on every edit.

// Where the new reference sits in a rewritten line: the replacement's name if the line kept it,
// otherwise the words that changed between the old line and the new one.
export function swapSpan(oldLine, newLine, name) {
  const byName = name ? newLine.toLowerCase().indexOf(name.toLowerCase()) : -1;
  if (byName >= 0) return { at: byName, len: name.length };
  const a = oldLine, b = newLine;
  let p = 0;
  while (p < a.length && p < b.length && a[p] === b[p]) p++;
  let q = 0;
  while (q < a.length - p && q < b.length - p && a[a.length - 1 - q] === b[b.length - 1 - q]) q++;
  while (p > 0 && /[\p{L}\p{N}]/u.test(b[p - 1])) p--;
  while (q > 0 && /[\p{L}\p{N}]/u.test(b[b.length - q])) q--;
  const changed = b.slice(p, b.length - q).trim();
  if (!changed) return null;
  return { at: b.indexOf(changed, p), len: changed.length };
}

export function locate(text, ref) {
  const at = text.lastIndexOf(ref.sentence, ref.start);
  return at >= 0 ? at : text.indexOf(ref.sentence);
}

// Replace a reference's sentence with newLine. With a replacement entity the reference becomes it
// (a swap); without one the reference leaves the script (a drop). An empty newLine removes the
// sentence and the spaces after it. Returns { text, refs } or null when the sentence is gone.
export function applyLine(text, refs, refId, newLine, replacement = null, score = null) {
  const ref = refs.find((r) => r.id === refId);
  if (!ref) return null;
  const old = ref.sentence;
  const at = locate(text, ref);
  if (at < 0) return null;
  let end = at + old.length;
  if (!newLine) while (end < text.length && text[end] === " ") end++;
  const out = text.slice(0, at) + newLine + text.slice(end);
  const delta = newLine.length - (end - at);
  const next = [];
  for (const r0 of refs) {
    const r = { ...r0 };
    if (r.id === refId) {
      if (!replacement) continue;
      const span = swapSpan(old, newLine, replacement.name || "");
      const s = span ? span.at : 0, n = span ? span.len : newLine.length;
      Object.assign(r, {
        surface: newLine.substr(s, n), name: replacement.name, match: replacement, candidates: [replacement],
        certain: true, start: at + s, end: at + s + n, sentence: newLine, score, swapped_from: ref.swapped_from || ref.surface,
      });
    } else if (r.end <= at) {
      // untouched
    } else if (r.start >= end) {
      r.start += delta;
      r.end += delta;
    } else {
      const j = newLine ? out.indexOf(r.surface, at) : -1;
      if (j < 0 || j > at + newLine.length) continue; // the line that held it is gone
      r.start = j;
      r.end = j + r.surface.length;
      r.sentence = newLine;
    }
    next.push(r);
  }
  return { text: out, refs: next };
}

// A proposal was written against the sentence as it stood. If an earlier accepted edit changed that
// sentence, carry a swap across by substituting the new words for the reference in the current
// sentence. A drop needs a fresh rewrite, so it returns null and the caller asks the server again.
export function rebase(proposal, ref) {
  if (ref.sentence === proposal.sentence) return proposal.line;
  if (proposal.action !== "swap") return null;
  const span = swapSpan(proposal.sentence, proposal.line, proposal.after || "");
  if (!span) return null;
  const words = proposal.line.substr(span.at, span.len);
  const i = ref.sentence.indexOf(ref.surface);
  if (i < 0) return null;
  return ref.sentence.slice(0, i) + words + ref.sentence.slice(i + ref.surface.length);
}

// Apply one proposal to a { text, refs } view. Resolves to the new view, or null if it no longer fits.
export async function applyProposal(view, proposal, recut) {
  const ref = view.refs.find((r) => r.id === proposal.ref_id);
  if (!ref) return null;
  let line = rebase(proposal, ref);
  if (line == null && proposal.action === "drop" && recut) line = await recut(view, ref);
  if (line == null) return null;
  return proposal.action === "swap"
    ? applyLine(view.text, view.refs, ref.id, line, proposal.candidate, proposal.score)
    : applyLine(view.text, view.refs, ref.id, line);
}
