# Lab 1 — Semantic Search: How Vector Search Actually Works

**Thesis:** You can run state-of-the-art semantic search — finding documents by *meaning*, not just matching keywords — without writing a single line of embedding code. Elasticsearch handles it server-side through the Elastic Inference Service.

## What you'll learn
- How `semantic_text` fields work and why you write zero embedding code
- The 4-step query mechanism: ES → Elastic Inference Service (EIS) → Jina v5 → ANN
- Why semantic search finds concepts your users never explicitly typed
- How ES chunks and stores document embeddings, and why that matters

## Before you start
This notebook reads credentials from environment variables:  
- **In Instruqt:** `ES_ENDPOINT` and `ES_API_KEY` are pre-configured — just run the cells.  
- **Re-running from the repo:** `export ES_ENDPOINT=https://...` and `export ES_API_KEY=...`


```python
# --- Workshop helpers ---
# Defined inline so this notebook is self-contained and runs from the repo too.

import os, json, time
import requests
from elasticsearch import Elasticsearch

INDEX = "aiewf-workshop-docs"

ES_ENDPOINT = os.environ.get("ES_ENDPOINT")
ES_API_KEY  = os.environ.get("ES_API_KEY")
if not ES_ENDPOINT or not ES_API_KEY:
    raise ValueError(
        "Set ES_ENDPOINT and ES_API_KEY.\n"
        "  In Instruqt: pre-configured in the sandbox.\n"
        "  Re-running the repo: export ES_ENDPOINT=https://...  export ES_API_KEY=..."
    )

es = Elasticsearch(ES_ENDPOINT, api_key=ES_API_KEY, request_timeout=60)

def show_hits(resp, fields=("id", "title", "summary"), score=True):
    """Pretty-print search hits as a ranked table."""
    hits = resp["hits"]["hits"]
    if not hits:
        print("  (no hits)"); return
    for rank, h in enumerate(hits, 1):
        src = h.get("_source", {})
        cols = "  ".join(str(src.get(f, "")) for f in fields)
        s = f"  {h['_score']:.4f}" if score and h.get("_score") is not None else ""
        print(f"  #{rank:<2}{s}  {cols}")

# Retriever builders — same query string, different strategy
def r_semantic(query):
    return {"standard": {"query": {"semantic": {"field": "body_semantic", "query": query}}}}

def r_bm25(query):
    return {"standard": {"query": {"multi_match": {
        "query": query, "fields": ["title^3", "body"], "type": "best_fields"}}}}

def r_rrf(query, rank_constant=60, rank_window_size=100):
    return {"rrf": {"retrievers": [r_bm25(query), r_semantic(query)],
                    "rank_constant": rank_constant, "rank_window_size": rank_window_size}}

def search(retriever, size=5, source=("id","title","summary","version_tags")):
    return es.search(index=INDEX, retriever=retriever, size=size, source=list(source))

print("✓ Helpers loaded")
```

    ✓ Helpers loaded



```python
# Sanity check: confirm we're connected and the corpus is indexed.
info = es.info()
print(f"Connected to Elasticsearch {info['version']['number']}")

count = es.count(index=INDEX)["count"]
print(f"Index '{INDEX}': {count} documents indexed")

if count == 0:
    print("\n⚠ No documents found — ingest may still be running. Wait 30s and retry.")
```

    Connected to Elasticsearch 9.5.0
    Index 'aiewf-workshop-docs': 62 documents indexed


## What does a `semantic_text` field look like in practice?

The corpus has a field called `body_semantic` that was mapped as `semantic_text`. Let's look at the actual mapping to understand what Elasticsearch stores.

Pay attention to:
- `type: semantic_text` — the field type that enables all of this
- `inference_id` — notice it's **auto-assigned** (`.jina-embeddings-v5-text-small`). You didn't set it; Elastic Serverless provisioned it for you.
- The nested `.embedding` sub-field — that's where the vectors live (we'll inspect it in a moment)


