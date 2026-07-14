# Facilitator Guide — Spoken Intro & Per-Lab Check-Ins

> AIEWF 2026 · **"Vector Isn't Enough: Hybrid Search & Retrieval for AI Engineers"**
>
> Format: attendees walk the labs self-paced; instructor regroups every ~20–25 min with a short
> recap of the lab just finished. Intro slide lives in Google Slides (see end of file).

---

## Spoken intro (~90 seconds)

> "Quick show of hands — who's shipped something with RAG in the last year? ... Okay, now who's a little tired of hearing the word 'RAG'?
>
> Here's the thing. A year ago RAG was the *headline* — 'retrieval augmented generation,' the whole architecture diagram on every slide. Today nobody demos 'a RAG app' anymore. But it didn't go away. It went **into the background** — and it got *more* important, not less.
>
> Because here's what changed: agents got good. Agents now decide *when* to retrieve, retrieve *multiple times*, chain lookups together. And every one of those retrieval calls is a chance to feed the model garbage. The model got smarter — but a smart model with the wrong context still gives you a confidently wrong answer. The agent is only as good as what you put in front of it.
>
> So this workshop is about the layer everyone stopped talking about and quietly started depending on more: **retrieval.** We're going to prove, with live queries against your own Elastic cluster — not slides — that in a RAG or agent pipeline, **retrieval quality, not model quality, is what bounds your answer.**
>
> You'll do this yourself. Vector search, where it breaks, how hybrid fixes it, and then wire it to a model and an agent and watch the *same model* give a great answer and then a terrible one — where the only thing that changed was the retrieval."

---

## What you'll learn / why you care (the slide version)

**You'll learn to:**
- Run semantic, keyword, and **hybrid** retrieval in Elasticsearch — and explain *why* each one fails where it does
- Build and tune a production hybrid retriever (RRF) that wins on every query type
- Wire retrieval to an LLM and an agent, and prove retrieval is the ceiling on answer quality

**Why you care:** *Everyone* reaches for "use a better model" when their AI app gives bad answers. Usually the model is fine — the retrieval is wrong. Fixing retrieval is cheaper, faster, and has way higher ROI than upgrading the model. That's the skill that survives the next model release.

**The one line to anchor it all:** *"The model didn't get dumber. The retrieval got worse."*

---

## Per-lab check-in lines

Short recaps to say when you regroup — what they *just proved*, then point at the next lab.

**After Lab 1 — Vector Search**
> "You just ran semantic search matching on *meaning* — found the TLS doc by asking about 'securing cluster traffic,' no keyword overlap. And Elastic generated the embeddings server-side; you wrote zero ML code. Feels like magic. Next lab we break it."

**After Lab 2 — Where Vector Breaks**
> "You found the cracks in *both* methods. Semantic blurs exact tokens — error codes, version numbers, config keys all collapse into the same fuzzy neighborhood. And BM25 buries anything phrased differently than the doc. You read the scores, so you didn't take my word for it. Neither one is safe alone — which is the whole setup for hybrid."

**After Lab 3 — Hybrid Search**
> "You fused them with RRF into one retriever that wins on *every* query that broke the others — and you didn't eyeball it, you measured it with MRR and the heatmap. The punchline: RRF needs zero tuning. You *can* match it by hand-tuning linear weights, but that win goes stale the moment your corpus or model changes. This is your production default."

**After Lab 4 — Why It Matters for Agents**
> "Here's the payoff. Same model, same question — good retrieval gave a great answer, deliberately bad retrieval gave 'I don't have enough information.' The model never changed. Then you took the *exact same Lab 3 retriever* up three abstraction levels: a one-shot RAG call, a hand-rolled multi-hop loop, and a real Agent Builder agent. The agent framework is swappable. Retrieval quality is not."

**After Lab 5 — Reranking (bonus)**
> "If you got here: you added a precision layer on top of hybrid — a rerank stage — and saw pointwise vs. listwise rerankers go head-to-head. The skill is knowing *when* it's worth the latency, and when your stage-1 results are already crisp enough to skip it."

---

## Intro slide

Single Elastic-branded intro slide (the "slide version" section above):
https://docs.google.com/presentation/d/1DOmkvjVbWfYqqDPrYbKyfnx7bV6F187L_PN7b6MkTLY/edit
