# Room

**Read the room before you walk in.**

Room reads a script, a stand-up set, a speech or an ad. It finds every cultural reference and tells you, city by city and age by age, whether each one lands with the people in the seats. When a reference dies, Room finds a local swap that does the same job in the line.

Room runs on [Qloo's](https://www.qloo.com) taste graph. An LLM alone can guess whether Lagos knows Greggs. Qloo measures it.

## What it does

1. **Read.** Gemini finds every reference in the text and names the job it does in its line ("cheap 3am chaos", "symbol of giving up").
2. **Match.** Qloo search turns each reference into a taste-graph entity. Uncertain matches are flagged so the writer can confirm or change them.
3. **Map.** One Qloo heatmap per reference covers every city in the room plus five anchor cities, drawn as a single `MULTIPOLYGON`. Qloo ranks heatmap affinity across the whole polygon, so all cities share one scale.
4. **Score.** Each city gets two numbers:
   - **Known**: cells with signal for the reference, against a household name of the same kind (Coca-Cola for brands, Beyoncé for artists, Friends for TV).
   - **Loved**: median affinity across those cells. With an age band set, Room reads it from an age-filtered heatmap.
5. **Verdict.** *Lands* (known and loved), *Roast* (known, kept at a distance), *Inside* (a slice of the room loves it), *Dies* (unknown), *Famous* (globally famous with a thin local fan base).
6. **Swap.** For a weak city, Qloo returns what that audience has affinity for, by taste similarity and by shared tags. Gemini keeps the candidates that do the same job, rewrites the line, and Room scores each swap in the same room.

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
