# Workshop Outline
## "Vector Isn't Enough: Hybrid Search & Retrieval for AI Engineers"
### AIEWF 2026 · ~2 hours

---

## What to Expect

This is a hands-on technical workshop. You will run real queries, break real things, fix them, and measure the improvement — against a live Elastic Serverless project provisioned in your browser tab.

Every demo is live. No pre-baked answers, no slides with screenshots of results. You will see actual scores, actual ranked documents, and actual LLM answers generated from the documents you retrieved.

By the end you will have built — from scratch, in Python — a complete RAG pipeline that demonstrates why retrieval quality, not model quality, is the limiting factor in AI search applications.

**The repo is your take-home.** Everything runs against your own Elastic cluster: `git clone` + two environment variables and all four notebooks execute locally.

---

## Prerequisites

- Basic Python familiarity (reading function definitions, running cells)
- No ML background required — no embedding code, no numpy, no model training
- No prior Elasticsearch experience required — the corpus is pre-indexed, the mapping is pre-set
- In Instruqt: credentials are pre-configured. You need nothing else.

---

## The Core Argument

The AI engineering world defaults to "use a better model" when search quality degrades. This workshop makes the opposing case:

> **Most of a strong RAG pipeline is not LLM generation. It's fast, precise retrieval, ranking, filtering, and security — handled at the database layer.**

We prove this empirically, not rhetorically. You will run the same question through bad retrieval and good retrieval, with the same model, and watch the answer quality collapse and recover.

---

## What You Will Build / Learn (6 Deliverables)

1. **Dense vector / semantic search** with `semantic_text` + Elastic Inference Service — no embedding code, no external model API
2. **Stress-test vector search** with queries where it fails: exact tokens, version numbers, config keys, error codes
3. **BM25 keyword search** — where it rescues vector, and where it fails in turn (paraphrase / synonym queries)
4. **Hybrid retrieval with RRF and linear score fusion** — a single retriever that wins on all query types, with objective Recall@K measurement
5. **Cross-encoder reranking** — two-stage retrieval: fast recall + slow precision, composed in a single query
6. **A complete RAG pipeline** showing retrieval quality drives answer quality: same model, same question, good context vs bad context → good answer vs bad answer

---

## Lab Overview

