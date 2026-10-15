// The review loop: what Room suggests for one city, streamed as it is decided.
// Gemini plans (swap, drop, keep); Qloo finds and tests swaps; Gemini cuts what goes.
// Nothing here edits the script: every result is a proposal the writer accepts or ignores.


export function verdictIn(ref, city) {
  return ref.score?.cities?.[city]?.verdict ?? null;
}

// opts: { api, text, refs (each with .score), city, cities, age, live(), onTrace(entries), onItem(item) }
// Items: { id, ref_id, action: "swap"|"drop"|"keep", status, proposal, why, fallback }
export async function runReview(opts) {
  const { api, text, refs, city, cities, age, live, onTrace, onItem } = opts;
  const trace = (e) => { if (live()) onTrace(e); };
  const plan = await api("/agent/plan", { text, refs, city });
  trace(plan.trace);
  if (!live()) return { before: plan.before, items: [] };

  const items = plan.plan.map((s, i) => ({ id: `${city}:${s.ref_id}`, ref_id: s.ref_id, action: s.action, why: s.why,
    status: s.action === "keep" ? "kept" : "working", order: i }));
  items.forEach((it) => onItem(it));
  const exclude = refs.filter((r) => r.match).map((r) => r.match.entity_id);
  const taken = new Set();   // a swap target serves one reference per review

  const work = items.filter((it) => it.action !== "keep");
  const next = async () => {
    while (work.length && live()) {
      const it = work.shift();
      const ref = refs.find((r) => r.id === it.ref_id);
      try {
        if (it.action === "swap") {
          const f = await api("/agent/find", { ref, city, exclude: [...exclude, ...taken] });
          trace(f.trace);
          const picks = f.picks.filter((p) => !taken.has(p.candidate.entity_id));
          if (picks.length) {
            const t = await api("/agent/test", { text, refs, ref_id: ref.id, picks, city, cities, age, apply: false });
            trace(t.trace);
            if (t.proposal && !taken.has(t.proposal.candidate.entity_id)) {
              it.proposal = t.proposal;
              taken.add(t.proposal.candidate.entity_id);
            }
          }
          if (!it.proposal && verdictIn(ref, city) === "dies") {
            const c = await api("/agent/cut", { text, refs, ref_id: ref.id, city, apply: false });
            trace(c.trace);
            it.proposal = c.proposal;
            it.fallback = true;
          }
        } else {
          const c = await api("/agent/cut", { text, refs, ref_id: ref.id, city, apply: false });
          trace(c.trace);
          it.proposal = c.proposal;
        }
        it.status = it.proposal ? "pending" : "kept";
        if (!it.proposal) it.why = `Nothing local beats ${ref.surface} in ${city}, so it stays.`;
      } catch (err) {
        it.status = "error";
        it.error = err.message;
      }
      if (live()) onItem(it);
    }
  };
  await Promise.all([next(), next()]);
  return { before: plan.before, items };
}
