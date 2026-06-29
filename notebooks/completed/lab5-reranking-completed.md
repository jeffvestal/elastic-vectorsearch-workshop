# Lab 5 (Bonus) — Reranking: Precision After Recall

**Bonus lab.** Labs 1–3 built a retriever; Lab 4 wired it to an LLM and an agent. This bonus lab adds the one stage we only *gestured* at in Lab 3: a **reranker** — a second-pass model that re-scores your top candidates for precision.

## What you'll learn
- **What reranking is** and why it's a *second stage* on top of retrieval (recall → precision)
- The two architecturally different kinds: **pointwise (cross-encoder)** vs **listwise**
- How to call the **rerank inference API directly** (`POST _inference/rerank/<id>`)
- **Jina Reranker v2 vs v3** head-to-head on the same candidates
- A **decision matrix**: when to use a reranker at all, and pointwise vs listwise
- The production path: the **`text_similarity_reranker`** retriever, in one `_search`

## Before you start
- **In Instruqt:** credentials are pre-configured — just run the cells.
- **Re-running from the repo:** `export ES_ENDPOINT=https://...` and `export ES_API_KEY=...`

> Everything here uses the **same** Elastic Inference Service you've used all workshop — the rerank models are built-in endpoints, no extra setup.


```python
# --- Workshop helpers (inline — same block across all notebooks, plus rerank helpers) ---

import os, json
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

# Reranker endpoints (both built-in on the provisioned project)
POINTWISE_ID = ".jina-reranker-v2-base-multilingual"   # cross-encoder, scores each doc alone
LISTWISE_ID  = ".jina-reranker-v3"                      # listwise, scores the whole set jointly

def r_semantic(query):
    return {"standard": {"query": {"semantic": {"field": "body_semantic", "query": query}}}}

def r_bm25(query):
    return {"standard": {"query": {"multi_match": {
        "query": query, "fields": ["title^3", "body"], "type": "best_fields"}}}}

def r_rrf(query, rank_constant=60, rank_window_size=100):
    return {"rrf": {"retrievers": [r_bm25(query), r_semantic(query)],
                    "rank_constant": rank_constant, "rank_window_size": rank_window_size}}

def get_candidates(query, retriever_builder=r_rrf, size=8):
    """Run a retriever and return flat dicts WITH body text — the input a reranker needs."""
    resp = es.search(index=INDEX, retriever=retriever_builder(query), size=size,
                     source=["id", "title", "trap_type", "body"])
    return [{"id": h["_source"]["id"], "title": h["_source"]["title"],
             "trap_type": h["_source"].get("trap_type"), "body": h["_source"]["body"]}
            for h in resp["hits"]["hits"]]

def docs_by_id(ids):
    """Fetch specific docs by id (used to hand-build a candidate set)."""
    resp = es.mget(index=INDEX, ids=ids, source=["id", "title", "trap_type", "body"])
    return [{"id": d["_source"]["id"], "title": d["_source"]["title"],
             "trap_type": d["_source"].get("trap_type"), "body": d["_source"]["body"]}
            for d in resp["docs"] if d.get("found")]

def rerank(inference_id, query, docs, text_field="body"):
    """Call the EIS rerank endpoint directly (POST _inference/rerank/<id>).
    Returns a NEW list of the same docs, reordered by relevance_score (desc),
    each annotated with a 'rerank_score'. The API returns results pre-sorted."""
    inputs = [d[text_field] for d in docs]
    resp = requests.post(
        f"{ES_ENDPOINT}/_inference/rerank/{inference_id}",
        headers={"Authorization": f"ApiKey {ES_API_KEY}", "Content-Type": "application/json"},
        json={"query": query, "input": inputs},
        timeout=60,
    )
    resp.raise_for_status()
    out = []
    for r in resp.json()["rerank"]:          # [{"index": i, "relevance_score": s}, ...]
        d = dict(docs[r["index"]])
        d["rerank_score"] = r["relevance_score"]
        out.append(d)
    return out

def show_ranked(docs, score_key=None, fields=("id", "title", "trap_type")):
    """Print a ranked list. If score_key is set, show that score column."""
    if not docs:
        print("  (none)"); return
    for rank, d in enumerate(docs, 1):
        cols = "  ".join(str(d.get(f, "") or "") for f in fields)
        s = f"  {d[score_key]:.4f}" if score_key and score_key in d else ""
        print(f"  #{rank:<2}{s}  {cols}")

info = es.info()
count = es.count(index=INDEX)["count"]
print(f"Connected to ES {info['version']['number']} | {count} docs in '{INDEX}'")
print("✓ Helpers loaded (POINTWISE_ID, LISTWISE_ID, rerank(), get_candidates(), docs_by_id())")
```

    Connected to ES 9.5.0 | 62 docs in 'aiewf-workshop-docs'
    ✓ Helpers loaded (POINTWISE_ID, LISTWISE_ID, rerank(), get_candidates(), docs_by_id())


