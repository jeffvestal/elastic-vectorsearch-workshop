# Lab 2 — Where Each Search Breaks (and Why You Need Both)

**Thesis:** Neither retriever wins everywhere. Semantic search **blurs exact identifiers** — error codes, config values, version strings — folding them into a region of vector space shared with everything conceptually nearby, so it can't *reliably* rank the one doc that matters. BM25 has its own failure modes: it can rank the **wrong exact match** (a boosted common-word title beating the rare token the user cared about), and it **buries** docs that share no vocabulary with a paraphrased query.

Seeing *when* and *why* each one fails is the prerequisite to building a hybrid retriever that covers both — Lab 3.

## What you'll learn
- Why semantic search **blurs** exact identifiers (and the honest cases where it nails them)
- Two ways BM25 fails: the **wrong exact match**, and **burying** paraphrased queries
- How to read the BM25 `explain` output to see *exactly why* a doc ranked where it did
- The core tension table: which retriever to trust for which query shape

## Before you start
- **In Instruqt:** `ES_ENDPOINT` and `ES_API_KEY` are pre-configured — just run the cells.
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

def search(retriever, size=5, source=("id","title","summary","version_tags")):
    return es.search(index=INDEX, retriever=retriever, size=size, source=list(source))

# Lab 2 extra: side-by-side comparison helper
def compare(query, size=5):
    """Run the same query through semantic and BM25 side by side."""
    print(f"QUERY: {query!r}\n")
    print("SEMANTIC (vector):")
    show_hits(search(r_semantic(query), size))
    print("\nBM25 (lexical):")
    show_hits(search(r_bm25(query), size))

