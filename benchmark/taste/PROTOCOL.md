# Taste track pilot: pre-registered protocol

Version 1, frozen at commit F0 before the evaluation charts are fetched.

```text
1. Question and claim
1.1 Question: for an artist a country knows, which of two cities in that country loves the artist more? The measure is Apple Music listeners in each city.
1.2 Claim under test, from the hackathon brief: the agent beats LLM-only approaches because of Qloo. The Fame track tested recognition. This pilot tests taste.
1.3 All copy names the measure "Apple Music listeners in the city". Apple describes its city charts as plays plus other signs of local momentum.

2. Snapshots, freezes, reproducibility
2.1 Dev snapshot. The 15 Oct data (spike/out/hometurf_sample.json and benchmark/taste_charts.json) serves three purposes: code dry runs, the room-composition check (5.4) and the power estimate (8.6). No accuracy is computed on it. Before the evaluation fetch, rename it to benchmark/taste_charts_dev_20261015.json.
2.2 Evaluation snapshot. Fetch once, after freeze F0, from the first Apple publication after the commit. That is expected at about 07:00 UTC on 2026-10-16. Write it to benchmark/taste_charts_eval.json. The fetch covers:
- the Apple Music Top 25 for every pilot city;
- the Apple Music Top 100 for the US, UK, Canada, South Africa and India;
- the Shazam city Top 50 for every pilot city where Shazam publishes one. Nairobi's Shazam chart covers all of Kenya and is ignored.
For every page, save the raw page, URL, fetch time, sha256 and datePublished.
2.3 Date rule. The most common Apple publish date across city charts is the evaluation date. A city chart with any other date gets one refetch. If the date still differs, the city drops out. On dev data this rule drops Liverpool.
2.4 Freezes.
- F0 is a git commit made before the fetch. It holds this protocol, the pilot code, score.py, all prompts, the city table and name map, the giveaway list, the population table, the genre-to-language map, the sha1 salt, the seeds and the PRESET edits in engine.py.
- F1 is a commit made before the first heatmap or Gemini prediction call. It holds items.json, the identity-check file, hometown tags, the India role list, the tenure table, the national-familiarity flags and the panel list.
- F2: every system writes predictions.jsonl to disk. The covered list and the balanced item sets are then computed from heatmap totals only. score.py then runs once.
results.json records the git hash and the sha256 of every frozen file.
2.5 Reruns. Rerun only calls that failed on transport, with identical inputs. Any other change after scoring starts a new numbered run, and every run is reported.
2.6 Cache and storage. ROOM_DISK_CACHE points to a new, empty folder. Store every raw Qloo and Gemini response with its request parameters, model id, response id and timestamp. Ship items.json, predictions.jsonl and score.py so anyone can rerun the scoring without API access.
2.7 Fallback. If the run must use the 15 Oct snapshot, the copy says so. Every result is then reported twice: with and without pairs that involve the ten hometurf cities.

3. Cities and groups
3.1 Every Apple Music city chart in the five countries is in, by rule. San Juan is out because it is a Spanish-language market with its own media. Otherwise a city drops out only under the date rule.
- US (15): Atlanta, Austin, Chicago, Dallas, Denver, Detroit, Honolulu, Houston, Los Angeles, Miami, Nashville, New York City, San Francisco, Seattle, Washington D.C.
- UK (5): Birmingham, Glasgow, Liverpool, London, Manchester
- Canada (6): Calgary, Edmonton, Ottawa, Toronto, Vancouver, Winnipeg
- South Africa (3): Cape Town, Durban, Johannesburg
- India (3): Bengaluru, Delhi, Mumbai
- Secondary, outside every headline: Africa cross-border (Accra, Johannesburg, Lagos, Nairobi). These pairs cross borders, so national fame returns.
3.2 Boxes. Every city resolves from engine.PRESET.
- Name map: "New York City" maps to "New York". Every other chart name equals its PRESET key.
- Before F0, the code asserts that no city falls through to Qloo /search, prints each box, and asserts each centroid lies inside the group's country.
- A person checks each box against a map before F0.
- Boxes are written to results.json.
3.3 Room. One heatmap per artist per group. The polygon is every city in the group plus the five anchors (New York, Los Angeles, London, Johannesburg, Lagos), deduplicated by PRESET key the way engine.room does it.

4. Items
4.1 Lead.
- The lead of an entry is the first artist in Apple's credit links, keyed by Apple artist ID.
- India: the lead is the first credited performer. Composers and lyricists on a role list are skipped. The list is built blind and frozen in F1.
- Featured credits form a secondary set.
4.2 Presence item (X, A, B). Gold is A. All three conditions hold:
- X leads at least one entry on A's Top 25.
- X has no credit on B's Top 25. Matching is by Apple artist ID, and by normalized name for title credits that have no ID.
- X is absent from B's Shazam Top 50, where one exists.
4.3 Rank-gap item (X, A, B). Gold is A. X leads entries on both charts, and X's best rank in A is at least 10 places above its best rank in B.
4.4 Exclusions. All are applied before any system call.
a. Giveaway names. The rule is a whole-word match against X's Apple credit, ignoring case and accents. The list:
- every pilot city name and its common alternatives: ATL, NYC, Bronx, BX, H-Town, HTX, DFW, 6ix, YYC, YVR, YEG, CPT, JHB, Jozi, DBN, Brum, Bombay, Bangalore, Dilli;
- the state, province or region of every pilot city;
- the 32 Mexican state names;
- country and nationality words: America, American, USA, Britain, British, UK, England, English, Scotland, Scottish, Canada, Canadian, Africa, African, Mzansi, India, Indian, Desi, Punjabi, Naija, Mexico, Mexican, Boricua;
- city demonyms: Texan, Atlantan, Houstonian, Angeleno, New Yorker, Mancunian, Glaswegian, Brummie, Scouse, Scouser, Torontonian, Capetonian, Mumbaikar.
The excluded names are published.
b. Cities removed by 3.1 or 2.3.
c. Entries whose lead has no Apple artist ID after an iTunes Lookup.
4.5 Balancing. This is done within each analysis population and each unordered city pair.
- Keep min(n_A, n_B) items in each direction, chosen by ascending sha1(salt|artist_id|A|B).
- A pair with items in only one direction contributes nothing.
- As a result, any predictor that is fixed per city pair scores about 50%. That covers population, data density per city and a big-city habit.
- There is no per-artist cap. Extra pairs cost no calls, and the macro average keeps each artist at weight 1.
4.6 Tags. All are frozen in F1 and come from sources independent of both systems.
- National: X is credited on 2 or more charts in its group, or appears on the country's Apple Top 100 the same day.
- Tenure: first release year from iTunes Lookup (entity=album, earliest releaseDate). Established means a first release in 2023 or earlier. New means later.
- Hometown: Wikidata P19 (place of birth) or P740 (location of formation), joined by Apple Music artist ID (P2850). MusicBrainz area is the backup. Blanks are hand-checked in the blind pass, under a time box, and stay unknown after that. An item is a hometown item when X's home metro is A or B.
- Album drop: 3 or more entries from one release dated within 14 days of the chart.
- Genre: Apple primary genre. Language comes from it through the frozen map.
- High-confidence: X's best rank in A is 15 or better, or X has 2 or more entries on A.
- Shazam-confirmed: X is on A's Shazam Top 50 and absent from B's.

5. Qloo resolution, coverage and storage
5.1 Resolution: engine.resolve on the Apple credit, type artist. Only certain matches count (quality 0.8 or more).
5.2 Blind identity check.
- One person compares each certain match with the Apple data. On the Qloo side: name, disambiguation, short description and top tags. On the Apple side: credit, primary genre and chart cities.
- Each match gets pass or fail. Unsure counts as fail.
- The check finishes before any heatmap or Gemini prediction call.
- Order: lead artists, then the Africa group, then featured credits. Featured matches still unchecked at the cutoff are reported as unchecked.
5.3 Covered artist: a certain match that passed the identity check and has a heatmap over its group polygon with at least one cell. An empty map is the condition under which the product switches to memory mode. Every other artist is a coverage gap. When an item has zero cells in both cities, it stays in and scores as an S1 tie.
5.4 Room-composition check, run before F0.
- Take 10 dev artists drawn by sha1, with 3 pairs each.
- For each, compare per-cell affinity_rank and geohash length between the group polygon and [A, B] plus the anchors.
- If they are identical, the group polygon is primary.
- If they differ, per-pair rooms are primary. That is up to about 2,000 heatmaps, about 1.5 hours at 4 concurrent.
5.5 Raw storage.
- Call /v2/insights with engine.profile's exact parameters: engine._polygon, take=50, filter.type urn:heatmap.
- Store every cell: geohash, lat, lon, affinity, affinity_rank, popularity, and the owner from engine._owner.
- Compute aggregates with engine.profile's code. A unit test asserts that the results match.
- Log total cells and geohash length. Flag any total of exactly 50.
- Every Qloo readout comes from these files.
5.6 Baseline: one Beyonce heatmap per group polygon. The entity ID is pinned in F0.

6. Systems
Confirmatory Qloo system
- S1, Room Loved (the product method).
  - Per city, Loved is the median cell affinity, at the 4 decimals engine.profile stores, when the city has 5 or more cells. With fewer cells, Loved is undefined.
  - ratio = the city's cells divided by Beyonce's cells for that city, in the same polygon.
  - The two cities are ordered by the key (Loved defined, Loved, ratio). This is engine.score's home key.
  - A full tie scores 0.5.
  - S1 makes no Gemini call.

Confirmatory LLM systems
Shared settings for all three:
- Model gemini-3.7-flash, called through llm._call. No race, no tools, no grounding, all asserted in code. Temperature 0.
- Each call is retried up to 5 times on the same model. A final failure scores 0.5 and is reported.
- The model and response id are logged for every call.

- S3L, Gemini alone, scored on loved (product parity).
  - Uses the GUESS prompt from guess_room verbatim, one call per artist.
  - Row format: "x | {Apple credit} | artist ({Apple primary genre})". The genre is the only change from the product.
  - Cities are given as "City, Country" in alphabetical order. Answers map back by exact label. A response that is missing a city counts as a transport failure.
  - Prediction: higher loved. Ties are broken on known, and then score 0.5.
- S3K, Gemini alone, scored on known x loved. It uses the same responses. Prediction: higher known x loved. Ties are broken on known, and then score 0.5.
- S4, Gemini asked directly.
  - Four calls per artist per group: two with the cities in alphabetical order and two in reverse order.
  - Prediction: lower mean rank. A tie scores 0.5.
  - Schema: {known: boolean, genre: string, ranking: [{city: string, rank: integer}]}.
  - Prompt, verbatim:
    You know popular music around the world. Answer from your own knowledge only.
    ARTIST: {Apple credit}
    APPLE MUSIC GENRE: {Apple primary genre}
    CITIES IN {country}: {cities as "City, Country", in the given order}
    First, say whether you know this artist (known: true or false) and name their main genre in a few words.
    Then rank every city from 1 to {k} by how strongly listeners in that city favour this artist compared with other artists, 1 being strongest. Use each rank once and copy each city exactly as written.

Null controls
- N1, Population: the bigger urban agglomeration in UN World Urbanization Prospects 2018, 2025 projection. The table is frozen in F0.
- N2, Beyonce map: S1's key applied to the baseline heatmap. It gives one fixed prediction per pair.
- N3, Gold city prior: each city's win rate on the items of all other artists (leave one artist out).
- N4, Qloo panel prior: each city's median Loved over a panel of up to 50 artists per country. The panel comes from the country Top 100 and excludes every artist on a city chart in the group. Certain matches only, without a hand check. About 250 heatmaps.

Reference system, outside the decision
- R1, Genre-city prior. It predicts the city whose chart, with X left out, has more leads in X's Apple genre. It is an oracle: it uses the test-day charts.

Exploratory systems
All are pre-registered and labelled exploratory, and none ever leads the copy. Unless marked, each comes from stored responses.
- E1: cells ratio (the draft's S2).
- E2: median cell popularity.
- E3: p75 affinity.
- E4: median affinity_rank. It is expected to agree with S1 on 100% of pairs, and any disagreement is reported.
- E5: S1 with the product's 2-decimal rounding.
- E6: S1 that scores 0.5 when either city lacks a Loved value.
- E7: S1 with each city's N4 median subtracted (demeaned Loved).
- E8: Room as shipped. S1 for covered artists and S3L for the rest, on population P2.
- E9: Hybrid. The mean of within-group ranks from S1 and S4, weighted 0.5 each, with S4 alone where S1 has no order. It is tested against S4 with the confirmatory test.
- E10: S4 with "right now, on Apple Music" wording, one alphabetical call.
- E11: S4 on gemini-3.6-flash.
- E12: artists on a shared map scored as S1 abstentions.
- E13: equal 20 km circles, computed from stored cells.
- Extra calls, run only after the confirmatory run and only if time remains:
  - E14: metro boxes for Toronto, Dallas and Vancouver.
  - E15: the person-record variant for artists with Qloo popularity below 0.5. It was fitted after the fact on the Fame track.
  - E16: a whole-country location query.

7. Populations and strata
7.1 Populations.
- P1, primary: covered lead artists in the five within-country groups, balanced. The decision rule runs on P1.
- P2, intent to treat (ITT): every eligible lead item, balanced on the eligible set. S1 scores 0.5 for uncovered artists.
7.2 Coverage floor. A group with less than 60% of its eligible lead artists covered leaves the P1 pool and is reported on its own.
7.3 Every confirmatory and null system is reported, with n, on these strata:
- national and local;
- established and new;
- hometown, non-hometown and unknown;
- high-confidence;
- Shazam-confirmed;
- presence items and rank-gap items;
- album drop;
- same-language, meaning the genre maps to the group's majority language;
- each group, plus the equal-weight mean over groups;
- Gemini-known (S4 says known in 3 or more of 4 runs), Qloo-covered, and known to both;
- the shared-map flag.
7.4 Secondary sets:
- featured-credit items, clustered by connected components of co-credited Apple IDs;
- the Africa cross-border group;
- the unbalanced items, scored with every null control.

8. Metrics and statistics
8.1 Item score: 1 for correct, 0.5 for a tie, 0 for wrong.
8.2 Cluster: one Apple artist ID, across all groups. Artists in the same group whose maps have cell-set Jaccard above 0.9 and affinity Spearman above 0.9 merge into one cluster.
8.3 Primary metric: macro accuracy. Each cluster scores the mean of its items, and the metric is the mean over clusters, pooled over the qualifying groups of P1.
8.4 Intervals. A cluster bootstrap with 10,000 resamples, seed 20261016, percentile 95% intervals, for every system and every paired difference. As a sensitivity check, a second bootstrap resamples city pairs.
8.5 Test. A one-sided paired sign-flip permutation test on per-cluster differences, with the mean difference as the statistic. It uses 10,000 draws, or exact enumeration at 16 clusters or fewer. Alpha is 0.05. The test applies to S1 against each of S3L, S3K, S4 and N1 to N4, and to E9 against S4.
8.6 Power, stated before any outcome is seen.
- On the dev snapshot (Liverpool dropped by the date rule), 155 lead artists form balanced items: US 58, India 33, South Africa 30, Canada 26, UK 8.
- 64 of them sit on 2 or more charts in their group.
- At 60 to 80% coverage, P1 holds about 95 to 125 clusters.
- Assume the per-cluster difference has an SD near 0.4. At 80% power and one-sided alpha 0.05, the minimum detectable effect is about 9 to 10 points for P1 and about 13 to 15 points for the national stratum.
- A true 5-point gap will most likely read as inconclusive. That outcome is planned.
8.7 Reported beside every macro score:
- micro accuracy, tie rate, and accuracy on decisive items;
- coverage and abstention rates per group;
- each system's rate of picking the bigger metro, and its accuracy split by whether gold is the bigger metro;
- S4's agreement across city orders, and its agreement with itself;
- pairwise agreement between Apple and Shazam, as the label-noise ceiling;
- the share of evaluation items that also appear in the dev snapshot.

9. Decision rule for README line 7 and all public copy
9.1 Outcome A, Room wins. All five conditions hold:
1. On P1, S1 beats each of S3L, S3K and S4 by 5 points or more, each with p below 0.05.
2. On P1, S1 beats each of N1 to N4 with p below 0.05.
3. On P2, S1 minus each LLM system is above 0.
4. S1 minus the best LLM system on P1 is above 0 in each of three strata: national, established, and non-hometown.
5. The same difference is above 0 in a majority of qualifying groups. A group qualifies if it meets the coverage floor and has 10 or more clusters.
9.2 Outcome B, Gemini wins. Some LLM system beats S1 on P1 by 5 points or more, with a one-sided p below 0.05 after Holm correction across the three LLM systems.
9.3 Outcome C, inconclusive: every other result.
9.4 The threshold and the test are the same in both directions. Conditions 2 to 5 in A guard the claim under test.
9.5 Copy, committed in F0:
- A. README line 7 stays: "Gemini knows fame. Qloo knows taste." The benchmark section leads with: "Taste track. Which of two cities in one country loves an artist more, judged by Apple Music city charts on {date}. Room's Qloo map {S1}%. Gemini alone {S3L}% and {S3K}%. Gemini asked directly {S4}%. {n} artists, {g} countries. Qloo covered {cov}% of eligible artists; counting the rest as coin flips, Room scores {ITT}%."
- B. README line 7 becomes: "Room runs on Qloo's taste graph and on Gemini. Gemini knows fame. In our Taste pilot Gemini also read local taste better than Qloo's map: {L}% against {S1}% on {n} artists." The Taste table runs with the same prominence as the Fame track and includes every stratum.
- C. README line 7 becomes: "Room runs on Qloo's taste graph. Gemini knows fame. Loved comes from Qloo's taste graph." The benchmark section adds: "Taste pilot, {date}: Room's Qloo map {S1}%, Gemini {L}% on {n} artists, gap {d} points ({CI}). The result falls short of the bar we set in advance: {failed condition}." The strata table follows.
- Under every outcome, the coverage rate and the ITT figure sit in the same sentence as the headline number.

10. Threats and their handling
- Chart momentum against long-run taste: the tenure strata, the album-drop flag, and the measure named in all copy.
- Freshness: record Gemini 3.7 Flash's documented knowledge cutoff and any date evidence for Qloo's data. The new-act stratum serves as the freshness track.
- City data density, which replaces the draft's take=50 threat. Heatmaps ignore take, and the cached totals reach 18,847 cells. Handled by balancing, N1 to N4, and the bigger-metro report.
- Shared cluster maps: cluster merging, plus E12.
- Boxes against Apple's metro areas (Brampton, Fort Worth): E13 and E14.
- Apple's listener skew in India and South Africa: per-group reports.
- Language and demographics: R1 and the same-language stratum.
- Hometown biography: the hometown strata and condition A4.
- Wrong entities: the blind identity check.
- Primacy bias: alphabetical city order, and S4 averaged over both orders.
- Model drift: pinned models, logged ids, S4 self-agreement.
- Design shaped by dev data: the freezes, the disclosure in section 0, and the overlap report.
- Gemini may have seen past charts: stated, and partly bounded by the tenure strata.
- Small n: the minimum detectable effect is stated in 8.6.

11. One-day run plan (2026-10-16, times in UTC)
- Before 07:00: code, unit tests, a dry run on dev data with stubbed systems, the room-composition check (about 30 heatmaps), the box map check, then commit F0.
- 07:15: fetch the evaluation snapshot (about 45 pages, paced) and apply the date rule.
- 07:30 to 08:30: build items and apply exclusions; about 250 iTunes Lookups, paced; one batch Wikidata query; about 600 Qloo searches.
- 08:30 to 10:00: the blind identity check, the role list and the hometown blanks, then commit F1.
- 10:00 to 10:45: about 500 heatmaps at 4 concurrent, taking 20 to 35 minutes. In parallel, about 230 S3 calls and about 920 S4 calls.
- 10:45 to 11:15: F2, then score.py runs once.
- 11:15 onward: exploratory runs that need calls, the featured set, and the write-up using the copy for the outcome that occurred.

12. Implementation notes, fixed at F0 before any evaluation data exists
12.1 Qloo's hackathon terms keep Qloo response data out of public repositories. Raw heatmap cells, search hits and every
     Qloo-derived value stay in a private folder. The public pick file (data/picks_eval.json) holds each system's score on
     each item (1, 0.5 or 0) with the item's tags, so anyone can recompute every metric from it.
12.2 The blind identity check (5.2) runs as two independent Claude reviewers per artist, each blind to every system output.
     A match passes only when both reviewers pass it. Unsure counts as fail. The same reviewers answer hometown blanks (4.6).
12.3 India's role list (4.1) is Apple's own composer field on each chart entry: the lead is the first credited name that the
     composer field leaves out.
12.4 N1 uses a hand-entered table of approximate 2025 metro populations, for ordering only (common.py). The UN WUP 2018
     download had moved. Balancing holds any fixed per-pair predictor near 50% whatever the values.
12.5 Qloo search results are cached across the dev and evaluation builds. Heatmaps and Gemini answers for the evaluation
     run start from an empty folder.
12.6 Hometown: Wikidata P740 (formation) before P19 (birth), joined on P2850; the home metro is the pilot city whose centre
     lies within 0.6 degrees of the place.
12.7 S3 and S4 answers map back to a city by its exact label or its exact city name.
12.8 The city-pair sensitivity bootstrap uses 2,000 resamples; the cluster bootstrap uses 10,000.
12.9 N3 computes each city's win rate over every eligible item in the group, leaving the item's artist out.
12.10 Shazam publishes city charts for 30 of the 35 cities on the dev snapshot. Austin, Washington D.C., Winnipeg, Accra and
     Nairobi fall back to country charts and skip the Shazam condition in 4.2.
12.11 R1 counts chart leads whose Apple genre came back from the iTunes lookups.
12.12 The featured-credit set and E14 to E16 run after the confirmatory scoring, if time allows.
12.13 File locations: the dev snapshot is data/charts_dev_20261015.json (rebuilt from the 15 Oct pages by fetch.py --dev);
     the evaluation snapshot is data/charts_eval.json; items, identity verdicts, picks and results sit beside them.
12.14 Change before F0, from dev coverage counts only (no accuracy was computed): on the dev snapshot Room's resolver
     matched 72 of 152 lead artists with certainty. Qloo's hackathon data files many current musicians as person records
     only (DJ Zinhle, Arjan Dhillon). Room's resolver, in the product and here, now takes a person record with the same
     name (match quality 0.95 or more: the same words) when no artist record matches with certainty. A first
     version at 0.8 let partial names through (Darque matched Jean-Claude Darque); the dev identity check caught them.
     Existing artist matches are untouched.
     Substituting a person record for a thin artist record stays exploratory (E15).
12.15 Wikidata throttled to one request a minute during the dev build; a hometown batch that fails stays unknown and is
     retried on the next build. Unknown hometowns fall in the hometown_unknown stratum.
12.16 The room-composition check (5.4) ran on dev data: in the 15-city US polygon Qloo returns geohash-5 cells, and in
     a two-city room geohash-6 cells, so cells and ranks differ; Canada, South Africa and India matched exactly. Per-pair
     rooms are therefore primary: S1 and E1 to E7 and E13 read one heatmap of X over [A, B] plus the anchors, with one
     Beyonce map per city pair (N2 reads it too).
12.17 Coverage (5.3), cluster merging (8.2) and E9's within-group ranks read one heatmap of X over the whole group
     polygon, the map 5.3 names. N4's panel also runs on group polygons: per-pair panels would need about 5,000 calls.
12.18 Per-pair heatmaps run for covered items in a scored population (P1, P2, the Africa set and below-floor groups). The
     unbalanced secondary set (7.4) is scored with the null controls only.
12.19 Primary metric weighting (amends 8.3, from the pre-F0 code review): each cluster weighs 1, split equally over
     its items; within each unordered city pair the two directions are then rescaled to equal total weight. Without
     this step the cluster macro broke 4.5's promise: on dev, fixed per-pair predictors ranged from 41% to 63%. With it,
     any fixed per-pair predictor scores exactly 50% (a unit test asserts it). The plain cluster macro is reported beside
     it. Bootstraps and the sign-flip test use the same weights; the test flips per-cluster weighted contributions.
12.20 N3 (amends 6 and 12.9): each city's win rate over the group's eligible items leaves out the item's whole city
     pair, so N3 is fixed per pair. Leaving out only the item's artist made N3 lean against gold by construction
     (0.37 on dev), which would have let a zero-skill system pass A2.
12.21 Leads (amends 4.1, 4.4c and 12.3): the lead is the first credit link. When it has no Apple ID the entry is
     excluded; a later credit is never promoted. India: two independent reviewers, blind to every system output, mark
     each credited name as performer or composer-only; a name is skipped when both mark it composer-only
     (data/india_roles_<snap>.json, frozen in F1). An entry credited to skipped names alone is excluded. Apple's
     composer field misread singer-songwriters (Karan Aujla's songs went to his producer).
12.22 Shazam matching (4.2, 4.6): names come from the split credit, the whole credit, and names featured in the title;
     "featuring" now splits whole.
12.23 Album drop (4.6): three or more of X's entries on A share the chart's album link, and that album's release date
     falls 0 to 14 days before the evaluation date.
12.24 Hometowns (4.6, 12.6): Wikidata first. Blanks come from the identity reviewers, who answer with a pilot city,
     "elsewhere" or "unknown"; the dev pass answered in free text, mapped through a short satellite table (Pretoria
     to Johannesburg, Brampton to Toronto). The MusicBrainz backup is replaced by this reviewer pass. Every build
     applies the reviewer answers.
12.25 S4 scores an item only when at least one answer exists in each city order; otherwise 0.5, counted as a failure.
     Gemini-known needs 3 of 4 runs (or 75% of the runs that answered). E11 makes four calls, like S4.
12.26 A scored item without its per-pair map or its pair baseline stops the scorer, so the call is rerun (2.5). The
     pair baseline never falls back to the group map for S1.
12.27 Strata report every confirmatory and null system plus R1 and E9. The coverage strata (Qloo-covered, Gemini-known,
     known to both) run on P2. A gating stratum with no items fails A4.
12.28 Cluster merging (8.2): cell-set Jaccard above 0.9, and common affinities identical or Spearman above 0.9.
12.29 E7 demeans group-map Loved by the N4 median (the same room); E9 gives tied S1 keys their mean rank.
12.30 The giveaway list matches 4.4a exactly. Every group's populations order strictly (N1).
12.31 Genre names seen on dev charts join the map: Sufi & Ghazals (hi), Regional Indian (pa), Modern Dancehall (en),
     South Africa (af), Worldwide and New Age (other).
12.32 Added outputs: an E9 minus S4 interval, Apple and Shazam agreement on items where both cities have a Shazam
     chart, S1 abstention by group, E4's agreement with S1, and the unbalanced items scored with N1 to N4. The public
     pick file carries each item's cluster and populations; stub runs write *_stub files.
12.33 Power restated (amends 8.6, from the dev dry run with real identity verdicts and stub maps): Qloo covers the
     US (71%), UK (80%) and Canada (60%) above the floor; South Africa (38%) and India (39%) fall below it and are
     reported on their own. P1 holds about 44 clusters over 123 city pairs. At a per-cluster SD near 0.4 the one-sided
     minimum detectable effect is about 15 points. Outcome A or B needs a large effect; C is the expected outcome
     otherwise, and the copy for C was written in advance (9.5).

13. Post-run notes (written after scoring; none changes a figure)
13.1 Transport: the first evaluation fetch at 07:05 UTC hit a truncated page; fetch.py gained retries (2.5) in a separate
     commit and the fetch reran at 07:07 UTC on the same publication (every chart dated 2026-10-16; Liverpool dropped).
13.2 Storage (deviation from 2.6): 40 Gemini attempts that failed and were retried (10 S3, 30 S4) were discarded unstored.
     Bound: dropping the retried S4 runs moves S4 by 0.0002; S3L moves at most 0.012.
13.3 Verification: three independent checks reproduced every P1 figure from the raw maps and answers, matched all 794
     stored picks, and found the prompts, labels, coverage and balancing clean. Outcome C stands under every cluster
     definition tried (one cluster per artist: gap 4.3 points, Holm 0.18). Results: RESULTS.md.

CHANGES FROM THE DRAFT
1. Cities resolve from a frozen PRESET table and name map, and Gemini gets "City, Country". All Apple city charts in the five countries are in by rule. San Juan is out, and the date rule removes stale charts, including Liverpool on dev data.
2. The 15 Oct data becomes the dev snapshot. Evaluation uses a fresh fetch after a git-committed freeze, with hashes and three freeze points.
3. Leads are keyed by Apple artist ID, featured credits are secondary, and India counts performers only.
4. Presence items now also require absence from B on Shazam. Rank-gap items are added. The "on every chart" exclusion is dropped because it never removed an item. The giveaway list covers nicknames, regions, Mexican states and demonyms.
5. Items are balanced by direction within each city pair. The per-artist cap of 3 is removed.
6. S1 follows engine.score: a 5-cell gate and a ratio fallback. It runs on one group heatmap per artist, with every raw cell stored.
7. S3 runs one call per artist with every city in the group, scored two ways, with fixed tie-breaks. S4 has a verbatim neutral prompt, gets the Apple genre, and takes four order-balanced samples. Models are pinned and grounding is off.
8. Null controls N1 to N4 and the oracle R1 are added.
9. The primary population is the covered set after a blind identity check. ITT becomes a condition for a Room win.
10. A cluster bootstrap and a sign-flip permutation test replace Wilson intervals and the item-level sign test. The minimum detectable effect is stated.
11. The decision rule has three outcomes, with copy committed in advance. A Gemini win rewrites README line 7.
12. Strata cover national reach, tenure, hometown, language and label strength. National, established and non-hometown gate a Room win.
13. The exploratory list is fixed in advance. Every Qloo variant other than S1 is exploratory.

FIXES SKIPPED OR MODIFIED, AND WHY
- Batches of 12 for S3 (method, minor): replaced by one call per artist. The devil review's major fix on batch leakage outranks it, and about 230 calls is cheap.
- Recency from Apple artist ID terciles (method, minor): replaced by first release year from Apple's catalogue, which measures recency directly.
- S1 on affinity_rank (Qloo, minor): S1 keeps affinity, the field the product uses. affinity_rank runs as the agreement check E4.
- Equal-weight mean over groups as the headline (devil, minor): reported as secondary. The pooled mean stays primary for power, and condition A5 adds the group-consistency check.
- Excluding Honolulu (devil, given as an example): Honolulu is kept. Thin data there is handled by the coverage floor and the per-group reports.
- Metro boxes and the whole-country query (method and Qloo, minor): they need extra calls, so they run last, and only if time remains.
- Sign test at p below 0.1 (Qloo): replaced by the permutation test at 0.05, which two of the three reviews proposed.
- National, established and non-hometown as the headline set (devil, major): adopted as conditions on a Room win and as reported strata. Their intersection leaves about 25 to 40 clusters on dev counts, a minimum detectable effect above 20 points, which neither outcome could reach.
- Best rank 15 or better in the headline (devil, major): kept as the high-confidence stratum. On dev data, national plus rank 15 or better leaves 30 artists before coverage.
- Shared-map artists as S1 abstentions (devil, major): the primary analysis merges them into one cluster instead, and E12 tests abstention. Abstaining would change the product method, and balancing removes the free win the review described.
- At least one cell in A or B to count as covered (Qloo, major): applied at the artist level, as an empty map. A per-pair cell rule would pick items using S1's own output.
- Gemini-known subset with a genre match (devil, major): only the known flag is used. Checking genre would need a second hand pass after system outputs exist, which breaks the blinding.
- Three S4 samples (devil, major): changed to four, so the method review's two-order fix is balanced.
- Room-as-shipped and the hybrid (Qloo and devil): both are kept as E8 and E9 with fixed formulas, labelled exploratory as the merge rules require.
```