## What reranking *is* — a second stage on top of retrieval

Everything you built in Labs 1–3 is **bi-encoder** retrieval: the model encodes the query and each document *independently* into vectors, and you compare those vectors (cosine similarity / RRF over ranks). That's what makes it fast enough to search millions of documents — every document vector is computed once, ahead of time, at index.

A **reranker** works differently. It reads the **query and a candidate document *together*** and scores how relevant that specific document is to that specific query. Because it sees both at once, it can catch relevance that vector proximity misses — but it can't be precomputed, so it's far too expensive to run over a whole corpus.

So you use it as a **second stage**:

```
            STAGE 1 — RECALL                      STAGE 2 — PRECISION
   ┌─────────────────────────────┐        ┌──────────────────────────────┐
   │  hybrid retriever (RRF)      │        │  reranker reads (query, doc)  │
   │  fast, scans the whole index │  top-N │  pairs and re-scores just     │
   │  → top 50–100 candidates     │ ─────► │  those N → returns best K      │
   └─────────────────────────────┘        └──────────────────────────────┘
        cheap, approximate                     expensive, precise
```

**Stage 1 (recall)** casts a wide, cheap net — get the right documents *somewhere* in the top 50. **Stage 2 (precision)** spends real compute only on those 50 to get the order at the very top exactly right. That top-K is what feeds a RAG prompt or an agent — so its precision is what the user actually feels.

## The two TYPES of reranker — pointwise vs listwise

Not all rerankers work the same way. There are two architectures, and the difference matters:

**Pointwise (cross-encoder) — e.g. Jina Reranker v2**
Scores each candidate **on its own**: one `(query, document)` forward pass per document. Document #3 is scored with no knowledge that document #4 exists. Simple, robust, trivially parallel — this is the classic cross-encoder reranker.

**Listwise — e.g. Jina Reranker v3**
Puts the **whole candidate set into one context window** and scores them **jointly**, so the model can compare documents *against each other* in a single pass ("last but not late" interaction). When two candidates are near-duplicates or overlap heavily, a listwise model can see that and order them sensibly — a pointwise model literally cannot, because it never sees them together. (Jina v3: listwise, GA Oct 2025, ~0.6B params, reranks up to ~64 docs per call.)

| | **Pointwise (cross-encoder, Jina v2)** | **Listwise (Jina v3)** |
|---|---|---|
| Scores each doc… | **independently**, one pair at a time | **jointly**, whole set in one pass |
| Sees other candidates? | ❌ no | ✅ yes (document↔document interaction) |
| Best at | clean, distinct candidates | similar / near-duplicate / overlapping candidates |
| Scales by | per-doc (batchable, no cap) | one bigger call (candidate cap, ~64) |

Elastic exposes **both** as built-in EIS endpoints — you swap a single `inference_id` to switch. We'll run them head-to-head in a moment, then give a full *which-to-choose* matrix once you've seen the difference.