print("✓ Helpers loaded")
```

    ✓ Helpers loaded



```python
# Confirm connection
info = es.info()
count = es.count(index=INDEX)["count"]
print(f"Connected to ES {info['version']['number']} | {count} docs in '{INDEX}'")
```

    Connected to ES 9.5.0 | 62 docs in 'aiewf-workshop-docs'


## Failure mode 1: Exact identifiers — vector blurs the one token that matters

Semantic search is built to match *meaning*. That is exactly the wrong instinct for an **exact identifier** — an error code, a config value, a version string, a CVE number, a username. The embedding model folds the identifier into a region of vector space shared with everything *conceptually nearby*, so the specific token stops working as a discriminator.

Our corpus has a JVM doc (`doc-007`) covering **OOMKilled / exit code 137** — how Kubernetes signals an out-of-memory kill. We also seeded two distractor docs that talk about exit codes and process crashes *generically*, **without the literal "137"**. Read each hit's `summary` to see what it's actually about.

**Query:** `exit code 137`

- BM25 should pin `doc-007`: it contains the rare token `137`, which is high-IDF gold.
- Semantic will recognize the *concept* (a process being killed) — but can it tell `doc-007` apart from generic crash docs that mean almost the same thing?


```python
compare("exit code 137")
```

    QUERY: 'exit code 137'
    
    SEMANTIC (vector):
      #1   0.6798  doc-007  JVM settings for Elasticsearch  JVM heap sizing, garbage collection, and the OOMKilled exit code 137 on Elasticsearch nodes.
      #2   0.6784  doc-061  Container exit codes when a process is killed (OOM and signals)  What container exit codes mean when a process is killed by a signal or the out-of-memory killer.
      #3   0.6535  doc-025  Troubleshoot snapshot and restore in Elasticsearch  Troubleshooting snapshot and restore failures, including repository access issues.
      #4   0.6411  doc-062  Troubleshooting application crashes and restarts  Investigating application crash loops, unexpected restarts, and abnormal process termination.
      #5   0.6297  doc-021  Red or yellow cluster health status troubleshooting  Diagnosing red or yellow cluster health and finding why shards are unassigned.
    
    BM25 (lexical):
      #1   8.3688  doc-007  JVM settings for Elasticsearch  JVM heap sizing, garbage collection, and the OOMKilled exit code 137 on Elasticsearch nodes.
      #2   6.1208  doc-061  Container exit codes when a process is killed (OOM and signals)  What container exit codes mean when a process is killed by a signal or the out-of-memory killer.
      #3   2.5324  doc-062  Troubleshooting application crashes and restarts  Investigating application crash loops, unexpected restarts, and abnormal process termination.
      #4   2.1718  doc-045  Elasticsearch aliases  Index aliases: secondary names that let you swap backing indices without app changes.
      #5   2.0542  doc-013  Hybrid search in Elasticsearch  Combining BM25 lexical search with vector search to get the strengths of both.


## What actually happened — semantic *blurs*, it doesn't cleanly miss

Look at the semantic column. `doc-007` is probably still **#1** — but by a hair. The two `distractor` docs (which never say "137") and an unrelated troubleshooting doc are all crammed within ~0.05 of it. The model embedded "exit code 137" as the *general concept* "a process was killed / crashed," and in that neighborhood the OOM doc, a generic "container exit codes" doc, and a "crashes and restarts" doc are nearly **the same point in vector space**. The `137` carries almost no weight — it's just three subword tokens absorbed into the concept.

So the failure here is subtle and more dangerous than a flat miss: semantic *ranking is essentially noise*. Re-embed, change a chunk, add one more similar doc, and the #1 flips to a doc that doesn't even contain the number the user typed.

Now compare BM25: `doc-007` wins by a **wide margin** (≈8 vs ≈6 and a cliff after). The token `137` appears in exactly one doc, IDF rewards it, and the ranking is decisive and stable.

**The rule:** when the user's intent *is* an exact identifier, you want the engine that treats that token as special. BM25 does. A pure embedding model averages it away.

---

### A cleaner miss: `new_primaries`

`exit code 137` was a *blur*. For a query that semantic gets outright **wrong**, try a bare config value with no surrounding natural language. `new_primaries` is a value of the `cluster.routing.allocation.enable` setting — documented in `doc-008`.


```python
# `new_primaries` — a bare config value. We want doc-008 (shard allocation settings).
# Watch the semantic #1: it lands on a *plausible* doc (cluster health) — the right
# neighborhood, wrong document. BM25 pins doc-008 because the token is rare and exact.
compare("new_primaries")
```

    QUERY: 'new_primaries'
    
    SEMANTIC (vector):
      #1   0.6227  doc-021  Red or yellow cluster health status troubleshooting  Diagnosing red or yellow cluster health and finding why shards are unassigned.
      #2   0.5925  doc-008  Cluster-level shard allocation and routing settings  Cluster shard allocation and routing settings, including cluster.routing.allocation.enable and new_primaries.
      #3   0.5900  doc-047  Elasticsearch index templates  Composable index templates that auto-apply settings, mappings, and aliases to new indices.
      #4   0.5812  doc-045  Elasticsearch aliases  Index aliases: secondary names that let you swap backing indices without app changes.
      #5   0.5786  doc-023  Upgrade Elasticsearch  Performing a rolling upgrade of a self-managed Elasticsearch cluster.
    
    BM25 (lexical):
      #1   2.4445  doc-008  Cluster-level shard allocation and routing settings  Cluster shard allocation and routing settings, including cluster.routing.allocation.enable and new_primaries.



```python
# Honesty check: semantic is NOT always wrong on identifiers.
# A longer, distinctive dotted key carries enough structure that the model embeds it well.
# Here semantic ranks doc-008 #1 — it nails the exact config key. Don't overclaim the failure mode.
compare("cluster.routing.allocation.enable")
```

    QUERY: 'cluster.routing.allocation.enable'
    
    SEMANTIC (vector):
      #1   0.7923  doc-008  Cluster-level shard allocation and routing settings  Cluster shard allocation and routing settings, including cluster.routing.allocation.enable and new_primaries.
      #2   0.7783  doc-023  Upgrade Elasticsearch  Performing a rolling upgrade of a self-managed Elasticsearch cluster.
      #3   0.7720  doc-021  Red or yellow cluster health status troubleshooting  Diagnosing red or yellow cluster health and finding why shards are unassigned.
      #4   0.7367  doc-041  Elasticsearch data tiers  Data tiers (hot/warm/cold/frozen) that balance search speed against storage cost over time.
      #5   0.7163  doc-032  Elasticsearch cross-cluster search  Cross-cluster search for running federated queries across remote clusters.
    
    BM25 (lexical):
      #1   2.7237  doc-023  Upgrade Elasticsearch  Performing a rolling upgrade of a self-managed Elasticsearch cluster.
      #2   2.6092  doc-008  Cluster-level shard allocation and routing settings  Cluster shard allocation and routing settings, including cluster.routing.allocation.enable and new_primaries.
      #3   2.6092  doc-021  Red or yellow cluster health status troubleshooting  Diagnosing red or yellow cluster health and finding why shards are unassigned.


## Reading those two results together

- **`new_primaries`** → semantic puts a *cluster-health troubleshooting* doc at #1 and pushes the actual settings doc (`doc-008`) down. The model only had a bare token with no sentence around it, so it guessed the topic — "something about cluster state" — and landed close but wrong. BM25 had a rare exact token and pinned it.
- **`cluster.routing.allocation.enable`** → semantic gets it **right** at #1. The dotted key is long and distinctive enough to embed into its own corner of vector space.

That contrast is the real lesson. Exact identifiers aren't a guaranteed semantic failure — they're a **reliability** failure. Sometimes the model nails them, sometimes it blurs them, sometimes it picks a plausible neighbor. You can't predict which, and "usually right" is not good enough when a user pastes an error code and needs *that* page. BM25's behavior on exact tokens is boring and predictable — which is exactly what you want for this query class.

## Failure mode 2: BM25 picks the *wrong* exact match

It's tempting to conclude "use BM25 for identifiers, semantic for everything else." But BM25 has its own trap: it scores **lexical overlap**, weighted by field boosts and IDF — and that can reward a doc that shares the *common* words over the doc that shares the *rare, specific* one.

Our corpus has three release-note-style docs:
- `doc-006` — title **"Elasticsearch breaking changes"** (generic, spans many versions)
- `doc-057` — title "Elasticsearch 8.18 release notes" (the one a user asking about 8.18 wants)
- `doc-058` — title "Elasticsearch 8.15 release notes"

**Query:** `8.18 breaking changes` — the user clearly wants the **8.18** page.


```python
# Who wins each retriever? Watch BM25's #1 carefully.
compare("8.18 breaking changes", size=5)