```python
# Fetch the index mapping and focus on the semantic_text field.
mapping = es.indices.get_mapping(index=INDEX)
props = mapping[INDEX]["mappings"]["properties"]

print("=== body_semantic field mapping ===")
print(json.dumps(props.get("body_semantic", {}), indent=2))

print("\n=== all field types ===")
for field, defn in props.items():
    ftype = defn.get("type", "object")
    print(f"  {field:<20} {ftype}")
```

    === body_semantic field mapping ===
    {
      "type": "semantic_text",
      "inference_id": ".jina-embeddings-v5-text-small",
      "model_settings": {
        "service": "elastic",
        "task_type": "text_embedding",
        "dimensions": 1024,
        "similarity": "cosine",
        "element_type": "float"
      }
    }
    
    === all field types ===
      body                 text
      body_semantic        semantic_text
      id                   keyword
      product              keyword
      summary              text
      title                text
      trap_type            keyword
      url                  keyword
      version_tags         keyword



```python
# The mapping pointed us at the embedding endpoint: .jina-embeddings-v5-text-small
# Fetch its config directly to see the model, dimensions, similarity, and chunking settings.
EMBEDDING_ENDPOINT = ".jina-embeddings-v5-text-small"

ep = es.inference.get(inference_id=EMBEDDING_ENDPOINT)
print(json.dumps(ep.body, indent=2))
```

    {
      "endpoints": [
        {
          "inference_id": ".jina-embeddings-v5-text-small",
          "task_type": "text_embedding",
          "service": "elastic",
          "service_settings": {
            "model_id": "jina-embeddings-v5-text-small",
            "similarity": "cosine",
            "dimensions": 1024
          },
          "chunking_settings": {
            "strategy": "sentence",
            "max_chunk_size": 250,
            "sentence_overlap": 1
          },
          "metadata": {
            "heuristics": {
              "properties": [
                "matryoshka",
                "multilingual",
                "open-weights"
              ],
              "status": "ga",
              "release_date": "2026-02-18"
            },
            "display": {
              "name": "Jina Embeddings v5 Text Small",
              "model_creator": "Jina"
            }
          }
        }
      ]
    }