```python
# Confirm both rerank endpoints exist on this project (same inspection skill as Lab 1).
all_eps = es.inference.get()
print("Rerank endpoints available (task_type='rerank'):\n")
for ep in all_eps.get("endpoints", []):
    if ep.get("task_type") == "rerank":
        print(f"  {ep.get('inference_id'):<40} service={ep.get('service')}")

print(f"\nWe'll use:\n  pointwise (v2): {POINTWISE_ID}\n  listwise  (v3): {LISTWISE_ID}")
```

    Rerank endpoints available (task_type='rerank'):
    
      .jina-reranker-v2-base-multilingual      service=elastic
      .jina-reranker-v3                        service=elastic
      .rerank-v1-elasticsearch                 service=elasticsearch
    
    We'll use:
      pointwise (v2): .jina-reranker-v2-base-multilingual
      listwise  (v3): .jina-reranker-v3


## Calling the reranker directly — the rawest form

Before the polished retriever, let's see the actual API a reranker exposes. It's dead simple:

```
POST _inference/rerank/<inference_id>
{
  "query": "encrypt traffic between cluster nodes",
  "input": [ "full text of doc A", "full text of doc B", ... ]
}
```

and it returns the candidates **re-sorted by relevance**, each with a score:

```
{ "rerank": [ {"index": 3, "relevance_score": 0.94},
              {"index": 0, "relevance_score": 0.71}, ... ] }
```

`index` points back into the `input` list you sent. Our `rerank()` helper (loaded above) wraps exactly this call and re-attaches each score to the original document. This is the *same* call the `text_similarity_reranker` retriever makes under the hood — we're just doing it by hand first so there's no magic.

A reranker earns its keep **two** ways, and we'll see both next:

1. **Rescue a weak first stage** — hand it a *BM25-only* candidate list (no embeddings at all) and watch it recover a doc that lexical search buried far down the list. This is the dramatic case.
2. **Sharpen an already-good first stage** — hand it an *RRF hybrid* list and watch it nudge the right doc past a close competitor at the very top. On a small corpus this is a *small* move — but it's the production-shaped one.


```python
# PART A — Rescue a weak first stage.
# Stage 1 is BM25-ONLY (no embeddings). On a paraphrase query, lexical search buries the
# right doc; the reranker reads each candidate *with* the query and pulls it back up.
query = "notify me when something goes wrong"   # target: doc-049 (Watcher alerting)

candidates = get_candidates(query, retriever_builder=r_bm25, size=8)

print(f"QUERY: {query!r}\n")
print("STAGE 1 — BM25-only recall (lexical, no embeddings):")
show_ranked(candidates)
print("  ↑ doc-049 (Watcher) is buried — the query shares almost no literal words with it.")

# Pointwise cross-encoder: reads each (query, doc) pair together — the 'classic' reranker.
# If the climb isn't dramatic, check Stage 1 for other monitoring/alerting docs competing,
# and try swapping POINTWISE_ID -> LISTWISE_ID on the next line.
reranked = rerank(POINTWISE_ID, query, candidates)
print(f"\nSTAGE 2 — after reranking with {POINTWISE_ID}:")
show_ranked(reranked, score_key="rerank_score")

print("\nBM25 ranked on word overlap, so it buried the Watcher doc on pure vocabulary mismatch.")
print("The cross-encoder read each candidate's body *together with the query* and should")
print("promote doc-049 toward the top — recovering relevance a lexical-only stage 1 missed.")
print("Takeaway: a reranker can rescue even a first stage that has no embeddings at all.")
```

    QUERY: 'notify me when something goes wrong'
    
    STAGE 1 — BM25-only recall (lexical, no embeddings):
      #1   doc-061  Container exit codes when a process is killed (OOM and signals)  distractor
      #2   doc-002  Troubleshoot authorization errors and role mapping  paraphrase
      #3   doc-022  Data streams in Elasticsearch  
      #4   doc-056  Elasticsearch 9.x what's new overview  version-specific
      #5   doc-049  Elasticsearch Watcher alerting  
      #6   doc-029  Elasticsearch mapping overview  
      #7   doc-015  Linear retriever  
      #8   doc-025  Troubleshoot snapshot and restore in Elasticsearch  
      ↑ doc-049 (Watcher) is buried — the query shares almost no literal words with it.
    
    STAGE 2 — after reranking with .jina-reranker-v2-base-multilingual:
      #1   0.1461  doc-049  Elasticsearch Watcher alerting  
      #2   0.1330  doc-025  Troubleshoot snapshot and restore in Elasticsearch  
      #3   0.1023  doc-061  Container exit codes when a process is killed (OOM and signals)  distractor
      #4   0.0804  doc-002  Troubleshoot authorization errors and role mapping  paraphrase
      #5   0.0685  doc-056  Elasticsearch 9.x what's new overview  version-specific
      #6   0.0592  doc-029  Elasticsearch mapping overview  
      #7   0.0427  doc-022  Data streams in Elasticsearch  
      #8   0.0373  doc-015  Linear retriever  
    
    BM25 ranked on word overlap, so it buried the Watcher doc on pure vocabulary mismatch.
    The cross-encoder read each candidate's body *together with the query* and should
    promote doc-049 toward the top — recovering relevance a lexical-only stage 1 missed.
    Takeaway: a reranker can rescue even a first stage that has no embeddings at all.


