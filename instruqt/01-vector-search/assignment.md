---
slug: vector-search
id: aiewf2026-lab1
type: challenge
title: "Lab 1 — Vector Search: The Thing Everyone Reaches For"
teaser: Run your first semantic queries and feel the magic — then find out exactly how the embedding is generated without any client-side code.
tabs:
- id: kibana-console
  title: Kibana Dev Console
  type: service
  hostname: serverless
  path: /app/dev_tools#/console
  port: 443
difficulty: basic
timelimit: 1800
---

# Lab 1 — Vector Search: The Thing Everyone Reaches For

**Time budget: ~25 minutes**

---

## What You're Building

By the end of this lab you will:
- Understand how `semantic_text` works — and who actually generates the embedding
- Run natural-language semantic queries that return semantically relevant docs
- Feel the magic: ask "securing cluster traffic" and get the TLS page even though "TLS" isn't in your query

---

## Step 1 — Inspect the Index Mapping

Open the **Kibana Dev Console** tab and run:

```
GET aiewf-workshop-docs/_mapping
```

Find the `body_semantic` field. It looks like this:

```json
"body_semantic": {
  "type": "semantic_text",
  "inference_id": ".jina-embeddings-v5-text-small"
}
```

**Key observation:** there is no `dims`, no `model_path`, no client config. You declare a field type and point it at an inference endpoint. Elasticsearch does the rest.

The `inference_id` `.jina-embeddings-v5-text-small` is an **Elastic Inference Service (EIS)** endpoint. EIS runs Jina v5 text embedding server-side — fully managed, no separate model hosting.

---

## Step 2 — See the Inference Endpoint

Run this to confirm EIS is real infrastructure, not hand-waving:

```
GET _inference/text_embedding/.jina-embeddings-v5-text-small
```

You'll see the model configuration: service `elastic`, task type `text_embedding`, the model id, and rate limits. This is the endpoint your `semantic_text` field calls automatically.

---

## Teaching Beat: How Does the Embedding Get Generated?

This is the question that trips up most engineers building their first semantic search system:

> "OK, I have a semantic_text field — but who embeds my query text before the ANN search?"

The naive answer: "I'll add a preprocessing step, call an embedding API, get a vector, then pass it to ES." That's an extra service, extra latency, extra infra to manage.

The Elastic answer: **you don't have to**. When you run a `semantic` query, ES sends your query text to EIS → Jina v5 embeds it → ANN search runs. Your query is plain text. No client-side embedding code, no model hosting.

This is what the `semantic_text` field type does at **both** times:
- **Index time:** when you index a doc, ES sends the `body` text to EIS → embeds it → stores the vector
- **Query time:** when you run a `semantic` query, ES sends your query text to EIS → embeds it → ANN search

---

## Step 3 — A Note on Retriever Syntax

Before we run queries, a terminology clarification:

**There is no top-level `semantic` retriever.** Semantic search works as:

```json
{
  "retriever": {
    "standard": {             ← standard retriever wraps the query
      "query": {
        "semantic": {         ← semantic is a QUERY TYPE, not a retriever type
          "field": "body_semantic",
          "query": "your question here"
        }
      }
    }
  }
}
```

You'll see this `standard` wrapping `semantic` shape throughout Labs 1–3. It's intentional — it composes cleanly with `rrf` and `linear` retrievers in Labs 2–3.

---

## Step 4 — Run Your First Semantic Query

Copy the query from the **queries.md** tab and run it in Dev Console:

**Query 1:** "securing cluster traffic"

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
  "_source": ["id", "title", "url", "trap_type"]
}
```

Look at the top result. The query never said "TLS", "SSL", or "certificate" — but the top result should be the TLS/SSL setup page. That's semantic matching: "securing cluster traffic" ≈ "TLS encryption for cluster communications" in the embedding space.

---

## Step 5 — Two More Semantic Wins

Run these queries from queries.md:

**Query 2:** "how do I back up my cluster data"
- Expected: snapshot and restore documentation

**Query 3:** "users can't connect to Kibana"
- Expected: Kibana network/proxy configuration

Both queries use natural language that doesn't appear verbatim in the docs. Vector search matches **intent**, not keywords.

---

## End State

You should feel: "Vector search is amazing. Why would I ever use keyword search again?"

That's the right reaction. **Hold onto it — Lab 2 is about to break it.**

---

## What's Happening Under the Hood (Summary)

```
Your query text
    → ES receives it
    → ES sends text to EIS
    → EIS runs Jina v5 text embedding
    → Returns a vector (~512-dim dense vector)
    → ES runs ANN (approximate nearest neighbor) search
    → Returns docs with semantically similar vectors
```

No Python embedding code. No model server. No preprocessing pipeline. Just a `semantic` query.

**Next: Lab 2 — Where Vector Breaks**
