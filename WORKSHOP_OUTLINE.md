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

62 Elasticsearch documentation documents (60 + 2 distractors), hand-engineered to demonstrate specific retrieval failure modes. Each doc carries a one-line neutral `summary` shown in query results so attendees can see what a hit is about; `trap_type` is retained for filtering (and the Lab 4 DLS demo) but is **not** displayed in learner-facing results — it would spoil the trick. Non-trap docs have `trap_type: null`.

| trap_type | Docs | What it tests |
|-----------|------|---------------|
| `paraphrase` | doc-001, 002 | Zero lexical overlap; only semantic search finds them |
| `exact-token` | doc-003–005, 007, 008 | Specific codes, config keys, version numbers; only BM25 finds them |
| `version-specific` | doc-006, 056–058 | Version-tagged release notes; filtering + BM25 required |
| `near-duplicate` | doc-009, 010 | Almost identical documents; tests ranking precision |
| `distractor` | doc-061, 062 | Semantic near-neighbors for `exit code 137` with no literal "137" — make the semantic near-tie real |
| filler (`null`) | doc-011–055, 059, 060 | Noise; realistic background |

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
  "_source": ["id", "title", "summary"]
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

## Lab 2 — Where Each Search Breaks (and Why You Need Both)

**Thesis:** Neither retriever wins everywhere. Semantic *blurs* exact identifiers — it can't reliably rank the one token that matters, though sometimes it nails them. BM25 has two failure modes of its own: it can rank the **wrong** exact match (a boosted common-word title beating the rare token the user cared about), and it **buries** docs that share no vocabulary with a paraphrase. (Jina v5 is strong enough that the old "vector can't find exact tokens at all" framing does not reproduce — the honest story is reliability, not blindness.)

### Dev Console Steps

**Part A — Semantic blurs / mis-ranks exact identifiers**
- `"exit code 137"` → `doc-007` is semantic #1 but only ~0.001 ahead of a distractor that lacks "137" — a near-tie, the ranking is essentially noise. BM25 pins `doc-007` decisively.
- `"new_primaries"` → semantic returns the WRONG doc at #1 (a cluster-health page); the real settings doc `doc-008` is #2. BM25 pins `doc-008`.
- `"cluster.routing.allocation.enable"` → honesty check: semantic gets `doc-008` #1. A long distinctive key embeds well. Reliability problem, not a guaranteed miss.

**Part B — BM25 is decisive on rare tokens, but mis-ranks a boosted title**
- `"exit code 137"` via `multi_match` → `doc-007` #1 by a wide margin (rare token "137", high IDF).
- `"8.18 breaking changes"` via `multi_match` → BM25 ranks the WRONG doc `doc-006` ("Elasticsearch breaking changes") #1; the 8.18 page `doc-057` is only #2. Its `title^3`-boosted common words beat the rare `8.18` token. (Semantic gets this one right.)

**Part C — Break BM25 with a paraphrase**

Run `"notify me when something goes wrong"` through BM25. The Watcher alerting doc (`doc-049`) uses "trigger / condition / actions / webhook" — none of the query words — so BM25 buries it (~#5). Run the same query through semantic: `doc-049` is #1.

### Notebook Deep-Dive (`lab2-where-vector-breaks.ipynb`)

- `compare(query)` helper — runs semantic and BM25 side by side, prints both ranked tables in one call
- **The blur aha:** "137" maps to the "process killed" neighborhood; distractor docs sit ~0.001 away. The number isn't discriminative in high-dimensional space.
- **The BM25 boosted-title aha:** `explain=True` on `"8.18 breaking changes"` shows `doc-006`'s title clause (~12.9) beating `doc-057`'s rare-token match (~7.4) — a field-boost effect, NOT term frequency.
- **The second BM25 `explain`:** on `"exit code 137"`, the rare token "137" contributes the largest term weight — the signal vector search couldn't replicate.
- **Why zero lexical overlap buries a doc:** the tf/idf formula; if a term doesn't appear, its tf = 0. *Buried*, not literally zero — a real index still returns it, just too low to use.
- **Core tension table:** semantic blurs exact identifiers and can mis-rank bare tokens; BM25 mis-ranks on boosted common words and goes blind to paraphrase; neither wins universally.

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
        { "standard": { "query": { "multi_match": { "query": "notify me when something goes wrong", "fields": ["title^3", "body"] } } } },
        { "standard": { "query": { "semantic": { "field": "body_semantic", "query": "notify me when something goes wrong" } } } }
      ],
      "rank_constant": 60,
      "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```

