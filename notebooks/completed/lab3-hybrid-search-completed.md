# Lab 3 — Hybrid Search: RRF, Linear Combination, Filtering, and Reranking

**Thesis:** Fusing BM25 and semantic rankings into a single hybrid retriever wins on *all* the query types that break each individual approach. And you can measure that win objectively, not just by eyeballing.

## What you'll learn
- How RRF (Reciprocal Rank Fusion) combines ranked lists without score normalization
- How to measure retrieval quality objectively with a Recall@K loop
- How metadata filters scope hybrid retrieval (version-specific, product-specific queries)
- How linear combination with MinMax normalization works — and when to use it instead of RRF
- How cross-encoder reranking adds a precision stage after the recall stage
- The decision framework: which retriever for which query type

## Before you start
- **In Instruqt:** credentials are pre-configured.
- **Re-running from the repo:** `export ES_ENDPOINT=https://...` and `export ES_API_KEY=...`


```python
# --- Workshop helpers (inline — same block across all 4 notebooks) ---

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

def r_semantic(query):
    return {"standard": {"query": {"semantic": {"field": "body_semantic", "query": query}}}}

def r_bm25(query):
    return {"standard": {"query": {"multi_match": {
        "query": query, "fields": ["title^3", "body"], "type": "best_fields"}}}}

def r_rrf(query, rank_constant=60, rank_window_size=100):
    return {"rrf": {"retrievers": [r_bm25(query), r_semantic(query)],
                    "rank_constant": rank_constant, "rank_window_size": rank_window_size}}

def r_linear(query, w_bm25=0.5, w_sem=0.5):
    return {"linear": {"retrievers": [
        {"retriever": r_bm25(query), "weight": w_bm25},
        {"retriever": r_semantic(query), "weight": w_sem}],
        "normalizer": "minmax", "rank_window_size": 100}}

def search(retriever, size=5, source=("id","title","summary","version_tags")):
    return es.search(index=INDEX, retriever=retriever, size=size, source=list(source))

print("✓ Helpers loaded")
```

    ✓ Helpers loaded



```python
info = es.info()
count = es.count(index=INDEX)["count"]
print(f"Connected to ES {info['version']['number']} | {count} docs in '{INDEX}'")
```

    Connected to ES 9.5.0 | 62 docs in 'aiewf-workshop-docs'


## RRF — Reciprocal Rank Fusion

RRF doesn't combine *scores*. It combines *ranks*. For each document, in each sub-retriever's result list, it computes:

```
contribution = 1 / (rank_constant + rank)
```

And sums the contributions across all sub-retrievers. A document that is #1 in BM25 *and* #1 in semantic gets a very high fused score. A document that only appears in one list at rank 20 contributes little.

**Why rank-based instead of score-based?**  
BM25 scores and semantic similarity scores are on completely different scales. BM25 scores are unbounded (depends on document length and corpus IDF); semantic scores are bounded cosine similarities. You can't add `12.7 + 0.84` and expect the result to mean anything. RRF sidesteps this entirely by only using rank position — no normalization required.

**Why RRF is so robust here:** in Lab 2 each retriever failed on a *different* query — and crucially, the retriever that failed usually still ranked the right doc somewhere in its top few, while the *other* retriever ranked it #1. RRF only needs one strong vote. A doc that's #1 in one arm and #2–5 in the other fuses to the top. It doesn't need both arms to agree — it needs at least one to be confident.

**RRF's tradeoff: it flattens confidence.**  
RRF only knows *where* a document ranked — not *how confident* the retriever was. If your semantic model is 99% confident in a match (similarity 0.98) and BM25 has a weak keyword hit, RRF treats both as "Rank 1" with equal weight. You lose the signal that one sub-retriever was far more certain than the other. For most use cases, this is fine — robustness over precision. But when you need to express "I trust the semantic signal more for this query type," you need the Linear retriever instead.

Let's replay Lab 2's failures through RRF and watch each target reach #1:


```python
# In Lab 2, each retriever failed on a different query. Watch RRF rescue all of them.

# Semantic blurred this exact identifier (target doc-008 fell to #2); BM25 pinned it.
print("HYBRID (RRF): 'new_primaries'  → want doc-008")
show_hits(search(r_rrf("new_primaries")))

# BM25 ranked the WRONG doc #1 here (boosted 'breaking changes' title); semantic understood intent.
print("\nHYBRID (RRF): '8.18 breaking changes'  → want doc-057")
show_hits(search(r_rrf("8.18 breaking changes"), source=("id", "title", "version_tags")))

# BM25 buried this paraphrase at #5; semantic found it on meaning.
print("\nHYBRID (RRF): 'notify me when something goes wrong'  → want doc-049")
show_hits(search(r_rrf("notify me when something goes wrong")))
```

    HYBRID (RRF): 'new_primaries'  → want doc-008
      #1   0.0325  doc-008  Cluster-level shard allocation and routing settings  Cluster shard allocation and routing settings, including cluster.routing.allocation.enable and new_primaries.
      #2   0.0164  doc-021  Red or yellow cluster health status troubleshooting  Diagnosing red or yellow cluster health and finding why shards are unassigned.
      #3   0.0159  doc-047  Elasticsearch index templates  Composable index templates that auto-apply settings, mappings, and aliases to new indices.
      #4   0.0156  doc-045  Elasticsearch aliases  Index aliases: secondary names that let you swap backing indices without app changes.
      #5   0.0154  doc-023  Upgrade Elasticsearch  Performing a rolling upgrade of a self-managed Elasticsearch cluster.
    
    HYBRID (RRF): '8.18 breaking changes'  → want doc-057
      #1   0.0325  doc-057  Elasticsearch 8.18 release notes  
      #2   0.0320  doc-006  Elasticsearch breaking changes  
      #3   0.0320  doc-056  Elasticsearch 9.x what's new overview  
      #4   0.0315  doc-058  Elasticsearch 8.15 release notes  
      #5   0.0303  doc-054  Elasticsearch enrich policies  
    
    HYBRID (RRF): 'notify me when something goes wrong'  → want doc-049
      #1   0.0318  doc-049  Elasticsearch Watcher alerting  Watcher, Elasticsearch's built-in alerting system: triggers, conditions, and actions that fire on data thresholds.
      #2   0.0308  doc-025  Troubleshoot snapshot and restore in Elasticsearch  Troubleshooting snapshot and restore failures, including repository access issues.
      #3   0.0307  doc-061  Container exit codes when a process is killed (OOM and signals)  What container exit codes mean when a process is killed by a signal or the out-of-memory killer.
      #4   0.0295  doc-019  Ingest pipelines in Elasticsearch  Building ingest pipelines from processors to transform and enrich documents before indexing.
      #5   0.0292  doc-042  Elasticsearch circuit breaker settings  Circuit breaker settings that fail requests before they exhaust JVM heap.


## Prove the win objectively — rank of the known-good doc

Eyeballing three queries is not a proof. Let's define a small **judgment set** — the trap queries from Lab 2 where we know the correct document — and report **the rank of that document** under BM25, semantic, and RRF.

Why rank and not Recall@5? In a 62-doc corpus, a "losing" retriever often still squeaks the right doc into the top 5, so Recall@5 is `1.0` almost everywhere and hides the story. **Rank** shows what actually happens: which retriever mis-orders the target, and whether fusion pulls it back to the top. Lower is better; `1` is perfect.

> **Note:** The native `_rank_eval` API only accepts `query` bodies (not `retriever` bodies), so it can't score an RRF retriever. This manual Python loop is the correct way to evaluate hybrid retrievers.


