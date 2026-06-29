# Lab 4 — Why It Matters: Retrieval Quality IS Answer Quality

**Thesis:** In a RAG (Retrieval-Augmented Generation) pipeline, answer quality is *bounded* by retrieval quality. Giving a better LLM bad context produces a bad answer. Giving any LLM excellent context produces an excellent answer. Most of a strong RAG pipeline is a **database problem**, not a model problem.

## What you'll learn
- How a RAG pipeline works mechanically: retrieve → build prompt → generate
- How to see the *exact* prompt sent to the LLM — what the model actually reads
- The GOOD vs BAD context experiment: same model, same question, different retrieval → different answers
- How retrieval shapes what the LLM sees — and how RBAC + DLS enforce that at the credential, not the prompt
- Citation-grounded prompting: making the LLM reference its sources

## LLM access
This notebook uses the **Elastic Inference Service** to call `claude-haiku-4.5` — the same `ES_API_KEY` that authenticates your search queries also authenticates the LLM call. No separate Anthropic key needed.

> ⏱ **The first LLM call is cold (~10–20s)** — that's normal warm-up latency, not a hang. Subsequent calls are faster.

## Before you start
- **In Instruqt:** credentials are pre-configured — just run the cells.
- **Re-running from the repo:** `export ES_ENDPOINT=https://...` and `export ES_API_KEY=...`


```python
# --- Workshop helpers (inline — same block across all 4 notebooks) ---

import os, json, time
import requests
from elasticsearch import Elasticsearch

INDEX = "aiewf-workshop-docs"

ES_ENDPOINT = os.environ.get("ES_ENDPOINT")
ES_API_KEY  = os.environ.get("ES_API_KEY")
if not ES_ENDPOINT or not ES_API_KEY:
    raise ValueError(
        "Set ES_ENDPOINT and ES_API_KEY.\n"
        "  In Instruqt: pre-configured in the sandbox.\n"
        "  Re-running the repo: export ES_ENDPOINT=https://...  export ES_API_KEY=..."
    )

es = Elasticsearch(ES_ENDPOINT, api_key=ES_API_KEY, request_timeout=60)

def show_hits(resp, fields=("id", "title", "summary"), score=True):
    hits = resp["hits"]["hits"]
    if not hits:
        print("  (no hits)"); return
    for rank, h in enumerate(hits, 1):
        src = h.get("_source", {})
        cols = "  ".join(str(src.get(f, "")) for f in fields)
        s = f"  {h['_score']:.4f}" if score and h.get("_score") is not None else ""
        print(f"  #{rank:<2}{s}  {cols}")

def r_semantic(query):
    return {"standard": {"query": {"semantic": {"field": "body_semantic", "query": query}}}}

def r_bm25(query):
    return {"standard": {"query": {"multi_match": {
        "query": query, "fields": ["title^3", "body"], "type": "best_fields"}}}}

def r_rrf(query, rank_constant=60, rank_window_size=100):
    return {"rrf": {"retrievers": [r_bm25(query), r_semantic(query)],
                    "rank_constant": rank_constant, "rank_window_size": rank_window_size}}

def search(retriever, size=5, source=("id","title","summary","version_tags")):
    return es.search(index=INDEX, retriever=retriever, size=size, source=list(source))

print("✓ Helpers loaded")
```

    ✓ Helpers loaded



```python
# --- LLM helpers ---
# Uses the Elastic Inference Service: ES_API_KEY authenticates both search AND LLM.
# No separate Anthropic key needed.

LLM_INFERENCE_ID = ".anthropic-claude-4.5-haiku-chat_completion"

SYSTEM_PROMPT = (
    "You are a helpful Elasticsearch documentation assistant. "
    "Answer the question using ONLY the provided documentation context. "
    "Do not guess or infer information not present in the context. "
    "If the context does not contain enough information to answer, "
    "say exactly: 'I do not have enough information in the provided context to answer this question.' "
)

def hybrid_search(query, size=5, filter_clause=None):
    """
    RRF hybrid retrieval — returns flat dicts WITH body text for prompt building.
    filter_clause: optional list of ES filter queries, e.g. [{"term": {"product": "kibana"}}]
    Used by the BAD context experiment to force wrong docs deterministically.
    """
    if filter_clause:
        retriever = {"rrf": {"retrievers": [
            {"standard": {"query": {"bool": {
                "must": [{"multi_match": {"query": query, "fields": ["title^3", "body"]}}],
                "filter": filter_clause}}}},
            {"standard": {"query": {"bool": {
                "must": [{"semantic": {"field": "body_semantic", "query": query}}],
                "filter": filter_clause}}}},
        ], "rank_constant": 60, "rank_window_size": 100}}
    else:
        retriever = r_rrf(query)
    resp = es.search(
        index=INDEX,
        retriever=retriever,
        size=size,
        source=["id", "title", "url", "body"]
    )
    return [
        {
            "id":    h["_source"]["id"],
            "title": h["_source"]["title"],
            "url":   h["_source"].get("url", ""),
            "body":  h["_source"]["body"],
            "score": h["_score"],
        }
        for h in resp["hits"]["hits"]
    ]

def build_prompt(context_docs, question):
    """Assemble a context-stuffed prompt from retrieved docs."""
    blocks = [
        f"[Source {i}: {d['title']}]\n{d['body']}"
        for i, d in enumerate(context_docs, 1)
    ]
    return "Context:\n" + "\n\n---\n\n".join(blocks) + f"\n\nQuestion: {question}"

def synthesize(context_docs, question, show_prompt=False):
    """Build prompt, call LLM via Elastic Inference Service (streaming), return answer."""
    user_msg = build_prompt(context_docs, question)   # full bodies go to the model

    if show_prompt:
        # Display-only truncation (600 chars per doc body) so the cell stays readable on screen;
        # the model still receives full text in user_msg above.
        preview_blocks = [
            f"[Source {i}: {d['title']}]\n{d['body'][:600]}{'...' if len(d['body']) > 600 else ''}"
            for i, d in enumerate(context_docs, 1)
        ]
        preview = "Context:\n" + "\n\n---\n\n".join(preview_blocks) + f"\n\nQuestion: {question}"
        print("=== PROMPT SENT TO LLM (bodies truncated to 600 chars for display) ===")
        print(preview)
        print("=== END PROMPT ===\n")

    # chat_completion task type requires streaming — collect all chunks into one string
    resp = requests.post(
        f"{ES_ENDPOINT}/_inference/chat_completion/{LLM_INFERENCE_ID}/_stream",
        headers={"Authorization": f"ApiKey {ES_API_KEY}", "Content-Type": "application/json"},
        json={"messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ]},
        stream=True,
        timeout=60,
    )
    if not resp.ok:
        print(f"LLM call failed {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    chunks = []
    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str.strip() == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            if "content" in delta:
                chunks.append(delta["content"])
        except json.JSONDecodeError:
            pass

    return "".join(chunks)

print("\u2713 LLM helpers loaded")
print(f"  Using inference endpoint: {LLM_INFERENCE_ID}")
```

    ✓ LLM helpers loaded
      Using inference endpoint: .anthropic-claude-4.5-haiku-chat_completion



```python
# Connect + count sanity
info = es.info()
count = es.count(index=INDEX)["count"]
print(f"Connected to ES {info['version']['number']} | {count} docs in '{INDEX}'")
```

    Connected to ES 9.5.0 | 62 docs in 'aiewf-workshop-docs'


## A RAG pipeline in 3 steps

Retrieval-Augmented Generation is not a complex architecture. It's literally:

```
1. RETRIEVE   → search for relevant documents using the user's question
2. BUILD PROMPT → stuff those documents into the LLM's context window
3. GENERATE   → call the LLM with that context; it answers from the docs
```

The key insight we'll demonstrate: **step 1 determines everything**. The LLM can only answer well if step 1 gave it the right documents. A better LLM cannot compensate for wrong documents in step 2.

Let's watch each step explicitly.

> ⏱ **The first LLM call is cold (~10–20s)** — that's the inference service spinning up. Subsequent calls are faster.

## Step 1: Retrieve — watch what comes back

