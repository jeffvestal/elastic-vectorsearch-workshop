---
slug: esql-vector-search
id: fufxor700z95
type: challenge
title: 'Lab 1 — Vector Search in ES|QL: The Thing Everyone Reaches For'
teaser: Run your first semantic queries in ES|QL with MATCH on a semantic_text field
  — embeddings generated server-side by Jina v5 via EIS. No client embedding code.
notes:
- type: text
  contents: |
    # Vector Search: Vector, Keyword, and Hybrid Retrieval

    **The thesis:** in RAG, retrieval quality — not the model — determines answer quality. Over the next two hours you'll build a hybrid retriever in **ES|QL** that wins on every kind of query, then express an entire RAG pipeline as a single ES|QL statement.

    | Lab | You'll do | Takeaway |
    | --- | --- | --- |
    | **1 — Vector Search** | `MATCH` on `semantic_text`, EIS, Jina v5 | match on *meaning*, not keywords |
    | **2 — Where It Breaks** | trap queries + read the score (no `explain`) | neither retriever is safe alone |
    | **3 — Hybrid** | `FORK \| FUSE` (RRF + linear) + a measured MRR eval | fuse to win on every query class |
    | **4 — Why It Matters** | `FORK \| FUSE \| RERANK \| COMPLETION` in ONE query + a multi-hop agent | retrieval *bounds* the answer |
    | **5 — Reranking** *(bonus)* | `RERANK`: pointwise vs listwise | the precision layer on top |

    **The throughline:** start with RRF, filter for scope, rerank for precision — and remember a better model can't rescue bad retrieval.
tabs:
- id: kyih8h3oiqjs
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
- id: nkngc4r1z9tm
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /notebooks/lab1-esql-semantic-search.ipynb
  port: 8888
difficulty: basic
timelimit: 1800
enhanced_loading: null
---
# Lab 1 — Vector Search in ES|QL: The Thing Everyone Reaches For

**Goal:** Run semantic queries against a pre-indexed corpus of Elastic docs — in ES|QL. See how `MATCH` on a `semantic_text` field embeds your query server-side (Jina v5 via EIS), with no client embedding code.

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

## Step 1 — Count the corpus, and meet ES|QL

ES|QL reads like a Unix pipe: a source, then `|`-separated stages. Start simple:

```esql
FROM aiewf-workshop-docs
| STATS docs = COUNT(*)
```

You should see **62**. To see what fields exist, look at the **field list on the left** of Discover — `body_semantic` is typed `semantic_text`, the rest are `text`/`keyword`.

***

## Step 2 — Your first semantic query

```esql
FROM aiewf-workshop-docs METADATA _score
| WHERE MATCH(body_semantic, "securing cluster traffic")
| SORT _score DESC
| LIMIT 5
| KEEP id, title, summary, _score
```

**What you should see:** the top result is a TLS / cluster-communications page — even though the query never uses the word **"TLS"**.

**Read the pipeline:**
- `FROM ... METADATA _score` — read the index *and ask for the relevance score*. **Without `METADATA _score`, `MATCH` is just a filter with no ranking.** This is the #1 ES|QL-search habit.
- `WHERE MATCH(body_semantic, "...")` — `body_semantic` is a `semantic_text` field, so this is a **semantic vector search**. Point `MATCH` at a `text` field instead and you'd get keyword search — the field type decides.
- `SORT _score DESC | LIMIT 5 | KEEP ...` — rank, trim, choose columns (the ES|QL `_source`).

***

## Step 3 — Try more queries

Change the string in `MATCH(body_semantic, "...")` and re-run. Try:

- `how do I back up my cluster data` — look for snapshot/restore docs
- `users can't connect to Kibana` — look for Kibana auth/access docs
- Any question you'd actually ask about Elasticsearch

Everyday language in, technical docs out — with no shared keywords. That's semantic search.

***

## Key Concept: what happens under the hood

1. Elasticsearch sends your query text to the Elastic Inference Service (EIS).
2. EIS runs Jina v5 and returns a dense vector (1024 numbers).
3. Elasticsearch runs approximate nearest-neighbor (ANN/HNSW) search over the stored document vectors.
4. The closest vectors become your results — no vocabulary matching required.

The single word `MATCH` in your ES|QL kicked off all of it.

***

Part 2 — Python Notebook
===

## Setup
1. Switch to the [button label="Python Notebook"](tab-1)
2. Open `lab1-esql-semantic-search.ipynb`

Run the cells in order. The notebook runs the same `MATCH` queries through `es.esql.query()`, inspects the `semantic_text` mapping and the embedding endpoint, and explains chunking and the Matryoshka dimension trade-off.

When you've finished, **click Next** to move to Lab 2.