```python
# Judgment set: (query, known-good document ID, which retriever failed it in Lab 2)
JUDGMENTS = [
    ("exit code 137",                       "doc-007", "exact id — semantic blurs"),
    ("new_primaries",                       "doc-008", "bare value — semantic wrong doc"),
    ("8.18 breaking changes",               "doc-057", "version — BM25 wrong doc"),
    ("notify me when something goes wrong", "doc-049", "paraphrase — BM25 buries"),
]

WINDOW = 60  # search deep enough to see where a "losing" retriever actually placed the doc

strategies = {"BM25": r_bm25, "Semantic": r_semantic, "RRF hybrid": r_rrf}

def rank_of(builder, query, good_id):
    resp = es.search(index=INDEX, retriever=builder(query), size=WINDOW, source=["id"])
    ids = [h["_source"]["id"] for h in resp["hits"]["hits"]]
    return ids.index(good_id) + 1 if good_id in ids else None

# Compute rank of the known-good doc for every (query, strategy)
ranks = {name: [rank_of(b, q, gid) for q, gid, _ in JUDGMENTS] for name, b in strategies.items()}

def fmt(r):
    return "—" if r is None else str(r)

print(f"{'Query':<38} {'BM25':>6} {'Semantic':>9} {'RRF':>6}   target")
print("-" * 78)
for i, (query, good_id, note) in enumerate(JUDGMENTS):
    win = "✅" if ranks["RRF hybrid"][i] == 1 else "  "
    print(f"{query:<38} {fmt(ranks['BM25'][i]):>6} {fmt(ranks['Semantic'][i]):>9} "
          f"{fmt(ranks['RRF hybrid'][i]):>6} {win} {good_id} ({note})")
print("-" * 78)
print("Rank of the correct doc (1 = perfect). Notice RRF = 1 on every row,")
print("even though BM25 or Semantic mis-ranks the target on each one.")
```

    Query                                    BM25  Semantic    RRF   target
    ------------------------------------------------------------------------------
    exit code 137                               1         1      1 ✅ doc-007 (exact id — semantic blurs)
    new_primaries                               1         2      1 ✅ doc-008 (bare value — semantic wrong doc)
    8.18 breaking changes                       2         1      1 ✅ doc-057 (version — BM25 wrong doc)
    notify me when something goes wrong         5         1      1 ✅ doc-049 (paraphrase — BM25 buries)
    ------------------------------------------------------------------------------
    Rank of the correct doc (1 = perfect). Notice RRF = 1 on every row,
    even though BM25 or Semantic mis-ranks the target on each one.


## Filtering — scoping retrieval with metadata

The corpus has `version_tags` and `product` keyword fields specifically for this. Real production indices have dozens of filter axes: tenant ID, department, document classification, date range, language, etc.

When a user asks `"8.18 breaking changes"`, the hybrid retriever returns the best match *across all versions*. But if you know the user is running 8.18, you can **pre-filter** both sub-retrievers to only consider 8.18 docs before fusion.

The key: the filter must go inside **each sub-retriever's `standard.query`** using a `bool.must` + `bool.filter` shape. This ensures both BM25 and semantic arms respect the constraint before their results are fused.

> This is the "filtering" promise in the workshop abstract — ES handles access control and scoping *before* retrieval, which means the LLM can never see documents the filter excluded.


```python
query = "8.18 breaking changes"
version_filter = [{"term": {"version_tags": "8.18"}}]

# Build each sub-retriever with a filter: bool.must wraps the real query, bool.filter adds the term
def r_bm25_filtered(q, filt):
    return {"standard": {"query": {"bool": {
        "must": [{"multi_match": {"query": q, "fields": ["title^3", "body"], "type": "best_fields"}}],
        "filter": filt}}}}

def r_semantic_filtered(q, filt):
    return {"standard": {"query": {"bool": {
        "must": [{"semantic": {"field": "body_semantic", "query": q}}],
        "filter": filt}}}}

r_hybrid_filtered = {"rrf": {
    "retrievers": [
        r_bm25_filtered(query, version_filter),
        r_semantic_filtered(query, version_filter),
    ],
    "rank_constant": 60,
    "rank_window_size": 100,
}}

print(f"QUERY: {query!r}  |  FILTER: version_tags = '8.18'\n")
print("Without filter (note doc-006 'breaking changes' and 8.15/9.x docs sneak in):")
show_hits(search(r_rrf(query)), fields=("id", "title", "version_tags"))
print("\nWith filter (version_tags = 8.18 only):")
resp_filtered = es.search(index=INDEX, retriever=r_hybrid_filtered, size=5,
                           source=["id", "title", "version_tags"])
show_hits(resp_filtered, fields=("id", "title", "version_tags"))
```

    QUERY: '8.18 breaking changes'  |  FILTER: version_tags = '8.18'
    
    Without filter (note doc-006 'breaking changes' and 8.15/9.x docs sneak in):
      #1   0.0325  doc-057  Elasticsearch 8.18 release notes  ['8.18']
      #2   0.0320  doc-006  Elasticsearch breaking changes  ['9.0', '9.1', '9.2', '9.4']
      #3   0.0320  doc-056  Elasticsearch 9.x what's new overview  ['9.0', '9.1', '9.2', '9.4']
      #4   0.0315  doc-058  Elasticsearch 8.15 release notes  ['8.15']
      #5   0.0303  doc-054  Elasticsearch enrich policies  ['9.0']
    
    With filter (version_tags = 8.18 only):
      #1   0.0328  doc-057  Elasticsearch 8.18 release notes  ['8.18']