```python
# [Optional] See every inference endpoint this project ships with.
# Elastic Serverless pre-provisions a whole catalog — embeddings, rerankers, and LLMs —
# so you rarely create one yourself. (Call inference.get() with no id to list them all.)
all_eps = es.inference.get()
for ep in all_eps.get("endpoints", []):
    print(f"  {ep.get('inference_id'):<45} task={ep.get('task_type')}")
```

      .anthropic-claude-4.5-haiku-chat_completion   task=chat_completion
      .anthropic-claude-4.5-haiku-completion        task=completion
      .anthropic-claude-4.5-opus-chat_completion    task=chat_completion
      .anthropic-claude-4.5-opus-completion         task=completion
      .anthropic-claude-4.5-sonnet-chat_completion  task=chat_completion
      .anthropic-claude-4.5-sonnet-completion       task=completion
      .anthropic-claude-4.6-opus-chat_completion    task=chat_completion
      .anthropic-claude-4.6-opus-completion         task=completion
      .anthropic-claude-4.6-sonnet-chat_completion  task=chat_completion
      .anthropic-claude-4.6-sonnet-completion       task=completion
      .anthropic-claude-4.7-opus-chat_completion    task=chat_completion
      .anthropic-claude-4.7-opus-completion         task=completion
      .elser-2-elastic                              task=sparse_embedding
      .elser-2-elasticsearch                        task=sparse_embedding
      .google-gemini-2.5-flash-chat_completion      task=chat_completion
      .google-gemini-2.5-flash-completion           task=completion
      .google-gemini-2.5-flash-lite-chat_completion task=chat_completion
      .google-gemini-2.5-flash-lite-completion      task=completion
      .google-gemini-2.5-pro-chat_completion        task=chat_completion
      .google-gemini-2.5-pro-completion             task=completion
      .google-gemini-3.0-flash-chat_completion      task=chat_completion
      .google-gemini-3.0-flash-completion           task=completion
      .google-gemini-3.1-flash-lite-chat_completion task=chat_completion
      .google-gemini-3.1-flash-lite-completion      task=completion
      .google-gemini-3.1-pro-chat_completion        task=chat_completion
      .google-gemini-3.1-pro-completion             task=completion
      .google-gemini-3.5-flash-chat_completion      task=chat_completion
      .google-gemini-3.5-flash-completion           task=completion
      .google-gemini-embedding-001                  task=text_embedding
      .google-gemini-embedding-2                    task=embedding
      .gp-llm-v2-chat_completion                    task=chat_completion
      .gp-llm-v2-completion                         task=completion
      .jina-clip-v2                                 task=embedding
      .jina-embeddings-v3                           task=text_embedding
      .jina-embeddings-v5-omni-nano                 task=embedding
      .jina-embeddings-v5-omni-small                task=embedding
      .jina-embeddings-v5-text-nano                 task=text_embedding
      .jina-embeddings-v5-text-small                task=text_embedding
      .jina-reranker-v2-base-multilingual           task=rerank
      .jina-reranker-v3                             task=rerank
      .microsoft-multilingual-e5-large              task=text_embedding
      .multilingual-e5-small-elasticsearch          task=text_embedding
      .openai-gpt-4.1-chat_completion               task=chat_completion
      .openai-gpt-4.1-completion                    task=completion
      .openai-gpt-4.1-mini-chat_completion          task=chat_completion
      .openai-gpt-4.1-mini-completion               task=completion
      .openai-gpt-5.2-chat_completion               task=chat_completion
      .openai-gpt-5.2-completion                    task=completion
      .openai-gpt-5.4-chat_completion               task=chat_completion
      .openai-gpt-5.4-completion                    task=completion
      .openai-gpt-5.4-mini-chat_completion          task=chat_completion
      .openai-gpt-5.4-mini-completion               task=completion
      .openai-gpt-5.4-nano-chat_completion          task=chat_completion
      .openai-gpt-5.4-nano-completion               task=completion
      .openai-gpt-oss-120b-chat_completion          task=chat_completion
      .openai-gpt-oss-120b-completion               task=completion
      .openai-gpt-oss-20b-chat_completion           task=chat_completion
      .openai-gpt-oss-20b-completion                task=completion
      .openai-text-embedding-3-large                task=text_embedding
      .openai-text-embedding-3-small                task=text_embedding
      .rainbow-sprinkles-elastic                    task=chat_completion
      .rerank-v1-elasticsearch                      task=rerank


## Your first semantic query — note: zero embedding code

Here's the query we're about to run:

```
"securing cluster traffic"
```

The top document is about **TLS / transport-layer encryption**. The document body doesn't contain the phrase "securing cluster traffic" — but it's *semantically about* securing cluster traffic.

We're just calling `r_semantic(query)` and printing results. No client-side embedding. No vector math. No numpy. The `semantic` query type in the retriever DSL handles it all server-side.


```python
query = "securing cluster traffic"
print(f"Query: {query!r}\n")

resp = search(r_semantic(query))
show_hits(resp)

# Print the top hit's body so we can verify it's semantically relevant
top = resp["hits"]["hits"][0]["_source"]
print(f"\nTop hit body preview:")
print(f"  {top.get('body','')[:300]}...")
```

    Query: 'securing cluster traffic'
    
      #1   0.7639  doc-010  TLS encryption for cluster communications  Securing node-to-node cluster communication with TLS certificates.
      #2   0.7261  doc-009  Set up security in self-managed Elasticsearch deployments  How self-managed Elasticsearch auto-configures security and how to set it up manually.
      #3   0.7103  doc-008  Cluster-level shard allocation and routing settings  Cluster shard allocation and routing settings, including cluster.routing.allocation.enable and new_primaries.
      #4   0.7044  doc-032  Elasticsearch cross-cluster search  Cross-cluster search for running federated queries across remote clusters.
      #5   0.6971  doc-038  Elasticsearch security overview  Overview of Elasticsearch security: authentication, authorization, and encryption.
    
    Top hit body preview:
      ...


## What just happened? The 4-step mechanism

```
Your query string
      │
      ▼
  Elasticsearch  ──── sends query text ───►  Elastic Inference Service (EIS)
      │                                              │
      │                                    Jina v5 embedding model
      │                                              │
      │          ◄── 1024-dim float vector ──────────┘
      │
      ▼
  HNSW ANN index  (approximate nearest-neighbour search over stored doc vectors)
      │
      ▼
  Top-K semantically similar documents
```

