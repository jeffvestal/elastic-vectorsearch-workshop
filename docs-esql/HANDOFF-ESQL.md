# Handoff — ES|QL edition

**Updated:** 2026-10-02 (NYC ElasticON readiness pass)
**Repo:** https://github.com/jeffvestal/elastic-vectorsearch-workshop — ES|QL content is **on `main`**
**Live Instruqt track:** `elastic/vector-keyword-hybrid-retrieval`, source in
`elastic/instruqt-field-tracks-dev` → `tracks/vector-keyword-hybrid-retrieval/` (setup clones `main`)

This file captures the state a fresh session (or a second laptop) can't pick up from a code
scan. It is specific to the ES|QL edition. General workshop context that is shared with the
DSL track lives in the root `HANDOFF.md`, `README.md`, and `corpus/TRAP_QUERY_VALIDATION.md`.

---

## 2026-10-02 re-validation — what changed (read this first)

**Where things live now.** `esql-track` was fast-forwarded into `main`. The dead
`instruqt-esql/` copy (old `aiewf-2026-esql-hybrid-search` slug) was deleted — the field-tracks
repo is the only Instruqt source. The `esql-track` branch is kept frozen as a fallback; nothing
reads it any more. The DSL track is untouched (still `instruqt/` + `notebooks/` on `main`).

**Validated live** (Jeff's Serverless sandbox + a fresh `instruqt track test` sandbox):
setup script clean end to end (~3 min); all 5 notebooks execute with 0 errors; every
`esql` block in every `assignment.md` runs; Discover + Agent Builder UI driven with Playwright.

**Platform drift found and fixed:**
- **Kibana UI redesign.** Discover opens straight into an ES|QL editor (`FROM *,-.*` default,
  **Search** button, "Switch to Classic"); no data view picker, no KQL/ES|QL switcher. Labs 1/2/3/5
  Discover notes rewritten. The data view is still created by setup (harmless, keeps Classic working).
- **Agent Builder** is now "Agents" in the nav. Lab 4's tab now opens
  `/app/agent_builder/agents/workshop-docs-agent` directly (agent pre-selected). Tool calls render
  as `tool: search-workshop-docs-hybrid` chips in the chat.
- **Default LLM is now Google Gemini 3.0 Flash**, which skips the second retrieval hop most of the
  time (5/15 runs did 2 hops). Fixes: agent instructions now REQUIRE a second search for
  cause+fix questions (setup_agent.py AND the Lab 4 notebook copy — keep them in sync); the notebook
  `converse` call pins `connector_id: Anthropic-Claude-Sonnet-4-5` when that preconfigured connector
  exists (6/6 two-hop); Lab 4 page tells attendees to pick **Claude Sonnet 4.5** in the chat's model
  picker (verified: 2 search chips).
- **ES|QL behavior changes:** `FUSE LINEAR` no longer renormalizes the fused #1 to 1.0 (quirk 2 below
  is outdated); linear 0.8/0.2 now puts `doc-049` at #5 (was #4) with `doc-002` #1 — the flip to #1 at
  0.3/0.7 still holds. `MATCH("title,body", q)` is now accepted (quirk 6 outdated; labs never used it).
  `--` is not an ES|QL comment — use `//` (fixed in notebook markdown blocks).
- **Content bugs fixed:** Lab 2 claimed BM25 puts `doc-007` #1 on `exit code 137` — live it is #2
  behind boosted-title distractor `doc-061` (now taught as a field-boost effect). Lab 4 notebook's
  headline block was missing `SORT _score DESC` after `RERANK`. Lab 4 page now has a paste-ready
  literal Discover query instead of "replace `?q` in three places" (there were four).

**Re-run the checks:** `tests-esql/` (see its README) — `run_all.sh` replays the sandbox setup,
executes the notebooks, asserts the teaching claims via `_query`, probes the agent, and drives the
Kibana UI with Playwright. Creds come only from `ES_ENDPOINT` / `ES_API_KEY` / `ES_KIBANA_URL`.
Use a throwaway project: ingest and `setup_agent.py` delete/recreate the index, tool, skill, and agent.
Note `02_assert_claims.py` still encodes some July expectations (linear #4, fused score 1.0,
multi-field MATCH rejected, Lab 2 doc-007 BM25 #1) — those ~9 "failures" are known drift, not bugs.

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
