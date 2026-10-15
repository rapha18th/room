# Room

**Read the room before you walk in.**

Room reads a script, a stand-up set, a speech, an ad, a deck or a document. It finds every cultural reference and tells you, city by city and age by age, whether each one lands with the people in the seats. Then it works like a spellchecker for culture: for every reference that falls flat, it suggests a local swap that does the same job in the line, or a cut, and you accept or ignore each one. Take the set on tour and Room writes a version for every stop.

Room runs on [Qloo's](https://www.qloo.com) taste graph. Gemini knows fame. Qloo knows taste. Room uses each for what it does best, and the benchmark below shows why.

## Try it

**Live at [sozoroom.web.app](https://sozoroom.web.app).** Open to everyone, on any screen. Ninety seconds:

1. Press **Read the room**. Room reads the launch-ad sample for Atlanta, Lagos and London and scores every reference in each city.
2. Press **Review for Atlanta**. In about half a minute Room suggests Chick-fil-A for Nando's. Accept it and the Atlanta score climbs from 80% to 92%.
3. Switch to **Tour** and press **Route the tour**. Every stop gets its own version of the set, and its own set list.
4. Load the **Stand-up** sample and review it for Dallas. Room keeps every weak reference there, because each one carries the joke.
5. Drop a Word file, a deck or a PDF on the page, review it, and press **Download** for the file with tracked changes.

Gemini chooses among Qloo's candidates, so a swap or a score can shift a point or two between runs.

## What it does

1. **Read.** Gemini finds every reference in the text and names the job it does in its line ("cheap 3am chaos", "symbol of giving up").
2. **Match.** Qloo search turns each reference into a taste-graph entity. Uncertain matches are flagged so the writer can confirm or change them.
3. **Map.** One Qloo heatmap per reference covers every city in the room plus five anchor cities, drawn as a single `MULTIPOLYGON`. Qloo ranks heatmap affinity across the whole polygon, so all cities share one scale.
4. **Score.** Each city gets two numbers, each from the tool that measures it best (see the benchmark below):
   - **Known**: how much of the city recognises the reference. Gemini estimates it from memory; Room raises it wherever Qloo measures a real local fan base (heatmap cells for the reference against a household name of the same kind: Coca-Cola for brands, Beyoncé for artists, Friends for TV).
   - **Loved**: Qloo's median affinity across the city's cells. With an age band set, Room reads it from an age-filtered heatmap.
5. **Verdict.** *Lands* (known and loved), *Roast* (known, kept at a distance), *Inside* (a slice of the room loves it), *Dies* (unknown), *Famous* (globally famous with a thin local fan base).
6. **Swap.** For a weak city, Qloo returns what that audience has affinity for, by taste similarity and by shared tags. Gemini keeps the candidates that do the same job, rewrites the line, and Room scores each swap in the same room.

## Benchmark: the Fame track

Qloo publishes affinity, a measure of how strongly an entity relates to an audience or a place, and advises comparing scores by rank. Its published numbers are client outcomes, so Room built a benchmark for the job it hands out: which city knows a name best.

[`benchmark/`](benchmark) holds 60 references with one home city among ten (New York, Los Angeles, Dallas, Atlanta, Toronto, London, Johannesburg, Lagos, Nairobi, Mumbai): sports teams, regional chains, local TV and local artists. Five that Qloo matches only loosely count as coverage gaps. The clean subset drops names that carry their home city, state or country.

| Subset | n | Qloo fan presence | Qloo taste (median affinity) | Gemini alone | Room |
|---|---|---|---|---|---|
| All | 55 | 87% | 87% | 100% | **100%** |
| Clean | 39 | 82% | 82% | 100% | **100%** |
| Africa and India | 19 | 74% | 68% | 100% | **100%** |
| Clean brands | 16 | 100% | 100% | 100% | **100%** |
| Clean artists | 18 | 67% | 67% | 100% | **100%** |

Qloo's map places every brand. Its misses are artists with thin records: several African artists share one cluster map that peaks in Lagos, and the signal per square kilometre in Lagos, Nairobi and Johannesburg runs at a quarter of New York's. So Room asks Gemini who recognises a name, lets Qloo raise that wherever a solid record shows a real fan base, and takes Loved, age, swaps, tours and every rewrite from Qloo's taste graph. Rerun with `python benchmark/run.py`; every row is in [`benchmark/results.md`](benchmark/results.md).

## Review: a spellchecker for culture

**Review for Atlanta** runs an agent over the script and streams suggestions, each with **Accept** and **Ignore** (or <kbd>A</kbd> and <kbd>I</kbd>, <kbd>J</kbd> and <kbd>K</kbd> to move). On the page, every suggestion sits on its word like a tracked change; click it for the card.

| Step | Who | What happens |
|---|---|---|
| Plan | Gemini | Reads the script and the city's verdicts, then decides for each weak reference: swap it, drop it, or keep it. A reference stays when its foreignness is the point of the line. |
| Find | Qloo, then Gemini | Qloo returns what the audience has affinity for; Gemini keeps the picks that do the same job and rewrites the line. Each swap target serves one reference. |
| Test | Qloo | Scores every pick in the same room with a fresh heatmap. The best one that lands becomes the suggestion. |
| Cut | Gemini | Rewrites the line minus the reference, for drops and for dead references that every local swap fails to beat. |

The room score counts up as you accept. The agent's full trace, every Qloo call and every choice, sits under **How the agent decided**. On the launch-ad sample, Review for Atlanta swaps Nando's for Chick-fil-A (80% to 92%) and keeps Burna Boy for the ad's energy. On the stand-up sample it keeps every reference for Dallas, because each belongs to the London cousin or to the punchline.

## Tour mode

Give Room up to eight stops. It scores the set in every city, runs a review per stop, and fills a tour sheet: one column per city, one row per reference, each cell saying what stays, what swaps and what gets cut, with the room score before and after. Tap a stop and the paper shows that city's version; **Print set lists** gives one page per stop with every change marked. In one run of the launch ad, with Chick-fil-A accepted for Atlanta and the tour routed through Atlanta, Dallas, London, Lagos and Nairobi, London took its Nando's back (76% to 88%) and Lagos took KFC (80% to 92%). The same line, three cities, three local answers.

## Files: decks and documents in, corrected files out

Drop or paste a PDF, PowerPoint (.pptx), Word (.docx), text or Markdown file anywhere on the page. Room reads slides, text boxes, tables and speaker notes, labels each block on the paper, and reviews it like any script. **Download** returns the file with the accepted changes written in:

- **Word** comes back with tracked changes by "Room", each with a comment carrying its reason. Accept All gives the corrected text; Reject All gives the original. A Room-edited file opens again in Room for another pass.
- **PowerPoint** gets its edits in place, with only the changed words moving, so a bold brand name stays bold. Each touched slide gets a change log in its speaker notes.
- **PDF** comes back as a tracked Word document, since a PDF holds positioned glyphs rather than editable paragraphs.
- **Text and Markdown** keep their spacing and markup.

Uploads stop at the door when they look hostile: zip bombs, macro payloads, password-locked PDFs, files over 12 MB or 60 pages. Libraries: python-pptx and python-docx (MIT), pypdf (BSD).

## Keyboard and access

Every control works from the keyboard and keeps focus through every update. In a review, <kbd>A</kbd> accepts, <kbd>I</kbd> ignores and <kbd>J</kbd> <kbd>K</kbd> move, while a review surface has focus; <kbd>Cmd</kbd>/<kbd>Ctrl</kbd>+<kbd>Z</kbd> undoes any accepted edit, and <kbd>Cmd</kbd>/<kbd>Ctrl</kbd>+<kbd>K</kbd> opens every command. The inline suggestion card is a labelled dialog tethered to its word. Text meets WCAG AA contrast on the stage and the paper, motion follows the reduced-motion setting, and type runs on Apple's system faces where they exist and Inter with optical sizes everywhere else.

## Second opinion

A switch on the board flips every verdict between **Room** and **Gemini alone**, where Gemini guesses Known and Loved from memory alone. Cells where the two disagree carry an outline, and hovering one shows the other's call. On the stand-up sample, Gemini alone says Crocs lands in every city; Room, reading Loved from Qloo, calls it a roast in all four.

## Room as an MCP server

Any MCP client can read the room mid-task. The endpoint is `https://sozoroom.web.app/mcp` (streamable HTTP, open to any client).

```bash
claude mcp add --transport http room https://sozoroom.web.app/mcp
```

| Tool | Does |
|---|---|
| `read_room(text, cities, age?)` | Every reference in a text, scored per city, with a room score per city |
| `score_reference(name, kind, cities, age?)` | One reference across up to four cities |
| `find_swap(line, reference, kind, city, job_in_line?)` | Local equivalents that keep the reference's job, each scored |
| `suggest_for_city(text, city, age?)` | Review a text for one city: swaps, cuts and keeps, returned as suggestions for you to apply |
| `rewrite_for_city(text, city, also_check?, max_swaps?)` | The rewrite agent, run on the server, with its trace |

## Qloo endpoints

| Endpoint | Use |
|---|---|
| `GET /search` | Reference to entity; city name to locality and boundary |
| `GET /v2/insights` `filter.type=urn:heatmap` | Known and loved per city over the room polygon, with `signal.demographics.age` |
| `GET /v2/insights` `filter.type=urn:entity:*` | Swap candidates by `signal.interests.entities` and by `filter.tags`, scoped with `signal.location` set to the city's own polygon |

## A request, start to finish

Nando's, in the launch ad, for a room of Atlanta, Lagos and London. Every call is a GET to `https://hackathon.api.qloo.com` with the key in the `X-Api-Key` header, held server-side.

1. **Read.** Gemini returns `Nando's`, type `brand`, job in the line: *crowd pleasing casual dining staple*.
2. **Match.** `GET /search?query=Nando's&types=urn:entity:brand&take=5` returns the Nando's brand entity with its tags. The name matches exactly, so Room marks it certain.
3. **Map.** `GET /v2/insights?filter.type=urn:heatmap&filter.location=MULTIPOLYGON(((Atlanta box)),((Lagos box)),((London box)),((five anchor boxes)))&signal.interests.entities=<Nando's id>&take=50` returns heatmap cells, each with `affinity`, `affinity_rank` and `popularity`. Room assigns every cell to its city.
4. **Score.** Loved is the median cell affinity in Atlanta. Known is Gemini's recognition estimate, raised by Qloo's fan presence (Nando's cells against Coca-Cola's in the same room). Nando's reads *Inside* in Atlanta: a slice of the city loves it.
5. **Find.** `GET /v2/insights?filter.type=urn:entity:brand&signal.interests.entities=<Nando's id>&signal.location=POLYGON((Atlanta box))&filter.exclude.entities=<Nando's id>&take=10`, and the same call with `filter.tags=<Nando's top tags>`, return brands Atlanta has affinity for.
6. **Pick and test.** Gemini keeps the candidates that do the same job and rewrites the line. Room maps each pick with a fresh heatmap over the same room. Chick-fil-A lands in Atlanta, and the room score moves from 80% to 92%.

## What a score means

- Qloo affinity describes audiences in a place, in aggregate. Room reads rooms and crowds, and every score speaks for the whole room.
- Known and Loved are relative signals on one scale for the cities in the room. Read them as a ranking: Atlanta loves Chick-fil-A more than Nando's.
- Qloo's hackathon data is richest for the US and the UK. Room flags loose matches and coverage gaps (Big Brother Naija and Tusker in the benchmark) and lets the writer pick the right entity.
- Each verdict shows its source. Known comes from Gemini with a Qloo floor; Loved, age, swaps and tours come from Qloo. The **Gemini alone** switch shows the model's own guess beside Room's.

## Your text and your files

- Room sends Qloo entity names, tags and city boundaries. Your words stay with Room.
- Gemini on Vertex AI reads the text to find references and rewrite lines. Pasted text stays in the server's working memory and clears when the instance recycles. Uploaded files are parsed and rebuilt in memory and come straight back to you.
- The shared cache in Firestore holds Qloo lookups and the built-in samples.
- The Qloo key lives in Secret Manager and reaches the server as an environment variable. The browser talks only to Room.

## Run locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r service/requirements.txt   # macOS/Linux: .venv/bin/pip
cp .env.example .env                                     # add QLOO_API_KEY
gcloud auth application-default login                    # Gemini on Vertex AI (enable the Vertex AI API)
GOOGLE_CLOUD_PROJECT=<your-project> .venv/Scripts/python service/dev.py
```

Open http://127.0.0.1:8787.

## Deploy

The API runs on Cloud Run and Firebase Hosting serves `web/` with `/api/**` rewritten to the service.

```bash
gcloud run deploy room-api --source . --region us-central1 --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=<project>,ROOM_FIRESTORE_DB=room \
  --set-secrets QLOO_API_KEY=room-qloo-key:latest   --memory 1Gi --timeout 300 --max-instances 3
firebase deploy --only hosting
```

`--timeout 300` gives the MCP tool `rewrite_for_city` room to run the whole agent in one call. Point `.firebaserc` and the `site` in `firebase.json` at your own Firebase project and Hosting site.

`ROOM_FIRESTORE_DB` names a Firestore database for the response cache. Room runs with an in-memory cache when it is unset.

## Stack

Python, FastAPI, Qloo Insights API, Gemini on Vertex AI, Cloud Run, Firebase Hosting, Firestore. The front end is plain HTML, CSS and JavaScript.

## License

MIT
