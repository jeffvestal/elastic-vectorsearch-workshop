---
slug: esql-rag-pipeline
id: fcyqazxcbzlu
type: challenge
title: 'Lab 4 — Why It Matters: A Whole RAG Pipeline in One ES|QL Query'
teaser: Express FORK | FUSE | RERANK | COMPLETION as a single ES|QL statement, then
  prove same model + worse retrieval = worse answer. Finish with a multi-hop agent.
tabs:
- id: mzx4qxb4x8rp
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /notebooks/lab4-esql-rag-pipeline.ipynb
  port: 8888
- id: uihj8qdz8x5k
  title: Kibana Discover
  type: service
  hostname: kubernetes-vm
  path: /app/discover
  port: 30001
  custom_request_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self'' https://kibana.estccdn.com; worker-src blob: ''self'';
      style-src ''unsafe-inline'' ''self'' https://kibana.estccdn.com; style-src-elem
      ''unsafe-inline'' ''self'' https://kibana.estccdn.com'
  custom_response_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self'' https://kibana.estccdn.com; worker-src blob: ''self'';
      style-src ''unsafe-inline'' ''self'' https://kibana.estccdn.com; style-src-elem
      ''unsafe-inline'' ''self'' https://kibana.estccdn.com'
- id: usl8miwpbdg0
  title: Agent Builder
  type: service
  hostname: kubernetes-vm
  path: /app/agent_builder
  port: 30001
  custom_request_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self'' https://kibana.estccdn.com; worker-src blob: ''self'';
      style-src ''unsafe-inline'' ''self'' https://kibana.estccdn.com; style-src-elem
      ''unsafe-inline'' ''self'' https://kibana.estccdn.com'
  custom_response_headers:
  - key: Content-Security-Policy
    value: 'script-src ''self'' https://kibana.estccdn.com; worker-src blob: ''self'';
      style-src ''unsafe-inline'' ''self'' https://kibana.estccdn.com; style-src-elem
      ''unsafe-inline'' ''self'' https://kibana.estccdn.com'
difficulty: intermediate
timelimit: 1800
enhanced_loading: null
---
# Lab 4 — Why It Matters: A Whole RAG Pipeline in One ES|QL Query

**Goal:** Show that retrieval — not the model — is the ceiling on answer quality. And do the whole RAG pipeline as a single ES|QL statement: `FORK | FUSE | RERANK | COMPLETION`.

This lab is **notebook-primary** (COMPLETION makes an LLM call per row — fine in a notebook, slow as a Discover spinner). There's a Discover "peek" at the end.

Part 1 — Python Notebook
===

1. Open the [button label="Python Notebook"](tab-0) tab → `lab4-esql-rag-pipeline.ipynb`
2. Run the cells in order. You will:
   - Verify a `completion`-task inference endpoint exists.
   - Build the one-query RAG pipeline in stages: `FORK | FUSE` → add `RERANK` → add `EVAL prompt` + `COMPLETION`.
   - Run the **GOOD vs BAD retrieval** experiment — same model, same question, only the FORK filter changes — and watch the answer fall apart on bad context.
   - Register the same `FORK | FUSE` retriever as an **Agent Builder** tool and drive a multi-hop agent.

***

## The headline query

```esql
FROM aiewf-workshop-docs METADATA _score, _id, _index
| FORK ( WHERE MATCH(body, ?q)          | SORT _score DESC | LIMIT 50 )
       ( WHERE MATCH(body_semantic, ?q) | SORT _score DESC | LIMIT 50 )
| FUSE | SORT _score DESC | LIMIT 20
| RERANK ?q ON body WITH {"inference_id": ".jina-reranker-v3"}
| SORT _score DESC | LIMIT 1
| EVAL prompt = CONCAT("Answer the question using ONLY the document below. Title: ", title, " === Document: ", body, " === Question: ", ?q)
| COMPLETION answer = prompt WITH {"inference_id": ".anthropic-claude-4.5-haiku-completion"}
| KEEP id, title, answer
```
Retrieve → fuse → rerank → generate, in one statement. `COMPLETION` needs a **`completion`**-task endpoint (not the streaming `chat_completion`). Note the `SORT _score DESC` right after `RERANK` — `RERANK` overwrites `_score` but does not reorder rows, so without that sort `LIMIT 1` would grab the pre-rerank (RRF) top doc instead of the reranked one.

Part 2 — Agent Builder
===

After the notebook creates the agent, open the [button label="Agent Builder"](tab-2) tab and chat with **Workshop Docs Agent**. Ask a two-part question (a symptom *and* a fix) and watch it run more than one retrieval hop.

Part 3 — Discover peek (optional)
===

Open the [button label="Kibana Discover"](tab-1) tab, switch to **ES|QL** mode, and paste the headline query (with the `?q` replaced by a literal question in all three places). It runs end-to-end in the UI — including the LLM call — and the answer lands in one `answer` cell.

> ⏱️ **Expect a multi-second spinner** — Discover waits on the reranker *and* the LLM. That latency is why this lab is notebook-primary; the peek is just to *see* a full RAG pipeline run as a database query.

**Click Next** for the bonus reranking lab.