## Why you can't just add BM25 and semantic scores

We said RRF is rank-based to avoid this problem. Let's actually see what the scores look like on the same query:


```python
q = "notify me when something goes wrong"

top_bm25 = es.search(index=INDEX, retriever=r_bm25(q), size=1)["hits"]["hits"]
top_sem  = es.search(index=INDEX, retriever=r_semantic(q), size=1)["hits"]["hits"]

bm25_score = top_bm25[0]["_score"] if top_bm25 else None
sem_score  = top_sem[0]["_score"]  if top_sem  else None

print(f"Query: {q!r}")
print(f"  BM25 top score:     {bm25_score}")
print(f"  Semantic top score: {sem_score}")
if bm25_score and sem_score:
    print(f"  Ratio: BM25/semantic = {bm25_score/sem_score:.1f}x")
    print()
    print("Different scales, different distributions. Naively adding them lets whichever")
    print("retriever happens to produce bigger raw numbers dominate the fused ranking.")
    print("MinMax normalization (linear retriever) rescales both to [0,1]. RRF avoids it entirely.")
```

    Query: 'notify me when something goes wrong'
      BM25 top score:     4.452428
      Semantic top score: 0.7496855
      Ratio: BM25/semantic = 5.9x
    
    Different scales, different distributions. Naively adding them lets whichever
    retriever happens to produce bigger raw numbers dominate the fused ranking.
    MinMax normalization (linear retriever) rescales both to [0,1]. RRF avoids it entirely.


## Linear combination with MinMax normalization

The `linear` retriever normalizes each sub-retriever's scores to [0, 1] using MinMax, then applies your weights:

```
normalized_score = (raw_score - min) / (max - min)   # per sub-retriever
fused_score = w_bm25 × normalized_bm25 + w_sem × normalized_semantic
```

This lets you tune the balance — but tuning cuts both ways. In the cell below:

- On the **paraphrase** query, equal `0.5/0.5` weights let a lexical distractor edge out the right doc; you have to lean **toward semantic** (`0.3/0.7`) to pull `doc-049` to #1.
- On the **`8.18`** query, leaning **toward BM25** (`0.8/0.2`) actually keeps the *wrong* doc at #1 — because BM25 itself is wrong here (it loves the boosted "breaking changes" title). You have to lean toward semantic to fix it.

That's the catch with linear: there's no single weight that's right for every query. **MinMax is also corpus-dependent** — the min/max shift as documents are added or the embedding model changes, so weights need recalibration. RRF needs none; it only uses rank position.

**Rule of thumb:** RRF for robust production defaults; linear only when you have a calibrated, stable workload and you've measured the right weights for *your* query mix.


