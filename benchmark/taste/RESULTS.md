# Taste track pilot: results

Evaluation charts: Apple Music city charts published 2026-10-16. Protocol frozen at F0 (`602d0bd`), items and identity
verdicts at F1 (`d94ef4d`), every prediction hashed at F2 (`73d2ec9`) before the scorer ran once. Three independent
checks reproduced every figure below from the raw Qloo maps and Gemini answers.

## The question

For an artist a country knows, which of two of its cities loves the artist more? Gold comes from Apple Music city
charts: the artist leads a song on one city's Top 25 and is absent from the other's charts (or ranks 10 places lower).
Both cities share a language, media and national fame, so the answer turns on local taste.

## Outcome C: inconclusive, as pre-registered

**Taste pilot, 16 October 2026.** On 48 artists in 30 clusters across 120 city pairs in the US, UK and Canada (794 items),
Room's Qloo map scored **79.9%** and Gemini asked directly scored **86.0%**, a gap of 6.1 points (95% interval 0.3 to
12.7, unadjusted). Qloo covered 68% of eligible artists in those countries; counting every uncovered artist in all five
countries as a coin flip, Room's map scores 64.8% against Gemini's 80.8%. The rule set in advance names this outcome
inconclusive: Gemini's lead clears the 5-point bar, and its Holm-corrected p of 0.072 sits above 0.05.

| P1: US, UK, Canada | Score | 95% interval |
|---|---|---|
| Room's Qloo map (S1, the product's Loved) | 79.9% | 71.0 to 86.3 |
| Gemini alone, Room's "second opinion" (S3L) | 85.0% | 78.7 to 88.8 |
| Gemini alone, known x loved (S3K) | 84.0% | 77.6 to 87.8 |
| Gemini asked directly, four order-balanced runs (S4) | 86.0% | 79.8 to 89.7 |
| Qloo map and Gemini ranks combined (E9, exploratory) | 85.3% | 78.6 to 89.7 |
| Null controls: population, Beyonce map, city prior, Qloo panel | 50.0% | |
| Genre-city oracle (R1, uses the test-day charts) | 73.5% | 63.4 to 80.8 |

Room's map beats every null control (p 0.0004 or less): Qloo's heatmaps carry real local taste. Gemini reads it at least
as well from memory on these charts.

## What the number rests on

- **Item by item it is close.** Micro accuracy: Room's map 81.2%, Gemini 81.5%. The 6.1-point gap comes from the
  pre-registered cluster weighting; four small clusters holding 21 items supply 4.8 of those points.
- **The interval depends on the merge rule.** With one cluster per artist the gap is 4.3 points (interval -0.4 to 8.6,
  Holm 0.18). The merge fires only in the US, where Qloo returns coarser cells.
- **The balancing draw favoured Room** by about 0.8 points against the median of 300 redraws.
- **Coverage.** Qloo's hackathon data holds empty maps for Drake, Future and Lady Gaga, and many current local acts are
  missing; South Africa (48%) and India (37%) fell below the 60% floor and are reported on their own.
- **Where Qloo holds the artist** (P2, covered artists in all five countries, exploratory): Room's map 84.3%, Gemini 82.9%.
- **Data quality.** Apple and Shazam agree on 98.9% of items where both carry a signal. Gemini answered every call.

## By stratum (P1, pair-balanced cluster macro)

| Stratum | Items | Clusters | Room's map | Gemini alone | Gemini direct |
|---|---|---|---|---|---|
| United States | 706 | 21 | 82.6% | 82.7% | 85.0% |
| Canada | 74 | 15 | 69.9% | 82.8% | 85.2% |
| United Kingdom | 14 | 6 | 77.8% | 83.3% | 83.3% |
| National acts | 722 | 25 | 79.9% | 81.3% | 81.8% |
| Local acts (one chart) | 72 | 9 | 88.1% | 95.4% | 95.4% |
| High-confidence gold | 493 | 19 | 83.5% | 81.0% | 83.2% |
| Shazam-confirmed | 176 | 13 | 79.7% | 86.4% | 86.9% |

Every system on every stratum, with intervals and tests: [`data/results_eval.json`](data/results_eval.json). Every item
with every system's pick: [`data/picks_eval.json`](data/picks_eval.json). The protocol: [`PROTOCOL.md`](PROTOCOL.md).

## What Room takes from it

Gemini reads current music taste by city about as well as Qloo's map, and better where Qloo's records are thin. Room
keeps both: Gemini for recognition, Qloo for Loved, ages, the candidate search behind every swap, and the test of every
pick. Combining the two (E9) matches Gemini's best score; the pilot was too small to show the combination ahead.
