export const meta = {
  name: 'taste-code-review',
  description: 'Before the F0 freeze: independent reviewers check the Taste-track code against its pre-registered protocol',
  phases: [
    { title: 'Review', detail: 'protocol fidelity, statistics, data and leakage' },
    { title: 'Verify', detail: 'a skeptic confirms or refutes each finding' },
  ],
}

const FINDINGS = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' },
          line: { type: 'integer' },
          protocol_section: { type: 'string' },
          problem: { type: 'string' },
          severity: { type: 'string', enum: ['blocker', 'major', 'minor'] },
          favours: { type: 'string', enum: ['room', 'gemini', 'neither'] },
          fix: { type: 'string' },
        },
        required: ['file', 'problem', 'severity', 'favours', 'fix'],
      },
    },
  },
  required: ['findings'],
}
const VERDICT = {
  type: 'object',
  properties: { real: { type: 'boolean' }, why: { type: 'string' } },
  required: ['real', 'why'],
}

const BASE = `Repo: C:\\Users\\USER\\Projects\\room. The Taste-track pilot lives in benchmark/taste/: PROTOCOL.md (pre-registered,
section 12 lists implementation notes), common.py, fetch.py, build.py, systems.py, score.py, test_taste.py; it uses
service/engine.py (aggregate, profile, room, _polygon, _owner, resolve, PRESET) and service/llm.py (GUESS, RoomGuess, client).
Dev outputs, if present: benchmark/taste/data/items_dev.json and charts_dev_20261015.json. Read the code and the protocol.
Do not call the Qloo or Gemini APIs and do not edit files. Report only concrete defects with file and line.`

const LENSES = [
  { key: 'fidelity', prompt: 'Check that the code implements PROTOCOL.md faithfully: items (4.2, 4.3), exclusions (4.4), balancing (4.5), tags (4.6), coverage (5.3), S1 key with the 5-cell gate and Beyonce ratio (6), S3L/S3K tie-breaks, S4 prompt verbatim and four order-balanced calls, null controls N1-N4, R1, the exploratory list, populations P1/P2 and the coverage floor (7), and the three outcomes with every condition (9).' },
  { key: 'stats', prompt: 'Check the statistics in score.py: macro accuracy over clusters, cluster merging (8.2), the cluster bootstrap and the city-pair bootstrap (8.4), the one-sided sign-flip permutation test and its p-value convention (8.5), Holm, the outcome logic in section 9, and any place where a bug would bias the result toward Room or toward Gemini.' },
  { key: 'data', prompt: 'Check the data path: chart parsing in fetch.py (Apple and Shazam), lead selection (including the India composer rule), absence checks by Apple ID and folded name, the date rule, iTunes and Wikidata lookups, home metro assignment, the public/private split required by Qloo terms (no Qloo-derived values in benchmark/taste/data), and any leakage of system outputs into the identity check or the items.' },
]

phase('Review')
const reviewed = await pipeline(
  LENSES,
  (l) => agent(`${BASE}\n\nLENS: ${l.prompt}`, { label: `review:${l.key}`, phase: 'Review', schema: FINDINGS }),
  (r, l) => parallel((r?.findings || []).map((f) => () =>
    agent(`${BASE}\n\nA reviewer reported this defect. Try to refute it by reading the code. Default to real=false if the code is in fact correct or the claim is speculative.\n${JSON.stringify(f)}`,
          { label: `verify:${l.key}`, phase: 'Verify', schema: VERDICT })
      .then((v) => ({ ...f, lens: l.key, verdict: v })))),
)
const all = reviewed.flat().filter(Boolean)
const confirmed = all.filter((f) => f.verdict?.real)
log(`${all.length} findings, ${confirmed.length} confirmed`)
return { confirmed, refuted: all.filter((f) => !f.verdict?.real).map((f) => ({ problem: f.problem, why: f.verdict?.why })) }
