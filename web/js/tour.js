// Tour mode: one set, many rooms. A review per stop, then each stop's own version of the set.

import { applyProposal } from "./edits.js";
import { runReview } from "./review.js";

export const MAX_STOPS = 8;

// opts: { api, text, refs (scored across all stops), stops, age, live(), onStop(stop) }
// Each stop: { city, status: "waiting"|"working"|"done"|"error", items, trace, before }
export async function runTour(opts) {
  const { api, text, refs, stops, age, live, onStop } = opts;
  const queue = stops.map((city) => ({ city, status: "waiting", items: [], trace: [], before: null }));
  queue.forEach(onStop);
  const pending = [...queue];
  const worker = async () => {
    while (pending.length && live()) {
      const stop = pending.shift();
      stop.status = "working";
      onStop(stop);
      try {
        const r = await runReview({
          api, text, refs, city: stop.city, cities: stops, age, live,
          onTrace: (entries) => { stop.trace.push(...entries); },
          onItem: () => onStop(stop),
        });
        stop.items = r.items;
        stop.before = r.before;
        stop.status = "done";
      } catch (err) {
        stop.status = "error";
        stop.error = err.message;
      }
      if (live()) onStop(stop);
    }
  };
  await Promise.all([worker(), worker()]);
  return queue;
}

// The stop's version of the set: every proposal applied in order. Drops whose sentence moved are cut again.
export async function stopVersion(text, refs, stop, recut) {
  let view = { text, refs };
  const applied = [];
  for (const it of stop.items) {
    if (it.status === "kept" || !it.proposal || it.ignored) continue;
    const nextView = await applyProposal(view, it.proposal, recut);
    if (nextView) { view = nextView; applied.push(it); }
  }
  return { ...view, applied };
}
