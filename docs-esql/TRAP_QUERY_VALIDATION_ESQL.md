# Trap Query Validation — ES|QL edition

> **STATUS: VALIDATED LIVE** on 2026-07-01 against `vectorsearch-workshop-dev` (Serverless,
> ES 9.5.0), 62 docs, index `aiewf-workshop-docs`. Every rank below was measured directly —
> see `docs-esql/README-ESQL.md` and memory `esql-track-validation-findings` for the full
> narrative of what changed vs `corpus/TRAP_QUERY_VALIDATION.md` (the retriever-DSL version).
> Two demo queries did **not** reproduce and were swapped for working replacements (see notes
> inline below) — the swaps are already applied in the notebooks and `instruqt-esql/` assignments.

- **Cluster:** `vectorsearch-workshop-dev`, Serverless, ES 9.5.0, 62 docs, index `aiewf-workshop-docs`.
- **Embedding model:** `.jina-embeddings-v5-text-small` (auto-assigned by `semantic_text`).
- **ES|QL expressions under test:**
  - semantic → `WHERE MATCH(body_semantic, ?q)`
  - BM25 → `WHERE MATCH(title, ?q, {"boost": 3.0}) OR MATCH(body, ?q)`
  - RRF → `FORK ( MATCH(body) )( MATCH(body_semantic) ) | FUSE`
- Rank = position of the target doc; `1` is best. Record **exact** ranks, not guesses.

---

## How to run the validation pass

In **Kibana Discover** (ES|QL mode) on a fresh sandbox, or via the notebooks. For each query,
run the semantic, BM25, and RRF variants and record where the **target doc** lands. Templates:

```esql
-- SEMANTIC
FROM aiewf-workshop-docs METADATA _score
| WHERE MATCH(body_semantic, "<query>")
| SORT _score DESC | LIMIT 10 | KEEP id, title, summary, _score
```
```esql
-- BM25
FROM aiewf-workshop-docs METADATA _score
| WHERE MATCH(title, "<query>", {"boost": 3.0}) OR MATCH(body, "<query>")
| SORT _score DESC | LIMIT 10 | KEEP id, title, summary, _score
```
```esql
-- RRF
FROM aiewf-workshop-docs METADATA _score, _id, _index
| FORK ( WHERE MATCH(body, "<query>")          | SORT _score DESC | LIMIT 50 )
       ( WHERE MATCH(body_semantic, "<query>") | SORT _score DESC | LIMIT 50 )
| FUSE | SORT _score DESC | LIMIT 10 | KEEP id, title, summary, _score
```

---

## Trap ranks to record