```python
# Linear lets you TUNE the balance — but the right weights depend on the query.
# Watch how the same query changes winner as we shift weight toward semantic.

q1 = "notify me when something goes wrong"  # paraphrase, target doc-049
print(f"LINEAR weights on {q1!r}  (target doc-049):")
for wb, ws in [(0.5, 0.5), (0.3, 0.7)]:
    print(f"\n  weights BM25={wb} / semantic={ws}:")
    show_hits(search(r_linear(q1, w_bm25=wb, w_sem=ws)), score=True)

q2 = "8.18 breaking changes"  # version, target doc-057; BM25's own #1 is WRONG (doc-006)
print(f"\n\nLINEAR weights on {q2!r}  (target doc-057):")
for wb, ws in [(0.8, 0.2), (0.2, 0.8)]:
    print(f"\n  weights BM25={wb} / semantic={ws}:")
    show_hits(search(r_linear(q2, w_bm25=wb, w_sem=ws)), fields=("id", "title", "version_tags"))
```

    LINEAR weights on 'notify me when something goes wrong'  (target doc-049):
    
      weights BM25=0.5 / semantic=0.5:
      #1   0.7166  doc-061  Container exit codes when a process is killed (OOM and signals)  What container exit codes mean when a process is killed by a signal or the out-of-memory killer.
      #2   0.5866  doc-049  Elasticsearch Watcher alerting  Watcher, Elasticsearch's built-in alerting system: triggers, conditions, and actions that fire on data thresholds.
      #3   0.4494  doc-022  Data streams in Elasticsearch  Data streams: an abstraction over backing indices optimized for append-only time-series data.
      #4   0.4492  doc-002  Troubleshoot authorization errors and role mapping  Diagnosing authorization exceptions and role-mapping problems for authenticated users.
      #5   0.3460  doc-025  Troubleshoot snapshot and restore in Elasticsearch  Troubleshooting snapshot and restore failures, including repository access issues.
    
      weights BM25=0.3 / semantic=0.7:
      #1   0.7519  doc-049  Elasticsearch Watcher alerting  Watcher, Elasticsearch's built-in alerting system: triggers, conditions, and actions that fire on data thresholds.
      #2   0.6033  doc-061  Container exit codes when a process is killed (OOM and signals)  What container exit codes mean when a process is killed by a signal or the out-of-memory killer.
      #3   0.4351  doc-025  Troubleshoot snapshot and restore in Elasticsearch  Troubleshooting snapshot and restore failures, including repository access issues.
      #4   0.3933  doc-042  Elasticsearch circuit breaker settings  Circuit breaker settings that fail requests before they exhaust JVM heap.
      #5   0.3874  doc-019  Ingest pipelines in Elasticsearch  Building ingest pipelines from processors to transform and enrich documents before indexing.
    
    
    LINEAR weights on '8.18 breaking changes'  (target doc-057):
    
      weights BM25=0.8 / semantic=0.2:
      #1   0.9250  doc-006  Elasticsearch breaking changes  ['9.0', '9.1', '9.2', '9.4']
      #2   0.6340  doc-057  Elasticsearch 8.18 release notes  ['8.18']
      #3   0.3688  doc-056  Elasticsearch 9.x what's new overview  ['9.0', '9.1', '9.2', '9.4']
      #4   0.3533  doc-058  Elasticsearch 8.15 release notes  ['8.15']
      #5   0.1416  doc-054  Elasticsearch enrich policies  ['9.0']
    
      weights BM25=0.2 / semantic=0.8:
      #1   0.9085  doc-057  Elasticsearch 8.18 release notes  ['8.18']
      #2   0.6999  doc-006  Elasticsearch breaking changes  ['9.0', '9.1', '9.2', '9.4']
      #3   0.6325  doc-056  Elasticsearch 9.x what's new overview  ['9.0', '9.1', '9.2', '9.4']
      #4   0.5879  doc-058  Elasticsearch 8.15 release notes  ['8.15']
      #5   0.3605  doc-042  Elasticsearch circuit breaker settings  ['9.0']


## Cross-encoder reranking — precision after recall

Both RRF and linear are **bi-encoder** retrievers: they encode the query and documents *independently* and compare the resulting vectors. Fast, scalable, great for recall over millions of documents.

A **cross-encoder** does something different: it takes a (query, document) pair and scores the relevance of *that specific pair jointly* — essentially reading the query and the full document body together and asking "how relevant is this document to this exact query?"

