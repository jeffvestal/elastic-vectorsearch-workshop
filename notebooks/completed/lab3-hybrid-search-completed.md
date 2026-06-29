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


```python
info = es.info()
count = es.count(index=INDEX)["count"]
print(f"Connected to ES {info['version']['number']} | {count} docs in '{INDEX}'")
```

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

## Linear combination with MinMax normalization

**First, what MinMax does — with vs without.** A linear retriever combines each sub-retriever's scores into one number. The catch is *whose scores* dominate that sum:

- **Without MinMax:** raw scores are combined as-is → the retriever that produces **larger numbers dominates**, weights are hard to interpret, and ranking is biased by score *scale* rather than relevance.
- **With MinMax:** each retriever is rescaled to the same **0–1 range** first → weights behave predictably and the combination is balanced by *relative result quality*, not magnitude.

*Quick example:* retriever A scores 0–100, retriever B scores 0–1. Without MinMax, A wins by scale alone; with MinMax, A and B compete fairly. That's our exact situation — **BM25 ~0–20 vs semantic ~0–1** — so without normalization BM25 would dominate every sum.

The `linear` retriever applies this automatically: MinMax-normalize each sub-retriever to [0, 1], then apply your weights:

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

## "Just measure the right weights" — OK, let's actually measure them

The rule of thumb above says linear *can* beat RRF **if you've measured the right weights**. That claim is easy to assert and rarely shown — so let's do it. We already have the one thing an eval needs: a **judgment set** (`JUDGMENTS` from the cell above — queries paired with their known-correct doc).