| Query | Target | Semantic | BM25 | RRF | Teaching point still holds? |
|---|---|---|---|---|---|
| `exit code 137` | doc-007 | 1 | 2 | 1 | ✅ BM25 rank 2 (a boosted-title distractor, `doc-061`, sums to #1) — RRF fixes it |
| `new_primaries` | doc-008 | 2 | 1 | 1 | ✅ semantic wrong doc at #2 / BM25 pins it / RRF #1 |
| `cluster.routing.allocation.enable` | doc-008 | 1 | 2 | 1 | ✅ semantic gets it right / RRF #1 |
| `8.18 breaking changes` | doc-057 | 1 | 2 | 1 | ✅ BM25 rank-2 wrong doc (`doc-006` boosted title) / RRF fixes it |
| `notify me when something goes wrong` | doc-049 | 1 | 5 | 1 | ✅ BM25 buries paraphrase at #5 / RRF fixes it |
| `reduce storage cost for old logs` | doc-041 | 1 | 5 | 1 | ✅ BM25 buries paraphrase at #5 / RRF fixes it |

**RRF lands the target at #1 on every single trap query.** That's the Lab 3 headline: RRF
needs zero tuning and wins everywhere a single retriever broke in Lab 2.

**Lab 1 "wow" queries (semantic #1 expected):**

| Query | Target | Semantic | OK? |
|---|---|---|---|
| `securing cluster traffic` | doc-010 | 1 | ✅ |
| `how do I back up my cluster data` | doc-037 | 1 | ✅ |
| `users can't connect to Kibana` | doc-024 | 1 | ✅ |

**Lab 2 explain-gap (two-query technique) — `8.18 breaking changes`:**

| Query variant | Expected #1 | Actual #1 |
|---|---|---|
| title-only `MATCH(title, q, {"boost":3.0})` | doc-006 | ✅ doc-006 |
| body-only `MATCH(body, q)` | doc-057 | ✅ doc-057 |

The field-boost effect reproduces cleanly — the two-query split is the primary Lab 2
technique (`SCORE(MATCH(...))` also works live and is promoted alongside it; see
`README-ESQL.md`).

**Lab 3 FUSE LINEAR weight-backfire:**

⚠️ **`8.18 breaking changes` does NOT reproduce the backfire** — `doc-057` (the correct doc)
wins outright at every weight tested (0.8/0.2, 0.5/0.5, 0.2/0.8). ES|QL `FUSE LINEAR` MinMax
normalizes within each FORK branch's own candidate set (not globally like the retriever
DSL's `linear`), which changes the dynamics enough that BM25-lean weighting can't drag the
wrong doc back on top here. **Swapped to a working replacement query** (already applied in
the Lab 3 notebook and `instruqt-esql/03-esql-hybrid-search/assignment.md`):

| Query: `notify me when something goes wrong` (target `doc-049`) | Weights (fork1 BM25 / fork2 semantic) | Actual #1 |
|---|---|---|
| BM25-lean (backfires) | 0.8 / 0.2 | `doc-061` (wrong — doc-049 sinks to rank 4) |
| balanced | 0.5 / 0.5 | `doc-061` (still wrong — doc-049 rank 2) |
| semantic-lean (fixes it) | 0.3 / 0.7 | ✅ `doc-049` (rank 1) |

Same "wrong weight buries the right doc" lesson, fully reproducible — just a different
query than the DSL track used. Note: weights must be **positive**; `0.0` is rejected with
"expected weight to be positive."

**Lab 4 good-vs-bad context:**

⚠️ **The original question (`How do I configure SAML authentication in Elasticsearch?`)
does NOT work** — it retrieves `doc-001`, which is SAML *troubleshooting*, not setup, so
even the GOOD-context run answers "I do not have enough information," collapsing the
contrast. **Swapped to a working replacement** (already applied in
`notebooks-esql/lab4-esql-rag-pipeline.ipynb`):

- [x] GOOD context (`How does Index Lifecycle Management move data through hot, warm, and
      cold phases?`) retrieves `doc-017` (ILM overview) and returns a detailed, grounded answer.
- [x] BAD context (`trap_type == "version-specific"`) retrieves `doc-056` ("Elasticsearch 9.x
      what's new overview") and returns "I do not have enough information."
- [x] `COMPLETION` returns a non-empty `answer`; latency ~1.2–2.6s per call.
- [x] Discover peek query (literal-string version) renders the `answer` cell without timeout.

**Lab 5 RERANK:**

⚠️ **Found a real bug, now fixed:** `RERANK` overwrites `_score` but does **NOT** reorder
rows. The Lab 5 notebook's `q_rerank()` helper was missing a `SORT _score DESC` after
`RERANK` — without it, rows silently keep their pre-rerank (RRF) order with the new scores
attached, so the reranking is computed but invisible. Fixed in
`notebooks-esql/lab5-esql-reranking.ipynb` and `instruqt-esql/05-esql-reranking/assignment.md`
(the Lab 3 and Lab 4 notebooks already had the sort). **Anywhere `RERANK` appears, `SORT
_score DESC` must follow it.**

- [x] `reduce storage cost for old logs`: RRF already puts `doc-041` (data tiers) and
      `doc-017` (ILM) in a near-tie for #1 (0.0325 vs 0.0320) — this is NOT the "buried doc"
      case the notebook originally assumed. After the SORT fix, **listwise (v3) flips to
      `doc-017` #1**; **pointwise (v2) agrees with RRF and keeps `doc-041` #1**. Reframed as
      a "reranker types can legitimately disagree on a near-tie" lesson (updated in both the
      notebook and assignment.md).
- [x] `cluster.routing.allocation.enable`: RRF already ranks `doc-008` #1, in a near-tie with
      `doc-023` (0.0325 vs 0.0325) — not "#2" as originally assumed. RERANK doesn't change
      the rank but widens the score gap to a decisive margin (0.52 vs 0.09). Reframed as
      "sharpens an already-decisive stage."
- [x] `user cannot authenticate` pointwise vs listwise: both rank `doc-001` (SAML) #1.
      Pointwise ranks `doc-002` (authz) #2; listwise drops it to #6 (out of top-5). Matches
      the intended lesson as originally written — no changes needed.

---

## Re-tuning notes (if a trap doesn't reproduce under ES|QL BM25)

The OR-MATCH BM25 *sums* the title and body contributions, unlike `multi_match best_fields`
(*max*). This was the highest-risk item and it **did** shift one trap (`exit code 137` — a
boosted-title distractor, `doc-061`, sums to BM25 #1 over `doc-007`) but the *lesson* held:
that's just a second demonstration of the same field-boost-sums mechanism as the `8.18`
trap, not a broken demo. No expression changes were needed elsewhere; RRF fixes every case.

---

## Resolved — no longer needs a live cluster

1. ~~Trap ranks under ES|QL BM25~~ — validated above; RRF #1 on all 6 traps.
2. ~~`SCORE(MATCH(...))`~~ — works live, wraps a full-text expr, gives clean per-field score
   columns. Promoted alongside the two-query split in Lab 2 (zero-arg `SCORE()` still errors).
3. ~~`.anthropic-claude-4.5-haiku-completion`~~ — present with `task_type=completion`.
4. ~~COMPLETION/RERANK latency~~ — COMPLETION ~1.2–2.6s, RERANK ~0.3s. No misleading error state.
5. ~~`FUSE LINEAR` JSON shape~~ — `{"weights": {"fork1": ..., "fork2": ...}, "normalizer": "minmax"}`; weights must be positive.
6. ~~`?q` named param inside `RERANK`/`COMPLETION`~~ — works in the query-text position for both.
7. Discover data-view auto-creation — not independently re-verified this pass; low risk, unchanged since last check.
8. ~~`es.esql.query` named-param format~~ — `params=[{"name": value}, ...]` works on the installed client.