**The trade-off:**
- Cross-encoders are much more accurate (query-document interaction, not just proximity)
- Cross-encoders are much slower (can't pre-compute; must score at query time for every candidate)

**The solution: two-stage retrieval**
1. **Stage 1 (Recall):** fast bi-encoder retriever (RRF, etc.) fetches a larger candidate window (e.g. top 50)
2. **Stage 2 (Precision):** slow cross-encoder reranker re-scores only those 50 candidates and returns the best N

The `text_similarity_reranker` retriever in ES does this in a single query.

> **Reality check on a 62-doc corpus:** reranking shines when stage 1 returns *hundreds* of plausible candidates and you need to reorder the top of that list precisely. On a tiny corpus, RRF already puts the right doc at #1, so the reranker has little room to help — and on some queries it may even shuffle a lexically-similar distractor upward. Treat this cell as a *mechanics* demo (how to wire the two-stage pipeline), not proof that reranking always improves ranking. The payoff is real at production scale.


```python
# Cross-encoder reranking — wraps the RRF retriever with a reranking stage.
#
# Required fields (verified against queries.md):
#   inference_id: ".jina-reranker-v2-base-multilingual"
#   inference_text: <the query string>  ← REQUIRED — the reranker needs the query too
#   field: "body"                       ← field to score against
#   rank_window_size: 50                ← how many candidates the inner retriever fetches
#
# Gating: if this cell errors with 404/400, the reranker endpoint may not be available
# on this provisioned project. Check with: es.inference.get() and look for
# .jina-reranker-v2-base-multilingual. If absent, read the commented explanation below.

RERANKER_ID = ".jina-reranker-v2-base-multilingual"
query = "how do I secure traffic between nodes"   # target doc-010 (TLS for cluster comms)

reranker_retriever = {
    "text_similarity_reranker": {
        "retriever": r_rrf(query),          # inner retriever (recall stage)
        "field": "body",                     # field the reranker scores
        "inference_id": RERANKER_ID,
        "inference_text": query,             # REQUIRED: query text for cross-encoder
        "rank_window_size": 50,              # candidates passed to reranker
    }
}

try:
    print(f"RRF (recall stage): {query!r}")
    show_hits(search(r_rrf(query)))
    resp = es.search(index=INDEX, retriever=reranker_retriever, size=5,
                     source=["id", "title", "trap_type"])
    print(f"\nRERANKED (cross-encoder precision stage): {query!r}")
    show_hits(resp)
    print("\n(scores are now cross-encoder relevance scores, not cosine or tf/idf)")
except Exception as e:
    print(f"⚠ Reranker unavailable: {e}")
    print(f"  To use this, verify that '{RERANKER_ID}' exists in es.inference.get()")
    print("  The RRF hybrid result above is still excellent for production use.")
```

    RRF (recall stage): 'how do I secure traffic between nodes'
      #1   0.0328  doc-010  TLS encryption for cluster communications  Securing node-to-node cluster communication with TLS certificates.
      #2   0.0320  doc-009  Set up security in self-managed Elasticsearch deployments  How self-managed Elasticsearch auto-configures security and how to set it up manually.
      #3   0.0301  doc-023  Upgrade Elasticsearch  Performing a rolling upgrade of a self-managed Elasticsearch cluster.
      #4   0.0299  doc-055  Elasticsearch cluster management best practices  Production best practices for heap sizing, shard sizing, and cluster operation.
      #5   0.0296  doc-008  Cluster-level shard allocation and routing settings  Cluster shard allocation and routing settings, including cluster.routing.allocation.enable and new_primaries.
    
    RERANKED (cross-encoder precision stage): 'how do I secure traffic between nodes'
      #1   1.5588  doc-010  TLS encryption for cluster communications  
      #2   1.2480  doc-009  Set up security in self-managed Elasticsearch deployments  
      #3   1.1895  doc-038  Elasticsearch security overview  
      #4   1.1883  doc-055  Elasticsearch cluster management best practices  
      #5   1.1689  doc-032  Elasticsearch cross-cluster search  
    
    (scores are now cross-encoder relevance scores, not cosine or tf/idf)


## Decision framework — which retriever for which situation?

| Situation | Recommended retriever | Why |
|---|---|---|
| Unknown query mix | **RRF** | No calibration needed; rank-based fusion is robust |
| Mostly natural language / meaning queries | **Semantic** (or RRF) | Embedding model understands paraphrase, concept |
| Mostly exact tokens (codes, keys, IDs) | **BM25** (or RRF) | tf/idf finds exact matches reliably |
| Scoped to a version, tenant, or category | **RRF + filter** | Pre-filter before fusion; DB handles security |
| Calibrated workload, stable corpus | **Linear (MinMax)** | Tune weights to your specific query distribution |
| High-precision, latency-tolerant | **Reranker on top of RRF** | Cross-encoder precision on a small candidate window |
| Real-time ranking / personalization | **Linear with dynamic weights** | Adjust w_bm25/w_sem per user segment |

**The one-line takeaway:** Start with RRF. Add filters when you have metadata scoping needs. Add a reranker when latency budget allows and precision matters more than throughput.

---

### Bonus: RRF `rank_constant` tuning (read-on-your-own)

The `rank_constant` (default: 60) controls how much each sub-retriever's rank position matters:

- `rank_constant = 1`: `1/(1+1) = 0.5` for rank 1; `1/(1+10) = 0.09` for rank 10. **Winner-take-all** — being first in any list dominates.
- `rank_constant = 60`: `1/(60+1) = 0.016` for rank 1; `1/(60+10) = 0.014` for rank 10. **Blended** — ranks 1-20 all contribute almost equally.
- `rank_constant = 100`: Even flatter — good when you want consensus across retrievers, not individual champions.

```python
# Try it:
# q = "notify me when something goes wrong"
# print("k=1 (winner-take-all):")
# show_hits(search(r_rrf(q, rank_constant=1)))
# print("k=100 (fully blended):")
# show_hits(search(r_rrf(q, rank_constant=100)))
```

---
*Continue in Dev Console → Lab 4 assignment, or open `lab4-rag-pipeline.ipynb`*
