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
- id: qr9t7hhxongj
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /notebooks/lab4-rag-pipeline.ipynb
  port: 8888
difficulty: intermediate
timelimit: 1800
enhanced_loading: null
---
# Lab 4 — Why It Matters for Agents: Do You Even Need a Model?

**Goal:** Wire the Lab 3 hybrid retriever to an LLM. Compare what happens when you give it good context vs bad context — using the same model, the same question, and the same code. Prove that retrieval quality — not model quality — bounds answer quality.

> **This lab runs entirely in the Python Notebook.** Open the **Python Notebook** tab and run `lab4-rag-pipeline.ipynb`. The cells below walk through what the notebook does and why each step exists.

***

## What a RAG Pipeline Actually Is

RAG (Retrieval-Augmented Generation) has three steps:

1. **Retrieve** — run a search query, get back relevant documents
2. **Augment** — stuff those documents into a prompt as context
3. **Generate** — send the prompt to an LLM, get back an answer

The model only sees what you put in the prompt. It cannot reach outside the context window. If step 1 returns bad documents, steps 2 and 3 will produce a bad answer no matter how good the model is.

***

## Notebook walkthrough

**Cells 1–3: Setup**

Imports, connects to Elasticsearch using `ES_ENDPOINT` and `ES_API_KEY` from the environment (these were pre-loaded when the sandbox started). Verifies the index is there and has documents.

**Cell 4: The LLM call**

Defines `synthesize(context_docs, question)`, which:
- Builds a prompt from the retrieved documents ("Here are N sources. Answer only using these.")
- Calls the LLM via the Elastic Inference Service — the same `ES_API_KEY` you use for search also authenticates the LLM call; no separate API key
- Returns the model's answer

> **Why EIS for the LLM?** The workshop uses Claude via Elastic's Inference Service instead of a direct Anthropic key. This keeps the architecture consistent — one endpoint, one credential, search and LLM in the same system.

**Cell 5: Run hybrid retrieval — see what comes back before the LLM sees it**

Runs the Lab 3 RRF hybrid retriever and prints the retrieved document titles, snippets, and scores.

> **What you should see:** Relevant Elastic docs ranked at the top. The retriever is doing the same job it did in Lab 3 — now you're about to feed this to an LLM.
>
> **Why look at this first:** Most RAG debugging happens here, not at the LLM. If the answer is wrong, the first question is always "what did the retriever actually return?"

**Cell 6: See the exact prompt the LLM receives**

Builds and prints the prompt before sending it — the assembled context plus the question, exactly as the model will see it.

> **What you should see:** Your retrieved documents laid out as numbered sources, followed by the question.
>
> **Why this matters:** LLMs are often treated as black boxes. Printing the prompt makes RAG transparent — you can see exactly why the model answered the way it did.

**Cell 7: GOOD context → good answer**

Runs hybrid retrieval for a question, feeds the results to the LLM, prints the answer.

> **What you should see:** A correct, specific, grounded answer that references the retrieved documentation.
>
> **Why it's good:** The hybrid retriever returned the right docs. The model summarized them accurately.

**Cell 8: BAD context → bad answer (same model, same question)**

Retrieves deliberately wrong documents by filtering to off-topic content, feeds *those* to the same LLM with the same question, prints the answer.

> **What you should see:** A vague, incorrect, or hedged answer — the model saying "I don't have enough information" or fabricating something plausible but wrong.
>
> **Why this is the key demo:** The model didn't get dumber. The retrieval got worse. Same question, same model, same code — the only variable is what came back from the database. This is why RAG is a database problem, not a model problem.

**Cell 9: Security at the database layer**

Explains document-level security (DLS) in Elasticsearch. With DLS enabled, Elasticsearch evaluates access permissions *before* running the query — filtered documents never appear in results and therefore never enter the prompt. The LLM physically cannot surface content the user isn't authorized to see.

> **Workshop vs production note:** The BAD context experiment used a manual `trap_type` filter we wrote ourselves — that's not real DLS. We did it this way because setting up RBAC roles takes more time than a workshop allows. In production, DLS attaches role-based filters automatically to users or API keys at query time, with no filter clause in application code. The concept is the same; the mechanism is automatic.
>
> **Why this matters for agents:** LLM-based systems need access control at the retrieval layer, not in the prompt ("don't mention confidential docs"). Prompt-level rules can be bypassed. Database-level rules cannot.

**Cell 10: Citation prompting**

Shows a prompt variant that asks the model to cite sources as `[Source N]`. Run this and compare the answer to Cell 7's answer.

> **What you should see:** The same factual content, but with explicit source citations you can trace back to retrieved documents.
>
> **Why this is useful:** Citations make RAG answers auditable. Users can verify the model's claims against the actual source documents.

**Cell 11: Run your own question**

A one-liner: `ask("your question here")` — runs hybrid retrieval and synthesis end to end. Try a question about anything in the Elasticsearch docs.

**Cell 12: Multi-hop agent**

A minimal agent loop that decides whether to run a follow-up query. Shows that retrieval + synthesis isn't just one-shot — you can chain it, and each hop is still just search + prompt + generate.

***

## The Thesis

> "Retrieval quality — not model quality — bounds answer quality."

You used the same model in cells 7 and 8. The answer changed because the database query changed. Most of the work in building a production RAG system is in steps 1 and 2 (retrieval and prompt construction), not in choosing a model.

The labs you just ran — vector search, understanding its failure modes, and fixing them with hybrid retrieval — are the database work. That's why it matters.
