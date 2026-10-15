# Room

**Read the room before you walk in.**

Room reads a script, a stand-up set, a speech or an ad. It finds every cultural reference and tells you, city by city and age by age, whether each one lands with the people in the seats. When a reference dies, Room finds a local swap that does the same job in the line.

Room runs on [Qloo's](https://www.qloo.com) taste graph. Gemini knows fame. Qloo knows taste. Room uses each for what it does best, and the benchmark below shows why.

## What it does

1. **Read.** Gemini finds every reference in the text and names the job it does in its line ("cheap 3am chaos", "symbol of giving up").
2. **Match.** Qloo search turns each reference into a taste-graph entity. Uncertain matches are flagged so the writer can confirm or change them.
3. **Map.** One Qloo heatmap per reference covers every city in the room plus five anchor cities, drawn as a single `MULTIPOLYGON`. Qloo ranks heatmap affinity across the whole polygon, so all cities share one scale.
4. **Score.** Each city gets two numbers, each from the tool that measures it best (see the benchmark below):
   - **Known**: how much of the city recognises the reference. Gemini estimates it from memory; Room raises it wherever Qloo measures a real local fan base (heatmap cells for the reference against a household name of the same kind: Coca-Cola for brands, Beyoncé for artists, Friends for TV).
   - **Loved**: Qloo's median affinity across the city's cells. With an age band set, Room reads it from an age-filtered heatmap.
5. **Verdict.** *Lands* (known and loved), *Roast* (known, kept at a distance), *Inside* (a slice of the room loves it), *Dies* (unknown), *Famous* (globally famous with a thin local fan base).
6. **Swap.** For a weak city, Qloo returns what that audience has affinity for, by taste similarity and by shared tags. Gemini keeps the candidates that do the same job, rewrites the line, and Room scores each swap in the same room.

## Benchmark: why Known and Loved come from different places

[`benchmark/`](benchmark) holds 56 references with an unambiguous home city among ten (New York, Los Angeles, Dallas, Atlanta, Toronto, London, Johannesburg, Lagos, Nairobi, Mumbai): sports teams, regional chains, local TV and local artists. Each system names the city where the reference is best known.

| System | Home city found | Home city called a blank |
|---|---|---|
| Qloo heatmap fan presence alone | 87.5% | 4 |
| Gemini alone, from memory | 96.4% | 0 |
| **Room: Gemini recognition, Qloo fan presence as a floor** | **94.6%** | **0** |

Gemini is strong on fame: it read the internet. Qloo's heatmaps measure where fans concentrate, which tracks taste more than awareness: Tim Hortons shows more fan cells in New York than in Toronto, and Waffle House reads thin in Dallas. Qloo also sees what memory misses. It finds Khaligraph Jones's fan base in Johannesburg and Lagos, and places Big Brother Naija in Lagos where Gemini guessed London. Room's two remaining misses are the same story: Kabza De Small and Khaligraph Jones show their densest fan base in Lagos.

So Room asks Gemini who recognises a reference, lets Qloo raise that wherever it measures fans, and takes Loved, age, swaps and every rewrite from Qloo's taste graph. Rerun with `python benchmark/run.py`; full rows in [`benchmark/results.md`](benchmark/results.md).

## The rewrite agent

One button: **Rewrite for Atlanta**. The agent works in three tools and shows every step in a live trace, while the script on the page rewrites itself.

| Step | Who | What happens |
|---|---|---|
| Plan | Gemini | Reads the script and the room's verdicts, then decides which weak references to swap and which to keep. A reference stays when its foreignness is the point of the line. |
| Find | Qloo, then Gemini | Qloo returns what the audience has affinity for; Gemini keeps the picks that do the same job and rewrites the line. |
| Test | Qloo | Scores every pick in the same room with a fresh heatmap. The best one that lands goes into the script. |

The agent stops when the city clears 80% or the plan runs out, and reports what the rewrite costs in every other city. Each step is its own short request, so the browser drives the loop and the trace streams as it happens.

On the launch-ad sample the agent swaps Nando's for Chick-fil-A for Atlanta (62% to 82%) and keeps Burna Boy for the ad's energy. On the stand-up sample it keeps every reference for Dallas, because each one belongs to the London cousin or to the punchline.

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
| `rewrite_for_city(text, city, also_check?, max_swaps?)` | The rewrite agent, run on the server, with its trace |

## Qloo endpoints

| Endpoint | Use |
|---|---|
| `GET /search` | Reference to entity; city name to locality and boundary |
| `GET /v2/insights` `filter.type=urn:heatmap` | Known and loved per city over the room polygon, with `signal.demographics.age` |
| `GET /v2/insights` `filter.type=urn:entity:*` | Swap candidates by `signal.interests.entities` and by `filter.tags`, scoped with `signal.location.query` |

## Run locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r service/requirements.txt   # macOS/Linux: .venv/bin/pip
cp .env.example .env                                     # add QLOO_API_KEY
gcloud auth application-default login                    # Gemini on Vertex AI
GOOGLE_CLOUD_PROJECT=<your-project> .venv/Scripts/python service/dev.py
```

Open http://127.0.0.1:8787.

## Deploy

The API runs on Cloud Run and Firebase Hosting serves `web/` with `/api/**` rewritten to the service.

```bash
gcloud run deploy room-api --source . --region us-central1 --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=<project>,ROOM_FIRESTORE_DB=room \
  --set-secrets QLOO_API_KEY=room-qloo-key:latest --max-instances 3
firebase deploy --only hosting
```

`ROOM_FIRESTORE_DB` names a Firestore database for the response cache. Room runs with an in-memory cache when it is unset.

## Stack

Python, FastAPI, Qloo Insights API, Gemini on Vertex AI, Cloud Run, Firebase Hosting, Firestore. The front end is plain HTML, CSS and JavaScript.

## License

MIT