We'll use our Lab 3 hybrid RRF retriever. It requests `body` in `_source` because the LLM needs the full text.


```python
question = "notify me when something goes wrong"

print(f"Question: {question!r}\n")
print("Retrieving top 5 documents...\n")

docs = hybrid_search(question)

for i, d in enumerate(docs, 1):
    print(f"  Source {i}: [{d['id']}] {d['title']}")
    print(f"    Score: {d['score']:.4f}")
    print(f"    Body preview: {d['body'][:200].strip()}...")
    print()
    print('-' * 60)
```

    Question: 'notify me when something goes wrong'
    
    Retrieving top 5 documents...
    
      Source 1: [doc-049] Elasticsearch Watcher alerting
        Score: 0.0318
        Body preview: Watcher is Elasticsearch's built-in alerting and notification system. Watches monitor conditions in your data and trigger actions when thresholds are met.
    
    Watch anatomy
    
    A watch consists of:
    1. Trigg...
    
    ------------------------------------------------------------
      Source 2: [doc-025] Troubleshoot snapshot and restore in Elasticsearch
        Score: 0.0308
        Body preview: Use the topics in this section to troubleshoot issues with Elasticsearch snapshots.
    
    Restore from snapshot
    
    When restoring from a snapshot fails, common causes include:
    - The snapshot repository is no...
    
    ------------------------------------------------------------
      Source 3: [doc-061] Container exit codes when a process is killed (OOM and signals)
        Score: 0.0303
        Body preview: When a containerized process terminates, the runtime records an exit code describing how it stopped. Understanding what these codes mean is essential for diagnosing why a container or service stopped...
    
    ------------------------------------------------------------
      Source 4: [doc-019] Ingest pipelines in Elasticsearch
        Score: 0.0297
        Body preview: Ingest pipelines transform and enrich documents before indexing. A pipeline is a sequence of processors, each performing a specific operation on the document.
    
    Creating a pipeline
    
    Use the Create inge...
    
    ------------------------------------------------------------
      Source 5: [doc-042] Elasticsearch circuit breaker settings
        Score: 0.0292
        Body preview: Circuit breakers prevent out-of-memory errors by failing requests that would exceed JVM heap limits. They monitor estimated memory usage and return HTTP 429 Too Many Requests when a limit is exceeded....
    
    ------------------------------------------------------------


## Step 2: See the EXACT prompt sent to the LLM

We're not going to abstract away the prompt — you'll see exactly what the model receives.

The LLM doesn't "know" anything about *your* cluster or how *you* monitor it — it only knows what we stuffed into the context window. The prompt is the complete information it works from. If the retrieved documents are wrong, the prompt is wrong, and the answer will be wrong.

`show_prompt=True` prints the assembled context before calling the model. (Bodies are truncated to 600 chars in the display; the model sees the full text.)