**ANN / HNSW** — Elasticsearch uses Hierarchical Navigable Small World graphs for approximate nearest-neighbour search. "Approximate" means it trades a tiny accuracy margin for being **orders of magnitude faster** than brute-force cosine similarity over millions of vectors. At this corpus size it's effectively exact; at 10M it's still fast.

**Why this matters:** at index time, when you wrote `body_semantic: doc["body"]`, ES sent the text to EIS, got a vector back, and stored it in the HNSW index — no separate pipeline, no Spark job, no ML framework. At query time, the same thing happens to your query string, and the ANN search runs. You wrote none of this.


```python
# More wow queries — these all find semantically related docs without keyword overlap.

wow_queries = [
    "how do I back up my cluster data",
    "users can't connect to Kibana",
]

for q in wow_queries:
    print(f"\n{'='*60}")
    print(f"QUERY: {q!r}")
    resp = search(r_semantic(q))
    show_hits(resp)
    # Show what the top result is actually about
    if resp["hits"]["hits"]:
        top = resp["hits"]["hits"][0]["_source"]
        print(f"  → top hit: {top.get('title','')}")
```

    
    ============================================================
    QUERY: 'how do I back up my cluster data'
      #1   0.7600  doc-037  Elasticsearch snapshot and restore overview  Snapshots as point-in-time backups of a cluster stored in a repository.
      #2   0.7497  doc-023  Upgrade Elasticsearch  Performing a rolling upgrade of a self-managed Elasticsearch cluster.
      #3   0.7485  doc-021  Red or yellow cluster health status troubleshooting  Diagnosing red or yellow cluster health and finding why shards are unassigned.
      #4   0.7413  doc-025  Troubleshoot snapshot and restore in Elasticsearch  Troubleshooting snapshot and restore failures, including repository access issues.
      #5   0.7406  doc-041  Elasticsearch data tiers  Data tiers (hot/warm/cold/frozen) that balance search speed against storage cost over time.
      → top hit: Elasticsearch snapshot and restore overview
    
    ============================================================
    QUERY: "users can't connect to Kibana"
      #1   0.8230  doc-024  Authentication in Kibana  Configuring authentication mechanisms for logging in to Kibana.
      #2   0.8037  doc-001  SAML authentication troubleshooting  Troubleshooting SAML authentication failures, realm errors, and login problems in Elasticsearch.
      #3   0.7968  doc-003  Diagnose password setup and connection failures  Fixing password setup and SSL/TLS connection errors such as PKIX path building failures.
      #4   0.7795  doc-052  Elasticsearch Kibana Discover and dashboards  Kibana Discover for interactively searching, filtering, and exploring document data.
      #5   0.7706  doc-010  TLS encryption for cluster communications  Securing node-to-node cluster communication with TLS certificates.
      → top hit: Authentication in Kibana


## How chunking works — and what `semantic_text` hides from you

Even with a 32K token context window, you don't always want to embed an entire document as one vector. Here's why: ANN search ranks *chunks*, not whole documents. If a 10,000-word document has one relevant paragraph buried in section 7, you want that paragraph to surface — not the entire document.

**The default `semantic_text` chunking strategy (`sentence`):**
- Size limit: up to ~250 words per chunk (size is measured in words)
- Boundaries: always fall at sentence endings — a chunk is never cut mid-sentence
- Overlap: 1 sentence shared between adjacent chunks for continuity

**Why not always use the maximum context window?**
Bigger chunks = more context per embedding, but also more noise. The relevant signal gets diluted. Smaller chunks = sharper retrieval precision, but you lose context for cross-sentence references. The 250-word default is a practical balance. You can tune `chunking_settings` on the `semantic_text` field if your corpus has different characteristics — but the default works well for documentation-style content.

**What happens at query time?** Your query vector is compared against *all* chunks across *all* documents. The **max similarity** across any chunk becomes the document's score. So a 5-chunk document competes fairly with a 1-chunk document.

Let's look inside a stored document to see the chunks:



