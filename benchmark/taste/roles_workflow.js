export const meta = {
  name: 'taste-india-roles',
  description: 'Blind role list for India chart credits (4.1): two reviewers mark composer-only and lyricist-only names',
  phases: [{ title: 'Classify', detail: 'two independent reviewers' }],
}

// args: { path }
const ROLES = {
  type: 'object',
  properties: {
    roles: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          role: { type: 'string', enum: ['performer', 'composer_only', 'unsure'] },
        },
        required: ['name', 'role'],
      },
    },
  },
  required: ['roles'],
}

const PROMPT = `Read ${args.path}. It lists every name credited on three Apple Music India city charts ("names"), and each chart
entry with its credits and Apple's composer field ("entries"). No system output exists or is shown to you.
For EVERY name in "names", decide its role on these charts:
- performer: the person or act is heard on the recording as a singer, rapper, band or DJ (singer-songwriters who perform
  their own songs are performers).
- composer_only: a film composer, music director, producer credit or lyricist who is not the voice of the charting song
  (for example Pritam, Irshad Kamil, Amitabh Bhattacharya when credited beside the singers).
- unsure: you cannot tell.
Use your own knowledge and the entries. Do not search the web. Return one row per name, copying the name exactly.`

phase('Classify')
const [a, b] = await parallel(['A', 'B'].map((who) => () =>
  agent(PROMPT + (who === 'B' ? '\nWork through the names from the last to the first.' : ''),
        { label: `roles-${who}`, phase: 'Classify', schema: ROLES })))
const ra = Object.fromEntries((a?.roles || []).map((r) => [r.name, r.role]))
const rb = Object.fromEntries((b?.roles || []).map((r) => [r.name, r.role]))
const names = [...new Set([...Object.keys(ra), ...Object.keys(rb)])].sort()
const composer_only = names.filter((n) => ra[n] === 'composer_only' && rb[n] === 'composer_only')
const disagree = names.filter((n) => ra[n] !== rb[n]).map((n) => ({ name: n, A: ra[n], B: rb[n] }))
log(`${composer_only.length} composer-only names; ${disagree.length} disagreements`)
return { composer_only, disagree }