```python
print(f"Question: {question!r}\n")
answer = synthesize(docs, question, show_prompt=True)
print("=== LLM ANSWER ===")
print(answer)
```

    Question: 'notify me when something goes wrong'
    
    === PROMPT SENT TO LLM (bodies truncated to 600 chars for display) ===
    Context:
    [Source 1: Elasticsearch Watcher alerting]
    Watcher is Elasticsearch's built-in alerting and notification system. Watches monitor conditions in your data and trigger actions when thresholds are met.
    
    Watch anatomy
    
    A watch consists of:
    1. Trigger: When the watch runs (typically a schedule).
    2. Input: What data to load (search results, HTTP response, etc.).
    3. Condition: Logic to evaluate the input and decide whether to act.
    4. Actions: What to do when the condition is true (email, webhook, index, Slack, etc.).
    
    Example watch
    
      PUT /_watcher/watch/cluster-health-check
      {
        "trigger": { "schedule": { "interval": "5m" } },
        "input":...
    
    ---
    
    [Source 2: Troubleshoot snapshot and restore in Elasticsearch]
    Use the topics in this section to troubleshoot issues with Elasticsearch snapshots.
    
    Restore from snapshot
    
    When restoring from a snapshot fails, common causes include:
    - The snapshot repository is not accessible from all nodes (network or credential issues).
    - The target index already exists. Use rename_pattern and rename_replacement in the restore request to restore to a different index name, or delete the existing index first.
    - Insufficient disk space on the target nodes for the restored shards.
    - Version incompatibility: snapshots can only be restored to the same major version or the next...
    
    ---
    
    [Source 3: Container exit codes when a process is killed (OOM and signals)]
    When a containerized process terminates, the runtime records an exit code describing how it stopped. Understanding what these codes mean is essential for diagnosing why a container or service stopped unexpectedly. A process killed by the out-of-memory killer does not stop normally — it is terminated by a kill signal and reports a high signal-based status instead of a clean shutdown.
    
    Termination by signal
    
    A process may stop on its own, or the operating system may terminate it with a signal. When a signal kills a process, the reported status is derived from the signal number using the 128 plus...
    
    ---
    
    [Source 4: Ingest pipelines in Elasticsearch]
    Ingest pipelines transform and enrich documents before indexing. A pipeline is a sequence of processors, each performing a specific operation on the document.
    
    Creating a pipeline
    
    Use the Create ingest pipeline API:
      PUT /_ingest/pipeline/my-pipeline
      {
        "description": "Extract and enrich log fields",
        "processors": [
          {
            "grok": {
              "field": "message",
              "patterns": ["%{IP:client_ip} %{WORD:method} %{URIPATHPARAM:request}"]
            }
          },
          {
            "date": {
              "field": "@timestamp",
              "formats": ["ISO8601"]
            }
          }
        ]...
    
    ---
    
    [Source 5: Elasticsearch circuit breaker settings]
    Circuit breakers prevent out-of-memory errors by failing requests that would exceed JVM heap limits. They monitor estimated memory usage and return HTTP 429 Too Many Requests when a limit is exceeded.
    
    Total circuit breaker
    
    indices.breaker.total.limit: Overall limit for all circuit breakers combined. Default: 95% of JVM heap. When this is exceeded, all memory-intensive operations are rejected.
    
    Request circuit breaker
    
    indices.breaker.request.limit: Limit for per-request memory (aggregations, sort, etc.). Default: 60% of JVM heap.
    
    indices.breaker.request.overhead: Estimated overhead multipli...
    
    Question: notify me when something goes wrong
    === END PROMPT ===
    
    === LLM ANSWER ===
    I do not have enough information in the provided context to answer this question.
    
    While the context includes documentation about Elasticsearch Watcher (an alerting system that can notify you when conditions are met) and some troubleshooting guides, it does not contain specific instructions on how to set up notifications for general errors or failures in Elasticsearch.
    
    To properly answer your question, I would need documentation that covers:
    - How to configure alerts for error conditions
    - What types of errors can trigger notifications
    - How to set up notification channels (email, Slack, webhooks, etc.)
    - Specific watch configurations for monitoring cluster health or errors
    
    You may want to consult the Elasticsearch Watcher documentation or Kibana Alerting documentation for detailed setup instructions.


## The experiment: GOOD vs BAD retrieval — same model, same question

We're going to run the same question twice:
1. **GOOD:** hybrid RRF retrieval → semantically relevant documents
2. **BAD:** deliberately wrong retrieval — documents about unrelated topics

The model is identical. The question is identical. The only difference is what was retrieved.

The BAD case is forced deterministically by filtering retrieval to an off-topic `trap_type` — we're not relying on luck.


```python
# ─── GOOD CONTEXT — hybrid retrieval finds genuinely relevant docs ───────────
question = "How do I configure SAML authentication in Elasticsearch?"

print("GOOD CONTEXT: hybrid RRF retrieval")
good_docs = hybrid_search(question)
print("Retrieved:")
for i, d in enumerate(good_docs, 1):
    print(f"  Source {i}: [{d['id']}] {d['title']}")

print("\nGenerating answer...")
good_answer = synthesize(good_docs, question)

print("\n=== GOOD ANSWER ===")
print(good_answer)
```

    GOOD CONTEXT: hybrid RRF retrieval
    Retrieved:
      Source 1: [doc-001] SAML authentication troubleshooting
      Source 2: [doc-024] Authentication in Kibana
      Source 3: [doc-005] LDAP user authentication
      Source 4: [doc-009] Set up security in self-managed Elasticsearch deployments
      Source 5: [doc-038] Elasticsearch security overview
    
    Generating answer...
    
    === GOOD ANSWER ===
    Based on the provided documentation, here's how to configure SAML authentication in Elasticsearch:
    
    ## Basic Configuration
    
    Configure a SAML realm in `elasticsearch.yml` under the `xpack.security.authc.realms.saml` namespace. Key settings include:
    
    1. **Service Provider (SP) Entity ID**: Set via `xpack.security.authc.realms.saml.saml1.sp.entity_id` - must match the service provider registration in your IdP.
    
    2. **Assertion Consumer Service (ACS) URL**: Configure `xpack.security.authc.realms.saml.saml1.sp.acs` - must match the URL where Kibana is accessible.
    
    3. **IdP Metadata**: Point to `xpack.security.authc.realms.saml.saml1.idp.metadata.path` with an up-to-date metadata file containing valid XML.
    
    4. **IdP Entity ID**: Set `xpack.security.authc.realms.saml.saml1.idp.entity_id` to match the EntityID in your IdP metadata.
    
    5. **Principal Attribute**: Configure `xpack.security.authc.realms.saml.saml1.attributes.principal` to point to the correct SAML attribute carrying the username (e.g., NameID or custom attributes).
    
    6. **NameID Format**: Set `xpack.security.authc.realms.saml.saml1.nameid_format` to match the format in the SAML response.
    
    7. **Clock Skew Tolerance**: Use `xpack.security.authc.realms.saml.saml1.allowed_clock_skew` to allow for clock differences between Elasticsearch and the IdP.
    
    ## Kibana Configuration
    
    In Kibana, configure the SAML provider:
    ```
    xpack.security.authc.providers:
      saml.saml1:
        order: 0
        realm: saml1
    ```
    
    ## Role Mapping
    
    After authentication, configure role mappings via `role_mapping.yml` or the Role Mappings API to map SAML attributes to Elasticsearch roles.



```python
# ─── BAD CONTEXT — same question, retrieval forced to off-topic docs ─────────
# We pass filter_clause to hybrid_search() to constrain retrieval to version-specific
# docs (release notes). They're completely irrelevant to SAML authentication.
# Same question, same model — only the retrieval changes.

BAD_FILTER = [{"term": {"trap_type": "version-specific"}}]

print("BAD CONTEXT: retrieval forced to off-topic docs")
bad_docs = hybrid_search(question, filter_clause=BAD_FILTER)

print("Retrieved (wrong docs):")
for i, d in enumerate(bad_docs, 1):
    print(f"  Source {i}: [{d['id']}] {d['title']}")

print("\nGenerating answer with bad context...")
bad_answer = synthesize(bad_docs, question)

print("\n=== BAD ANSWER ===")
print(bad_answer)

```

    BAD CONTEXT: retrieval forced to off-topic docs
    Retrieved (wrong docs):
      Source 1: [doc-006] Elasticsearch breaking changes
      Source 2: [doc-058] Elasticsearch 8.15 release notes
      Source 3: [doc-056] Elasticsearch 9.x what's new overview
      Source 4: [doc-057] Elasticsearch 8.18 release notes
    
    Generating answer with bad context...
    
    === BAD ANSWER ===
    I do not have enough information in the provided context to answer this question.
    
    The documentation context provided covers breaking changes and new features in Elasticsearch 8.15, 8.18, and 9.x releases, but it does not contain information about how to configure SAML authentication. To get accurate guidance on SAML authentication configuration, you would need to consult the Elasticsearch authentication or security configuration documentation.



```python
# Side-by-side comparison
print(f"Question: {question!r}")
print("=" * 70)
print("GOOD CONTEXT ANSWER:")
print("-" * 70)
print(good_answer)
print()
print("BAD CONTEXT ANSWER:")
print("-" * 70)
print(bad_answer)
print()
print("=" * 70)
print("\n💡 The model didn't get dumber. The retrieval got worse.")
print("   This is not a model quality problem. It's a retrieval quality problem.")
```

    Question: 'How do I configure SAML authentication in Elasticsearch?'
    ======================================================================
    GOOD CONTEXT ANSWER:
    ----------------------------------------------------------------------
    Based on the provided documentation, here's how to configure SAML authentication in Elasticsearch:
    
    ## Basic Configuration
    
    Configure a SAML realm in `elasticsearch.yml` under the `xpack.security.authc.realms.saml` namespace. Key settings include:
    
    1. **Service Provider (SP) Entity ID**: Set via `xpack.security.authc.realms.saml.saml1.sp.entity_id` - must match the service provider registration in your IdP.
    
    2. **Assertion Consumer Service (ACS) URL**: Configure `xpack.security.authc.realms.saml.saml1.sp.acs` - must match the URL where Kibana is accessible.
    
    3. **IdP Metadata**: Point to `xpack.security.authc.realms.saml.saml1.idp.metadata.path` with an up-to-date metadata file containing valid XML.
    
    4. **IdP Entity ID**: Set `xpack.security.authc.realms.saml.saml1.idp.entity_id` to match the EntityID in your IdP metadata.
    
    5. **Principal Attribute**: Configure `xpack.security.authc.realms.saml.saml1.attributes.principal` to point to the correct SAML attribute carrying the username (e.g., NameID or custom attributes).
    
    6. **NameID Format**: Set `xpack.security.authc.realms.saml.saml1.nameid_format` to match the format in the SAML response.
    
    7. **Clock Skew Tolerance**: Use `xpack.security.authc.realms.saml.saml1.allowed_clock_skew` to allow for clock differences between Elasticsearch and the IdP.
    
    ## Kibana Configuration
    
    In Kibana, configure the SAML provider:
    ```
    xpack.security.authc.providers:
      saml.saml1:
        order: 0
        realm: saml1
    ```
    
    ## Role Mapping
    
    After authentication, configure role mappings via `role_mapping.yml` or the Role Mappings API to map SAML attributes to Elasticsearch roles.
    
    BAD CONTEXT ANSWER:
    ----------------------------------------------------------------------
    I do not have enough information in the provided context to answer this question.
    
    The documentation context provided covers breaking changes and new features in Elasticsearch 8.15, 8.18, and 9.x releases, but it does not contain information about how to configure SAML authentication. To get accurate guidance on SAML authentication configuration, you would need to consult the Elasticsearch authentication or security configuration documentation.
    
    ======================================================================
    
    💡 The model didn't get dumber. The retrieval got worse.
       This is not a model quality problem. It's a retrieval quality problem.


## Retrieval shapes what the LLM sees

The BAD-context experiment is really a lesson about *scope of context*. The LLM **could not** talk about SAML auth — not because we instructed it to avoid the topic, but because those documents were **never retrieved**, so they were never in the prompt. The model can only reason over what retrieval handed it.

```
User question
    │
    ▼
Elasticsearch retrieval  ← decides WHICH documents exist for this request
    │  Only the retrieved docs move forward
    ▼
LLM prompt building      ← the prompt contains exactly those docs, nothing else
    │
    ▼
LLM generation           ← the model can only answer from what's in the prompt
```

This is why RAG is a *retrieval* problem first. Whatever shapes the result set — the query, a relevance ranker, a filter, or an access-control rule — directly determines the universe the LLM reasons over.

> ⚠️ **Be precise about what we just did.** The BAD-context cell passed a `bool.filter` clause **that we wrote ourselves** into the search request. That's an *application-side filter*: it shaped the results for this demo, but it enforces nothing — anyone holding the same API key can simply omit the clause and retrieve everything. It is **not** access control. Real access control is enforced by the *credential*, not the query — that's the next cell.

## Real access control: RBAC and Document-Level Security

An application filter shapes results. **Access control** restricts them — enforced by Elasticsearch on the *credential*, so the application cannot turn it off. Two layers:

- **RBAC (role-based access control)** — a role grants or denies whole indices and actions. *Can this credential read `aiewf-workshop-docs` at all?*
- **DLS (document-level security)** — a role attaches a **query** to an index privilege, so the credential can only ever see the **subset of documents** that query matches. *Which rows may this credential see?*

The crucial difference from our demo filter: the restriction lives in the **role**, evaluated on every request. It is not a clause the application adds and can therefore not be removed by the application. A document the credential isn't allowed to see simply **isn't returned** — no error, no redaction, just absence — so it never enters the retrieval result, never enters the prompt, and the LLM cannot surface it.

```
Request carries the user's credential (API key / token)
    │
    ▼
Elasticsearch
    │  • RBAC: is this credential allowed to read the index?     ← enforced by the ROLE
    │  • DLS:  which documents may this credential see?          ← enforced by the ROLE
    │  • app's own bool.filter narrows further                   ← convenience, NOT security
    ▼
Only authorized docs returned → prompt → LLM
```

Here is what a DLS-restricted credential looks like. **We are not running this in the workshop** (see the note below) — it's the real mechanism, for reference:

```python
# Create an API key whose role can ONLY ever read non-confidential docs.
# The DLS query is part of the ROLE — no request made with this key can widen it.
es.security.create_api_key(
    name="contractor-key",
    role_descriptors={
        "restricted_reader": {
            "indices": [{
                "names": ["aiewf-workshop-docs"],
                "privileges": ["read"],
                "query": {"bool": {"must_not": {"term": {"confidential": True}}}}
            }]
        }
    },
)
# A search with contractor-key for a confidential doc returns nothing —
# the document is invisible to that credential, so it can never reach the LLM.
```

> **Why we don't execute this cell here:** the sandbox authenticates you with a *managed API key*, and Elastic Serverless does not let an API key mint a privilege-bearing child key (you'd get `creating derived api keys requires an explicit role descriptor that is empty`). DLS roles are created by an admin/user credential with `manage_security`, not from inside a notebook running as an API key. Copy the snippet into a cluster where you authenticate as such a user and it works as written.

**The takeaway:** in RAG, security belongs in the **credential's role** at the retrieval layer — RBAC for index access, DLS for row-level access. An application `bool.filter` (our BAD-context demo) shapes results but enforces nothing. Prompt-level rules ("don't mention confidential documents") can be bypassed; role-enforced DLS cannot.

## Citation-grounded prompting — making answers verifiable

We prepend each document with `[Source N: Title]`. We can tell the LLM to cite those sources in its answer — making every claim traceable back to a specific retrieved document.

This dramatically reduces hallucination risk: if the LLM can't cite a source, it shouldn't make the claim. And users can click through to verify.


```python
CITATION_SYSTEM_PROMPT = (
    "You are a helpful Elasticsearch documentation assistant. "
    "Answer the question using ONLY the provided documentation context. "
    "For each claim you make, cite the source using [Source N] notation. "
    "If the context does not contain enough information, say so and do not speculate."
)

def synthesize_with_citations(context_docs, question):
    """Synthesize with citation instruction. Uses the streaming chat_completion API
    (the chat_completion task type only supports _stream on Serverless)."""
    user_msg = build_prompt(context_docs, question)
    resp = requests.post(
        f"{ES_ENDPOINT}/_inference/chat_completion/{LLM_INFERENCE_ID}/_stream",
        headers={"Authorization": f"ApiKey {ES_API_KEY}", "Content-Type": "application/json"},
        json={"messages": [
            {"role": "system", "content": CITATION_SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ]},
        stream=True,
        timeout=60,
    )
    resp.raise_for_status()
    chunks = []
    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str.strip() == "[DONE]":
            break
        try:
            delta = json.loads(data_str).get("choices", [{}])[0].get("delta", {})
            if "content" in delta:
                chunks.append(delta["content"])
        except json.JSONDecodeError:
            pass
    return "".join(chunks)

print(f"Question: {question!r}\n")
cited_answer = synthesize_with_citations(good_docs, question)
print("=== CITED ANSWER ===")
print(cited_answer)
print("\nSource list:")
for i, d in enumerate(good_docs, 1):
    print(f"  [Source {i}] {d['title']} — {d['url']}")
```

    Question: 'How do I configure SAML authentication in Elasticsearch?'
    
    === CITED ANSWER ===
    # Configuring SAML Authentication in Elasticsearch
    
    Based on the provided documentation, here's how to configure SAML authentication:
    
    ## Basic Configuration
    
    Configure a SAML realm in your `elasticsearch.yml` file under the `xpack.security.authc.realms.saml` namespace [Source 1]. The key settings include:
    
    - **Identity Provider Metadata**: Point to your IdP's metadata file with `xpack.security.authc.realms.saml.saml1.idp.metadata.path` [Source 1]
    
    - **Service Provider Entity ID**: Configure `xpack.security.authc.realms.saml.saml1.sp.entity_id` to match your service provider registration in the IdP [Source 1]
    
    - **Assertion Consumer Service URL**: Set `xpack.security.authc.realms.saml.saml1.sp.acs` to the URL where Kibana is accessible [Source 1]
    
    - **Principal Attribute**: Configure `xpack.security.authc.realms.saml.saml1.attributes.principal` to point to the SAML attribute that carries the username (such as NameID or a custom attribute) [Source 1]
    
    - **NameID Format**: Ensure `xpack.security.authc.realms.saml.saml1.nameid_format` matches the format in your SAML response [Source 1]
    
    - **Clock Skew Tolerance**: Set `xpack.security.authc.realms.saml.saml1.allowed_clock_skew` to handle clock differences between Elasticsearch and your IdP [Source 1]
    
    ## Kibana Configuration
    
    In Kibana, configure the SAML authentication provider [Source 2]:
    ```
    xpack.security.authc.providers:
      saml.saml1:
        order: 0
        realm: saml1
    ```
    
    The documentation does not provide a complete example configuration, so you should refer to additional setup guides for detailed parameter values.
    
    Source list:
      [Source 1] SAML authentication troubleshooting — https://www.elastic.co/docs/troubleshoot/elasticsearch/security/trb-security-saml
      [Source 2] Authentication in Kibana — https://www.elastic.co/docs/deploy-manage/users-roles/cluster-or-deployment-auth/kibana-authentication
      [Source 3] LDAP user authentication — https://www.elastic.co/docs/deploy-manage/users-roles/cluster-or-deployment-auth/ldap
      [Source 4] Set up security in self-managed Elasticsearch deployments — https://www.elastic.co/docs/deploy-manage/security/self-setup
      [Source 5] Elasticsearch security overview — https://www.elastic.co/docs/deploy-manage/security


## Try it: Run your own question

Replace `your_question` below with any Elasticsearch question and run the cell. The hybrid retriever will find the most relevant docs in our 62-doc corpus and the LLM will answer from them.


```python
def ask(your_question):
    """One-liner: hybrid search → LLM synthesis → print answer."""
    docs = hybrid_search(your_question)
    print(f"Retrieved {len(docs)} docs:")
    for i, d in enumerate(docs, 1):
        print(f"  {i}. [{d['id']}] {d['title']} (score={d['score']:.4f})")
    print()
    answer = synthesize(docs, your_question)
    print("=== ANSWER ===")
    print(answer)

# Replace with your question:
ask("How do I monitor shard allocation in Elasticsearch?")
```

    Retrieved 5 docs:
      1. [doc-008] Cluster-level shard allocation and routing settings (score=0.0328)
      2. [doc-055] Elasticsearch cluster management best practices (score=0.0313)
      3. [doc-021] Red or yellow cluster health status troubleshooting (score=0.0311)
      4. [doc-023] Upgrade Elasticsearch (score=0.0292)
      5. [doc-020] Node roles in Elasticsearch (score=0.0290)
    
    === ANSWER ===
    Based on the provided documentation, here are the ways to monitor shard allocation in Elasticsearch:
    
    **Check Cluster Health:**
    ```
    GET /_cluster/health
    ```
    A healthy cluster shows `status: green` and `unassigned_shards: 0`. Yellow status means only replicas are unassigned, while red means one or more primaries are unassigned.
    
    **View Unassigned Shards:**
    ```
    GET /_cat/shards?v&h=index,shard,prirep,state,unassigned.reason
    ```
    This shows shard details including their state. Unassigned shards have `state: UNASSIGNED`. The `prirep` value indicates `p` for primaries and `r` for replicas.
    
    **Get Root Cause for Specific Unassigned Shards:**
    ```
    POST /_cluster/allocation/explain
    { "index": "my-index", "shard": 0, "primary": false }
    ```
    This provides detailed information about why a specific shard is unassigned.
    
    **Monitor Disk Watermarks:**
    The documentation recommends monitoring disk usage against the configured watermarks:
    - Low watermark (default 85%): No new shards allocated to nodes exceeding this
    - High watermark (default 90%): Existing shards relocated away from nodes exceeding this
    - Flood stage (default 95%): Indices become read-only on nodes exceeding this
    
    These tools help you identify allocation issues and diagnose why shards may be unassigned or experiencing allocation problems.


## Multi-hop retrieval agent

A single-turn RAG pipeline answers one question from one retrieval. But some questions need **two lookups**: find one fact, then use it to decide what to search for next. Example: *"my cluster is yellow with unassigned shards — what causes that, and how do I use the allocation-explain API to fix it?"* The first retrieval explains *yellow / unassigned shards*; the agent then realizes it still needs the *allocation-explain* mechanics and searches again.

The cell below is a minimal multi-hop agent. Each turn, the LLM replies in a strict format — `ANSWER:` (the context is sufficient) or `LOOKUP: <query>` (a sub-fact is missing) — and the loop acts on that decision. Two design points worth calling out, because the naive version of this cell silently runs only one hop:

1. **The system prompt must *invite* a follow-up.** Telling the model "answer if you can" biases it to one-shot everything. We explicitly tell it to emit `LOOKUP:` when a two-part question is only half-covered.
2. **Parse the decision robustly.** Chat models love to dress up output (`# ANSWER:`, `**LOOKUP:**`). A bare `text.startswith("ANSWER:")` misses those and the loop misbehaves. We strip markdown and match the first `ANSWER:`/`LOOKUP:` token case-insensitively.

This is the hand-rolled version — you own the loop, the prompt, and the parsing. In **Part 2** you'll build the same multi-hop behavior in Elastic **Agent Builder**, where the platform runs the loop for you. Seeing both is the point: the mechanics here are exactly what Agent Builder automates.

> ⏱ This cell makes up to 4 LLM calls (a decision + an answer per hop), so it runs ~20–40s.


```python
import re

# The decision prompt. Note it (a) explicitly invites a single follow-up on two-part
# questions, and (b) forbids markdown so the first token is machine-parseable.
AGENT_SYSTEM = (
    "You are a multi-hop retrieval agent. You are given a user question and the documents "
    "retrieved for it so far. Decide between two actions and respond in a STRICT format:\n"
    "- If the retrieved context fully answers the question, reply: ANSWER: <the answer>\n"
    "- If a key sub-fact is missing (a specific setting, root cause, threshold, or related\n"
    "  subsystem the context points to but does not fully explain), reply:\n"
    "  LOOKUP: <a short search query for that missing fact>\n"
    "Rules:\n"
    "- Your reply MUST begin with the literal token ANSWER: or LOOKUP: — no markdown, no '#', no preamble.\n"
    "- A LOOKUP must be a SHORT search query on one line (a few keywords) — not a sentence or explanation.\n"
    "- Prefer LOOKUP when the question has two parts (e.g. 'why does X happen AND how do I fix it')\n"
    "  and the current context covers only one part.\n"
    "- Use at most one LOOKUP, then ANSWER from the combined context."
)

def _stream_llm(system, user_msg):
    """POST to the streaming chat_completion endpoint; return the concatenated text."""
    resp = requests.post(
        f"{ES_ENDPOINT}/_inference/chat_completion/{LLM_INFERENCE_ID}/_stream",
        headers={"Authorization": f"ApiKey {ES_API_KEY}", "Content-Type": "application/json"},
        json={"messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_msg},
        ]},
        stream=True,
        timeout=60,
    )
    resp.raise_for_status()
    chunks = []
    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str.strip() == "[DONE]":
            break
        try:
            delta = json.loads(data_str).get("choices", [{}])[0].get("delta", {})
            if "content" in delta:
                chunks.append(delta["content"])
        except json.JSONDecodeError:
            pass
    return "".join(chunks)

def parse_action(text):
    """Robustly extract (kind, payload) from the agent's reply.
    Strips leading markdown/quote chars and matches the first ANSWER:/LOOKUP: token,
    case-insensitively — so '# ANSWER:', '**LOOKUP:**', etc. all parse correctly.
    Defaults to ANSWER if neither token appears."""
    cleaned = text.lstrip("#*>- \n\t")
    m = re.search(r"(ANSWER|LOOKUP)\s*:", cleaned, re.IGNORECASE)
    if not m:
        return ("ANSWER", text.strip())
    payload = cleaned[m.end():].strip()
    # For a LOOKUP, keep only the first line — the query — in case the model over-explains.
    if m.group(1).upper() == "LOOKUP" and payload:
        payload = payload.splitlines()[0].strip()
    return (m.group(1).upper(), payload)

def agent_decide(question, context_docs, history=""):
    """One decision turn of the agent loop. Returns the raw model reply."""
    ctx = build_prompt(context_docs, question)
    user_msg = (f"Previous context:\n{history}\n\n" if history else "") + ctx
    return _stream_llm(AGENT_SYSTEM, user_msg)

def multi_hop_agent(question, max_hops=2):
    """Minimal multi-hop RAG agent: retrieve → decide (ANSWER/LOOKUP) → maybe retrieve again."""
    original_question = question
    print(f"Question: {question!r}\n")
    history = ""
    for hop in range(1, max_hops + 1):
        print(f"--- Hop {hop}: retrieving for {question!r} ---")
        docs = hybrid_search(question)
        for i, d in enumerate(docs[:3], 1):
            print(f"  {i}. [{d['id']}] {d['title']}")

        reply = agent_decide(question, docs, history)
        kind, payload = parse_action(reply)
        history += f"\n\n[Hop {hop} retrieved context]\n" + build_prompt(docs, question)

        if kind == "ANSWER":
            print(f"\nAgent decided: ANSWER (after {hop} hop{'s' if hop > 1 else ''})\n")
            return payload
        # kind == LOOKUP
        print(f"\nAgent decided: LOOKUP → {payload!r}\n")
        question = payload

    # Hit the hop limit still wanting more — synthesize a final answer from everything gathered
    print(f"Reached max_hops={max_hops}; synthesizing from combined context...\n")
    return _stream_llm(SYSTEM_PROMPT, history + f"\n\nQuestion: {original_question}")

# Try it — a genuinely two-part question: cause (yellow/unassigned shards) + fix (allocation-explain API)
answer = multi_hop_agent(
    "My cluster health is yellow with unassigned shards — what causes that, "
    "and how do I use the allocation explain API to fix it?"
)
print("=== FINAL ANSWER ===")
print(answer)
```

    Question: 'My cluster health is yellow with unassigned shards — what causes that, and how do I use the allocation explain API to fix it?'
    
    --- Hop 1: retrieving for 'My cluster health is yellow with unassigned shards — what causes that, and how do I use the allocation explain API to fix it?' ---
      1. [doc-021] Red or yellow cluster health status troubleshooting
      2. [doc-008] Cluster-level shard allocation and routing settings
      3. [doc-043] Elasticsearch cat APIs overview
    
    Agent decided: LOOKUP → 'allocation explain API parameters and response fields'
    
    --- Hop 2: retrieving for 'allocation explain API parameters and response fields' ---
      1. [doc-008] Cluster-level shard allocation and routing settings
      2. [doc-021] Red or yellow cluster health status troubleshooting
      3. [doc-035] Elasticsearch REST API conventions
    
    Agent decided: LOOKUP → 'allocation explain API response fields'
    
    Reached max_hops=2; synthesizing from combined context...
    
    === FINAL ANSWER ===
    # Yellow Cluster Health with Unassigned Shards
    
    ## What Causes Yellow Health
    
    **Yellow cluster health** means:
    - All primary shards are assigned to nodes
    - Some **replica shards are unassigned**
    - This increases data loss risk if a node fails
    
    ## Diagnosing the Issue
    
    ### Step 1: Check cluster health
    ```
    GET /_cluster/health
    ```
    A yellow status shows `unassigned_shards` > 0 with only replicas unassigned.
    
    ### Step 2: View unassigned shards
    ```
    GET /_cat/shards?v&h=index,shard,prirep,state,unassigned.reason
    ```
    Look for rows with:
    - `state: UNASSIGNED`
    - `prirep: r` (replica shards)
    
    ### Step 3: Use the allocation explain API
    ```
    POST /_cluster/allocation/explain
    { "index": "my-index", "shard": 0, "primary": false }
    ```
    This returns the **root cause** for why a specific shard cannot be allocated.
    
    ## Common Causes & Fixes
    
    | Cause | Fix |
    |-------|-----|
    | **Single-node cluster** | Set `index.number_of_replicas: 0` (replicas can't go on the same node as the primary) |
    | **Lost data node** | Wait for the node to rejoin; Elasticsearch automatically reallocates shards |
    | **Misconfigured allocation settings** | Fix `cluster.routing.allocation.include/exclude/require` settings |
    | **Low disk space** | Free disk space (low watermark: 85%, high: 90%, flood stage: 95%) |
    | **Allocation disabled** | Reset: `PUT /_cluster/settings { "persistent": { "cluster.routing.allocation.enable": null } }` |
    | **High JVM memory pressure** | Reduce heap usage to allow circuit breakers to enable allocation |
    
    The allocation explain API provides the specific reason preventing assignment, allowing you to address the actual root cause rather than guessing.


---

# Part 2 — The same agent, built in Elastic Agent Builder

You just hand-rolled a multi-hop agent: you wrote the loop, the decision prompt, the parser, and the retrieval call. That's the right way to *understand* it. It's not the way you'd *ship* it — every one of those pieces is something to maintain and get subtly wrong (remember the `# ANSWER:` parsing bug this lab was built to avoid).

**Elastic Agent Builder** runs that loop for you. You give it three things:
1. A **tool** — the retrieval step. We'll register the *exact* Lab 3 hybrid retriever (BM25 + semantic, RRF-fused) as a tool the agent can call.
2. A **skill** — a reusable playbook that specializes the agent for a recurring task. We'll add a **Diagnose and Fix** skill that tells the agent how to handle "symptom → cause → fix" questions.
3. An **agent** — a system prompt plus the tools and skills it's allowed to use. The platform handles the reason → call tool → read result → call again → answer loop natively, including multi-hop.

No loop code, no SSE parsing, no decision-token regex. The agent decides when to search again on its own — and you watch it happen in the Kibana UI, tool call by tool call.

> **Why create these in code, not by clicking?** You *can* build the tool, skill, and agent entirely in the Agent Builder UI (and you'll go look at them there in a moment). We create them **programmatically** here because it's idempotent, re-runnable from the repo, version-controlled, and shows you the *exact* ES|QL and prompt that define each piece — nothing hidden behind a form. Then you'll switch to the UI to **see and drive** what the code created.

## The hybrid retriever as one ES|QL statement

In Lab 3 the hybrid retriever was an `rrf` retriever in the `_search` API. Agent Builder tools of type `esql` wrap an **ES|QL** query — and ES|QL expresses the identical fusion with `FORK` + `FUSE`:

```esql
FROM aiewf-workshop-docs METADATA _score, _id, _index
| FORK ( WHERE match(body, ?query)          | SORT _score DESC | LIMIT 50 )
       ( WHERE match(body_semantic, ?query) | SORT _score DESC | LIMIT 50 )
| FUSE
| SORT _score DESC
| KEEP id, title, url, body, _score
| LIMIT 5
```

`FORK` runs the two retrieval arms — a BM25 `match` on `body` and a semantic `match` on `body_semantic` — and `FUSE` applies RRF over their ranked lists. This returns the **same ranking** as the `r_rrf()` retriever you've used all workshop (verified: `doc-049` is #1 on *"notify me when something goes wrong"*, same as the `_search` version). `?query` is a tool parameter the agent fills in at call time.

## Create the tool, the skill, and the agent

Agent Builder is a **Kibana** API, so these calls go to `KIBANA_URL` (the `.kb.` endpoint), not the Elasticsearch endpoint. The same `ES_API_KEY` authenticates it.

- **In Instruqt:** `KIBANA_URL` is pre-set as a sandbox variable — just run the cell.
- **Re-running from the repo:** `export KIBANA_URL=https://your-deployment.kb.<region>.<cloud>.elastic.cloud:443`

The cell is **idempotent** — it deletes any existing agent, skill, and tool (in that order — the agent references the skill and tool, the skill references the tool) before recreating them, so you can re-run it freely. (It's the same logic as `agent-builder/setup_agent.py`, inlined here so the notebook is self-contained.)

> **If the skill step prints `⚠`** (some Serverless builds may not expose the skills API yet), it's non-fatal: the tool and agent still create successfully, and you can add the **Diagnose and Fix** skill by hand in the UI walkthrough below.


```python
# Create the Agent Builder hybrid-search tool + Diagnose and Fix skill + multi-hop agent (idempotent).
KIBANA_URL = os.environ.get("KIBANA_URL")
if not KIBANA_URL:
    raise ValueError(
        "Set KIBANA_URL — the Kibana endpoint (.kb.), not Elasticsearch (.es.).\n"
        "  In Instruqt: pre-configured. Repo: export KIBANA_URL=https://...kb...:443"
    )

AB_TOOL_ID  = "search-workshop-docs-hybrid"
AB_SKILL_ID = "workshop-docs-diagnose-fix"
AB_AGENT_ID = "workshop-docs-agent"

# The Lab 3 RRF hybrid retriever, expressed in ES|QL (FORK = two arms, FUSE = RRF).
HYBRID_ESQL = (
    "FROM aiewf-workshop-docs METADATA _score, _id, _index\n"
    "| FORK ( WHERE match(body, ?query) | SORT _score DESC | LIMIT 50 )\n"
    "       ( WHERE match(body_semantic, ?query) | SORT _score DESC | LIMIT 50 )\n"
    "| FUSE\n"
    "| SORT _score DESC\n"
    "| KEEP id, title, url, body, _score\n"
    "| LIMIT 5"
)

# A SKILL specializes the agent for a recurring task. This diagnose-and-fix playbook
# matches the lab's two-part demo questions (symptom -> cause -> fix) and references the
# same hybrid tool. It's attached to the agent via skill_ids below.
SKILL_CONTENT = """# Diagnose and Fix playbook

When the user reports an Elasticsearch symptom and wants both *why it happens* and *how to fix it*, work in this order:

1. **Find the cause.** Search the symptom (the error code, the cluster state, the failure) with `search-workshop-docs-hybrid` to identify the root cause.
2. **Find the fix.** The first results usually point at a specific API, setting, or subsystem. Run a SECOND search targeting that fix — the exact setting name, the repair API, the config key.
3. **Answer as Cause -> Fix -> Citations.**
   - **Cause:** one or two sentences on what's actually wrong.
   - **Fix:** the concrete steps, naming the exact settings, commands, or API calls from the docs.
   - **Citations:** the doc titles you used, as [title].

Never guess a setting name or a command — if the docs don't contain it, say so."""

AGENT_INSTRUCTIONS = """You are an Elasticsearch documentation assistant built on hybrid retrieval.

## Your tool
- **search-workshop-docs-hybrid**: hybrid (BM25 + semantic, RRF-fused) search over the Elasticsearch docs corpus. It returns the top 5 docs with id, title, url, and body.

## How you work (multi-hop)
1. Call `search-workshop-docs-hybrid` with the user's question to get an initial set of docs.
2. Read the results. If they fully answer the question, write the answer.
3. If answering well requires a fact the first results point to but don't fully cover (a setting, a root cause, a related subsystem), run a SECOND search with a refined query targeting that specific gap, then answer from the combined results. Prefer one focused follow-up over many.
4. Ground every claim in retrieved docs. Cite sources as [title]. If the docs don't contain the answer, say so — do not guess.

## Style
Concise and technical. Use short sections or bullets. Name the specific settings, codes, or commands the docs mention."""

def _ab(method, path, body=None):
    """Call the Kibana Agent Builder API. Returns (status_code, json|text)."""
    resp = requests.request(
        method,
        f"{KIBANA_URL}{path}",
        headers={"Authorization": f"ApiKey {ES_API_KEY}",
                 "kbn-xsrf": "true", "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text

# Idempotent reset — delete in dependency order. The agent references both the skill
# (skill_ids) and the tool, and the skill references the tool: agent -> skill -> tool.
_ab("DELETE", f"/api/agent_builder/agents/{AB_AGENT_ID}")
_ab("DELETE", f"/api/agent_builder/skills/{AB_SKILL_ID}")
_ab("DELETE", f"/api/agent_builder/tools/{AB_TOOL_ID}")

# 1) Create the hybrid retrieval tool
status, resp = _ab("POST", "/api/agent_builder/tools", {
    "id": AB_TOOL_ID,
    "type": "esql",
    "description": (
        "Hybrid (BM25 + semantic) search over the Elasticsearch documentation corpus, "
        "fused with RRF. Use this to find relevant docs for ANY question about Elasticsearch "
        "— error codes, version notes, config keys, or natural-language 'how do I' questions. "
        "Returns id, title, url, and body for the top 5 docs. Call it again with a refined "
        "query if the first results don't fully answer the question."
    ),
    "tags": ["workshop", "search", "hybrid", "rag"],
    "configuration": {
        "query": HYBRID_ESQL,
        "params": {"query": {"type": "string",
                             "description": "The natural-language search query or keywords."}},
    },
})
print(f"{'✓' if status == 200 else '✗'} tool  '{AB_TOOL_ID}'  (HTTP {status})")

# 2) Create the Diagnose and Fix skill (references the tool above).
# NOTE: a skill `name` may only contain letters, numbers, spaces, hyphens, and
# underscores — NO '&' (that returns HTTP 400). So the display name is "Diagnose and Fix".
status, resp = _ab("POST", "/api/agent_builder/skills", {
    "id": AB_SKILL_ID,
    "name": "Diagnose and Fix",
    "description": (
        "Use when the user reports an Elasticsearch symptom (error code, yellow cluster, "
        "failed login) and wants both the cause and the fix. Drives a two-search "
        "diagnose-then-repair flow and answers as Cause -> Fix -> Citations."
    ),
    "content": SKILL_CONTENT,
    "tool_ids": [AB_TOOL_ID],
})
skill_ok = status == 200
# Non-fatal: if a Serverless build doesn't expose the skills API yet, the agent still
# works — you can create/attach the skill in the Kibana UI (Customize → Skills).
print(f"{'✓' if skill_ok else '⚠'} skill '{AB_SKILL_ID}'  (HTTP {status})"
      + ("" if skill_ok else f" — skipped: {resp}"))

# 3) Create the multi-hop agent wired to the tool, with the skill attached via skill_ids.
agent_cfg = {"instructions": AGENT_INSTRUCTIONS, "tools": [{"tool_ids": [AB_TOOL_ID]}]}
if skill_ok:
    agent_cfg["skill_ids"] = [AB_SKILL_ID]

agent_body = {
    "id": AB_AGENT_ID,
    "name": "Workshop Docs Agent",
    "description": "Multi-hop RAG agent over the workshop docs corpus, powered by hybrid retrieval.",
    "labels": ["workshop"],
    "configuration": agent_cfg,
}
status, resp = _ab("POST", "/api/agent_builder/agents", agent_body)
# If skill_ids tripped a build that doesn't accept it, retry once without it so the agent lands.
if status != 200 and "skill_ids" in agent_cfg:
    print(f"⚠ agent create with skill_ids failed (HTTP {status}); retrying without it...")
    agent_cfg.pop("skill_ids", None)
    status, resp = _ab("POST", "/api/agent_builder/agents", agent_body)
print(f"{'✓' if status == 200 else '✗'} agent '{AB_AGENT_ID}'  (HTTP {status})")
print(f"\nOpen Agent Builder in Kibana: {KIBANA_URL}/app/agent_builder")
```

    ✓ tool  'search-workshop-docs-hybrid'  (HTTP 200)
    ✓ skill 'workshop-docs-diagnose-fix'  (HTTP 200)
    ✓ agent 'workshop-docs-agent'  (HTTP 200)
    
    Open Agent Builder in Kibana: https://aiewf-2026-vector-hybrid-search-r3v8vrea8y2x-17826-fc93bc.kb.us-east-1.aws.elastic.cloud/app/agent_builder


## Run the agent — and watch it multi-hop

The `converse` API runs the agent and returns its full reasoning trace, including every tool call it made. We send the **same two-part question** the hand-rolled agent handled above. Watch the `steps`: the agent calls `search-workshop-docs-hybrid`, reads the results, decides it needs more, and calls it **again** with a refined query — entirely on its own. No loop code on our side.


```python
# Run the agent via the converse API and show its multi-hop tool calls.
agent_question = (
    "My Elasticsearch container keeps dying with exit code 137. Why does that happen, "
    "and what specific JVM and memory settings should I change to prevent it?"
)
print(f"Asking the agent: {agent_question!r}\n(this runs the full agent loop server-side; ~15-25s)\n")

status, result = _ab("POST", "/api/agent_builder/converse", {
    "agent_id": AB_AGENT_ID,
    "input": agent_question,
})
if status != 200:
    raise RuntimeError(f"converse failed (HTTP {status}): {result}")

# Walk the trace and print each tool call + reasoning. The agent makes two KINDS of tool call:
#   • load_skill — it pulls in the "Diagnose and Fix" playbook. Its param is `skill` (the skill
#     NAME), not `query` — so don't print it as an empty search.
#   • search-workshop-docs-hybrid — an actual retrieval hop, with a `query` param.
retrieval_hops = 0
for step in result.get("steps", []):
    if step.get("type") == "reasoning":
        print(f"  💭 {step['reasoning'][:140]}")
    elif step.get("type") == "tool_call":
        tool_id = step.get("tool_id", "")
        params = step.get("params", {}) or {}
        if "query" in params:                              # a retrieval hop
            retrieval_hops += 1
            print(f"  🔧 retrieval hop {retrieval_hops}: {tool_id}  query={params['query']!r}")
        elif "skill" in params:                            # the agent loading its skill
            print(f"  🧩 {tool_id}: loaded skill {params['skill']!r}")
        else:                                              # any other tool call
            print(f"  🧩 {tool_id}  {params if params else ''}")

# The final answer is a list of content blocks (or a dict with 'message')
resp = result.get("response", "")
answer = resp if isinstance(resp, str) else (resp.get("message") if isinstance(resp, dict)
         else "".join(b.get("text", "") for b in resp if isinstance(b, dict)))

print(f"\n{'='*60}")
print(f"Retrieval hops: {retrieval_hops}   |   LLM calls: {result.get('model_usage', {}).get('llm_calls', '?')}")
print(f"(plus a load_skill call — that's the agent pulling in its Diagnose and Fix playbook)")
print(f"{'='*60}\n")
print("=== AGENT ANSWER ===")
print(answer)
```

    Asking the agent: 'My Elasticsearch container keeps dying with exit code 137. Why does that happen, and what specific JVM and memory settings should I change to prevent it?'
    (this runs the full agent loop server-side; ~15-25s)
    
      💭 I'll check the relevant skill and search the docs simultaneously to get you a thorough answer.
      🧩 load_skill: loaded skill 'Diagnose and Fix'
      🔧 retrieval hop 1: search-workshop-docs-hybrid  query='container exit code 137 Elasticsearch killed OOM'
      💭 Now let me run the targeted fix search for the specific JVM and memory settings.
      🔧 retrieval hop 2: search-workshop-docs-hybrid  query='JVM heap size Xms Xmx bootstrap.memory_lock cgroups container memory limit Elasticsearch'
    
    ============================================================
    Retrieval hops: 2   |   LLM calls: 3
    (plus a load_skill call — that's the agent pulling in its Diagnose and Fix playbook)
    ============================================================
    
    === AGENT ANSWER ===
    Here is a complete diagnosis and fix.
    
    ---
    
    ## Cause
    
    Exit code **137 = 128 + signal 9 (SIGKILL)**. The Linux kernel's **OOM (Out-of-Memory) killer** sent SIGKILL to the Elasticsearch JVM process because the host (or container) ran out of memory. Elasticsearch is a prime OOM-killer target because of its large heap.
    
    **Confirm it happened:**
    ```bash
    dmesg | grep -i "out of memory"
    # or
    journalctl -k | grep oom
    ```
    You'll see a line like: `Out of memory: Kill process <pid> (java)`
    
    Also: the Elasticsearch process will have vanished with **no JVM fatal error log** (`hs_err_pid*.log`) — that's the tell-tale sign it was killed externally, not a JVM crash.
    
    ---
    
    ## Fix
    
    ### 1. Right-size the JVM heap (`jvm.options`)
    
    Always set `-Xms` and `-Xmx` to the **same value** to avoid heap resizing pauses.
    
    ```
    -Xms16g
    -Xmx16g
    ```
    
    **Sizing rules:**
    - **≤ 50% of available RAM** — leave the other half for the OS page cache and Lucene's off-heap memory (which is *not* counted in the heap).
    - **≤ 26 GB** — above this the JVM switches from compressed OOPs to full 64-bit pointers, increasing overhead and GC pressure. 26 GB is the safe upper bound.
    
    > If your container has 8 GB of RAM, set `-Xms4g -Xmx4g`.
    
    ---
    
    ### 2. Lock the heap in RAM (`elasticsearch.yml`)
    
    Prevent the JVM heap from being swapped out, which can cause memory accounting confusion:
    
    ```yaml
    bootstrap.memory_lock: true
    ```
    
    ---
    
    ### 3. Set a proper container memory limit (Docker/Kubernetes)
    
    Use **cgroups memory limits** so the OOM killer targets only the ES container and not other system processes. The limit must be large enough to cover:
    - JVM heap (`-Xmx`)
    - Lucene off-heap (native memory, file system cache)
    - JVM overhead (metaspace, threads, etc.)
    
    A safe rule: container memory limit ≈ **`-Xmx` × 2** (e.g., 4 GB heap → 8 GB container limit).
    
    ---
    
    ### 4. Enable heap dump on OOM (for diagnosis)
    
    Add to `jvm.options` so you can analyze what consumed the heap:
    
    ```
    -XX:+HeapDumpOnOutOfMemoryError
    -XX:HeapDumpPath=/var/lib/elasticsearch/heapdump.hprof
    ```
    
    Ensure the path has enough disk space (up to the heap size).
    
    ---
    
    ### 5. Enable GC logging (for ongoing monitoring)
    
    ```
    -Xlog:gc*,gc+age=trace,safepoint:file=/var/log/elasticsearch/gc.log:utctime,level,pid,tags:filecount=32,filesize=64m
    ```
    
    ---
    
    ### 6. Monitor heap usage via API
    
    ```
    GET /_cat/nodes?v&h=name,heap.percent,heap.current,heap.max
    GET /_nodes/stats/jvm
    ```
    
    - Heap consistently **> 75–80%** → memory pressure
    - Heap consistently **> 90%** → critical; circuit breakers will start tripping (HTTP 429)
    
    ---
    
    ### Summary checklist
    
    | Setting | Where | Value |
    |---|---|---|
    | `-Xms` / `-Xmx` | `jvm.options` | Equal, ≤ 50% RAM, ≤ 26 GB |
    | `bootstrap.memory_lock` | `elasticsearch.yml` | `true` |
    | Container memory limit | Docker/K8s | ≥ 2× heap size |
    | `-XX:+HeapDumpOnOutOfMemoryError` | `jvm.options` | Enable |
    | GC logging | `jvm.options` | Enable (see above) |
    
    **Sources:** [JVM settings for Elasticsearch], [Container exit codes when a process is killed (OOM and signals)], [High JVM memory pressure troubleshooting], [Elasticsearch deployment configuration guide]


## Now go look at it — and drive it — in Kibana

You proved the agent multi-hops from Python. Everything you created in code is also a living object in the Kibana UI. First take a quick tour of the pieces, then drive the agent yourself.

### Tour the agent you just built

1. **Open Agent Builder** (use the **Agent Builder** Kibana tab → **Agents** → **Workshop Docs Agent** → **Overview**). *Or* navigate directly to `${KIBANA_URL}/app/agent_builder/agents/workshop-docs-agent` — but the tab is the reliable path inside the sandbox.
2. **Capabilities → Tool (1):** this is the hybrid retriever you registered. Click through to `search-workshop-docs-hybrid` → **Edit in library** to see the `FORK … FUSE` ES|QL — the same Lab 3 RRF retriever, now a tool.
3. **Capabilities → Skills:** open **Diagnose and Fix** — the playbook that specializes the agent for "symptom → cause → fix" questions. Notice it references the same hybrid tool.
   > **If you don't see the skill here,** the API skill step printed `⚠` for your build. Add it now: **Capabilities → Skills → Add skill → Diagnose and Fix** (it was still created in your skill library; you just need to attach it).
4. **Customizations → Custom instructions:** the multi-hop system prompt — the loop logic that tells the agent when to take a second hop. **Edit agent settings** is where you'd change any of this by hand.
5. **The takeaway:** **Tool + Skill + instructions = the whole agent.** All three were created by the code cell above, and all three are editable right here in the UI. The code path and the click path produce the same object.

### Drive it yourself

6. Back on the agent, ask a genuinely two-part question, for example:
   - *"My cluster is yellow with unassigned shards — what causes it and how do I use the allocation explain API to fix it?"*
   - *"Container exits with code 137 — why, and which JVM heap settings prevent it?"*
   - *"Users can't log in after I configured SAML — what's the likely cause and how do I map their attributes to roles?"*
7. Watch the conversation. Each **🔧 tool call** is a hybrid-retrieval hop. On a two-part question you'll see the agent search, read, then **search again** with a refined query before it answers — the exact loop you hand-wrote, now run by the platform. (You'll also see a **🧩 load_skill** step — that's the agent pulling in the Diagnose and Fix playbook; it carries a `skill` name, not a search query.)
8. Click into a tool call to inspect the ES|QL it ran and the docs it got back. That's your Lab 3 hybrid retriever, executing inside the agent.

---

## Where this leaves you

You built a RAG pipeline three times, at increasing levels of abstraction:

| Level | What you wrote | What ran the loop |
|---|---|---|
| **Single-shot RAG** | retrieve → prompt → generate | you, one pass |
| **Hand-rolled agent** | the loop, decision prompt, parser | your Python `while` loop |
| **Agent Builder** | a tool + a skill + a system prompt | the Elastic platform |

The retriever never changed. It was the **Lab 3 hybrid (BM25 + semantic, RRF)** every single time — in the `_search` API, then as a Python helper, then as an ES|QL tool. That's the thesis landing: **the agent framework is the easy part to swap; retrieval quality is the part that determines whether any of it works.** A better model or a fancier agent loop cannot rescue bad retrieval — and you measured exactly that in Labs 2 and 3.

That's the workshop. You can run all of this — notebooks, corpus, and the Agent Builder setup — against your own Elastic project: `git clone`, set `ES_ENDPOINT` / `ES_API_KEY` / `KIBANA_URL`, and everything here executes.

---

## Bonus — Lab 5: Reranking

Want one more level of precision? Open **`lab5-reranking.ipynb`** (the bonus lab). It goes deep on **reranking** — the precision layer that re-scores your hybrid results by reading each (query, document) pair *together*: calling the rerank API directly, the **pointwise (cross-encoder) vs. listwise** distinction (Jina Reranker **v2 vs. v3** head-to-head), the production `text_similarity_reranker` path, and a decision matrix for when a rerank stage is worth adding at all.

The retriever you built across Labs 1–4 is still the foundation — reranking just sits on top as the final precision layer.
