---
slug: reranking
id: ynspkvguehjb
type: challenge
title: 'Lab 5 (Bonus) — Reranking: Precision After Recall'
teaser: 'Add the precision stage: rerank your hybrid results with Jina v2/v3 via EIS.
  Learn pointwise vs listwise rerankers and when to use which.'
tabs:
- id: rzmdb5nxb7yc
  title: Elastic Cloud Serverless
  type: service
  hostname: kubernetes-vm
  path: /app/dev_tools
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
- id: jszqsbhjmslh
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /notebooks/lab5-reranking.ipynb
  port: 8888
difficulty: intermediate
timelimit: 1800
enhanced_loading: null
---
# Lab 5 (Bonus) — Reranking: Precision After Recall

**Bonus lab — if you have time after Agent Builder.** Labs 1–3 built a retriever; Lab 4 wired it to an LLM and an agent. This bonus adds the one stage we only gestured at in Lab 3: a **reranker** — a second-pass model that re-scores your top candidates so the order at the very top is exactly right.

Part 1 — Python Notebook
========================

## Setup:
1. Switch to the [button label="Python Notebook"](tab-1)
2. Open `lab5-reranking.ipynb` and run the cells top to bottom

The sections below explain what each step shows and why it matters.

***

## Reranking = a second stage

Everything you built so far is **bi-encoder retrieval**: the model encodes the query and each document *independently* into vectors and compares them. Fast, scales to millions of docs — because every document vector is computed once, at index time.

A **reranker** reads the **query and a candidate document *together*** and scores how relevant that exact document is to that exact query. It catches relevance that vector proximity misses — but it can't be precomputed, so it's too expensive to run over a whole corpus. So you run it as **stage 2**:

1. **Stage 1 — Recall:** the fast hybrid retriever (RRF) returns the top 50–100 candidates.
2. **Stage 2 — Precision:** the reranker re-scores only those candidates and returns the best few.

That sharpened top-K is what feeds a RAG prompt or an agent — so its precision is what the user actually feels.

***

## The two TYPES — pointwise vs listwise

The new idea in this lab: not all rerankers work the same way.

- **Pointwise (cross-encoder) — Jina Reranker v2:** scores each candidate **on its own**, one `(query, doc)` pass per doc. No knowledge of the other candidates. Simple, robust, batchable.
- **Listwise — Jina Reranker v3:** puts the **whole candidate set in one context window** and scores them **jointly**, so it can compare documents against each other. Better when candidates are similar / near-duplicate / overlapping. (GA Oct 2025, reranks up to ~64 docs per call.)

Elastic ships **both** as built-in EIS endpoints — you swap a single `inference_id` to switch.

***

## Notebook walkthrough

**Discover the endpoints** — list the rerank endpoints on your project (`.jina-reranker-v2-base-multilingual` and `.jina-reranker-v3`). Same inference-inspection skill you used in Lab 1.

**Call the rerank API directly** — `POST _inference/rerank/<id>` with a `query` and a list of document texts → each doc gets a `relevance_score`, re-sorted. This is exactly what the production retriever calls under the hood.

**Before / after on a real candidate set** — run RRF recall, then rerank it, and compare the order. Watch the doc you'd actually want climb.

**Pointwise vs listwise, head-to-head** — the **same** candidates (built to include the **doc-009 / doc-010 near-duplicate pair**) through v2 and v3, side by side. Watch the order *between the near-duplicates* and the score gap.

> **Honest expectation:** on a small, clean candidate set the two models often agree — a valid result. The listwise advantage grows with more candidates and more overlap. On our 62-doc corpus this is a **mechanics** demo; the payoff is real at production scale.

**Decision matrix** — when to choose pointwise vs listwise (and *why not* each), then the separate question of when to add a reranker *at all*.

**Production path** — the `text_similarity_reranker` retriever does recall → precision in a single `_search`. Swap `inference_id` between v2 and v3 with one line.

***

## The takeaway

Reranking is the **precision layer** on top of the retriever you built all workshop. It's a tool you reach for when the order at the very top has to be right — like the top-K feeding an agent. Start with pointwise; reach for listwise when you see near-duplicate or ambiguous candidates fighting for the top slots.

When you've finished the notebook, that's the workshop. Thanks for staying.
