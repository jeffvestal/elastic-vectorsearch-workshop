# Handoff — elastic-vectorsearch-workshop

**Updated:** 2026-06-26
**Workshop:** AI Engineer World's Fair, June 29 — 3 days out
**Repo:** https://github.com/jeffvestal/elastic-vectorsearch-workshop (public)

This file captures context a fresh session can't pick up from a code scan. Everything
mechanical (file layout, query content, cell structure) is in the code and `README.md`.

---

## Current state (as of 2026-06-26)

All four labs **verified live** against a real Serverless cluster (ES 9.5.0, Jina v5).
Every trap query's SEM/BM25/RRF rank confirmed, all notebooks execute end-to-end clean,
EIS LLM calls return.

**This session (2026-06-26) added reviewer-requested content, all verified live:**
- **Lab 3 eval (the reviewer's "weak link" fix):** two new cells after the linear-weights
  demo — (1) an MRR weight-sweep that scores every BM25/semantic linear split against the
  `JUDGMENTS` set and compares the best to RRF; (2) a strategies×queries **heatmap**
  (matplotlib, with a text-grid fallback). Live numbers: BM25 0.675, Semantic 0.875,
  RRF 1.000; best linear (sem 0.6–0.7) **ties** RRF only after measuring, while 0.5/0.5
  scores 0.750. RRF is the only all-green heatmap row. This is the "measure it, don't
  assert it" story the reviewer wanted.
- **Lab 4 multi-hop fix:** the hand-rolled agent now reliably fires ≥2 hops. The old bug
  was threefold — prompt said "use LOOKUP only once," the demo question was single-hop,
  and `startswith("ANSWER:")` missed the model's `# ANSWER:`. New prompt invites one
  focused follow-up; `parse_action()` strips markdown + matches the token case-insensitively;
  demo question is now genuinely two-part (yellow/unassigned shards → allocation-explain API).
- **Lab 4 Part 3 — Agent Builder closer (NEW finale):** the Lab 3 RRF retriever, expressed
  as one ES|QL `FORK … FUSE` statement, registered as an Agent Builder **tool**; a multi-hop
  **agent** wired to it; both created via the Kibana API. Notebook runs it through `converse`
  (shows ≥2 tool calls), then attendees drive it in the AB Kibana UI. See "Agent Builder"
  section below — several non-obvious facts there.

`main` is the source of truth. See "Two delivery paths" below — non-obvious, bit us once.
**This session's changes were NOT yet committed/pushed at handoff time if you're reading a
fresh clone — check `git log`.**

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

## Agent Builder (Lab 4 Part 3) — non-obvious facts

The new closer creates an AB tool + agent via the **Kibana** API (`/api/agent_builder/...`).
Several things that cost time this session, so you don't re-discover them:

- **AB is a Kibana API, not ES.** Calls go to `KIBANA_URL` (the `.kb.` host), authenticated
  by the same `ES_API_KEY`. The notebook + `agent-builder/setup_agent.py` both read
  `KIBANA_URL`. The sandbox already stored the Kibana endpoint as agent var `ES_KIBANA_URL`;
  the boot script now also exports it as `KIBANA_URL` and runs `setup_agent.py`.
- **FUSE == RRF(rank_constant 60).** The Lab 3 hybrid retriever is reproduced *exactly* in
  ES|QL as `FROM ... | FORK (match body) (match body_semantic) | FUSE`. Verified the ranking
  is byte-identical to the `_search` `rrf` retriever (doc-049 #1 on the paraphrase query,
  same scores). `FUSE` needs a `LIMIT` **inside each FORK branch** or you get a 400
  ("FUSE can only be used on a limited number of rows").
- **esql tool param type is `string`, not `text`/`keyword`.** The AB tool param schema only
  accepts string/integer/float/boolean/date/array — NOT ES field types. Using `keyword` or
  `text` returns a 400. (Cost two failed creates before I read the validation error.)
- **AB + Workflows are BOTH enabled** on the vector-optimized Serverless project (verified:
  `/api/agent_builder/tools`, `/api/agent_builder/agents`, `/api/workflows` all 200). We use
  AB only — no workflow needed, because FUSE gave us hybrid in one ES|QL statement.
- **Multi-hop is native.** The agent calls its search tool more than once on its own (driven
  by the system prompt's "How you work" steps); no loop code. Verified live: a two-part
  question ("exit code 137 — why AND which JVM settings") produced 2 `tool_call` events in
  the converse trace, grounded answer.
- **Idempotent provisioning.** `setup_agent.py` deletes the agent then the tool (agent
  references tool) before recreating — safe to re-run. Tool id `search-workshop-docs-hybrid`,
  agent id `workshop-docs-agent`.
- **`instruqt/04-why-it-matters/lab4.ipynb` is the STALE/unused copy.** The sandbox serves
  `notebooks/lab4-rag-pipeline.ipynb` (that's what's copied to Jupyter and what the tab path
  points at). The Part 3 + multi-hop fix went into the served notebook ONLY. The instruqt copy
  was deliberately left alone — see "Open items" for the decision to delete it.

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
