# AIEWF 2026 — Instructor Guide
## "Vector → Hybrid → Do You Even Need a Model?"

**Event:** AI Engineer World's Fair 2026
**Date:** June 29, 2026
**Duration:** 2 hours
**Instructor:** Jeff Vestal (jeff.vestal@elastic.co)
**Co-presenter:** Philipp Krenn (confirm scope sync — see Open Items)

---

## Workshop Overview

**Thesis:** Most of a RAG pipeline is a database problem, not a model problem.

The arc:
1. Vector search feels like magic — semantic matching without keywords
2. Vector breaks on exact tokens (version numbers, error codes, setting names)
3. BM25 rescues exact tokens but fails on vocabulary mismatch (paraphrases)
4. Hybrid (RRF + linear) wins on both simultaneously
5. Wire the retriever to an LLM — retrieval quality determines answer quality, not the model

**Interface:**
- Labs 1–3: Kibana Dev Console (retriever DSL is cleanest here)
- Lab 4: Python notebook (synthesis requires a model call — console can't do that)
- One Elasticsearch Serverless backend for both

---

## Time Budget

| Segment | Time | Interface |
|---|---|---|
| Intro + sandbox orientation + EIS/Jina framing | ~10 min | — |
| Lab 1 — Vector: the thing everyone reaches for | ~25 min | Dev Console |
| Lab 2 — Where vector breaks (and lexical's own gap) | ~25 min | Dev Console |
| Lab 3 — Hybrid: RRF + linear combination | ~40 min | Dev Console |
| Lab 4 — Why it matters for agents | ~20 min | Notebook |

**Total: 120 min.** Buffer is baked into Lab 3 (heaviest cognitive load).

---

## Pre-Event Checklist

Work through this at least 72h before the event. All items are blocking unless marked optional.

### Infrastructure

- [ ] **Serverless project provisioned** — one Elastic Serverless project for the instructor demo; Instruqt provisions one per attendee automatically
- [ ] **EIS inference endpoint available** — run `GET _inference` and confirm `.jina-embeddings-v5-text-small` is listed
- [ ] **Jina Reranker v2 available** — run `GET _inference` and confirm `.jina-reranker-v2-base-multilingual` (or equivalent) is listed. Note exact inference_id and update the reranker snippet in `instruqt/03-hybrid-search/queries.md` if different.
- [ ] **Run ingest.py** — `ES_ENDPOINT=... ES_API_KEY=... python corpus/ingest.py` — verify all 60 docs indexed, test semantic query returns results

### Corpus Validation (CRITICAL)

- [ ] **Run each Lab 2 adversarial query** against the real index. Fill in the verification table in `corpus/TRAP_QUERY_VALIDATION.md`. Each query must show the expected pass/fail behavior.
- [ ] **Verify paraphrase trap (doc-001)** — "user can't log in" must rank doc-001 in top 2 via semantic, and doc-001 must NOT appear in BM25 top 5. This is the highest-risk live moment. Do not assume — pre-test.
- [ ] **Run all 4 trap queries through RRF hybrid** — confirm hybrid wins on all 4. Fill in the Lab 3 Verification table in `TRAP_QUERY_VALIDATION.md`.
- [ ] **Run Lab 1 "wow" queries** — "securing cluster traffic", "how do I back up my cluster data", "users can't connect to Kibana" — confirm satisfying semantic results.

### Lab 4 (Notebook)

- [ ] **HARD GATE: Instruqt notebook-tab availability** — verify whether the Instruqt sandbox can expose a notebook/code-server tab alongside Kibana against the Serverless project. The answer determines the Lab 4 in-room format:
  - Option 1 (preferred): Instruqt notebook tab — attendees run the notebook themselves
  - Option 2 (fallback): instructor-driven notebook on screen — attendees follow along
  - Option 3 (last resort): skip the notebook, show a single Python snippet in console
  - **Decide before the event and update the Lab 4 assignment.md and track.yml accordingly**
- [ ] **Pre-run Cell 5 (good context)** — verify it produces a clear, accurate answer about SAML auth troubleshooting
- [ ] **Pre-run Cell 6 (bad context)** — verify it produces a clearly degraded/irrelevant answer
- [ ] **Pre-run Cell 7 (full pipeline)** — verify end-to-end retrieve → synthesize works

### Pacing

- [ ] **Pacing dry-run** — run through all 4 labs against the real index. Time each lab. Confirm 10/25/25/40/20 holds with buffer. If Lab 3 runs long, cut the `rank_constant` tuning experiment (it's optional).

---

## Open Items / Human-Gated

These require human action before the event:

1. **Instruqt notebook-tab check** (HARD GATE) — does the sandbox support a notebook tab alongside Kibana against one Serverless project? Determines Lab 4 in-room format. Jeff or Philipp must test this before build.

2. **Scope confirmation with Philipp Krenn** — the search/retrieval angle (per `projects/aiewf-2026-ai-search-workshop.md`). Confirm co-presenter role and any content changes.

3. **EIS model IDs** — confirm exact inference IDs for Jina v5 embedding and Jina Reranker v2 in the provisioned Serverless project. Update `corpus/ingest.py` and queries if different from defaults.

4. **Corpus trap query pre-test** — must be run against the REAL index (not assumed). Fill in `corpus/TRAP_QUERY_VALIDATION.md` before the event.

---

## File Map

```
workshops/aiewf-2026/
├── README.md                        ← you are here (instructor guide)
├── corpus/
│   ├── docs.json                    ← 60-doc pre-baked corpus
│   ├── ingest.py                    ← ingest script (run before event)
│   └── TRAP_QUERY_VALIDATION.md     ← pre-event trap query checklist
├── instruqt/
│   ├── track.yml                    ← Instruqt track definition
│   ├── 01-vector-search/
│   │   ├── assignment.md            ← Lab 1 attendee instructions
│   │   └── queries.md               ← Lab 1 Dev Console snippets
│   ├── 02-where-vector-breaks/
│   │   ├── assignment.md
│   │   └── queries.md
│   ├── 03-hybrid-search/
│   │   ├── assignment.md
│   │   └── queries.md
│   └── 04-why-it-matters/
│       ├── assignment.md
│       └── lab4.ipynb               ← Python RAG notebook
└── reference-repo/                  ← attendee take-home
    ├── README.md
    ├── labs/
    │   ├── lab1-vector-search.md
    │   ├── lab2-where-vector-breaks.md
    │   ├── lab3-hybrid.md
    │   └── lab4.ipynb
    └── corpus/
        ├── docs.json
        └── ingest.py
```

---

## Presenter Notes by Lab

### Intro (~10 min)

- Name the EIS/Jina framing upfront. This audience knows Jina. Don't bury it.
- The "how does the embedding get generated?" question is your hook. Set it up before Lab 1 answers it.
- Orient the sandbox: show Kibana Dev Console, show the index exists, mention the corpus is pre-indexed.

### Lab 1 (~25 min)

- Do Snippet 1 (mapping) together, explain `semantic_text` + `inference_id`
- Do Snippet 2 (GET inference endpoint) — "this is real infrastructure, not hand-waving"
- Walk the query-time embedding mechanism before running Snippet 3
- Run Snippets 3-5, ask attendees to call out what they notice
- End on a hook: "Why would you ever use keyword search?"

### Lab 2 (~25 min)

- Part A: run A1-A3, let attendees guess the results before revealing them
- Part B: rerun the same queries as BM25 — the contrast is the teaching moment
- Part C: the paraphrase query is the highest-risk moment. Have the output pre-run in a buffer if possible. Never demo this cold.

### Lab 3 (~40 min)

- Build the RRF retriever step by step, don't paste the full query at once
- "RRF doesn't care about score magnitude — only rank position" — say this twice
- After attendees build RRF, have them re-run the Lab 2 trap queries. Watch the room when hybrid wins all 4 simultaneously.
- Linear: explain MinMax normalization before showing the query. "Scores are on different scales — MinMax makes them comparable."
- Reranker: instructor-run only, talk through what it does and why it's not in the hands-on

### Lab 4 (~20 min)

- Frame the four-stage pipeline before opening the notebook
- Cell 5 (good context): read the output aloud, point to the specific auth troubleshooting content
- Cell 6 (bad context): pause before running. "Same question. Same model. Same prompt. Watch."
- After Cell 6: "The model didn't get dumber. The retrieval got worse." — this is the closing line.
- Cell 7: if time allows, take a question from the audience and run it live through the full pipeline

---

## Corpus Trap Docs Quick Reference

| Doc ID | Title | Trap Type | Adversarial Query |
|---|---|---|---|
| doc-001 | SAML authentication troubleshooting | paraphrase | "user can't log in" (vector wins, BM25 misses) |
| doc-007 | JVM settings for Elasticsearch | exact-token | "exit code 137" |
| doc-057 | Elasticsearch 8.18 release notes | version-specific | "8.18 breaking changes" |
| doc-058 | Elasticsearch 8.15 release notes | version-specific | (version blur test) |
| doc-006 | Elasticsearch breaking changes (9.x) | version-specific | (version blur test) |
| doc-008 | Cluster shard allocation settings | exact-token | "xpack.security.authc.realms configuration" |
| doc-009 | Security setup (self-managed) | near-duplicate | (paired with doc-010) |
| doc-010 | TLS for cluster communications | near-duplicate | (paired with doc-009) |

Full validation details: `corpus/TRAP_QUERY_VALIDATION.md`