```python
# Fetch doc-010 directly and inspect its stored semantic chunks.
# doc-010 is the TLS cluster communications doc — a good length to inspect.
doc = es.get(index=INDEX, id="doc-010")
src = doc["_source"]

print(f"Document: {src.get('id')} — {src.get('title')}")
print(f"Body length: {len(src.get('body',''))} chars")

# The embedding data lives in body_semantic
sem = src.get("body_semantic", {})
if isinstance(sem, dict):
    chunks = sem.get("chunks", [])
    print(f"\nStored as {len(chunks)} semantic chunk(s):")
    for i, chunk in enumerate(chunks):
        text = chunk.get("text", "")
        emb  = chunk.get("embeddings", [])
        dims = len(emb) if isinstance(emb, list) else "?"
        print(f"  Chunk {i+1}: {len(text)} chars → {dims}-dim vector")
        print(f"    Preview: {text[:120].strip()}...")
else:
    # Serverless may return the raw text at the top level (model-encoded)
    print(f"body_semantic (raw): {str(sem)[:200]}")
```

    Document: doc-010 — TLS encryption for cluster communications
    Body length: 2371 chars
    body_semantic (raw): This page explains how to secure communications and set up TLS certificates in your Elastic Stack deployments.
    
    For Elastic Cloud Hosted and Elastic Cloud Serverless, communication security is fully m


## Matryoshka dimensions — storage vs. recall trade-off

Jina v5 uses Matryoshka Representation Learning (MRL): the model is trained so that the **first N dimensions of every vector already capture most of the semantic meaning**. Later dimensions add precision, but at rapidly diminishing returns.

This means you can truncate stored vectors to save space with minimal retrieval loss:

| Dimensions | Storage vs. full | Approximate recall retention |
|---|---|---|
| 1024 (default) | 100% | 100% |
| 512 | 50% | ~99% |
| 256 | 25% | ~95% |
| 128 | 12.5% | degrades noticeably |

**In practice:** For most RAG use cases, 1024 dims (the default) is fine. At very large scale (hundreds of millions of documents), 512 or 256 dims can cut infrastructure costs significantly with acceptable recall loss. This is configured in the mapping when you create the index — not something you can change post-index without reindexing.

**Also relevant: BBQ (Binary Quantization)**  
At extreme scale (billions of vectors), Elasticsearch supports BBQ — compressing each dimension to 1 bit. 96% storage reduction, ~95% recall. Requires specific Elasticsearch versions. Mentioned here as a "when you hit scale" tool, not something you'll configure today.


## One more the model can do: late chunking

The chunking you just inspected is *fixed-size* — each chunk is embedded on its own, with no knowledge of the rest of the document. Jina v5 also supports **late chunking**: it runs the *entire document* through the model first (up to its 32K-token context) to produce token-level vectors that carry full-document context, and only *then* pools those tokens into chunk vectors. The payoff is cross-paragraph coherence — a chunk that says "it crashed" still encodes that "it" = the cluster introduced three paragraphs earlier.

**It's a property of the model, not something you can switch on here.** Late chunking is available today through the Jina API directly, and it's on the roadmap for the Elastic Inference Service — but the EIS-managed `.jina-embeddings-v5-text-small` endpoint doesn't expose the toggle yet. Worth knowing it exists; for documentation-style corpora the default sentence chunking you saw above works well.

## Summary — and a question

You just ran semantic search that:
- Finds documents by **concept**, not keyword overlap
- Uses a **production-grade embedding model** (Jina v5, 1024 dims) managed by Elastic
- Handles **chunking, embedding, and ANN indexing** automatically
- Requires **zero ML infrastructure** from you — just `semantic_text` in the mapping

---

**The setup question for Lab 2:**

> If semantic search is this good at understanding meaning, why would you ever need old-fashioned keyword (BM25) search?

Try this in the **Dev Console** (or here):

```python
show_hits(search(r_semantic("exit code 137")))
```

Does the result look right? What doc should be #1 for that query? Lab 2 will show you exactly why semantic search fails here — and why you need both.

---
*Continue in Dev Console → Lab 2 assignment, or open `lab2-where-vector-breaks.ipynb`*
