# Handoff — ES|QL migration (branch `esql-track`)

**Updated:** 2026-07-14
**Branch:** `esql-track` (pushed to `origin`, NOT merged to `main`)
**Repo:** https://github.com/jeffvestal/elastic-vectorsearch-workshop
**Last commit on branch:** `329df6c` — "ES|QL track: notebooks, Instruqt assignments, docs"

This file captures the state a fresh session (or a second laptop) can't pick up from a code
scan. It is specific to the ES|QL migration. General workshop context that is shared with the
DSL track lives in the root `HANDOFF.md`, `README.md`, and `corpus/TRAP_QUERY_VALIDATION.md`.

---

## Why this branch exists

The ES|QL work was authored and live-validated on the primary laptop but had **never been
committed** — it existed only as untracked files (`docs-esql/`, `instruqt-esql/`,
`notebooks-esql/`, root `FACILITATOR.md`). This branch was created to get it into git so it can
be continued on the second machine (**Miss LaBonz**). `main` is deliberately untouched.

To pick up on the other machine:

```
git fetch origin
git checkout esql-track
```

The gitignored `.env` (ES_ENDPOINT + ES_API_KEY) is **not** in the branch — copy it over
separately or re-create it. Dev-cluster creds are never committed (see root HANDOFF "Dev/test
cluster").

---

## What the ES|QL edition is

A **parallel** track — the ES|QL edition of "Vector → Hybrid → Do You Even Need a Model?".
Same corpus, same thesis, same five labs; every retrieval operation expressed in **ES|QL**
instead of the `_search` retriever DSL. It **coexists** with the original DSL track — nothing in
`instruqt/`, `notebooks/`, `corpus/`, or `agent-builder/` is modified. Corpus and Agent Builder
setup are **shared**.

| | DSL track | ES|QL track |
|---|---|---|
| Labs 1–3 & 5 surface | Kibana Dev Console | Kibana **Discover** (ES\|QL mode) |
| Lab 4 surface | Notebook | Notebook (+ Discover "peek") |
| Semantic | `semantic` retriever | `MATCH(body_semantic, q)` |
| BM25 | `multi_match ["title^3","body"]` | `MATCH(title,q,{"boost":3}) OR MATCH(body,q)` |
| Hybrid RRF | `rrf` retriever | `FORK (…)(…) \| FUSE` |
| Linear | `linear` retriever + MinMax | `FUSE LINEAR WITH {"weights":…,"normalizer":"minmax"}` |
| Rerank | `text_similarity_reranker` | `RERANK q ON body WITH {...}` |
| LLM synthesis | Python SSE to `_inference/chat_completion/_stream` | `COMPLETION` command |
| Lab 2 "read the score" | `explain=True` | two queries (title-only vs body-only); `SCORE(MATCH())` bonus |

**Headline:** Lab 4's entire RAG pipeline is **one ES|QL query** — `FORK \| FUSE \| RERANK \|
COMPLETION` — no orchestration code.

---

## Current status

### ✅ Done — authored and live-validated
- **All 5 lab notebooks** (`notebooks-esql/lab1..lab5`) — complete, execute end-to-end.
- **All 5 Instruqt `assignment.md`** + `instruqt-esql/track.yml`.
- **Docs** (`docs-esql/`): `README-ESQL.md`, `FACILITATOR-ESQL.md`,
  `TRAP_QUERY_VALIDATION_ESQL.md` (status: **VALIDATED**).
- **Full live validation pass 2026-07-01** on the serverless dev cluster
  (`vectorsearch-workshop-dev`, ES 9.5.0, index `aiewf-workshop-docs`, 62 docs). FORK\|FUSE,
  FUSE LINEAR, RERANK, COMPLETION, and the one-query `FORK\|FUSE\|RERANK\|COMPLETION` pipeline
  all confirmed working. Detail in `TRAP_QUERY_VALIDATION_ESQL.md`.

### ⚠️ Not done — two blockers before this can run for attendees

1. **Instruqt track has never been pushed.** All 5 `assignment.md` files still contain
   `REPLACE_CHALLENGE_ID_*` and `REPLACE_TAB_*` placeholders, and `track.yml` intentionally has
   no `id`/`checksum`. See **"Deploying the Instruqt track"** below.
2. **Not on `main`.** Notebooks + corpus reach a sandbox via `git clone` of `main` at boot
   (see root HANDOFF "two delivery paths"). Until these are merged/pushed to `main`, a sandbox
   boot will **not** serve the ES|QL notebooks. Decide with Jeff whether the ES|QL track ships
   from `main` or from its own branch/setup script before relying on a sandbox.

---

## Deploying the Instruqt track (HARD ORDERING — you cannot push placeholders)

Run from `instruqt-esql/`. You must mint real ids before the first push:

```
cd instruqt-esql
instruqt track create        # registers the track, assigns the track id
instruqt challenge create    # ×5 — mints a real challenge id + tab ids per lab
```

Then replace every placeholder in the 5 `assignment.md` files with the minted ids:

| Placeholder | Where |
|---|---|
| `REPLACE_CHALLENGE_ID_1..5` | each `assignment.md` frontmatter `id:` |
| `REPLACE_TAB_DISCOVER_1..5` | the Kibana Discover tab `id:` (all labs except pure-notebook) |
| `REPLACE_TAB_NB_1..5` | the Python Notebook tab `id:` |
| `REPLACE_TAB_AB_4` | Lab 4 Agent Builder tab `id:` |

Then:

```
instruqt track push --force
```

`track.yml` `id`/`checksum` are intentionally absent — Instruqt assigns/recomputes both on
first push. **Do not** copy them from the DSL track (a stale checksum makes `--force` reject).

---

## The behavioral quirks that drove content decisions (live-confirmed, don't "fix" back)

These are ES|QL-specific differences from the retriever DSL. Each one changed a lab; reverting
any of them re-breaks the demo. Full detail in `TRAP_QUERY_VALIDATION_ESQL.md`.

1. **ES|QL BM25 SUMS field scores; DSL `best_fields` takes MAX.** So `MATCH(title,q,{boost:3})
   OR MATCH(body,q)` on `exit code 137` sends a boosted-title distractor (doc-061) to BM25 #1.
   Lab 2 is reframed to teach this as the *same* field-boost mechanism as the 8.18 trap — not a
   bug. Don't switch to body-only globally (the 8.18 boosted-title trap needs the title clause).
2. **FUSE LINEAR renormalizes so fused #1 always = 1.0, per-branch MinMax.** The DSL 8.18
   weight-backfire demo does NOT reproduce. Replacement query that DOES flip cleanly:
   `notify me when something goes wrong` (target doc-049) — 0.8/0.2 BM25-lean sinks it to #4,
   0.3/0.7 semantic-lean restores #1.
3. **FUSE LINEAR weights must be positive** — weight 0.0 → HTTP 400. Can't demo a pure single
   branch via a zero weight.
4. **`RERANK` overwrites `_score` but does NOT reorder rows.** Every `RERANK` MUST be
   immediately followed by `| SORT _score DESC`, or `LIMIT N`/`KEEP` silently returns the
   pre-rerank (RRF) order with new scores attached. This was a real bug fixed in **three**
   places: Lab 5 `q_rerank()` helper, Lab 4 `Q_RETRIEVE`/`Q_RAG`/Discover-peek, and the Lab 4/5
   `assignment.md` literal query blocks. Rule is now baked into the docs.
5. **`SCORE(MATCH(...))` works** (per-clause score as a column) — a cleaner `explain=True`
   replacement, promoted to a Lab 2 bonus. Zero-arg `SCORE()` still errors.
6. **No multi-field MATCH** — `MATCH("title,body", q)` and `MULTI_MATCH` both rejected. Use
   OR-composed MATCH or QSTR.
7. **Lab 4 GOOD-context question** is `How does Index Lifecycle Management move data through
   hot, warm, and cold phases?` → retrieves doc-017 (real how-to) → grounded answer. The old
   SAML question was confirmed broken live (GOOD context also answered "I don't have enough
   information," collapsing the good/bad contrast) — replaced everywhere.
8. **`.anthropic-claude-4.5-haiku-completion`** is the `completion`-task endpoint for
   `COMPLETION` (NOT the streaming `chat_completion`). Confirmed present on the dev cluster.

---

## Files on this branch

```
notebooks-esql/     lab1..lab5 ES|QL notebooks (es.esql.query())
instruqt-esql/      track.yml + 5 assignment.md + setup-kubernetes-vm
docs-esql/          README-ESQL, FACILITATOR-ESQL, TRAP_QUERY_VALIDATION_ESQL, this handoff
FACILITATOR.md      (root) spoken intro / per-lab check-in lines
corpus/             SHARED, unchanged (index aiewf-workshop-docs, 62 docs)
agent-builder/      SHARED, unchanged (AB tool is already an ES|QL FORK+FUSE)
```

---

## Next steps (in order)

1. **Decide the delivery path for `main`** with Jeff — merge ES|QL into `main`, or keep it on a
   branch with its own setup script. Sandbox boot clones `main`, so this gates everything.
2. **Mint Instruqt ids and `track push --force`** (section above) — replaces the `REPLACE_`
   placeholders.
3. **Pre-event validation on a FRESH sandbox** — old sandboxes don't re-clone. Checklist in
   `README-ESQL.md` ("Pre-event checklist"): corpus count = 62, all 4 inference endpoints
   present, Discover data view exists, trap ranks reproduce, Lab 4 COMPLETION runs, AB agent
   shows ≥2 hops.
4. **Discover orientation** is the #1 attendee friction point — data view + ES|QL mode +
   `METADATA _score`. Called out in `FACILITATOR-ESQL.md`.