### …and sharpen an already-good first stage

That rescue was dramatic because BM25 alone is a *weak* first stage for a paraphrase. But your real stage 1 is the **RRF hybrid** from Lab 3 — and RRF already nails #1 on almost every query in this corpus (that was the whole Lab 3 win). So where does a reranker help when stage 1 is already good?

On the queries where RRF lands the right doc at **#2** — close, but not first. The reranker, reading each candidate together with the query, can break that near-tie and promote it.

> **Honest expectation:** on our 62-doc corpus this move is *small* — often a single position. That's a feature of the small, clean dataset, not the reranker. In production, where stage 1 hands over hundreds of overlapping candidates, the reordering is much larger. But it **does** move — watch the target climb from #2 to #1.


```python
# PART B — Sharpen an already-good first stage.
# Now stage 1 is the full RRF hybrid (BM25 + semantic). RRF already does well — but on this
# query it lands the right doc at #2, just behind a close competitor. The reranker, reading
# query+doc together, should push it to #1.
query = "cluster.routing.allocation.enable"   # target: doc-008 — RRF ranks it #2
# Alternate RRF-#2 query if the move isn't visible: "reduce storage cost for old logs" -> doc-041
candidates = get_candidates(query, retriever_builder=r_rrf, size=8)

print(f"QUERY: {query!r}\n")
print("STAGE 1 — RRF hybrid recall (already strong — target is #2, not #1):")
show_ranked(candidates)

# Swap POINTWISE_ID -> LISTWISE_ID if the order doesn't change: listwise scores the whole
# set jointly and is likelier to break a close #1/#2 tie.
reranked = rerank(POINTWISE_ID, query, candidates)
print(f"\nSTAGE 2 — after reranking with {POINTWISE_ID}:")
show_ranked(reranked, score_key="rerank_score")

print("\nThe reranker re-scored each candidate against the query and promoted the target.")
print("On a 62-doc corpus the move is small — often just one or two positions. In production,")
print("where stage 1 returns hundreds of overlapping candidates, the reordering is far larger.")
print("The point stands either way: the order at the top is exactly what reranking earns you.")
```

    QUERY: 'cluster.routing.allocation.enable'
    
    STAGE 1 — RRF hybrid recall (already strong — target is #2, not #1):
      #1   doc-023  Upgrade Elasticsearch  
      #2   doc-008  Cluster-level shard allocation and routing settings  exact-token
      #3   doc-021  Red or yellow cluster health status troubleshooting  
      #4   doc-041  Elasticsearch data tiers  
      #5   doc-032  Elasticsearch cross-cluster search  
      #6   doc-020  Node roles in Elasticsearch  
      #7   doc-039  Elasticsearch deployment configuration guide  
      #8   doc-036  Elasticsearch index settings  
    
    STAGE 2 — after reranking with .jina-reranker-v2-base-multilingual:
      #1   0.9173  doc-008  Cluster-level shard allocation and routing settings  exact-token
      #2   0.7564  doc-021  Red or yellow cluster health status troubleshooting  
      #3   0.6234  doc-023  Upgrade Elasticsearch  
      #4   0.3789  doc-036  Elasticsearch index settings  
      #5   0.3320  doc-041  Elasticsearch data tiers  
      #6   0.2337  doc-020  Node roles in Elasticsearch  
      #7   0.2173  doc-032  Elasticsearch cross-cluster search  
      #8   0.1451  doc-039  Elasticsearch deployment configuration guide  
    
    The reranker re-scored each candidate against the query and promoted the target.
    On a 62-doc corpus the move is small — often just one or two positions. In production,
    where stage 1 returns hundreds of overlapping candidates, the reordering is far larger.
    The point stands either way: the order at the top is exactly what reranking earns you.


## Pointwise vs listwise — head to head

Now the part that's hard to see in the abstract: does the **listwise** model actually behave differently from the **pointwise** one? The honest answer is *it depends on the candidates*. The difference shows up when the set contains documents that **overlap** — because that's the only situation where "seeing the other candidates at once" can change a decision.

So we hand both models the **same** set of related authentication docs for the query *"user cannot authenticate"*:
- **doc-001** — *SAML authentication troubleshooting*
- **doc-002** — *Troubleshoot authorization errors and role mapping* (the paraphrase near-miss: it's about *authorization*, not *authentication*)
- **doc-005** — *LDAP user authentication*
- **doc-024** — *Authentication in Kibana*
- **doc-038** — *Elasticsearch security overview*

They overlap heavily — every one is about security/auth. The question is how each reranker orders them, and especially what it does with **doc-002**, the one doc that's really about a *post*-login (authorization) problem.

> **Set expectations honestly:** on some sets the two models agree, and that's a valid result. Here they don't — but note that *both* put doc-001 #1. The signal is **lower in the list**: watch where doc-002 lands under pointwise vs listwise.


```python
# Same query, same candidates — pointwise (v2) vs listwise (v3), side by side.
query = "user cannot authenticate"

# Hand-built set of overlapping auth docs. doc-001 (SAML) and doc-002 (authz/role-mapping)
# are the corpus's paraphrase pair — doc-002 is the one that's really about *authorization*.
candidate_ids = ["doc-001", "doc-002", "doc-005", "doc-024", "doc-038"]
candidates = docs_by_id(candidate_ids)

print(f"QUERY: {query!r}")
print(f"Candidates: {[d['id'] for d in candidates]}  (doc-001/doc-002 are the paraphrase pair)\n")
print("Both models rank doc-001 (SAML auth) #1 — the interesting signal is lower:")
print("watch where doc-002 (authorization / role-mapping) lands in each.\n")

def safe_rerank(label, inference_id):
    try:
        ranked = rerank(inference_id, query, candidates)
        print(f"{label}  ({inference_id}):")
        show_ranked(ranked, score_key="rerank_score")
    except Exception as e:
        print(f"{label}  ({inference_id}): ⚠ unavailable — {str(e)[:120]}")
    print()

safe_rerank("POINTWISE v2", POINTWISE_ID)
safe_rerank("LISTWISE  v3", LISTWISE_ID)

print("Pointwise scored each doc alone, so doc-002 ranks high on its own merits.")
print("Listwise scored the whole set together, and doc-002 drops toward the bottom —")
print("consistent with its focus on *authorization* (post-login role errors), while the")
print("other docs are about *authentication* (the actual login failure). Same candidates,")
print("different orderings: that's the pointwise-vs-listwise difference made visible.")
```

    QUERY: 'user cannot authenticate'
    Candidates: ['doc-001', 'doc-002', 'doc-005', 'doc-024', 'doc-038']  (doc-001/doc-002 are the paraphrase pair)
    
    Both models rank doc-001 (SAML auth) #1 — the interesting signal is lower:
    watch where doc-002 (authorization / role-mapping) lands in each.
    
    POINTWISE v2  (.jina-reranker-v2-base-multilingual):
      #1   0.6142  doc-001  SAML authentication troubleshooting  paraphrase
      #2   0.4407  doc-002  Troubleshoot authorization errors and role mapping  paraphrase
      #3   0.2659  doc-005  LDAP user authentication  exact-token
      #4   0.2379  doc-024  Authentication in Kibana  
      #5   0.2134  doc-038  Elasticsearch security overview  
    
    LISTWISE  v3  (.jina-reranker-v3):
      #1   0.2884  doc-001  SAML authentication troubleshooting  paraphrase
      #2   0.0471  doc-005  LDAP user authentication  exact-token
      #3   0.0189  doc-038  Elasticsearch security overview  
      #4   -0.0209  doc-024  Authentication in Kibana  
      #5   -0.0303  doc-002  Troubleshoot authorization errors and role mapping  paraphrase
    
    Pointwise scored each doc alone, so doc-002 ranks high on its own merits.
    Listwise scored the whole set together, and doc-002 drops toward the bottom —
    consistent with its focus on *authorization* (post-login role errors), while the
    other docs are about *authentication* (the actual login failure). Same candidates,
    different orderings: that's the pointwise-vs-listwise difference made visible.


## Which reranker should you choose — pointwise vs listwise?

Now that you've seen them run, here's how to pick. This is about **pointwise vs listwise**; the next cell covers the separate question of whether to add a reranker *at all*.

| | **Pointwise (cross-encoder, Jina v2)** | **Listwise (Jina v3)** |
|---|---|---|
| **How it scores** | each `(query, doc)` **independently** | the whole candidate set **jointly**, one pass |
| **Choose it when** | candidates are already distinct; you stream/score docs in isolation; you want a stable per-doc score you can cache or threshold | candidates are **similar / near-duplicate / overlapping** and the order *among them* matters; it's the final top-k feeding a RAG prompt or agent |
| **Why *not*** | can't see that two candidates are near-dupes, so it may mis-order them relative to each other | one call must hold the whole set in its context window (cap ~64 docs); the per-doc score isn't independent, so it's harder to cache/threshold |
| **Cost / latency** | scales per document; trivially parallel and batchable | one larger call; bounded candidates per call |
| **Maturity** | the classic, battle-tested cross-encoder | newer (GA 2025-10), SOTA on noisy/ambiguous sets |

**Why choose listwise (v3):** cross-document context lets it resolve ties between near-duplicates that a pointwise model *structurally cannot see*. It tends to win exactly where retrieval is hardest — lots of similar candidates competing for the top slots.

**Why *not* listwise:** if your candidates are already clean and distinct, it's extra capability you don't need; the candidate-window cap and single-call shape are also a worse fit if you want to score documents independently (streaming, caching, per-doc thresholds).

**Why choose pointwise (v2):** simplicity, independence, batchability, and a long track record. A per-doc score you can compute, cache, and threshold in isolation.

**Default guidance:** start with **pointwise**. Reach for **listwise** when you *observe* near-duplicate or ambiguous candidates fighting for the top — which is precisely what you can measure with the judgment-set / MRR harness you built in Lab 3.

## The production path — `text_similarity_reranker` in one query

Calling the rerank API by hand was for understanding. In production you don't fetch candidates, marshal their text, POST them, and re-sort yourself — you let Elasticsearch do the whole **recall → precision** pipeline in a single `_search`:

```
text_similarity_reranker
├── retriever:         <your RRF hybrid>     ← STAGE 1: recall (Lab 3)
├── field:             "body"                 ← which field the reranker reads
├── inference_id:      ".jina-reranker-v3"    ← STAGE 2: which reranker (swap v2/v3 here)
├── inference_text:    "<the query>"          ← the query the reranker scores against
└── rank_window_size:  50                     ← how many candidates stage 1 hands to stage 2
```

It fetches `rank_window_size` candidates from the inner retriever, reranks them with the named endpoint, and returns the reordered top hits — same pattern as the Lab 3 reranker cell, now with a one-line swap between **pointwise** and **listwise**.


```python
# Production recall->precision in a single _search, on TWO queries. Guarded per-query: if the
# endpoint is missing on this project, that query explains rather than crashes (same gating
# style as Lab 3) — and the other query still runs.
RERANKER_ID = LISTWISE_ID                          # swap to POINTWISE_ID to compare

def show_search(resp, fields=("id", "title", "trap_type")):
    for rank, h in enumerate(resp["hits"]["hits"], 1):
        src = h.get("_source", {})
        cols = "  ".join(str(src.get(f, "") or "") for f in fields)
        sc = f"  {h['_score']:.4f}" if h.get("_score") is not None else ""
        print(f"  #{rank:<2}{sc}  {cols}")

def demo(query, note):
    """Run RRF recall vs the production text_similarity_reranker for one query."""
    reranker_retriever = {
        "text_similarity_reranker": {
            "retriever": r_rrf(query),       # STAGE 1: recall (the Lab 3 hybrid retriever)
            "field": "body",                  # field the reranker scores
            "inference_id": RERANKER_ID,      # STAGE 2: which reranker
            "inference_text": query,          # REQUIRED: the query text
            "rank_window_size": 50,           # candidates passed from stage 1 to stage 2
        }
    }
    print(f"### {note}")
    try:
        print(f"STAGE 1 — RRF recall: {query!r}")
        show_search(es.search(index=INDEX, retriever=r_rrf(query), size=5,
                              source=["id", "title", "trap_type"]))
        print(f"\nSTAGE 1+2 — text_similarity_reranker ({RERANKER_ID}):")
        show_search(es.search(index=INDEX, retriever=reranker_retriever, size=5,
                              source=["id", "title", "trap_type"]))
        print("(scores are now cross-encoder/listwise relevance scores, not RRF rank-fusion scores)")
    except Exception as e:
        print(f"⚠ Reranker unavailable: {str(e)[:160]}")
        print(f"  Verify '{RERANKER_ID}' appears in es.inference.get() (task_type='rerank').")
        print("  The RRF result above is still strong on its own.")
    print()

# Watch RRF's #1 vs the reranked #1 in each.
demo("reduce storage cost for old logs",
     "CORRECTION — RRF's #1 is a JVM/memory doc, wrong for a storage question; "
     "the reranker promotes the data-tiers doc to #1")
demo("cluster.routing.allocation.enable",
     "SHARPENING — doc-008 was tied at #2 under RRF; the reranker makes it a decisive #1")
```

    ### CORRECTION — RRF's #1 is a JVM/memory doc, wrong for a storage question; the reranker promotes the data-tiers doc to #1
    STAGE 1 — RRF recall: 'reduce storage cost for old logs'
      #1   0.0320  doc-007  JVM settings for Elasticsearch  exact-token
      #2   0.0318  doc-041  Elasticsearch data tiers  
      #3   0.0313  doc-017  Index lifecycle management overview  
      #4   0.0304  doc-053  Elasticsearch vector storage optimization  
      #5   0.0294  doc-037  Elasticsearch snapshot and restore overview  
    
    STAGE 1+2 — text_similarity_reranker (.jina-reranker-v3):
      #1   1.2866  doc-041  Elasticsearch data tiers  
      #2   1.2386  doc-018  Create an ILM policy in Elasticsearch  
      #3   1.2378  doc-017  Index lifecycle management overview  
      #4   1.1690  doc-037  Elasticsearch snapshot and restore overview  
      #5   1.1002  doc-020  Node roles in Elasticsearch  
    (scores are now cross-encoder/listwise relevance scores, not RRF rank-fusion scores)
    
    ### SHARPENING — doc-008 was tied at #2 under RRF; the reranker makes it a decisive #1
    STAGE 1 — RRF recall: 'cluster.routing.allocation.enable'
      #1   0.0325  doc-023  Upgrade Elasticsearch  
      #2   0.0325  doc-008  Cluster-level shard allocation and routing settings  exact-token
      #3   0.0317  doc-021  Red or yellow cluster health status troubleshooting  
      #4   0.0156  doc-041  Elasticsearch data tiers  
      #5   0.0154  doc-032  Elasticsearch cross-cluster search  
    
    STAGE 1+2 — text_similarity_reranker (.jina-reranker-v3):
      #1   1.6590  doc-008  Cluster-level shard allocation and routing settings  exact-token
      #2   1.3083  doc-023  Upgrade Elasticsearch  
      #3   1.2369  doc-021  Red or yellow cluster health status troubleshooting  
      #4   1.0481  doc-034  Keyword field type in Elasticsearch  
      #5   1.0461  doc-036  Elasticsearch index settings  
    (scores are now cross-encoder/listwise relevance scores, not RRF rank-fusion scores)
    


## When to add a reranker *at all* — and when to skip it

Choosing pointwise vs listwise (above) only matters *if* you add a reranker. Here's whether to:

**Add a reranker when:**
- You have a **latency budget** for a second pass and **precision matters more than raw throughput**.
- Stage 1 returns **many plausible candidates** and the exact order of the top few matters.
- It's the **final top-k feeding a RAG prompt or an agent** — where a wrong #1 becomes a wrong answer (exactly the Lab 4 lesson: retrieval quality bounds answer quality).

**Skip it when:**
- Stage 1 is already crisp (the right doc is reliably #1) — there's nothing to fix. **On our 62-doc corpus this is usually the case**, which is why these cells are about *mechanics*, not a dramatic accuracy jump.
- Latency is tight and you can't afford the extra model call.
- The candidate set is tiny — a reranker can even shuffle a lexically-similar distractor upward.

**Sizing:** rerank a **window** (top 50–100), never the whole index — that's the entire point of the two-stage split. Bigger windows = more recall fed to precision, but more rerank cost per query.

**Tie-back to Lab 4:** the cleanest place to drop a reranker is right before you build the prompt — feed the Agent Builder hybrid tool's results through a reranker and the agent reasons over a sharper top-k.

## Wrap-up

You added the **precision stage** that sits on top of everything from Labs 1–3:

- **Reranking = stage 2.** Recall (fast, wide, bi-encoder/RRF) → precision (expensive, narrow, reranker reads query+doc together).
- **Two kinds.** *Pointwise* cross-encoders (Jina v2) score each doc alone; *listwise* (Jina v3) scores the whole candidate set jointly and shines on near-duplicate/ambiguous sets.
- **Both are built-in EIS endpoints** — swap one `inference_id`. You called the rerank API directly *and* via the `text_similarity_reranker` retriever.
- **It's a tool, not a default.** Add it for the final top-k when precision matters; skip it when stage 1 is already sharp.

The retriever you built across the workshop is still the foundation. Reranking is the optional, high-precision layer you reach for when the order at the very top has to be right — like the top-k feeding an agent.

---
*That's the bonus. Thanks for staying — go build something.*