The metric is **MRR (Mean Reciprocal Rank)**: for each query, score `1 / rank_of_correct_doc` (1.0 if it's #1, 0.5 if #2, 0.33 if #3…), then average across the set. One number per strategy; higher is better. It rewards putting the right doc at the very top, which is what a RAG prompt actually consumes.

Below we sweep the linear retriever's BM25↔semantic weight across the full range, score each split by MRR, and compare the **best measured** linear weight to plain RRF.

> **This block is the eval harness in miniature.** In production you'd run it over hundreds of judged queries pulled from real user telemetry (clicks, thumbs, conversions) — not four — and re-run it on every corpus or embedding-model change. The *shape* is identical: judgments → sweep → metric → pick. What you're about to see in four queries is what a relevance-tuning pipeline does at scale.


```python
# Weight recommendation: sweep linear weights, score each by MRR over the judgment set.
# Reuses JUDGMENTS and rank_of() from the "rank of the known-good doc" cell above.

def mrr(builder):
    """Mean Reciprocal Rank of the known-good doc across the judgment set."""
    total = 0.0
    for query, good_id, _ in JUDGMENTS:
        r = rank_of(builder, query, good_id)
        total += (1.0 / r) if r else 0.0
    return total / len(JUDGMENTS)

# Baselines — the single-strategy retrievers and zero-tuning RRF
print("Baselines (MRR — higher is better, 1.0 = every target at rank 1):")
print(f"  BM25 only:      {mrr(r_bm25):.3f}")
print(f"  Semantic only:  {mrr(r_semantic):.3f}")
print(f"  RRF (no tuning):{mrr(r_rrf):>6.3f}")

# Sweep the linear BM25<->semantic balance across the full range
print("\nLinear weight sweep:")
print(f"  {'BM25':>5} {'semantic':>9} {'MRR':>7}")
print("  " + "-" * 23)
sweep = []
for w_sem in [round(i * 0.1, 1) for i in range(11)]:
    w_bm25 = round(1.0 - w_sem, 1)
    score = mrr(lambda q, wb=w_bm25, ws=w_sem: r_linear(q, w_bm25=wb, w_sem=ws))
    sweep.append((w_bm25, w_sem, score))

best = max(sweep, key=lambda x: x[2])
rrf_score = mrr(r_rrf)
for w_bm25, w_sem, score in sweep:
    flag = "  <- best measured" if (w_bm25, w_sem) == (best[0], best[1]) else ""
    print(f"  {w_bm25:>5} {w_sem:>9} {score:>7.3f}{flag}")

print("\n" + "=" * 52)
print(f"Best linear weight (measured): BM25={best[0]} / semantic={best[1]}  → MRR {best[2]:.3f}")
print(f"RRF, zero tuning:                                  → MRR {rrf_score:.3f}")
print("=" * 52)
print(
    "\nThe best-measured linear weight matches RRF — but notice the 0.5/0.5 'obvious'\n"
    "split scores well below it, and the winning weight leans semantic specifically\n"
    "because THIS judgment set is paraphrase- and version-heavy. Change the query mix\n"
    "(or re-embed the corpus and watch the MinMax ranges shift) and that number moves.\n"
    "RRF hit the same score with nothing to tune and nothing to re-calibrate later."
)
```

## The whole story in one picture — strategies × queries

The sweep gave us numbers. Here's the same data as a **heatmap**: every retrieval strategy (rows) against every trap query (columns), colored by the **rank of the correct doc** — green = 1 (perfect), red = buried.

This is the single most useful artifact in a retrieval eval. Read it by row and by column:
- **Scan a row** to see where a strategy fails — BM25 and Semantic each have a red/yellow cell, on *different* queries.
- **Scan the RRF row** — it should be green all the way across. That's the entire thesis of the lab in one strip of color: every other strategy breaks on *some* query; fusion breaks on none.

(If `matplotlib` isn't installed, the cell falls back to a colored text grid with the same numbers — no plot library required.)


```python
# Heatmap: rank of the known-good doc for every (strategy, query).
# Builds on rank_of() + JUDGMENTS from the cells above.

HEATMAP_STRATEGIES = {
    "BM25":           r_bm25,
    "Semantic":       r_semantic,
    "Linear 0.8/0.2": lambda q: r_linear(q, w_bm25=0.8, w_sem=0.2),
    "Linear 0.5/0.5": lambda q: r_linear(q, w_bm25=0.5, w_sem=0.5),
    "Linear 0.2/0.8": lambda q: r_linear(q, w_bm25=0.2, w_sem=0.8),
    "RRF hybrid":     r_rrf,
}
QUERY_LABELS = [q for q, _, _ in JUDGMENTS]

# matrix[strategy][query] = rank of the correct doc (None if outside the window)
matrix = [[rank_of(b, q, gid) for q, gid, _ in JUDGMENTS]
          for b in HEATMAP_STRATEGIES.values()]

CAP = 8  # ranks >= CAP (or missing) all show as the most "broken" color

try:
    import matplotlib.pyplot as plt
    # None -> CAP so missing docs render as the worst color
    color_vals = [[min(r, CAP) if r else CAP for r in row] for row in matrix]

    fig, ax = plt.subplots(figsize=(9, 4.5))
    im = ax.imshow(color_vals, cmap="RdYlGn_r", vmin=1, vmax=CAP, aspect="auto")

    ax.set_xticks(range(len(QUERY_LABELS)))
    ax.set_xticklabels(QUERY_LABELS, rotation=20, ha="right")
    ax.set_yticks(range(len(HEATMAP_STRATEGIES)))
    ax.set_yticklabels(list(HEATMAP_STRATEGIES))

    # annotate each cell with the actual rank
    for i, row in enumerate(matrix):
        for j, r in enumerate(row):
            ax.text(j, i, "—" if r is None else str(r),
                    ha="center", va="center", color="black", fontweight="bold")

    ax.set_title("Rank of the correct doc — lower (green) is better", pad=12)
    cbar = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label(f"rank (capped at {CAP})")
    plt.tight_layout()
    plt.show()

except ImportError:
    # Zero-dependency fallback: ANSI-colored text grid with the same numbers.
    GREEN, YELLOW, RED, RESET = "\033[42m\033[30m", "\033[43m\033[30m", "\033[41m\033[97m", "\033[0m"
    def cell(r):
        if r == 1:            bg = GREEN
        elif r and r <= 3:    bg = YELLOW
        else:                 bg = RED
        return f"{bg} {('—' if r is None else r):>2} {RESET}"
    print("Rank of the correct doc (green=1 best, yellow=2-3, red=4+/missing):\n")
    print(f"{'strategy':<16}" + "".join(f"{q[:13]:<15}" for q in QUERY_LABELS))
    for name, row in zip(HEATMAP_STRATEGIES, matrix):
        print(f"{name:<16}" + "".join(f"  {cell(r)}        "[:15] for r in row))
    print("\n(install matplotlib for the graphical heatmap: pip install matplotlib)")

print("\nRead the RRF row: green across every query. Every other row has at least one\n"
      "non-green cell — a query where that strategy mis-ranked the doc the user wanted.")
```

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

> 📓 **Want to go deeper?** This is a single mechanics cell. The **bonus Lab 5 — Reranking** notebook (`lab5-reranking.ipynb`) goes in depth: calling the rerank API directly, the **pointwise (cross-encoder) vs listwise** distinction, Jina Reranker **v2 vs v3** head-to-head, and a decision matrix for when to use which.


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
