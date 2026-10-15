import assert from "node:assert/strict";
import { applyLine, rebase, applyProposal, swapSpan } from "../../web/js/edits.js";

const T = "We grabbed a double-double at Tim Hortons before the show, and the crowd was electric. Then Greggs catered the after-party. Nando's and Greggs both closed.";
const mk = (id, surface, from = 0) => {
  const start = T.indexOf(surface, from);
  const a = Math.max(T.lastIndexOf(". ", start) + 2, 0);
  const e = T.indexOf(".", start + surface.length) + 1;
  return { id, surface, start, end: start + surface.length, sentence: T.slice(a === 1 ? 0 : a, e).trim() };
};
const refs = [mk("r0", "Tim Hortons"), mk("r1", "Greggs"), mk("r2", "Nando's"), mk("r3", "Greggs", T.indexOf("Nando's"))];
refs.forEach((r) => assert.equal(T.slice(r.start, r.end), r.surface));
const check = (v) => v.refs.forEach((r) => assert.equal(v.text.slice(r.start, r.end), r.surface, `anchor ${r.id}`));

// swap 1
let v = applyLine(T, refs, "r0", "We grabbed a scoop at Cold Stone Creamery before the show, and the crowd was electric.", { name: "Cold Stone Creamery" });
check(v); assert.equal(v.refs.find((r) => r.id === "r0").surface, "Cold Stone Creamery");
// drop whole sentence
v = applyLine(v.text, v.refs, "r1", "");
check(v); assert(!v.text.includes("catered")); assert(!v.refs.find((r) => r.id === "r1"));
// two refs in one sentence: swap one, the other re-anchors and gets the new sentence
v = applyLine(v.text, v.refs, "r2", "Chicken Republic and Greggs both closed.", { name: "Chicken Republic" });
check(v); assert.equal(v.refs.find((r) => r.id === "r3").sentence, "Chicken Republic and Greggs both closed.");
// rebase a swap written against the old sentence
const prop = { action: "swap", ref_id: "r3", sentence: "Nando's and Greggs both closed.", line: "Nando's and Sweetkiwi both closed.", after: "Sweetkiwi", candidate: { name: "Sweetkiwi" } };
const r3 = v.refs.find((r) => r.id === "r3");
assert.equal(rebase(prop, r3), "Chicken Republic and Sweetkiwi both closed.");
v = await applyProposal(v, prop, null);
check(v); assert(v.text.endsWith("Chicken Republic and Sweetkiwi both closed."));
// a drop whose sentence moved asks for a recut
const dropProp = { action: "drop", ref_id: "r2", sentence: "Nando's and Greggs both closed.", line: "Greggs closed." };
let asked = false;
const v2 = await applyProposal(v, dropProp, async () => { asked = true; return "Sweetkiwi closed."; });
assert(asked); check(v2); assert(!v2.refs.find((r) => r.id === "r2"));
// span by changed words when the name differs
assert.deepEqual(swapSpan("just Greggs in a hat.", "just Chuy's in a hat.", "Chuy's Restaurant"), { at: 5, len: 6 });
console.log("edits.js: all assertions passed\n" + v2.text);
