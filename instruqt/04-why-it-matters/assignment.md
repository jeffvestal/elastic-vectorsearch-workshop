---
slug: why-it-matters
id: iv9mcrwqbj4z
type: challenge
title: 'Lab 4 — Why It Matters for Agents: Do You Even Need a Model?'
teaser: Wire the Lab 3 hybrid retriever to an LLM. Prove that retrieval quality —
  not model quality — determines answer quality. Most of a RAG pipeline is a database
  problem.
tabs:
- id: xbqxhnhzzklv
  title: Elastic Cloud Serverless
  type: service
  hostname: kubernetes-vm
  path: /app/dev_tools
  port: 30001
- id: qr9t7hhxongj
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /
  port: 8888
difficulty: intermediate
timelimit: 1800
enhanced_loading: null
---
# Lab 4 — Why It Matters for Agents: Do You Even Need a Model?

**Goal:** Wire the Lab 3 hybrid retriever to an LLM. Compare good context vs bad context. Prove that retrieval quality — not model quality — determines answer quality.

Open the **Python Notebook** tab and run the cells in order.

---

## What the notebook does

**Cell 1–3:** Setup — imports, reads `ES_ENDPOINT` and `ES_API_KEY` from environment (pre-loaded from Lab 1 setup).

**Cell 4:** `synthesize(context_docs, question)` — sends context + question to Claude, returns the LLM's answer.

**Cell 5 (pre-baked):** Good context + question → good answer. The model explains TLS cluster encryption correctly because the retrieved docs are relevant.

**Cell 6 (pre-baked):** Bad context + same question → bad/hallucinated answer. Same model, same question, wrong retrieval → wrong answer.

**Cell 7 — [INSTRUCTOR DEMO]:** Live hybrid retrieval → synthesis. Runs the Lab 3 RRF retriever, feeds real retrieved docs to the LLM, calls Claude via the workshop LLM proxy.

---

## The thesis

> "The model didn't get dumber. The retrieval got worse."

In a RAG system, answer quality is bounded by retrieval quality. A better model cannot compensate for bad context. Most of a RAG pipeline is a **database problem**, not a model problem.

---

## Take-home cells

**Cell 7b and Cell 8** are marked `[TAKE-HOME]` — run these after the workshop with your own Elastic Serverless project and Anthropic API key to experiment with reranking and multi-turn retrieval.