| Lab | Title | Format | Time |
|-----|-------|--------|------|
| 1 | Vector Search: The Thing Everyone Reaches For | Dev Console + Notebook | ~20 min |
| 2 | Where Vector Breaks (and Lexical's Own Gap) | Dev Console + Notebook | ~25 min |
| 3 | Hybrid: Best of Both (RRF, Linear, Reranking) | Dev Console + Notebook | ~35 min |
| 4 | Why It Matters for Agents: Do You Even Need a Model? | Notebook | ~30 min |

Each lab has two surfaces:
- **Dev Console** (Kibana) — fast, visual, paste-and-run DSL queries
- **Python Notebook** — the deep-dive: live code, mechanism explanations, side-by-side comparisons, objective measurement

---

## The Corpus

60 Elasticsearch documentation documents, hand-engineered to demonstrate specific retrieval failure modes:

| trap_type | Docs | What it tests |
|-----------|------|---------------|
| `paraphrase` | doc-001, 002 | Zero lexical overlap; only semantic search finds them |
| `exact-token` | doc-003–005, 007, 008 | Specific codes, config keys, version numbers; only BM25 finds them |
| `version-specific` | doc-006, 056–058 | Version-tagged release notes; filtering + BM25 required |
| `near-duplicate` | doc-009, 010 | Almost identical documents; tests ranking precision |
| filler | doc-011–055, 059, 060 | Noise; realistic background |

---

## Lab 1 — Vector Search: The Thing Everyone Reaches For

**Thesis:** Semantic search finds documents by meaning, not keywords. Elasticsearch handles embedding, chunking, and ANN indexing server-side — you write zero ML code.

### Dev Console Steps

**Step 1 — Inspect the index mapping**
```
GET aiewf-workshop-docs/_mapping
```
Look for `body_semantic.type = "semantic_text"` and the auto-assigned `inference_id`. You did not set it; Elastic Serverless provisioned it automatically.

**Step 2 — Inspect the inference endpoint**
```
GET _inference
```
Find the Jina v5 endpoint. Notice `service: "elastic"` — this is the Elastic Inference Service (EIS), not an external API call you pay for separately.

**Step 3 — Run your first semantic query**
```json
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": { "field": "body_semantic", "query": "securing cluster traffic" }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```
The word "TLS" does not appear in the query. The top result is the TLS cluster communications document. That is semantic matching.

**Step 4 — Try the wow queries**
- `"how do I back up my cluster data"` → snapshot/restore docs
- `"users can't connect to Kibana"` → Kibana access/network docs

### Notebook Deep-Dive (`lab1-vector-search.ipynb`)

- Inspect the live mapping and inference endpoint in Python
- `show_hits()` helper — ranked table with scores and fields
- `r_semantic(query)` builder — the retriever DSL as a Python function
- **The 4-step mechanism diagram:** ES → EIS → Jina v5 → HNSW ANN index
- **ANN / HNSW explained:** why approximate nearest-neighbour search is orders of magnitude faster than brute-force at scale, and why the approximation barely matters in practice
- **Why chunking exists:** embedding token limits vs long documents; what `semantic_text` automates (chunk → embed → store → max-sim at query time)
- `es.get(index, id="doc-010")` — inspect stored semantic chunks inside a document

### Key Concept

When you run a `semantic` query:
1. ES sends your query text to EIS
2. EIS runs Jina v5 → returns a 1024-dimensional vector
3. ES runs ANN search (HNSW) over all stored document chunk vectors
4. Returns semantically similar documents — no vocabulary matching

**Setup question for Lab 2:** Try `"exit code 137"`. Does the right document come back?

---

## Lab 2 — Where Vector Breaks (and Lexical's Own Gap)

**Thesis:** Embeddings compress exact tokens — version numbers, error codes, config keys — into generic semantic clusters. The specific number or string is lost. BM25 rescues this. But BM25 has the mirror-image failure: zero lexical overlap = zero score, even when the document is obviously relevant.

### Dev Console Steps

**Part A — Break vector with exact tokens**

Run the semantic query with each of these strings. Observe that the correct document is NOT at rank 1:
- `"exit code 137"` — JVM OOMKilled doc (`doc-007`) should be #1; semantic misses it
- `"8.18 breaking changes"` — semantic blurs 8.15 / 8.18 / 9.0 release notes
- `"xpack.security.authc.realms configuration"` — exact config key; semantic returns generic security docs

**Part B — BM25 rescues exact tokens**

Switch the retriever to `multi_match` on `title^3, body`. Same queries. The correct documents appear at rank 1. Exact token matching works.

**Part C — Break BM25 with a paraphrase**

Run `"user can't log in"` through BM25. The SAML authentication troubleshooting doc (`doc-001`) contains zero instances of the word "login" — it uses "authentication", "identity provider", "assertion". BM25 score = effectively zero. The doc is invisible.

Run the same query through semantic. `doc-001` appears in the top 3.

### Notebook Deep-Dive (`lab2-where-vector-breaks.ipynb`)

- `compare(query)` helper — runs semantic and BM25 side by side, prints both ranked tables in one call
- All 4 trap queries compared side by side
- **The embedding compression aha:** "137" maps to the same vector neighborhood as other error codes. The number itself is not discriminative in high-dimensional space.
- **Why zero lexical overlap kills BM25:** the tf/idf formula; if a term doesn't appear, its tf = 0, its contribution = 0
- `es.search(..., explain=True)` on a BM25 query — print the `_explanation` tree showing term contributions, IDF values, field boosts
- Why we do NOT `explain` the semantic query: semantic explain trees are hundreds of nested per-chunk similarity scores, unreadable on stage
- **Core tension table:** vector wins at meaning / paraphrase; BM25 wins at exact tokens / codes / versions; neither wins universally

---

## Lab 3 — Hybrid: Best of Both (RRF, Linear, Filtering, Reranking)

**Thesis:** Fuse BM25 and semantic rankings into a single retriever that wins on all query types — and measure that win objectively, not by eyeballing.

### Dev Console Steps

**Part A — RRF Hybrid Retriever**

```json
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        { "standard": { "query": { "multi_match": { "query": "user can't log in", "fields": ["title^3", "body"] } } } },
        { "standard": { "query": { "semantic": { "field": "body_semantic", "query": "user can't log in" } } } }
      ],
      "rank_constant": 60,
      "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

Test against both Lab 2 failure queries:
- `"exit code 137"` — BM25 sub-retriever wins this arm; hybrid surfaces `doc-007`
- `"user can't log in"` — semantic sub-retriever wins this arm; hybrid surfaces `doc-001`

**Why RRF, not score addition:** BM25 scores are unbounded tf/idf values (e.g. 12.7). Semantic scores are bounded cosine similarities (e.g. 0.84). Adding `12.7 + 0.84` is meaningless. RRF uses only rank position — no normalization needed.

**Part B — Linear Retriever with MinMax Normalization**

```json
"retriever": {
  "linear": {
    "retrievers": [
      { "retriever": { "standard": { "query": { "multi_match": ... } } }, "weight": 0.5 },
      { "retriever": { "standard": { "query": { "semantic": ... } } }, "weight": 0.5 }
    ],
    "normalizer": "minmax",
    "rank_window_size": 100
  }
}
```

Try shifting weights: `0.8` BM25 / `0.2` semantic for exact-token-heavy workloads.

### Notebook Deep-Dive (`lab3-hybrid-search.ipynb`)

**Objective measurement — Recall@K**

Define a judgment set: the 4 trap queries with their known-correct document IDs. For each query, run BM25, semantic, and RRF. Count the known-good document in the top-K results. Print a Recall@5 table.

> Note: The native `_rank_eval` API only accepts `query` bodies — it cannot score `rrf` or `linear` retrievers. This Python loop is the correct approach for evaluating hybrid retrieval.

Expected result: RRF wins on average recall, fixing the failure cases of each individual approach.

**Filtered hybrid retrieval**

Add a `bool.filter` inside each sub-retriever's standard query to scope to `version_tags: "8.18"`:

```python
{"standard": {"query": {"bool": {
    "must": [{"multi_match": ...}],
    "filter": [{"term": {"version_tags": "8.18"}}]
}}}}
```

Same filter applies to the semantic arm. RRF fuses the filtered results. This is the "filtering handled at the database layer" promise from the abstract — ES enforces the scope before retrieval, so the LLM never sees out-of-scope documents.

**Raw score scales (why MinMax is needed for linear)**

Print the top BM25 score and top semantic score for the same query. They are on completely different scales. MinMax normalization maps each to [0, 1] before weighting.

**Why RRF is the production default over linear:**
- Linear fusion needs recalibration when the corpus changes or the embedding model updates
- RRF only uses rank positions — stable regardless of raw score distributions
- Rule: use RRF as default; use linear when you have calibrated per-workload weights

**Cross-encoder reranking**

Two retrieval modes:
- **Bi-encoder (RRF, linear, semantic):** query and documents embedded independently; fast because doc vectors are pre-computed; good for recall over millions of documents
- **Cross-encoder (reranker):** query and document processed jointly at query time; much more accurate because it models query-document interaction; slow because it can't be pre-computed

**Two-stage retrieval:** bi-encoder fetches top 50 (recall), cross-encoder re-scores those 50 (precision):

```python
{
  "text_similarity_reranker": {
    "retriever": r_rrf(query),           # inner retriever: recall stage
    "field": "body",
    "inference_id": ".jina-reranker-v2-base-multilingual",
    "inference_text": query,             # required — cross-encoder needs the query
    "rank_window_size": 50
  }
}
```

**Decision framework table**

| Situation | Recommended |
|-----------|-------------|
| Unknown query mix | RRF |
| Mostly natural language / meaning | Semantic or RRF |
| Mostly exact tokens (codes, versions, keys) | BM25 or RRF |
| Scoped retrieval (version, tenant, category) | RRF + filter |
| Calibrated workload, stable corpus | Linear (MinMax) |
| High precision, latency-tolerant | Reranker on top of RRF |

---

## Lab 4 — Why It Matters for Agents: Do You Even Need a Model?

**Thesis:** Answer quality is bounded by retrieval quality. The same model with bad context produces a bad answer. The same model with excellent context produces an excellent answer. Most of a RAG pipeline is a database problem.

**LLM access:** Uses the Elastic Inference Service (`claude-haiku-4.5`). The same `ES_API_KEY` authenticates both your search queries and LLM calls — no separate Anthropic key, no per-attendee quota management.

### Notebook Steps (`lab4-rag-pipeline.ipynb`)

**Helpers**

- `hybrid_search(query, size=5)` — RRF retrieval returning flat dicts with `id`, `title`, `url`, `body`, `score` (note: the shared `search()` helper does NOT return `body`; this wrapper explicitly requests it)
- `build_prompt(context_docs, question)` — assembles `[Source N: Title]\nbody` blocks with `---` separators
- `synthesize(context_docs, question, show_prompt=False)` — POSTs to Elastic Inference API, returns the LLM's answer

**Step 1: Retrieve — watch what comes back**

```python
docs = hybrid_search("user can't log in")
```

Print titles, scores, and body previews. See exactly what the LLM will read.

**Step 2: See the exact prompt**

```python
answer = synthesize(docs, question, show_prompt=True)
```

`show_prompt=True` prints the fully-assembled context before calling the model (bodies truncated to 600 chars for display; full text sent to the model). This is what the LLM actually reads — document bodies, titles, source numbers, then the question.

**The GOOD vs BAD experiment**

Same model. Same question. Different retrieval.

```python
# GOOD: hybrid RRF retrieval — semantically relevant documents
good_docs = hybrid_search("How do I configure SAML authentication in Elasticsearch?")
good_answer = synthesize(good_docs, question)

# BAD: retrieval forced to off-topic docs via a filter
# Constrain to version-specific release notes — guaranteed irrelevant
bad_docs = [retrieve with filter: trap_type = "version-specific"]
bad_answer = synthesize(bad_docs, question)
```

The BAD case is **forced deterministically** via a metadata filter — not luck. This guarantees the demo works reliably on stage.

Print both answers side by side. The model did not change. The question did not change. Only the retrieved context changed.

> **"The model didn't get dumber. The retrieval got worse."**

**Security at the database layer**

The BAD filter demonstrates the security architecture:

```
User request
    │
    ▼
Elasticsearch — access control / document-level security evaluated HERE
    │              (RBAC, DLS filters, query-time authorization)
    │  Only authorized documents returned
    ▼
LLM prompt — model sees only what ES returned
    │
    ▼
LLM answer — cannot expose unauthorized content (it was never in context)
```

Document-level security (DLS) in Elasticsearch assigns role-based filters at query time, regardless of which query is run. The LLM serving a restricted user cannot surface restricted documents — not because of a prompt instruction, but because the database never returned them.

**Citation-grounded prompting**

Update the system prompt to require `[Source N]` citations. The LLM must cite which source it used for each claim — every statement is traceable to a specific retrieved document.

```python
CITATION_SYSTEM_PROMPT = (
    "... For each claim you make, cite the source using [Source N] notation. ..."
)
```

This reduces hallucination risk: if the LLM can't cite a source, it should say so rather than speculate.

**Try your own question**

```python
ask("How do I monitor shard allocation in Elasticsearch?")
```

One-liner: `hybrid_search` → `synthesize` → print answer.

**Multi-hop retrieval agent (take-home)**

A minimal agent loop using the Inference API to decide whether a follow-up retrieval is needed:

```python
def multi_hop_agent(question, max_hops=2):
    # Hop 1: retrieve → ask LLM: answer or LOOKUP?
    # If LOOKUP: retrieve on the follow-up query → answer
```

The LLM uses the same ES_API_KEY to call the inference endpoint. No extra infrastructure. The entire agent runs against your Elastic project.

---

## Key Takeaways

1. **Semantic search is powerful but not universal.** Exact tokens (error codes, version numbers, config keys) survive in BM25 but are compressed into generic neighborhoods by embeddings.

2. **Hybrid retrieval wins on all query types.** RRF fuses BM25 and semantic rankings without requiring score normalization — it's the production default.

3. **Filtering is retrieval-layer security.** Metadata filters applied before fusion ensure the LLM physically cannot see unauthorized or out-of-scope documents.

4. **The retrieval quality ceiling is real.** A better model cannot compensate for wrong context. Improving retrieval has a higher ROI than upgrading the model.

5. **Elastic handles the infrastructure.** Embedding, chunking, ANN indexing, inference service, and LLM gateway are all managed — you write search queries and Python, not ML pipelines.

---

## Workshop Track

- **Instruqt slug:** `aiewf-2026-vector-hybrid-search`
- **Repo:** https://github.com/jeffvestal/elastic-vectorsearch-workshop
- **Notebooks:** `notebooks/lab1-vector-search.ipynb` through `lab4-rag-pipeline.ipynb`