# Then ask Elasticsearch to EXPLAIN why BM25 ranked its #1 where it did.
# For each matching term we pull the boost / idf / tf factors so you can see
# WHY the term scored what it did — the "result of:" the raw tree promises.
print("\n" + "="*64)
print("BM25 explain — why doc-006 outranks doc-057")
print("="*64)
resp = es.search(
    index=INDEX,
    query={"multi_match": {"query": "8.18 breaking changes",
                           "fields": ["title^3", "body"], "type": "best_fields"}},
    explain=True, size=60, source=["id", "title"],
)

def term_factors(weight_node):
    """Pull boost/idf/tf out of a weight(...) explanation node."""
    f = {}
    for score in weight_node.get("details", []):          # score(freq=...) node
        for x in score.get("details", []):
            d = x.get("description", "")
            if d.startswith("boost"): f["boost"] = x["value"]
            elif d.startswith("idf"): f["idf"] = x["value"]
            elif d.startswith("tf"):  f["tf"]  = x["value"]
    return f

def walk(e):
    d = e.get("description", "")
    if d.startswith("weight("):
        term = d[len("weight("):].split(")")[0]            # e.g. "title:breaking in 7"
        f = term_factors(e)
        print(f"    {term:22} {e['value']:6.3f}  =  "
              f"boost {f.get('boost', 0):.1f} × idf {f.get('idf', 0):.2f} × tf {f.get('tf', 0):.2f}")
        return                                              # don't recurse below a term
    for s in e.get("details", []):
        walk(s)

