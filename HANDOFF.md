# Handoff — elastic-vectorsearch-workshop

**Updated:** 2026-06-24
**Workshop:** AI Engineer World's Fair, June 29 — 5 days out
**Repo:** https://github.com/jeffvestal/elastic-vectorsearch-workshop (public)

This file captures context a fresh session can't pick up from a code scan. Everything
mechanical (file layout, query content, cell structure) is in the code and `README.md`.

---

## Current state (as of 2026-06-24)

All four labs have been **verified live** against a real Serverless cluster (ES 9.5.0,
Jina v5 embeddings). Every trap query's SEM/BM25/RRF rank was confirmed, all notebooks
execute end-to-end clean, and the EIS LLM calls return. This is a big change from the
prior handoff ("nothing tested against a live cluster") — the labs now match their output.

`main` is the source of truth and is pushed. The Instruqt track is pushed too. See
"Two delivery paths" below — this bit is non-obvious and bit us once.

---

## The one thing that's easy to get wrong: two delivery paths

Content reaches attendees by **two independent mechanisms**. Both must be updated or the
sandbox runs stale content:

1. **Notebooks + corpus** → the sandbox setup script (`instruqt/01-vector-search/setup-kubernetes-vm`)
   does `git clone` of GitHub `main` at boot, runs `ingest.py`, and copies the `.ipynb`
   files into Jupyter. So **notebook/corpus fixes go live by pushing to `main`** — no
   Instruqt push needed. A sandbox started before your push has the old code baked in.
2. **assignment.md / queries.md / track.yml (the Dev Console UI)** → delivered by
   `instruqt track push --force` (run from the `instruqt/` dir). GitHub does NOT update these.

**Standing rule for this repo (Jeff's instruction):** when you finish a change, commit +
`git push origin main`, and ALSO `instruqt track push --force` if any Instruqt UI file
changed. Don't wait to be asked. (Saved in agent memory as `feedback_done_means_commit_and_push`.)

**Always verify on a FRESH sandbox** — old ones don't re-clone.

---

## Why the corpus/queries are the way they are (the big rework)

The original labs were written assuming a *weak* embedding model. The live corpus runs
**Jina v5**, which is strong enough that the classic "vector can't find exact tokens"
demos **taught the opposite of the live output**. The whole chain was reworked so every
example does on the cluster exactly what the prose says. Key decisions baked in:

- **Distractor docs (doc-061, doc-062)** were added specifically so `exit code 137` is a
  *genuine* semantic near-tie (doc-007 #1 by ~0.001 over doc-061), not an asserted one.
  They deliberately omit the literal "137". If you re-ingest and doc-007 stops being a
  near-tie, that's the knob — re-check those two docs.
- **`summary` field** on all 62 docs is shown in result tables instead of `trap_type`.
  It's a NEUTRAL description of each doc (what it's about), NOT a "why it ranks" hint —
  that would spoil the lesson. It is plain `text`, NOT copied into `body_semantic`, so it
  does not affect embeddings or ranks (verified: ranks identical before/after).
- **`trap_type`** is real JSON `null` for non-trap docs (was the literal string `"null"` —
  a bug). It's hidden from learner-facing results but kept for the Lab 4 filter demo.
- **The `8.18 breaking changes` mechanism is field-boost, NOT term frequency.** The explain
  output shows title terms carry boost 6.6 (= 2.2 × the `title^3` boost) vs body 2.2 — that's
  why doc-006's common-word title beats doc-057. Don't relabel it a "TF trap"; the prose is
  deliberately precise about this because it's the kind of thing that gets challenged.
- `reference-repo/` was DELETED — it was a stale parallel chain with the old broken queries.

Full verified ranks: `corpus/TRAP_QUERY_VALIDATION.md` (filled from real runs, not assumed).

---

## EIS gotcha (cost a real bug, now fixed — don't reintroduce)

The Elastic Inference Service `chat_completion` task type is **streaming-only**. A
non-streaming `_inference/chat_completion` call returns HTTP 400. Lab 4 uses the
`/_stream` endpoint and parses SSE chunks. If you add an LLM call, use `_stream` (or the
`completion` task type for non-streaming). Saved in memory as `ref_eis_chat_completion_streaming`.

---

## Lab 4 security framing (deliberate — don't "simplify" it back)

The Lab 4 "security" section was rewritten because the original called an application-side
`bool.filter` "DLS/RBAC" — which is wrong and would get torn apart in a technical room.
Current framing, intentionally:
- The filter demo is reframed as "**retrieval shapes what the LLM sees**" (a scope/correctness
  point) and explicitly says a self-written filter is NOT access control.
- A separate cell covers REAL access control: RBAC (index-level) + DLS (row-level), enforced
  on the **credential's role**, with real `create_api_key` + DLS role-descriptor code shown
  as reference — **not run**.
- **Why DLS isn't run live:** the sandbox key is a *managed API key*, and Serverless blocks an
  API key from minting a privilege-bearing child key (`creating derived api keys requires an
  explicit role descriptor that is empty` — verified live). A runnable DLS demo would need an
  admin/user credential with `manage_security`. Jeff said: if everything else is clean and
  there's time, we can attempt a genuinely-runnable DLS demo later — otherwise leave as-is.

Note the two Lab 4 files use DIFFERENT RAG questions, both correct:
- `instruqt/04-why-it-matters/lab4.ipynb` (instructor, pre-baked context) → Watcher question
  ("How do I get notified when something goes wrong in my cluster?")
- `notebooks/lab4-rag-pipeline.ipynb` (repo, live retrieval) → SAML question

---

## Dev/test cluster (NOT in the repo — was for development only)

A long-lived dev Serverless project in Jeff's account was used to verify all ranks/queries
this session. Its creds are NOT committed and must NEVER be hardwired — notebooks/labs stay
`os.environ.get()`. The provisioned per-attendee sandbox supplies its own creds via Instruqt
agent variables. Ask Jeff for the dev creds if you need to re-verify; don't go looking for
them in the repo.

`pip` in the sandbox setup pins `elasticsearch>=8.17,<9` (8.x client vs 9.5 server). It works,
but flag it if you ever hit a client/server mismatch.

---

## Open items / human-gated (unchanged, still need a human)

1. **HARD GATE: Instruqt notebook-tab availability** — confirmed working in practice this
   session (Jupyter on :8888, all 4 notebooks served from `/root/notebooks`). Re-verify on a
   fresh sandbox before the event.
2. **Co-presenter scope** with Philipp Krenn — confirm role/content.
3. **Conference logistics** — sandbox access for attendees (code at the door?), slides, WiFi.

---

## Where things live

| Item | Location |
|---|---|
| Workshop repo (this) | `~/repos/elastic-vectorsearch-workshop` |
| Instructor guide + attendee summary | `README.md` |
| Verified trap ranks | `corpus/TRAP_QUERY_VALIDATION.md` |
| GitHub | https://github.com/jeffvestal/elastic-vectorsearch-workshop |
| Instruqt track | https://play.instruqt.com/manage/elastic/tracks/aiewf-2026-vector-hybrid-search |
