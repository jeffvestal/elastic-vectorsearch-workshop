---
slug: esql-reranking
id: REPLACE_CHALLENGE_ID_5
type: challenge
title: 'Lab 5 (Bonus) — Reranking in ES|QL: Precision After Recall'
teaser: Add a second-stage RERANK on top of FUSE recall. Compare pointwise (Jina v2) vs
  listwise (Jina v3) by swapping one inference_id.
tabs:
- id: REPLACE_TAB_DISCOVER_5
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
- id: REPLACE_TAB_NB_5
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /notebooks/lab5-esql-reranking.ipynb
  port: 8888
difficulty: intermediate
timelimit: 1800
enhanced_loading: null
---
# Lab 5 (Bonus) — Reranking in ES|QL: Precision After Recall

**Goal:** `FORK | FUSE` gets the right docs into the top-N (recall). `RERANK` fixes the order at the very top (precision). One pipe stage.

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

## Recall, then precision

Stage 1 — RRF recall:
```esql
FROM aiewf-workshop-docs METADATA _score, _id, _index
| FORK ( WHERE MATCH(body, "reduce storage cost for old logs")          | SORT _score DESC | LIMIT 50 )
       ( WHERE MATCH(body_semantic, "reduce storage cost for old logs") | SORT _score DESC | LIMIT 50 )
| FUSE | SORT _score DESC | LIMIT 8 | KEEP id, title, summary, _score
```
Stage 1+2 — add `RERANK`:
```esql
FROM aiewf-workshop-docs METADATA _score, _id, _index
| FORK ( WHERE MATCH(body, "reduce storage cost for old logs")          | SORT _score DESC | LIMIT 50 )
       ( WHERE MATCH(body_semantic, "reduce storage cost for old logs") | SORT _score DESC | LIMIT 50 )
| FUSE | SORT _score DESC | LIMIT 8
| RERANK "reduce storage cost for old logs" ON body WITH {"inference_id": ".jina-reranker-v3"}
| SORT _score DESC | LIMIT 5 | KEEP id, title, summary, _score
```
`RERANK` sends the query + each candidate's `body` to the reranker and **overwrites `_score`** — but does NOT reorder rows, so the `SORT _score DESC` *after* `RERANK` is required or the reranked scores land on the old RRF ordering.

RRF already puts the data-tiers doc (`doc-041`) and the ILM overview (`doc-017`) in a near-tie for #1. Watch the reranker break that tie — it flips its pick to `doc-017`.

***

## Pointwise vs listwise — swap one id

Change the `inference_id` to `.jina-reranker-v2-base-multilingual` (pointwise cross-encoder) and compare against `.jina-reranker-v3` (listwise). On `user cannot authenticate`, watch where the *authorization* doc (`doc-002`) lands — listwise, scoring the whole set jointly, tends to push it down.

***

Part 2 — Python Notebook
===

1. Switch to the [button label="Python Notebook"](tab-1)
2. Open `lab5-esql-reranking.ipynb`

The notebook runs both rerankers head-to-head, walks the pointwise-vs-listwise difference, and gives the "when to rerank at all" decision framework.

That's the workshop — you've expressed **every** stage of a modern retrieval pipeline (semantic, BM25, RRF/linear fusion, reranking, LLM synthesis) entirely in ES|QL.