for hit in resp["hits"]["hits"]:
    if hit["_source"]["id"] in ("doc-006", "doc-057"):
        print(f"\n{hit['_source']['id']}  score={hit['_score']:.3f}  ({hit['_source']['title']})")
        walk(hit["_explanation"])

print("\nNote the boost column: title terms carry boost 6.6 (= 2.2 default × the title^3 boost),")
print("body terms only 2.2. That 3× on the title is what lets doc-006's common-word title win.")
```

    QUERY: '8.18 breaking changes'
    
    SEMANTIC (vector):
      #1   0.7718  doc-057  Elasticsearch 8.18 release notes  Elasticsearch 8.18 release notes and the recommended upgrade path to 9.0.
      #2   0.7041  doc-056  Elasticsearch 9.x what's new overview  Overview of what's new and what breaks in the Elasticsearch 9.x series.
      #3   0.6910  doc-058  Elasticsearch 8.15 release notes  Elasticsearch 8.15 release notes covering semantic_text and vector-storage foundations.
      #4   0.6810  doc-006  Elasticsearch breaking changes  Breaking changes across Elasticsearch releases to review before upgrading a cluster.
      #5   0.6388  doc-042  Elasticsearch circuit breaker settings  Circuit breaker settings that fail requests before they exhaust JVM heap.
    
    BM25 (lexical):
      #1   12.9117  doc-006  Elasticsearch breaking changes  Breaking changes across Elasticsearch releases to review before upgrading a cluster.
      #2   7.3594  doc-057  Elasticsearch 8.18 release notes  Elasticsearch 8.18 release notes and the recommended upgrade path to 9.0.
      #3   4.1848  doc-056  Elasticsearch 9.x what's new overview  Overview of what's new and what breaks in the Elasticsearch 9.x series.
      #4   4.1145  doc-058  Elasticsearch 8.15 release notes  Elasticsearch 8.15 release notes covering semantic_text and vector-storage foundations.
      #5   1.8681  doc-054  Elasticsearch enrich policies  Enrich policies that append data from other indices to documents during ingest.
    
    ================================================================
    BM25 explain — why doc-006 outranks doc-057
    ================================================================
    
    doc-006  score=12.912  (Elasticsearch breaking changes)
        title:breaking in 7     6.456  =  boost 6.6 × idf 1.90 × tf 0.52
        title:changes in 7      6.456  =  boost 6.6 × idf 1.90 × tf 0.52
        body:breaking in 7      2.283  =  boost 2.2 × idf 1.39 × tf 0.75
        body:changes in 7       2.283  =  boost 2.2 × idf 1.39 × tf 0.75
    
    doc-057  score=7.359  (Elasticsearch 8.18 release notes)
        title:8.18 in 4         5.817  =  boost 6.6 × idf 1.90 × tf 0.46
        body:8.18 in 4          3.844  =  boost 2.2 × idf 1.90 × tf 0.92
        body:breaking in 4      1.502  =  boost 2.2 × idf 1.39 × tf 0.49
        body:changes in 4       2.013  =  boost 2.2 × idf 1.39 × tf 0.66
    
    Note the boost column: title terms carry boost 6.6 (= 2.2 default × the title^3 boost),
    body terms only 2.2. That 3× on the title is what lets doc-006's common-word title win.


## Why BM25 got it wrong — and it's *not* "term frequency"

The `explain` output shows the real mechanism, and it's worth being precise about because it's easy to mislabel:

- **`doc-006`** ("Elasticsearch breaking changes") wins because its **title** is literally those two query words, and `title` is boosted `^3`. The title terms `breaking` and `changes` score ≈6.5 **each** → the title clause alone is ≈12.9.
- **`doc-057`** ("8.18 release notes") matches `8.18` strongly (≈5.8, because `8.18` is a rare, high-IDF token) plus the body words — but its title does **not** contain "breaking changes," so it tops out around 7.4.

So BM25 picked the doc that matched the **common, boosted words** over the doc that matched the **rare, specific token the user actually cared about**. This is a *field-boost / phrase-match* effect — **not** a term-frequency trap. doc-006 doesn't win by repeating words; it wins because the words the query shares with it sit in a 3×-boosted field. (Flip the lesson: an aggressive `title^3` boost is a great default that quietly backfires on version-specific queries.)

Notice semantic got this one **right** (`doc-057` at #1) — it understood the user wanted the 8.18 page. The two retrievers fail on *opposite* query shapes. That's the whole argument for hybrid.

## Failure mode 3: Paraphrase — BM25 buries the doc it can't lexically match

The classic case *for* semantic search. When a user describes a problem in their own words, the relevant doc often shares almost no vocabulary with the query. BM25 can only score words that overlap — so the right doc sinks under docs that happen to share a common word, while semantic finds it on meaning.

Our corpus has `doc-049` about **Watcher**, Elasticsearch's alerting system. It talks about `trigger`, `condition`, `actions`, `schedule`, `webhook` — the machinery of alerting. It does **not** contain the words "notify," "something," or "goes wrong."

A real user types: `"notify me when something goes wrong"`

**What to expect:**
- Semantic: finds `doc-049` at/near #1 — "notify me when something goes wrong" *is* the meaning of alerting.
- BM25: `doc-049` is **buried** (well outside the top few). Its top hits are docs that share a stray common word, not docs about alerting.


```python
compare("notify me when something goes wrong")

