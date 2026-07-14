# ES|QL Workshop Track — Instructor Guide

The **ES|QL edition** of "Vector → Hybrid → Do You Even Need a Model?". Same corpus, same thesis, same five labs — every retrieval operation expressed in **ES|QL** instead of the `_search` retriever DSL.

> **Thesis (unchanged):** *"The model didn't get dumber. The retrieval got worse."* In RAG, retrieval quality — not the model — determines answer quality.

This track **coexists** with the original retriever-DSL track; nothing in `instruqt/`, `notebooks/`, `corpus/`, or `agent-builder/` is modified. The corpus and Agent Builder setup are **shared**.

---

## What's different from the DSL track

| | DSL track | **ES|QL track** |
|---|---|---|
| Labs 1–3 & 5 surface | Kibana **Dev Console** | Kibana **Discover** (ES|QL mode) |
| Lab 4 surface | Notebook | Notebook (+ Discover "peek") |
| Semantic search | `semantic` retriever | `MATCH(body_semantic, q)` |
| BM25 | `multi_match` `["title^3","body"]` | `MATCH(title,q,{"boost":3}) OR MATCH(body,q)` |
| Hybrid RRF | `rrf` retriever | `FORK (…)(…) \| FUSE` |
| Linear fusion | `linear` retriever + MinMax | `FUSE LINEAR WITH {"weights":…,"normalizer":"minmax"}` |
| Reranking | `text_similarity_reranker` | `RERANK q ON body WITH {...}` |
| LLM synthesis | Python `requests` to `_inference/chat_completion/_stream` | `COMPLETION` command (whole RAG pipeline in one query) |
| Lab 2 "read the score" | `explain=True` | two queries (title-only vs body-only) — ES|QL has no `explain` |

**The headline:** Lab 4's entire RAG pipeline is **one ES|QL query** — `FORK | FUSE | RERANK | COMPLETION` — no orchestration code.

---

## Files

```
notebooks-esql/        lab1..lab5 ES|QL notebooks (es.esql.query())
instruqt-esql/         track.yml + 5 assignment.md + setup-kubernetes-vm
docs-esql/             this guide, FACILITATOR-ESQL.md, TRAP_QUERY_VALIDATION_ESQL.md
corpus/                SHARED, unchanged (index aiewf-workshop-docs)
agent-builder/         SHARED, unchanged (the AB tool is already ES|QL FORK+FUSE)
```

Two delivery paths (same rule as the DSL track, per `HANDOFF.md`):
1. **Notebooks + corpus** → `git clone` of `main` at sandbox boot. Push to `main` to update.
2. **`track.yml` / `assignment.md`** → `instruqt track push --force` **run from `instruqt-esql/`**. GitHub does NOT update these.

---

## Deploying the track for the first time (HARD ORDERING)

You **cannot** push placeholder challenge/tab ids. Mint them first:

```
cd instruqt-esql
instruqt track create                 # registers the track, assigns the track id
instruqt challenge create             # ×5 — mints a real challenge id + tab ids per lab
```

Then, for each `assignment.md`, replace the `REPLACE_CHALLENGE_ID_*` and `REPLACE_TAB_*` placeholders with the ids Instruqt minted, and finally:

```
instruqt track push --force
```

The track `id` and `checksum` are intentionally absent from `track.yml` — Instruqt assigns/recomputes both on first push. Do **not** copy them from the DSL track.

---

## Pre-event checklist (run on a FRESH sandbox)

A fresh sandbox is required — existing sandboxes don't re-clone. See `TRAP_QUERY_VALIDATION_ESQL.md` for the full validation pass. The essentials:

1. **Corpus:** `FROM aiewf-workshop-docs | STATS COUNT(*)` → 62.
2. **Endpoints:** `es.inference.get()` shows `.jina-embeddings-v5-text-small` (text_embedding), `.jina-reranker-v3` + `.jina-reranker-v2-base-multilingual` (rerank), and **`.anthropic-claude-4.5-haiku-completion` (completion — NOT chat_completion)**.
3. **Data view:** confirm Discover lists `aiewf-workshop-docs` (the boot script creates it via the data-views API — without it, Labs 1–3 & 5 open to an empty Discover).
4. **Trap ranks:** run every Lab 1–3 & 5 query in Discover, record actual ranks in `TRAP_QUERY_VALIDATION_ESQL.md`, re-tune the BM25 expression (boost value or `QSTR`) if a trap doesn't reproduce.
5. **Lab 4 COMPLETION:** run the one-query pipeline end-to-end (good + bad context); confirm a non-empty `answer`; note latency; confirm the Discover peek renders.
6. **Agent Builder:** `setup_agent.py` ran; converse shows ≥2 retrieval hops.

---

## Presenter notes

- **Discover orientation is the #1 friction point.** Every Lab 1–3/5 attendee must (a) select the `aiewf-workshop-docs` data view and (b) flip the query bar to **ES|QL** mode. If results look like keyword search or the `_score` column is missing, they forgot `METADATA _score`. Say it out loud at the start of Lab 1.
- **Lab 2 explain-gap:** "ES|QL has no `explain` tree. We read the score by splitting the match — title-only vs body-only — and comparing. You see *which field drove the match*, no nested JSON." This is arguably a clearer teaching moment than the DSL `explain`. (`SCORE(MATCH(...))` also works live and gives clean per-field score columns — a good bonus if there's time.)
- **Lab 3 FUSE LINEAR caveat:** ES|QL MinMax normalizes within each FORK branch's candidate set, not globally — the original `8.18 breaking changes` weight-backfire demo does **not** flip under this normalization (the correct doc wins at every weight). The lab now uses `notify me when something goes wrong` (target `doc-049`) instead, which does flip cleanly (0.8/0.2 BM25-lean sinks it to rank 4; 0.3/0.7 semantic-lean restores #1).
- **Lab 4:** the wow is "a whole RAG pipeline is now a database query." `COMPLETION` is one LLM call per row — keep `LIMIT 1` before it. The Discover peek will spin for several seconds; that's expected, not a hang. The GOOD-context question is `How does Index Lifecycle Management move data through hot, warm, and cold phases?` — the original SAML question retrieved a troubleshooting doc and collapsed the good/bad contrast.
- **Lab 5 RERANK:** `RERANK` overwrites `_score` but does **not** reorder rows — always follow it with `SORT _score DESC`, or the reranked scores land on the pre-rerank (RRF) ordering and the demo looks like a no-op.

---

## Validated on a live cluster (2026-07-01)

Full detail in `TRAP_QUERY_VALIDATION_ESQL.md`. Summary:
1. **Trap ranks under ES|QL BM25** — RRF lands the target at #1 on all 6 trap queries. BM25's OR-MATCH sum (vs `best_fields` max) does shift individual BM25 ranks (e.g. `exit code 137` — a boosted-title distractor sums to BM25 #1), but it's an *additional* demonstration of the same mechanism, not a broken one.
2. **`SCORE(MATCH(...))`** works live (zero-arg `SCORE()` still errors) — two-query split remains primary in Lab 2, `SCORE()` is a nice-to-have.
3. **`?q` param inside `RERANK`/`COMPLETION`** — works in the query-text position for both.
4. **`es.esql.query` named-param format** — `params=[{"name": value}, ...]` works on the installed client.
5. **Discover/notebook latency** — COMPLETION ~1.2–2.6s, RERANK ~0.3s. No misleading error states observed.
