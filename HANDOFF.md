# Handoff — elastic-vectorsearch-workshop
**Date:** 2026-06-22  
**From:** Barry B Foldin  
**To:** Miss Labonz  
**Workshop:** AI Engineer World's Fair, June 29 — 7 days out

---

## State

All workshop content has been built and lives in this repo. Nothing has been tested against a live Elasticsearch cluster yet. The repo is public at:

```
https://github.com/jeffvestal/elastic-vectorsearch-workshop
```

---

## What's Built

```
corpus/
  docs.json                  60 real Elastic docs, 13 annotated trap docs
  ingest.py                  Creates index + bulk-indexes corpus against any Serverless ES project
  TRAP_QUERY_VALIDATION.md   Pre-event checklist — exact queries, expected doc IDs, why each trap works

instruqt/
  track.yml                  4 challenges, 30 min each
  01-vector-search/          Lab 1: semantic_text + EIS/Jina, Dev Console
  02-where-vector-breaks/    Lab 2: adversarial queries (vector fails) + BM25 rescue + paraphrase trap
  03-hybrid-search/          Lab 3: RRF + linear combination, the heart (40 min)
  04-why-it-matters/         Lab 4: hybrid + LLM synthesis, pre-baked good/bad context pairs

reference-repo/              Attendee take-home — self-contained, runs against any Serverless project
  README.md
  labs/lab1..lab4.ipynb
  corpus/docs.json + ingest.py

README.md                    Instructor guide: time budget, pre-event checklist, presenter notes
```

---

## Critical Path Before June 29

These are **human-gated** — cannot be done by an agent.

### 1. Instruqt notebook-tab check (HARD GATE — do this first)
The outline calls this the top gate before finalizing Lab 4. Lab 4 currently assumes a notebook tab can be opened in the Instruqt sandbox alongside Kibana, pointing at the same ES endpoint.

**Action:** Open the Instruqt track editor. Check if `managed-vm-elastic-9-4-0` sandbox preset supports a notebook/code-server tab. If **yes** → Lab 4 in-room is the notebook. If **no** → Lab 4 in-room becomes instructor-driven notebook on screen; attendees follow along, do it at home with `reference-repo/`.

See `instruqt/track.yml` — there's a `# HARD GATE` comment where the notebook tab would be configured.

### 2. Run ingest.py against a real Serverless project

```bash
export ES_ENDPOINT="https://your-project.es.us-east-1.aws.elastic.cloud"
export ES_API_KEY="your-api-key"
cd corpus
pip install elasticsearch
python ingest.py
```

Verify: `GET aiewf-workshop-docs/_count` → should return `{"count": 60}`.

### 3. Validate trap queries against the live index

Open `corpus/TRAP_QUERY_VALIDATION.md` and run every query. Fill in the "Verified" checkboxes.

The most critical: **"user can't log in"** paraphrase trap.
- Semantic query → doc-001 (SAML auth troubleshooting) should appear in top 3
- BM25 query → doc-001 should NOT appear in top 5

If doc-001 doesn't behave as expected, `TRAP_QUERY_VALIDATION.md` names a fallback doc (doc-002).

### 4. EIS model availability check

In the Serverless project Dev Console, confirm these inference endpoints exist:
```
GET _inference/_all
```
Need: `.jina-embeddings-v5-text-small` (used by `semantic_text`) and `.jina-reranker-v2-base-multilingual` (Lab 3 pre-run cell).

---

## Lab 4 — API Key Setup

`lab4.ipynb` uses `claude-haiku-4-5-20251001` for synthesis. You'll need an Anthropic API key set as `ANTHROPIC_API_KEY`. The good/bad context pairs are pre-baked (hardcoded) — the LLM call is real but the context fed to it is deterministic.

---

## Open Questions (unresolved as of 2026-06-22)

- [ ] Co-presenters from Search spec team — has Mayzak confirmed anyone helping?
- [ ] Logistics from conference org — slide template, room setup, projector, WiFi for attendees?
- [ ] Instruqt provisioning — how do attendees get sandbox access? Via a code at the door?

---

## Where Things Live

| Item | Location |
|---|---|
| Workshop repo (this) | `~/repos/elastic-vectorsearch-workshop` |
| Project file (KK) | `~/repos/kuchi-kopi/projects/aiewf-2026-ai-search-workshop.md` |
| Original outline | `~/repos/kuchi-kopi/drafts/aiewf-workshop-outline-2026-05-28.md` |
| GitHub | https://github.com/jeffvestal/elastic-vectorsearch-workshop |