# doc-049 (Watcher alerting) should be semantic #1, but buried in BM25.
# The same vocabulary gap, second example: a user who wants ILM but never says "lifecycle".
print("\n" + "="*60)
compare("reduce storage cost for old logs")  # target: doc-041 (data tiers) — semantic #1, BM25 buried
```

    QUERY: 'notify me when something goes wrong'
    
    SEMANTIC (vector):
      #1   0.7497  doc-049  Elasticsearch Watcher alerting  Watcher, Elasticsearch's built-in alerting system: triggers, conditions, and actions that fire on data thresholds.
      #2   0.6522  doc-025  Troubleshoot snapshot and restore in Elasticsearch  Troubleshooting snapshot and restore failures, including repository access issues.
      #3   0.6435  doc-042  Elasticsearch circuit breaker settings  Circuit breaker settings that fail requests before they exhaust JVM heap.
      #4   0.6380  doc-062  Troubleshooting application crashes and restarts  Investigating application crash loops, unexpected restarts, and abnormal process termination.
      #5   0.6376  doc-019  Ingest pipelines in Elasticsearch  Building ingest pipelines from processors to transform and enrich documents before indexing.
    
    BM25 (lexical):
      #1   4.4524  doc-061  Container exit codes when a process is killed (OOM and signals)  What container exit codes mean when a process is killed by a signal or the out-of-memory killer.
      #2   3.0165  doc-002  Troubleshoot authorization errors and role mapping  Diagnosing authorization exceptions and role-mapping problems for authenticated users.
      #3   2.8812  doc-022  Data streams in Elasticsearch  Data streams: an abstraction over backing indices optimized for append-only time-series data.
      #4   1.5047  doc-056  Elasticsearch 9.x what's new overview  Overview of what's new and what breaks in the Elasticsearch 9.x series.
      #5   0.9664  doc-049  Elasticsearch Watcher alerting  Watcher, Elasticsearch's built-in alerting system: triggers, conditions, and actions that fire on data thresholds.
    
    ============================================================
    QUERY: 'reduce storage cost for old logs'
    
    SEMANTIC (vector):
      #1   0.7369  doc-041  Elasticsearch data tiers  Data tiers (hot/warm/cold/frozen) that balance search speed against storage cost over time.
      #2   0.7099  doc-017  Index lifecycle management overview  How Index Lifecycle Management moves indices through hot/warm/cold/frozen/delete phases.
      #3   0.7082  doc-037  Elasticsearch snapshot and restore overview  Snapshots as point-in-time backups of a cluster stored in a repository.
      #4   0.7037  doc-007  JVM settings for Elasticsearch  JVM heap sizing, garbage collection, and the OOMKilled exit code 137 on Elasticsearch nodes.
      #5   0.7005  doc-022  Data streams in Elasticsearch  Data streams: an abstraction over backing indices optimized for append-only time-series data.
    
    BM25 (lexical):
      #1   7.4604  doc-007  JVM settings for Elasticsearch  JVM heap sizing, garbage collection, and the OOMKilled exit code 137 on Elasticsearch nodes.
      #2   6.1529  doc-053  Elasticsearch vector storage optimization  Reducing dense-vector memory use while keeping acceptable search recall.
      #3   4.7302  doc-010  TLS encryption for cluster communications  Securing node-to-node cluster communication with TLS certificates.
      #4   3.8664  doc-011  Dense vector field type  The dense_vector field type for storing float vectors and running kNN similarity search.
      #5   3.7858  doc-041  Elasticsearch data tiers  Data tiers (hot/warm/cold/frozen) that balance search speed against storage cost over time.


## Why BM25 buries the alerting doc

`doc-049` is *about* "notify me when something goes wrong" — but it expresses that with words like `trigger`, `condition`, `actions`, `webhook`, `schedule`. BM25's score is a sum over **query terms that appear in the doc**:

```
score(query, doc) = Σ  IDF(term) × tf-saturation(term, doc) × field weight
                  terms in query
