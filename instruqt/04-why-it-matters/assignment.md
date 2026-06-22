---
slug: why-it-matters
id: aiewf2026-lab4
type: challenge
title: "Lab 4 — Why It Matters for Agents: Do You Even Need a Model?"
teaser: Wire the Lab 3 hybrid retriever to an LLM synthesis call. Prove that retrieval quality — not model quality — determines answer quality.
tabs:
- id: kibana-console
  title: Kibana Dev Console
  type: service
  hostname: serverless
  path: /app/dev_tools#/console
  port: 443
- id: notebook
  title: Python Notebook
  type: service
  hostname: host-1
  path: /
  port: 8888
  # NOTE: If the notebook tab is not available, this lab runs instructor-driven on screen.
  # See README.md — "Instruqt notebook-tab availability" is a hard pre-event gate.
difficulty: intermediate
timelimit: 1800
---

# Lab 4 — Why It Matters for Agents: Do You Even Need a Model?

**Time budget: ~20 minutes**

---

## The Thesis

Labs 1–3 built a retrieval pipeline. Lab 4 shows why it matters for AI systems — and delivers the workshop's closing argument:

**Most of a RAG pipeline is a database problem, not a model problem.**

---

## The Four-Stage Pipeline

Every RAG / agentic system that retrieves knowledge follows this pipeline:

```
1. Retrieve   →   2. Rank / Filter   →   3. Assemble Context   →   4. Synthesize
```

| Stage | Tool | Cost | Latency |
|---|---|---|---|
| Retrieve | Elasticsearch hybrid retriever | fractions of a cent | ~50ms |
| Rank / Filter | Reranker + document-level security | fractions of a cent | ~100ms |
| Assemble Context | Your application code | compute cost only | ~10ms |
| Synthesize | LLM (one call, good context) | ~$0.001–0.01 | ~1s |

**Observation:** Synthesis is one step out of four, and it's the most expensive. The model earns its tokens by synthesizing — not by compensating for bad retrieval.

---

## Lab 4 is Notebook-Driven

Open the **Python Notebook** tab. The notebook is `lab4.ipynb`. It's pre-loaded with all cells.

If the notebook tab is unavailable: the instructor will drive the notebook on screen. Follow along — the key insights are in the output and the markdown cells.

---

## What's in the Notebook (Walk-Through)

### Cell 1 — Imports and Setup

Install requirements, import `elasticsearch`, `anthropic`. Reads `ES_ENDPOINT` and `ES_API_KEY` from environment.

### Cell 2 — Connect to Elasticsearch

Verifies your connection to the same Serverless project you used in Labs 1–3.

### Cell 3 — The Hybrid Retriever as a Python Function

The Lab 3 RRF retriever implemented as `hybrid_search(query, size=5)`. Calls `es.search()` with the same RRF DSL you built in Dev Console — just Python now.

### Cell 4 — LLM Synthesis Function

A simple `synthesize(context_docs, question)` function. Calls `anthropic.messages.create()` with:
- A system prompt: "You are a helpful Elasticsearch documentation assistant."
- The question
- The retrieved docs as context

Uses `claude-haiku-4-5-20251001` — the cheapest Anthropic model. This is deliberate: the point is that model capability barely matters here. Retrieval quality does.

---

## Cell 5 — Good Context Demo (PRE-BAKED)

**Run this cell. Do not modify it.**

This cell uses a hardcoded query ("user can't log in") and pre-retrieved good context (the top docs from your hybrid retriever, including doc-001). It calls the LLM with that context.

**Expected output:** A clear, accurate answer about SAML authentication troubleshooting, including references to realm configuration, credential validation, and the IdP metadata.

**Why it works:** The retrieval pipeline delivered the right context. The model's only job is to synthesize it into a readable answer. Even a small, cheap model does this well when the context is good.

---

## Cell 6 — Bad Context Demo (PRE-BAKED)

