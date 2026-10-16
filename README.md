# Room

**Read the room before you walk in.**

Say what you are launching and Room pitches it: it reads who loves it across music, shows, film, podcasts, brands, people, games, books and travel, maps where those fans are and the rooms they gather in, city by city, and pitches up to three ideas built only from those names. Then it checks the work. Room reads a script, an ad, a picture, a deck or a set, finds every cultural reference and tells you, city by city and age by age, whether each one lands with the people in the seats. For every reference that falls flat it suggests a local swap that does the same job, and you accept or ignore each one, like a spellchecker for culture.

Room runs on [Qloo's](https://www.qloo.com) taste graph. Gemini knows fame. Loved comes from Qloo's taste graph. The two benchmarks below show where each one stands.

## Try it

**Live at [sozoroom.web.app](https://sozoroom.web.app).** Open to everyone, on any screen. Ninety seconds:

1. Room opens on **Pitch**. Press **Debut album**, or write one line: "A debut album for fans of SZA and Daniel Caesar. London, Atlanta, Lagos." Room reads the fans, maps the cities, finds their rooms and pitches up to three ideas. Every underlined name opens its Qloo receipt.
2. Type "start it in record stores" in the What if line. Qloo names the record stores these fans favour in each city (Reckless Records, Phonica and Next Door Records in London) and the ideas move there. Keep one, kill one with a reason, press **Again**, then **Roll it out** for a Tease, Drop and Live plan per city.
3. Switch to **Room** and press **Read the room**. Room reads the launch-ad sample for Atlanta, Lagos and London and scores every reference in each city. Press **Review for Atlanta**. In about half a minute Room suggests Chick-fil-A for Nando's. Accept it and the Atlanta score climbs from 80% to 92%.
4. Switch to **Picture** and open the **Lagos bar** sample. Tennis on the TV reads as Stella Artois ground for Heineken; Room redraws the screen with the Champions League and reads the new frame back.
5. Drop a Word file, a deck or a PDF on the page, review it, and press **Download** for the file with tracked changes.

Gemini chooses among Qloo's candidates, so a swap or a score can shift a point or two between runs.

## Pitch: from a brief to ideas you can defend

One line goes in, the way a brief gets said across a table: the thing, the news, and the cities. "Liquid Death launches a sparkling tea. Austin, London, Atlanta." A launch with no record of its own speaks through its comps, the way labels and studios already describe audiences: "A horror film for fans of Midsommar and The Lighthouse." Gemini reads the line into chips, and Qloo resolves every name. Each step below runs as its own request, and the trace shows each one with its seconds.

1. **Their people.** One `GET /v2/insights` per kind of culture (artist, TV, film, podcast, brand, person, game, book, destination) with the subject as the signal, a popularity floor and the subject excluded. The same list then goes back with a household name of the subject's kind as the signal (Coca-Cola for a brand, Beyoncé for an artist, Titanic for a film). Lift is the subject's fans' affinity minus the control's fans' affinity on the same names, so Room ranks what is distinctive to these fans. Liquid Death's fans: City Morgue +0.224, Trailer Park Boys +0.128, KILL TONY +0.170, The Lighthouse +0.122, Voodoo Ranger +0.278. A row folds when the control's fans barely know its names or the subject's fans barely separate from the field (Liquid Death's "They follow" row is a crowd of influencer accounts; it folds).
2. **Threads.** The tags on each row's top ten, kept when they cross two or more rows and appear more often than on the control's own lists. Liquid Death's fans run on comedy, raw, youthful and atmospheric. Identity words and content descriptors stay out.
3. **Where they gather.** Room's own map of the subject (or its comps) over the room's cities. Known, Gemini's estimate with a Qloo floor, says where a launch starts small or waits; Loved, from Qloo's heatmap and relative across the room's one map, says which known city opens and which builds. For the album sample, Atlanta and London open and Lagos builds. Then one `GET /v2/insights` per kind of room per city, with `filter.type=urn:entity:place`, the city's own box as `filter.location` and the room as a category tag: record stores for an album, cinemas for a film, bars for a drink. Qloo's order stands, and a chain that turns up twice in one box drops.
4. **The ideas.** Gemini writes up to three from the evidence pack with ids in five slots: With, Where, On, Sound and Look. Its words carry placeholders and Room renders every name from its own Qloo record, so every artist, brand, show, film, book, game, podcast and room on the page is a Qloo record with a receipt. Room strikes any sentence with a name outside the pack, a number, a ranking or a claimed deal, and its script reader reads the finished ideas back; an idea the reader has yet to clear says so. Ink is Qloo; pencil is Gemini.
5. **Talk back.** The What if line takes a name ("with Frank Ocean": Qloo measures his lift against these fans), a kind of room ("in record stores"), a city, an age band, a kind of culture ("more podcasts") or a mood ("darker", matched to Qloo's own tags). Qloo answers first, in one line, and the next round builds on it. Keep and Kill with a reason steer the round after.
6. **Roll it out.** A Tease, Drop and Live beat per city, each in a room from that city's list, in the order the map sets.
7. **Draw it.** A key visual for one idea, from Room's own description of it: the kind of room and the city, people by role, the threads as mood, no names, marks or text. The picture check reads the frame back and flags any mark the image model added; for a brand, **Check it in Picture** scores the frame city by city.

A pitch idea goes to the paper with **Check the copy**, where Room reads every reference in it city by city, and **Take it on tour** sends the rollout's cities to Tour. Qloo returns the same lifts for the same request. Gemini reads the brief, picks which of Qloo's names fill each slot and writes the words, so those shift between runs; the samples hold still because their first pitch is cached.

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

## Benchmark: the Taste pilot

**Taste pilot, 16 October 2026.** Which of two cities in one country loves an artist more, judged by Apple Music city charts. On 48 artists in 30 clusters across 120 city pairs in the US, UK and Canada, Room's Qloo map scored 79.9% and Gemini asked directly scored 86.0%, a gap of 6.1 points (95% interval 0.3 to 12.7). Qloo covered 68% of eligible artists in those countries; counting every uncovered artist as a coin flip, Room's map scores 64.8% against Gemini's 80.8%. The result falls short of the bar we set in advance: Gemini's lead clears 5 points, and its Holm-corrected p of 0.072 sits above 0.05.

| P1: US, UK, Canada | Score |
|---|---|
| Room's Qloo map (Loved) | 79.9% |
| Gemini alone, Room's second opinion | 85.0% |
| Gemini asked directly | 86.0% |
| Qloo map and Gemini combined (exploratory) | 85.3% |
| Null controls | 50.0% |

Room's map beats every null control, so Qloo's heatmaps carry real local taste; Gemini reads it at least as well from memory. Item by item the two sit close (81.2% and 81.5%). The protocol was frozen in a public commit before the charts were fetched, and every prediction was hashed before scoring. Strata, caveats and every item: [`benchmark/taste/RESULTS.md`](benchmark/taste/RESULTS.md).

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

## Picture: the check for frames and clips

A frame is a script whose references are boxes. Switch to **Picture**, name the brand and drop a frame or a short clip from an ad. Gemini reads every cultural element a viewer would notice: what is on the TV, in hand, on a shirt or a wall. Qloo scores each one for the brand and for each city in the room with three signals:

- **Lift.** How much more the brand's fans lean toward it than Coca-Cola's fans do (Room's mass-brand control): `GET /v2/insights?filter.type=urn:entity:brand&signal.interests.entities=<brand>&filter.results.entities=<every sports property>`, and the same call with Coca-Cola as the control. For Heineken's fans Formula One leads at +0.065 and the NFL sits at -0.056.
- **Ownership.** Qloo's brand records carry partnership, competitor and similar-brand tags. Heineken holds Formula 1, the UEFA Champions League and the Rugby World Cup; Stella Artois holds Wimbledon; Bud Light holds the NFL, MLB and the UFC. Qloo lists the NFL for Coors Light as well: a brand's own partnership stays its ground, and Room names the competitor that shares it.
- **City love.** Room's own Known and Loved per city, from one heatmap over the room, so every city sits on one scale. In the Lagos sample's room, Lagos loves the Champions League at 0.79; Dallas keeps it at 0.19 and loves the NFL at 0.54.

Each element gets a verdict per city: *Fits* (with a *yours* badge when the brand holds it), *Rival's*, *Off-market* or *Off-brand*. A flagged element comes with the best local alternative: a property the city loves (Loved 0.45 or more), free of competitors' partnerships, that the brand's fans lean toward. The brand's own partnerships come first; then city love plus lift decides.

**Redraw for a city** sends the frame to Gemini's image model with one instruction: change only that box. Room then reads the new frame back and confirms the slot now shows the pick and everything else held. On the Lagos sample, grass-court tennis on the bar's TV reads as Wimbledon, Stella Artois territory; Room redraws a floodlit Champions League night, Heineken's own partner, which Lagos loves at 0.79 in the sample's room, and the Lagos score goes from 0% to 100%. On the Dallas sample, the NFL on a backyard TV is Bud Light's own partnership: it fits in Dallas (0.54) and New York (0.69) and reads off-market in London and Lagos. One frame, two answers.

Clips are sampled into up to 16 frames in the browser; each element carries its time span, and a flagged one gets a shot note. Sports on screen map to a pinned catalog of 24 properties (football, American football, basketball, baseball, ice hockey, tennis, golf, motor racing, cricket, rugby, MMA, wrestling). Gemini's stated sport routes each screen first; events Qloo files under their league or tour (Wimbledon, the Super Bowl, the Ryder Cup) map to the property behind them and keep their name for the ownership check. Every redraw prompt is built on the server from Room's own read of the frame and the catalog's description of the sport.

## Files: decks and documents in, corrected files out

Drop or paste a PDF, PowerPoint (.pptx), Word (.docx), text or Markdown file anywhere on the page. A picture or a clip opens the picture check. Room reads slides, text boxes, tables and speaker notes, labels each block on the paper, and reviews it like any script. **Download** returns the file with the accepted changes written in:

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
| `pitch(brief, cities?, age?)` | A launch brief in, up to three ideas out, read back; every cultural name in an idea is a Qloo record with its lift, every room a Qloo place |
| `read_audience(subject, kind?, age?)` | What fans of one thing love more than fans of a household name of the same kind do, across nine kinds of culture, with the threads |
| `check_scene(brand, cities, image_base64? or image_url?, age?)` | The picture check: every element in an ad frame, scored for the brand in each city, with the best local alternative |

## Qloo endpoints

| Endpoint | Use |
|---|---|
| `GET /search` | Reference to entity; city name to locality and boundary |
| `GET /v2/insights` `filter.type=urn:heatmap` | Known and loved per city over the room polygon, with `signal.demographics.age` |
| `GET /v2/insights` `filter.type=urn:entity:*` | Swap candidates by `signal.interests.entities` and by `filter.tags`, scoped with `signal.location` set to the city's own polygon |
| `GET /v2/insights` `filter.type=urn:entity:*` with `filter.popularity.min` | Pitch's nine rows: what the subject's fans love, then the same names for the control's fans, for lift |
| `GET /v2/insights` `filter.type=urn:entity:place` | Pitch's rooms: `filter.location` set to the city's box, `filter.tags` set to a place category |
| `GET /search` `types=urn:entity:brand` | A brand's partnership, competitor and similar-brand tags, for ownership in the picture check |
| `GET /v2/insights` `filter.results.entities` | The brand's audience affinity for each sports property, against Coca-Cola's audience: lift |

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
- A typed brief and the ideas Room writes for it stay in the server's working memory. Pictures you upload are read in memory too; the samples' results sit in the shared cache.
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