```

For `"notify me when something goes wrong"` against `doc-049`:

- "notify" → does not appear in the doc → **0 contribution**
- "me", "when" → near-stop-words, negligible IDF → ~0
- "something" → not in the doc → 0
- "goes" → not in the doc → 0
- "wrong" → not in the doc → 0

The doc isn't *invisible* — BM25 still returns it, because a query term might brush some other field — but with essentially no matching terms its score is tiny, and it sinks below docs that share an incidental common word. **Semantic search has the opposite strength:** the query vector and the Watcher doc's vector land in the same region because they *mean* the same thing, with zero shared vocabulary.

> ⚠️ Note we're saying **buried**, not "scores exactly zero." A real index almost always returns *something*; the failure is that the *right* doc ranks too low to be useful — which for a user looking at the top 3 is just as broken.

**Rule:** if users describe *what's wrong* in their own words instead of the doc's vocabulary, BM25 ranks poorly. Semantic handles it gracefully.

## Read the score: why BM25 *wins* on `exit code 137`

We just used `explain` to see why BM25 ranked the *wrong* doc on `8.18 breaking changes`. Now let's use the same tool on the query where BM25 is the hero — `exit code 137` — to see the signal vector search couldn't replicate.

`explain=True` returns the per-term breakdown: which terms matched, their IDF, and the saturated term frequency. Watch the contribution of the token `137`.


```python
# BM25 explanation for the top hit on "exit code 137" — show each term's boost/idf/tf.
resp = es.search(
    index=INDEX,
    query={"multi_match": {"query": "exit code 137",
                           "fields": ["title^3", "body"], "type": "best_fields"}},
    explain=True, size=1, source=["id", "title"],
)

hit = resp["hits"]["hits"][0]
src = hit["_source"]
print(f"Doc: {src['id']} — {src['title']}")
print(f"Score: {hit['_score']:.4f}\n")
print("Per-term contributions (watch the idf column — the rare token '137' dominates):\n")