**Run this cell. Do not modify it.**

Same query ("user can't log in"), same model, same prompt. But the context is deliberately wrong — we replaced the retrieved docs with irrelevant docs about ILM lifecycle policies and snapshot configuration.

**Expected output:** A confused, irrelevant answer that mentions lifecycle policies or snapshots instead of authentication. Or the model hedges and says it doesn't have enough information.

**The lesson (read the markdown cell):**

> The model didn't get dumber. The retrieval got worse.

Swap the context, the answer degrades — even with the same model, same prompt, same temperature. The LLM is a synthesis engine. It can only work with what you give it.

---

## Cell 7 — Full Pipeline End-to-End

This cell wires everything together:
1. Takes your query as input
2. Calls `hybrid_search()` to retrieve docs
3. Calls `synthesize()` with the retrieved context
4. Prints the answer with citations

Try it with your own questions about Elasticsearch.

---

## Pre-Run Cells (Talk-Through — Instructor-Driven)

The instructor will run and explain these cells. You don't need to run them yourself.

### Pre-Run: Document-Level Security

The pattern for pre-filtering by user permissions **before** retrieval:

```python
# Add a filter to the hybrid retriever based on the user's allowed products
def hybrid_search_with_security(query, allowed_products):
    return es.search(
        index="aiewf-workshop-docs",
        body={
            "retriever": {
                "rrf": {
                    "retrievers": [
                        {
                            "standard": {
                                "query": {
                                    "bool": {
                                        "must": {"multi_match": {"query": query, "fields": ["title^3", "body"]}},
                                        "filter": {"terms": {"product": allowed_products}}  # security pre-filter
                                    }
                                }
                            }
                        },
                        {
                            "standard": {
                                "query": {
                                    "bool": {
                                        "must": {"semantic": {"field": "body_semantic", "query": query}},
                                        "filter": {"terms": {"product": allowed_products}}
                                    }
                                }
                            }
                        }
                    ],
                    "rank_constant": 60
                }
            },
            "size": 5
        }
    )
```

**The point:** document-level security is a retrieval filter, not a prompt instruction. You never need to say "only use docs the user is allowed to see" in your system prompt. The filter ensures the model never sees forbidden docs.

### Pre-Run: Cost and Latency

A comparison of what each stage costs:

| Stage | Approx cost | Latency |
|---|---|---|
| Hybrid retrieval (ES) | $0.0001–0.001 | 30–100ms |
| Reranking (Jina v2 via EIS) | $0.0001–0.001 | 50–200ms |
| LLM synthesis (Haiku) | $0.001–0.01 | 500–2000ms |

The database does OS-level work — indexed, vectorized, cached — for a fraction of a cent. The LLM synthesizes. This is the Karpathy OS/CPU analogy: the LLM is the CPU; Elasticsearch is the RAM + disk + OS. You don't ask the CPU to do storage.

---

## Optional Stretch — Multi-Hop Agent Loop (Take-Home)

Cell 8 (optional) shows a minimal agent loop that retrieves twice — each hop uses the prior result to refine the next query. Example:

1. Query 1: "authentication failure after upgrading to 9.0"
   → Retrieves: doc about 9.0 breaking changes (authentication APIs changed)
2. Query 2: use the 9.0 breaking change info to form a follow-up: "migrating security realms to 9.0"
   → Retrieves: migration guide

The model decides when to retrieve again. ES does the heavy lifting each hop.

---

## Closing Argument

You built a retrieval pipeline in 3 labs:
1. Vector — semantic magic, but exact tokens fail
2. BM25 + vector contrast — each wins where the other loses
3. Hybrid RRF + linear — production-grade, wins on all query types

Lab 4 showed: plug this pipeline into any agent or RAG system, and retrieval quality determines answer quality. Not model quality. Not prompt engineering. **Retrieval.**

Most of your RAG pipeline is a database problem. You just built the database part.

**Thank you. Questions?**
