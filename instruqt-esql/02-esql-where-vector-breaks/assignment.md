---
slug: esql-where-vector-breaks
id: 2hy203rtdof9
type: challenge
title: Lab 2 — Where Vector Breaks (and Lexical's Own Gap) — ES|QL
teaser: Find the queries that break semantic AND the ones that break BM25. Read the
  score in ES|QL — no explain needed — to see why neither retriever is safe alone.
tabs:
- id: usiwrukmw89t
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
- id: ipezhgle6vae
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /notebooks/lab2-esql-where-vector-breaks.ipynb
  port: 8888
difficulty: basic
timelimit: 1800
enhanced_loading: null
---
# Lab 2 — Where Vector Breaks (and Lexical's Own Gap)

**Goal:** Find where each retriever fails. Semantic **blurs** exact identifiers; BM25 picks the **wrong exact match** and **buries** paraphrases. Seeing why is the setup for hybrid (Lab 3).

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

> **Semantic vs BM25 is just which field you `MATCH`:**
> - `MATCH(body_semantic, q)` → semantic
> - `MATCH(title, q, {"boost": 3.0}) OR MATCH(body, q)` → BM25 keyword search, title weighted 3×

***

## Failure 1 — semantic blurs exact identifiers

```esql
FROM aiewf-workshop-docs METADATA _score
| WHERE MATCH(body_semantic, "exit code 137")
| SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score
```
`doc-007` (the OOM/137 doc) may still be #1 — but by a *hair*, with distractor docs that never say "137" right behind. Now run the BM25 version and watch `doc-007` win decisively:
```esql
FROM aiewf-workshop-docs METADATA _score
| WHERE MATCH(title, "exit code 137", {"boost": 3.0}) OR MATCH(body, "exit code 137")
| SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score
```
Try `new_primaries` in both — semantic lands a *plausible* but **wrong** doc at #1; BM25 pins `doc-008`.

***

## Failure 2 — BM25 picks the WRONG exact match

```esql
FROM aiewf-workshop-docs METADATA _score
| WHERE MATCH(title, "8.18 breaking changes", {"boost": 3.0}) OR MATCH(body, "8.18 breaking changes")
| SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score
```
BM25 ranks `doc-006` ("Elasticsearch breaking changes") #1 — the **wrong** doc. The 8.18 release-notes page (`doc-057`) is what the user wanted. Semantic gets this one right.

### Read the score WITHOUT `explain`

ES|QL has no `explain` mode. Prove *why* `doc-006` wins by splitting the match into two queries:
```esql
FROM aiewf-workshop-docs METADATA _score
| WHERE MATCH(title, "8.18 breaking changes", {"boost": 3.0})
| SORT _score DESC | LIMIT 5 | KEEP id, title, _score
```
```esql
FROM aiewf-workshop-docs METADATA _score
| WHERE MATCH(body, "8.18 breaking changes")
| SORT _score DESC | LIMIT 5 | KEEP id, title, _score
```
**Title-only** rewards `doc-006` (its boosted title literally *is* "breaking changes"). **Body-only** rewards `doc-057` (the rare token `8.18` lives in its body). In the combined query the boosted title wins — a *field-boost* effect, not term frequency.

***

## Failure 3 — paraphrase: BM25 buries it

```esql
FROM aiewf-workshop-docs METADATA _score
| WHERE MATCH(body_semantic, "notify me when something goes wrong")
| SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score
```
```esql
FROM aiewf-workshop-docs METADATA _score
| WHERE MATCH(title, "notify me when something goes wrong", {"boost": 3.0}) OR MATCH(body, "notify me when something goes wrong")
| SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score
```
Semantic finds the Watcher alerting doc (`doc-049`) at #1. BM25 **buries** it — the doc shares no vocabulary with the query (it says `trigger`, `condition`, `webhook`, never "notify").

***

The two retrievers fail on **opposite** query shapes. Neither is safe alone — that's the argument for hybrid.

Part 2 — Python Notebook
===

1. Switch to the [button label="Python Notebook"](tab-1)
2. Open `lab2-esql-where-vector-breaks.ipynb`

The notebook runs every trap with a `compare()` helper, shows the two-query score-reading technique, includes an experimental `SCORE()` cell, and ends with the core tension table. **Click Next** for Lab 3.