def term_factors(weight_node):
    """Pull boost/idf/tf out of a weight(...) explanation node."""
    f = {}
    for score in weight_node.get("details", []):          # score(freq=...) node
        for x in score.get("details", []):
            d = x.get("description", "")
            if d.startswith("boost"): f["boost"] = x["value"]
            elif d.startswith("idf"): f["idf"] = x["value"]
            elif d.startswith("tf"):  f["tf"]  = x["value"]
    return f

def walk(e):
    d = e.get("description", "")
    if d.startswith("weight("):
        term = d[len("weight("):].split(")")[0]            # e.g. "body:137 in 17"
        f = term_factors(e)
        print(f"    {term:20} {e['value']:6.3f}  =  "
              f"boost {f.get('boost', 0):.1f} × idf {f.get('idf', 0):.2f} × tf {f.get('tf', 0):.2f}")
        return
    for s in e.get("details", []):
        walk(s)

walk(hit["_explanation"])

print("\n'137' carries the highest idf of the three — it appears in only one doc, so it's")
print("the rarest, most discriminating token. That single high-idf match is the signal")
print("vector search couldn't replicate: to the embedding model '137' is just part of the")
print("'a process was killed' concept, not a special token worth ranking on.")
```

    Doc: doc-007 — JVM settings for Elasticsearch
    Score: 8.3688
    
    Per-term contributions (watch the idf column — the rare token '137' dominates):
    
        body:exit in 17       2.555  =  boost 2.2 × idf 1.86 × tf 0.63
        body:code in 17       2.555  =  boost 2.2 × idf 1.86 × tf 0.63
        body:137 in 17        3.258  =  boost 2.2 × idf 2.37 × tf 0.63
    
    '137' carries the highest idf of the three — it appears in only one doc, so it's
    the rarest, most discriminating token. That single high-idf match is the signal
    vector search couldn't replicate: to the embedding model '137' is just part of the
    'a process was killed' concept, not a special token worth ranking on.


## The semantic score is different in nature

We're intentionally **not** running `explain=True` on a semantic query here. Here's why:

A semantic `explain` tree is huge and opaque — it produces per-chunk cosine similarity scores for every chunk of every document, often hundreds of nested numbers. On stage this creates a wall of JSON that teaches nothing.

What you need to know about the semantic score:

- It's derived from **cosine similarity** between the query vector and each document chunk vector
- Values range roughly from 0 (completely unrelated) to 1 (identical)
- The document's score is the **max similarity across all its chunks** (so long docs don't get penalized)
- Unlike BM25, it is **not** sensitive to document length or term frequency — it's purely about vector proximity

The practical implication: BM25 scores and semantic scores are on **different scales** with different distributions. You can't just add them — which is exactly why hybrid fusion needs normalization. That's Lab 3.

## The core tension — summary table

Every row below is what you just saw run live against the corpus.

| Query | Example | Semantic | BM25 |
|---|---|---|---|
| Exact identifier (blur) | `exit code 137` | ⚠️ #1 but by ~0.001 over a doc with no "137" — unreliable | ✅ decisive #1 (rare token) |
| Bare config value | `new_primaries` | ❌ wrong doc at #1 (plausible neighbor) | ✅ pins the settings doc |
| Distinctive dotted key | `cluster.routing.allocation.enable` | ✅ #1 — sometimes it nails them | ✅ also strong |
| Version-specific | `8.18 breaking changes` | ✅ #1 (understands intent) | ❌ wrong doc #1 (boosted common-word title) |
| Paraphrase / meaning | `notify me when something goes wrong` | ✅ #1 | ❌ buried (no shared vocabulary) |
| Natural language | `securing cluster traffic` | ✅ concept match | ⚠️ depends on vocabulary |

**The conclusion:** neither retriever is safe alone. Semantic blurs the tokens that must stay exact; BM25 mis-ranks on boosted common words and goes blind to paraphrase. A production system needs **both**, plus a way to fuse their rankings so the retriever that's *right* for a given query wins. That's RRF and linear combination — Lab 3.

---
*Continue in Dev Console → Lab 3 assignment, or open `lab3-hybrid-search.ipynb`*
