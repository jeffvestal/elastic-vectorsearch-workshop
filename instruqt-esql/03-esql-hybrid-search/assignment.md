---
slug: esql-hybrid-search
id: REPLACE_CHALLENGE_ID_3
type: challenge
title: 'Lab 3 — Hybrid in ES|QL: FORK, FUSE, Filtering, Reranking'
teaser: Fuse BM25 + semantic with FORK | FUSE (RRF and linear) into one retriever that wins
  on every query type that broke the others.
tabs:
- id: REPLACE_TAB_DISCOVER_3
  title: Kibana Discover
  type: service
  hostname: kubernetes-vm
  path: /app/discover
  port: 30001
  custom_request_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self'' https://kibana.estccdn.com; worker-src blob: ''self'';
      style-src ''unsafe-inline'' ''self'' https://kibana.estccdn.com; style-src-elem
      ''unsafe-inline'' ''self'' https://kibana.estccdn.com'
  custom_response_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self'' https://kibana.estccdn.com; worker-src blob: ''self'';
      style-src ''unsafe-inline'' ''self'' https://kibana.estccdn.com; style-src-elem
      ''unsafe-inline'' ''self'' https://kibana.estccdn.com'
- id: REPLACE_TAB_NB_3
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /notebooks/lab3-esql-hybrid-search.ipynb
  port: 8888
difficulty: intermediate
timelimit: 1800
enhanced_loading: null
---
# Lab 3 — Hybrid in ES|QL: FORK, FUSE, Filtering, Reranking

**Goal:** Combine BM25 + semantic into one retriever that wins on every query that broke a single method in Lab 2 — with `FORK` (run both) and `FUSE` (combine rankings).

Part 1 — Kibana Discover (ES|QL)
===

> [!NOTE]
> **How to run ES|QL in Kibana Discover:**
> 1. Open the **Kibana Discover** tab above.
> 2. Top-left, click the data view selector and choose **`aiewf-workshop-docs`**.
> 3. Make sure the query bar is in **ES|QL** mode — look for the **ES|QL** label in the
>    top-left of the query bar. If it says *KQL* or *Lucene*, click it and pick **ES|QL**.
> 4. Paste each `FROM ... | ...` block into the query bar and press **▶ Run** (or **Ctrl+Enter**).
>
> Results render as a **table** — one row per document, one column per field you `KEEP`.
> The `_score` column appears whenever your query starts with `... METADATA _score`.

***

## Part A — RRF hybrid via `FORK | FUSE`

Reciprocal Rank Fusion combines two ranked lists using only **rank position** — no score normalization, no tuning. Start with Lab 2's paraphrase failure:

```esql
FROM aiewf-workshop-docs METADATA _score, _id, _index
| FORK ( WHERE MATCH(body, "notify me when something goes wrong")          | SORT _score DESC | LIMIT 50 )
       ( WHERE MATCH(body_semantic, "notify me when something goes wrong") | SORT _score DESC | LIMIT 50 )
| FUSE
| SORT _score DESC
| LIMIT 5
| KEEP id, title, summary, _score
```
**What you should see:** the Watcher doc (`doc-049`) — buried by BM25 in Lab 2 — back at **#1**. The semantic branch ranked it #1, and FUSE only needs *one* branch to rank a doc highly.

Now swap the query string in **both branches** to `8.18 breaking changes`, then `new_primaries`, then `exit code 137`. Same structure — whichever branch was *right* carries the fusion. RRF lands the target at #1 on all four.

***

## Part B — Linear fusion with MinMax — `FUSE LINEAR`

RRF ignores raw scores. Linear uses them, normalized to 0–1 per branch (so BM25's larger numbers don't dominate semantic's), then weighted:

```esql
FROM aiewf-workshop-docs METADATA _score, _id, _index
| FORK ( WHERE MATCH(body, "notify me when something goes wrong")          | SORT _score DESC | LIMIT 50 )
       ( WHERE MATCH(body_semantic, "notify me when something goes wrong") | SORT _score DESC | LIMIT 50 )
| FUSE LINEAR WITH {"weights": {"fork1": 0.8, "fork2": 0.2}, "normalizer": "minmax"}
| SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score
```
`fork1` is the first branch (BM25), `fork2` the second (semantic). This is the paraphrase query from Part A — BM25 buries the Watcher doc (`doc-049`). Leaning **0.8 BM25** sinks it out of the top few; flip to `"fork1": 0.3, "fork2": 0.7` and `doc-049` climbs back to #1. **No single weight is right for every query** — which is why RRF (no weights) is the robust default.

***

## Part C — Filter inside the FORK branches

Scope hybrid search to a subset by adding a term filter to each branch:

```esql
FROM aiewf-workshop-docs METADATA _score, _id, _index
| FORK ( WHERE version_tags == "8.18" AND MATCH(body, "breaking changes")          | SORT _score DESC | LIMIT 50 )
       ( WHERE version_tags == "8.18" AND MATCH(body_semantic, "breaking changes") | SORT _score DESC | LIMIT 50 )
| FUSE | SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score, version_tags
```
Only `8.18`-tagged docs are eligible — the boosted-title distractor is filtered out entirely.

***

Part 2 — Python Notebook
===

1. Switch to the [button label="Python Notebook"](tab-1)
2. Open `lab3-esql-hybrid-search.ipynb`

The notebook proves the win **objectively**: rank-of-the-correct-doc across BM25/semantic/RRF, an MRR weight sweep, a strategies×queries heatmap, and a `RERANK` precision preview. **Click Next** for Lab 4.
