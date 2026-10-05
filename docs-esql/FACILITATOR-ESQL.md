# Facilitator Guide (ES|QL edition) — Spoken Intro & Per-Lab Check-Ins

> **"Vector Search: Vector, Keyword, and Hybrid Retrieval"** — ES|QL edition (ElasticON NYC, Oct 2026)
>
> Labs 1–3 & 5 run in **Kibana Discover** (which now opens straight into ES|QL); Lab 4 is a notebook + the Agent Builder chat. Attendees walk self-paced; regroup after each lab with a recap, then brief the next lab from the deck.
>
> **Two decks, both in `elastic/field-workshop-assets-public` → `workshops/vector-keyword-hybrid-retrieval/`:**
> 1. **`briefing/`: present first, about 10 minutes, before Lab 1.** A 15-slide concept deck in Dave Erickson's style.
>    - Topics: words vs meaning, BM25/IDF, embeddings, `semantic_text` + EIS, Flat/HNSW/DiskBBQ, BBQ, scores-don't-mix → RRF, the relevance pyramid, recall → precision, RAG + agents, and MRR.
>    - Most slides are interactive: click the buttons on the slide. Arrow keys move between slides.
>    - Slides 03–05, 07 and 10 use real data from the workshop index.
>    - Attendees have it in the **Briefing** tab of every lab (port 5000).
>    - Present from your laptop with speaker notes: `cd briefing/src && fslides serve`, then press **N**. Or open `briefing/index.html` and press **N**; the notes are baked in.
>    - Talk track: `briefing/slides.md`.
> 2. **`intro/`: the between-lab deck.** It has a brief and a recap slide per lab, a "which retriever when" slide, and a troubleshooting backup slide. Open `intro/index.html` locally and use the arrow keys to advance.

---

## Spoken intro (~90 seconds)

> "Quick show of hands — who's shipped something with RAG in the last year? ... Now who's a little tired of hearing the word 'RAG'?
>
> A year ago RAG was the headline. Today nobody demos 'a RAG app' anymore — it went into the background and got *more* important, because agents now decide when to retrieve, retrieve multiple times, chain lookups. Every one of those calls is a chance to feed the model garbage. A smart model with the wrong context still gives a confidently wrong answer.
>
> So this workshop is about the layer everyone stopped talking about and quietly started depending on more: **retrieval.** And we're going to write all of it in **ES|QL** — one piped query language, the same way you'd write a database query. Vector, keyword, hybrid, reranking, and — the part that surprises people — the *LLM call itself*, all as ES|QL. By the end you'll express an entire RAG pipeline as a single query.
>
> We prove it with live queries against your own Elastic cluster — not slides — that in a RAG or agent pipeline, **retrieval quality, not model quality, bounds your answer.**"

---

## One ES|QL habit to repeat all day

> "Two things every query needs: start with `METADATA _score`, and end with `SORT _score DESC`. Without `METADATA _score`, `MATCH` is just a yes/no filter — no ranking. That one keyword is the difference between a filter and a search."

And the Discover reminder:
> "Discover opens with an ES|QL editor and a default `FROM *,-.*` query. Select all, paste the lab's query, click **Search**. The `FROM` line picks the index — no data view to choose."

---

## What you'll learn / why you care (the slide version)

**You'll learn to:**
- Run semantic, keyword, and **hybrid** retrieval in **ES|QL** — and explain *why* each one fails where it does
- Build a production hybrid retriever with `FORK | FUSE` (RRF) that wins on every query type
- Express an entire RAG pipeline — retrieve, rerank, *and generate* — as one ES|QL statement

**Why you care:** Everyone reaches for "use a better model" when their AI app gives bad answers. Usually the model is fine — the retrieval is wrong. Fixing retrieval is cheaper, faster, higher-ROI than upgrading the model. And ES|QL lets you build and inspect the whole pipeline in one place.

**The one line to anchor it all:** *"The model didn't get dumber. The retrieval got worse."*

---

## Per-lab check-in lines

**After Lab 1 — Vector Search**
> "You ran semantic search in ES|QL — matched the TLS doc by asking about 'securing cluster traffic,' no keyword overlap — and it was *one line*: `MATCH` on a `semantic_text` field. Elastic embedded it server-side; you wrote zero ML code. Next lab we break it."

**After Lab 2 — Where Vector Breaks**
> "You found the cracks in *both* methods. Semantic blurs exact tokens; BM25 buries paraphrases and rewards the wrong boosted title. And notice — ES|QL has no `explain`, so you read the score the honest way: title-only versus body-only, and watched which field drove the match. Neither one is safe alone — that's the setup for hybrid."

**After Lab 3 — Hybrid Search**
> "Two commands — `FORK` to run both searches, `FUSE` to combine their rankings — and you had a retriever that wins on every query that broke the others. You measured it with MRR and the heatmap, not vibes. RRF needs zero tuning; linear can match it only if you hand-tune weights that go stale. RRF is your production default."

**Before Lab 4 — the Agent Builder tip (say it out loud)**
> "In the Agent Builder tab, leave the model as it is — Claude Sonnet 5 is the default. Ask the exit-code-137 question and watch: the agent loads its *Diagnose and Fix* skill, then searches twice — the cause, then the fix. Each search shows up as a `tool: search-workshop-docs-hybrid` chip — you're looking for two."

**After Lab 4 — Why It Matters for Agents**
> "Here's the payoff, and it's wild in ES|QL: `FORK | FUSE | RERANK | COMPLETION` — retrieve, rerank, *and call the LLM* — in a single query. Then same model, same question: good retrieval gave a great answer, bad retrieval gave 'I don't have enough information.' Only the FORK filter changed. Then you ran the *same* retriever as an Agent Builder agent. The framework is swappable; retrieval quality is not."

**After Lab 5 — Reranking (bonus)**
> "You added a precision layer with one pipe stage — `RERANK` — and swapped pointwise for listwise by changing a single `inference_id`. The skill is knowing *when* the latency is worth it, and when your stage-1 results are already crisp enough to skip it."

---

## Slides

Use the two HTML decks (see top of this file): Briefing first, then the intro deck between labs. The old single Google Slides intro slide from AIEWF
(https://docs.google.com/presentation/d/1DOmkvjVbWfYqqDPrYbKyfnx7bV6F187L_PN7b6MkTLY/edit) is superseded.
