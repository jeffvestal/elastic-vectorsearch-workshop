---
slug: vector-search
id: lospxxdgg76r
type: challenge
title: 'Lab 1 — Vector Search: The Thing Everyone Reaches For'
teaser: Run your first semantic queries. Learn how Jina v5 via EIS generates embeddings
  server-side — no client embedding code needed.
tabs:
- id: bn0o5ijt9rls
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
- id: lab1-notebook-tab
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /
  port: 8888
difficulty: basic
timelimit: 1800
enhanced_loading: null
---
# Lab 1 — Vector Search: The Thing Everyone Reaches For

**Goal:** Run semantic queries against a pre-indexed corpus of Elastic docs. See how Jina v5 via EIS embeds your query server-side — no client embedding code required.

***

## Step 1 — Inspect the index mapping

```
GET aiewf-workshop-docs/_mapping
```

Look for:
- `body_semantic.type` = `"semantic_text"`
- `body_semantic.inference_id` — this wires the field to the Jina v5 EIS endpoint

***

## Step 2 — Inspect the EIS inference endpoint

```
GET _inference
```

Find the Jina embedding endpoint. Notice `service: "elastic"` — this is EIS infrastructure, not an external API call.

***

## Step 3 — Run a semantic query

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "securing cluster traffic"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

The word **"TLS"** doesn't appear in the query — but the top result should be the TLS cluster communications page. That's semantic matching.

***

## Step 4 — Try more queries

Swap the `"query"` string and re-run:

- `"how do I back up my cluster data"` → should return snapshot/restore docs
- `"users can't connect to Kibana"` → should return Kibana network/access docs
- Your own question about Elasticsearch

***

## Key Concept

When you run a `semantic` query:
1. ES sends your query text to EIS
2. EIS runs Jina v5 → returns a dense vector
3. ES runs approximate nearest-neighbor search over `body_semantic`
4. Returns semantically similar docs — no vocabulary matching needed

**Next lab:** we'll find queries where this breaks.

***

## Go deeper — Python Notebook

Open the **Python Notebook** tab and run `lab1-vector-search.ipynb` to:
- Inspect the mapping and live inference endpoint in Python
- See the ANN/HNSW mechanism explained step by step
- Look inside a stored document to see how `semantic_text` chunks and embeds automatically