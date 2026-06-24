# Trap Query Validation

Pre-event checklist: every query below was run live against the corpus and the **actual
ranks recorded** (no "expected" guesses). Re-run before the workshop if the corpus or
embedding model changes.

- **Cluster verified on:** `vectorsearch-workshop-dev` (Serverless, ES 9.5.0), 62 docs.
- **Embedding model:** `.jina-embeddings-v5-text-small` (auto-assigned by `semantic_text`).
- **Retrievers:** `semantic` (vector), `multi_match` on `title^3,body` (BM25), `rrf` (hybrid).
- Rank = position of the target doc; `1` is best. Verified ranks are exact, not approximate.

> **Result display:** queries `_source` `["id", "title", "summary"]` (plus `version_tags`
> where relevant). Each doc has a one-line neutral `summary` so attendees can see *what* a
> hit is about without reading the full body — it makes the near-tie on `exit code 137`
> legible (the #2 distractor's summary shows it's about crashes, never "137"). `summary` is
> a plain `text` field, **not** copied into `body_semantic`, so it does not affect embeddings
> or ranks. `trap_type` is kept in the corpus (and used as a retrieval filter in Lab 4) but is
> **not displayed** in learner-facing query results — it would spoil the trick. Non-trap docs
> have `trap_type: null`.

> **Why this file was rewritten:** the original trap queries were never run against the
> live index (the model is Jina v5, which is strong enough that the classic "vector can't
> find exact tokens" demos do not reproduce). The queries below are the ones that *actually*
> demonstrate each failure mode, with real ranks. See the per-lab notebooks for the teaching prose.

---

## Failure Mode 1 — Exact identifiers (semantic blurs / mis-ranks)

### Trap 1A — Exit code (semantic *blurs*; near-tie)
- **Query:** `exit code 137` → **target `doc-007`** (JVM / OOMKilled)
- **Verified:** semantic **#1** but at ~0.680 with distractor `doc-061` #2 at ~0.678 (~0.001 gap); BM25 **#1** decisive (~8.4 vs ~6.1). RRF **#1**.
- **Mechanism:** "137" is absorbed into the "process killed" concept; distractors `doc-061`/`doc-062` (no literal "137") crowd it. BM25 pins it via the rare token.
- **Teaching point:** semantic can't *reliably rank* exact identifiers — the ranking is essentially noise. Not a flat miss; a reliability failure.

### Trap 1B — Bare config value (semantic ranks the WRONG doc)
- **Query:** `new_primaries` → **target `doc-008`** (shard allocation settings)
- **Verified:** semantic **#2** (wrong doc — `doc-021` cluster-health — at #1); BM25 **#1**; RRF **#1**.
- **Teaching point:** a bare symbolic token with no sentence around it lands in the right *neighborhood* but the wrong *document*.

### Trap 1C — Distinctive dotted key (HONESTY: semantic gets it right)
- **Query:** `cluster.routing.allocation.enable` → **target `doc-008`**
- **Verified:** semantic **#1** (~0.79); BM25 **#2**; RRF **#2**.
- **Teaching point:** exact identifiers are a *reliability* problem, not a guaranteed miss — long distinctive keys embed well. Don't overclaim the failure mode.

---

## Failure Mode 2 — BM25 picks the WRONG exact match (boosted title)

### Trap 2A — Version string
- **Query:** `8.18 breaking changes` → **target `doc-057`** (8.18 release notes)
- **Verified:** BM25 **#2** — the WRONG doc `doc-006` ("Elasticsearch breaking changes") is #1 (~12.9 vs ~7.4). Semantic **#1** (understood intent). RRF **#1**.
- **Mechanism (from `explain`):** `doc-006`'s title is literally "breaking changes" and `title` is `^3`-boosted → `title:breaking` ~6.5 + `title:changes` ~6.5 ≈ 12.9. `doc-057` matches rare `8.18` (~5.8) but its title lacks "breaking changes". **Field-boost / phrase-match effect, NOT term frequency.**
- **Teaching point:** BM25 can reward the common, boosted words over the rare token the user cared about.

---

## Failure Mode 3 — Paraphrase / vocabulary gap (BM25 buries it)

### Trap 3A — Paraphrase (PRIMARY)
- **Query:** `notify me when something goes wrong` → **target `doc-049`** (Watcher alerting)
- **Verified:** semantic **#1** (~0.75); BM25 **#5** (buried — top BM25 hits share incidental words); RRF **#1**.
- **`doc-049` vocabulary:** uses `trigger`, `condition`, `actions`, `webhook`, `schedule`; contains none of "notify / something / goes / wrong".
- **Teaching point:** BM25 only scores query terms present in the doc; with no overlap it sinks. *Buried*, not literally zero — a real index still returns it, just too low to use.

### Trap 3B — Paraphrase (SECONDARY)
- **Query:** `reduce storage cost for old logs` → **target `doc-041`** (data tiers)
- **Verified:** semantic **#1**; BM25 **#5**; RRF **#2**.
- **Note:** `doc-041` never says "logs" — weaker burial than 3A. Use as a backup example.

---

## Lab 3 — Hybrid wins on every trap (rank of the target)

| Query | Target | Semantic | BM25 | RRF |
|---|---|---|---|---|
| `exit code 137` | doc-007 | 1 (near-tie) | 1 | **1** |
| `new_primaries` | doc-008 | 2 (wrong #1) | 1 | **1** |
| `8.18 breaking changes` | doc-057 | 1 | 2 (wrong #1) | **1** |
| `notify me when something goes wrong` | doc-049 | 1 | 5 (buried) | **1** |

RRF lands the target at **#1 on all four** — including the two where an individual retriever
mis-ranked it. (Use *rank*, not Recall@5: in a 62-doc corpus a "losing" retriever often still
squeaks the target into the top 5, so Recall@5 ≈ 1.0 everywhere and hides the contrast.)

### Linear retriever — weights matter, and the obvious choice can backfire
- `notify me when something goes wrong`: `0.5/0.5` → distractor `doc-061` #1; `0.3/0.7` (semantic-lean) → `doc-049` #1.
- `8.18 breaking changes`: `0.8/0.2` (BM25-lean) → WRONG `doc-006` still #1; `0.2/0.8` (semantic-lean) → `doc-057` #1.
- **Takeaway:** no single weight is right for every query; RRF (rank-based, no weights) is the robust default.

---

## Distractor docs (added to make Failure Mode 1 real)

| ID | Title | Role |
|---|---|---|
| `doc-061` | Container exit codes when a process is killed (OOM and signals) | Semantic near-neighbor for "exit code 137"; **no literal "137"** so BM25 still ranks doc-007 #1 |
| `doc-062` | Troubleshooting application crashes and restarts | Generic crash/restart prose; second distractor crowding doc-007 |

Both have `trap_type: "distractor"` and `version_tags: ["9.0"]`. If you reindex and doc-007
stops being a near-tie on `exit code 137`, re-check these two docs.

---

## Lab 1 — "Wow" query verification (semantic finds concepts without keyword overlap)

| Query | Verified top result | Why |
|---|---|---|
| `securing cluster traffic` | doc-010 (TLS) #1 | "securing traffic" ≈ "TLS encryption" |
| `how do I back up my cluster data` | doc-037 (snapshot/restore) #1 | "back up data" ≈ "snapshot, restore" |

Both intact after adding the distractors (verified).