Test against each Lab 2 failure — whichever sub-retriever was right carries the fusion:
- `"notify me when something goes wrong"` — semantic wins this arm; hybrid surfaces `doc-049` at #1 (BM25 buried it)
- `"8.18 breaking changes"` — semantic wins this arm; hybrid surfaces `doc-057` at #1 (BM25 ranked the wrong doc)
- `"new_primaries"` — BM25 wins this arm; hybrid surfaces `doc-008` at #1 (semantic picked the wrong doc)
- `"exit code 137"` — BM25 wins this arm; hybrid keeps `doc-007` at #1 (semantic was a near-tie)

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

**Objective measurement — rank of the known-good doc**

Define a judgment set: the trap queries with their known-correct document IDs. For each query, run BM25, semantic, and RRF and report the **rank** of the target. (Not Recall@5: in a 62-doc corpus a "losing" retriever often still squeaks the target into the top 5, so Recall@5 ≈ 1.0 everywhere and hides the contrast — rank shows which retriever mis-ordered it and whether fusion fixed it.)

> Note: The native `_rank_eval` API only accepts `query` bodies — it cannot score `rrf` or `linear` retrievers. This Python loop is the correct approach for evaluating hybrid retrieval.

Result: RRF lands the target at #1 on every trap query, even the ones where semantic OR BM25 mis-ranked it.

**MRR weight-sweep and strategies×queries heatmap**

After confirming that RRF ranks every target correctly, the notebook sweeps the linear retriever's BM25/semantic weight split (in 0.1 increments) and scores each configuration by MRR over the judgment set. The best linear weight (around sem 0.6–0.7) ties RRF at MRR 1.000 — but only after measurement reveals it; the intuitive 0.5/0.5 equal split scores only 0.750. The notebook then renders a strategies×queries heatmap (matplotlib, text fallback) showing the rank of the correct document for each retriever × query pair. RRF is the only all-green row. The teaching point is concrete: you can match RRF with a tuned linear weight, but the optimal weight is corpus- and workload-dependent, it goes stale when either changes, and finding it requires a judgment set most teams don't maintain. RRF needs zero tuning.

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
docs = hybrid_search("notify me when something goes wrong")
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

**Multi-hop retrieval agent**

A hand-rolled agent loop in the notebook: retrieve on the user question, ask the LLM whether it can answer or needs a follow-up lookup, and if so retrieve again on the follow-up query before generating the final answer. The prompt explicitly invites a second hop ("if you need more context, output LOOKUP: <query>"), and the parser is robust to markdown formatting (e.g. `# ANSWER:` headers). For a two-part question the agent reliably fires both hops — you can watch the tool calls in the cell output. The LLM uses the same `ES_API_KEY` to call the inference endpoint; no extra infrastructure is needed.

```python
def multi_hop_agent(question, max_hops=2):
    # Hop 1: retrieve → prompt LLM: answer directly or LOOKUP: <follow-up query>
    # Hop 2 (if needed): retrieve on the follow-up query → final answer
```

**Agent Builder finale**

Part 3 takes the same retriever to a third abstraction level. The notebook (via `agent-builder/setup_agent.py`) registers the Lab 3 RRF hybrid retriever as an Elastic Agent Builder tool — implemented as an ES|QL `FORK … FUSE` query so the retrieval logic lives entirely in Elasticsearch. A multi-hop agent is wired to this tool via the Kibana API. Running the two-part question through the converse API shows ≥2 tool calls in the response, with each hop's retrieved context visible in the trace. Attendees then drive the same agent interactively in the Kibana Agent Builder UI.

The closing beat: the same retriever — the RRF hybrid built in Lab 3 — powers all three abstraction levels: the single-shot RAG cell, the hand-rolled Python loop, and the Agent Builder agent. The agent framework is swappable. Retrieval quality is not.

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
