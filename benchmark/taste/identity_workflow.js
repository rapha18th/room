export const meta = {
  name: 'taste-identity-check',
  description: 'Blind identity check: two independent reviewers per batch confirm each Qloo artist match; pass needs both',
  phases: [
    { title: 'Review', detail: 'two independent reviewers per batch of artists' },
  ],
}

// args: { path, count, size, snap }
const VERDICTS = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          artist_id: { type: 'string' },
          verdict: { type: 'string', enum: ['pass', 'fail', 'unsure'] },
          reason: { type: 'string', description: 'A few words' },
          hometown: { type: 'string', description: 'Only when apple.home_metro is null: a pilot city, "elsewhere" or "unknown"' },
        },
        required: ['artist_id', 'verdict', 'reason'],
      },
    },
  },
  required: ['verdicts'],
}

const RULES = `You are checking entity matches for a benchmark, blind: no system output exists yet and none is shown to you.
Read the JSON file ${args.path} (a list). Review ONLY the entries with index from START to END-1 (0-based).
Each entry pairs an artist from an Apple Music city chart ("apple": credit name, Apple genre, the charts it sits on, the country group)
with the entity Qloo's search returned ("qloo": name, disambiguation, short description, top tags).
For each entry decide: is the Qloo entity the same artist as the Apple credit?
- pass: clearly the same artist (same name and a consistent genre, region or description).
- fail: a different artist, a namesake, a band versus a solo act of the same name, or a non-music entity.
- unsure: you cannot tell. Unsure counts as fail, so say unsure rather than guess.
Use your own knowledge and the fields given. Do not search the web and do not run code that calls any API.
When apple.home_metro is null, also give the artist's home metro: exactly one of ${args.cities} when the artist was born or
the act formed within about 60 km of that city, "elsewhere" when they come from somewhere else, or "unknown" when you do not know.
Return one verdict per entry in your range, with its artist_id copied exactly.`

const n = args.count
const size = args.size || 40
const chunks = []
for (let s = 0; s < n; s += size) chunks.push([s, Math.min(n, s + size)])
log(`${n} artists in ${chunks.length} batches, two reviewers each`)

phase('Review')
const results = await parallel(chunks.flatMap(([s, e], k) => ['A', 'B'].map((who) => () =>
  agent(RULES.replace('START', String(s)).replace('END', String(e)).replace('START to END-1', `${s} to ${e - 1}`) +
        (who === 'B' ? '\nWork from the last entry in your range back to the first.' : ''),
        { label: `reviewer-${who}-${k}`, phase: 'Review', schema: VERDICTS })
    .then((r) => r ? { who, k, verdicts: r.verdicts } : null))))

const byArtist = {}
for (const r of results.filter(Boolean)) {
  for (const v of r.verdicts) {
    byArtist[v.artist_id] = byArtist[v.artist_id] || {}
    byArtist[v.artist_id][r.who] = v
  }
}
const verdicts = {}, hometowns = {}, disagreements = [], missing = []
for (const [aid, both] of Object.entries(byArtist)) {
  if (!both.A || !both.B) { verdicts[aid] = 'fail'; missing.push(aid); continue }
  verdicts[aid] = both.A.verdict === 'pass' && both.B.verdict === 'pass' ? 'pass' : 'fail'
  if (both.A.verdict !== both.B.verdict) disagreements.push({ artist_id: aid, A: both.A, B: both.B })
  const ha = (both.A.hometown || '').trim(), hb = (both.B.hometown || '').trim()
  if (ha && ha.toLowerCase() !== 'unknown' && ha.toLowerCase() === hb.toLowerCase()) hometowns[aid] = ha
}
log(`pass ${Object.values(verdicts).filter((v) => v === 'pass').length} of ${Object.keys(verdicts).length}; ${disagreements.length} disagreements; ${missing.length} reviewed once`)
return { verdicts, hometowns, disagreements, missing, reviewed: Object.keys(verdicts).length }
