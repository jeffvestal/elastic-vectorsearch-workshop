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
- id: usnn10csmtyf
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /notebooks/lab1-vector-search.ipynb
  port: 8888
difficulty: basic
timelimit: 1800
enhanced_loading: null
---
# Lab 1 — Vector Search: The Thing Everyone Reaches For

**Goal:** Run semantic queries against a pre-indexed corpus of Elastic docs. See how Jina v5 via EIS embeds your query server-side — no client embedding code required.


Part 1 — Dev Console
===
 > [!NOTE]
> **How to run queries:** Copy each code block below into the **Elastic Cloud Serverless** tab (the Dev Console). Click the green ▶ play button or press **Ctrl+Enter** to execute.

***

## Step 1 — Inspect the index mapping

Copy this into the Dev Console and run it:

```
GET aiewf-workshop-docs/_mapping
```

In the response, look for the `body_semantic` field. You'll see:
- `"type": "semantic_text"` — this is not a regular text field
- `"inference_id"` — this tells Elasticsearch which embedding model to use automatically

**Why this matters:** You don't write any embedding code. Elasticsearch handles the "text → vector" conversion for every document at index time and every query at search time.

***

## Step 2 — Inspect the inference endpoint

```
GET _inference
```

Look for the Jina v5 endpoint in the response. Notice `"service": "elastic"` — this is the Elastic Inference Service (EIS), running inside your Elasticsearch cluster. There's no external API call, no API key to manage for embeddings.

**Why this matters:** EIS means embeddings are co-located with search. Your query text stays inside the cluster.

***

## Step 3 — Run your first semantic query

Copy this into the Dev Console and run it:

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
  "_source": ["id", "title", "summary"]
}
```

**What you should see:** The top result should be a TLS / cluster communications page — even though the query says "securing cluster traffic" and never uses the word **"TLS"**.

**Why this works:** The query text goes to EIS → Jina v5 converts it to a dense vector → Elasticsearch finds documents whose stored vectors are closest in meaning. "Securing cluster traffic" and "TLS encryption" land near each other in vector space because they describe the same concept.

***

## Step 4 — Try more queries

Change the `"query"` value in the code above and run it again. Try:

- `"how do I back up my cluster data"` — look for snapshot/restore docs in the results
- `"users can't connect to Kibana"` — look for Kibana network/access docs
- Any question you'd actually ask about Elasticsearch

Each time, notice that the query uses everyday language but the matching docs use technical terms. That's semantic search working.

***

## Key Concept: What happens under the hood

When you run a `semantic` query, four things happen in order:

1. Elasticsearch sends your query text to EIS
2. EIS runs Jina v5 and returns a dense vector (a list of ~500 numbers)
3. Elasticsearch runs approximate nearest-neighbor (ANN) search over all stored document vectors
4. The closest matching document vectors become your results — no vocabulary matching required

**This is fast because ANN is approximate** — it doesn't compare your query vector to every document, it navigates a graph (HNSW) to find near-matches in milliseconds.

***


Part 2 — Python Notebook
===

## Setup:
1. Switch to the [button label="Python Notebook"](tab-1)
2. Oopen `lab1-vector-search.ipynb`

## Run the cells in order.

The notebook goes deeper on everything you just ran:

- Inspect the mapping and inference endpoint in Python — see the model config including context window and chunking settings
- Understand the ANN/HNSW mechanism step by step
- Look inside a stored document to see exactly how `semantic_text` chunked and embedded the body
- Learn why chunking strategy matters and how Jina v5's late chunking keeps cross-paragraph context coherent
- See the Matryoshka dimension trade-off: same model, smaller vectors, 95% of the retrieval quality

When you've finished the notebook, **click Next** to move to Lab 2.
