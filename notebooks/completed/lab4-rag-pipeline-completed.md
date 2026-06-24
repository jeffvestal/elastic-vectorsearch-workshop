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
        Score: 0.0307
        Body preview: When a containerized process terminates, the runtime records an exit code describing how it stopped. Understanding what these codes mean is essential for diagnosing why a container or service stopped...
    
    ------------------------------------------------------------
      Source 4: [doc-019] Ingest pipelines in Elasticsearch
        Score: 0.0295
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
    Based on the provided documentation, here are the ways to be notified when something goes wrong in Elasticsearch:
    
    ## Using Watcher (Built-in Alerting)
    
    Elasticsearch's **Watcher** is the built-in alerting system that can monitor conditions and send notifications. You can set up a watch to trigger actions when problems occur:
    
    **Actions available include:**
    - Email
    - Webhook
    - Slack
    - Index (store the alert)
    - HTTP requests
    
    **Example:** A watch that monitors cluster health and notifies Slack when the cluster status turns RED:
    
    ```json
    PUT /_watcher/watch/cluster-health-check
    {
      "trigger": { "schedule": { "interval": "5m" } },
      "input": {
        "http": {
          "request": {
            "host": "localhost",
            "port": 9200,
            "path": "/_cluster/health"
          }
        }
      },
      "condition": {
        "compare": {
          "ctx.payload.status": { "eq": "red" }
        }
      },
      "actions": {
        "notify_slack": {
          "webhook": {
            "method": "POST",
            "url": "https://hooks.slack.com/...",
            "body": "{\"text\": \"Cluster health is RED!\"}"
          }
        }
      }
    }
    ```
    
    ## Modern Alternative: Kibana Alerting
    
    **Kibana Alerting (Rules and Connectors)** is the modern alerting system with a UI and broader action support.
    
    Choose Watcher if you prefer managing alerts via the Elasticsearch API, or use Kibana Alerting for a graphical interface.


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
    
    ## Elasticsearch Configuration
    
    Configure a SAML realm in `elasticsearch.yml` under `xpack.security.authc.realms.saml`. Key settings include:
    
    - **`idp.metadata.path`**: Path to an up-to-date IdP metadata file (must contain valid XML)
    - **`sp.entity_id`**: The Service Provider entity ID that must match what the IdP expects
    - **`sp.acs`**: Assertion Consumer Service URL where the IdP sends SAML responses (must match the URL Kibana is accessible at)
    - **`attributes.principal`**: Points to the SAML attribute carrying the username (e.g., NameID or a custom attribute)
    - **`nameid_format`**: The NameID format the SAML response should use
    - **`allowed_clock_skew`**: Tolerance for clock differences between Elasticsearch and IdP
    
    ## Kibana Configuration
    
    Configure Kibana to use SAML SSO with:
    
    ```
    xpack.security.authc.providers:
      saml.saml1:
        order: 0
        realm: saml1
    ```
    
    ## Additional Considerations
    
    - Ensure the IdP certificate used to sign SAML assertions is current
    - Configure role mappings so SAML assertion attributes map to Elasticsearch roles
    - Enable debug logging if authentication fails: `logger.org.elasticsearch.xpack.security.authc: DEBUG`
    
    For troubleshooting specific SAML authentication errors, the documentation provides detailed guidance on common issues like certificate expiration, clock skew, signature validation failures, and role mapping problems.



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
    
    The documentation provided covers breaking changes and new features in Elasticsearch 8.15-9.4, but it does not contain information about how to configure SAML authentication. While the context mentions some security-related changes (such as LDAP authentication validation and TLS requirements), it does not include SAML configuration details.
    
    To find information about SAML authentication configuration, you would need to consult the Elasticsearch Security documentation or authentication configuration guides.



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
    
    ## Elasticsearch Configuration
    
    Configure a SAML realm in `elasticsearch.yml` under `xpack.security.authc.realms.saml`. Key settings include:
    
    - **`idp.metadata.path`**: Path to an up-to-date IdP metadata file (must contain valid XML)
    - **`sp.entity_id`**: The Service Provider entity ID that must match what the IdP expects
    - **`sp.acs`**: Assertion Consumer Service URL where the IdP sends SAML responses (must match the URL Kibana is accessible at)
    - **`attributes.principal`**: Points to the SAML attribute carrying the username (e.g., NameID or a custom attribute)
    - **`nameid_format`**: The NameID format the SAML response should use
    - **`allowed_clock_skew`**: Tolerance for clock differences between Elasticsearch and IdP
    
    ## Kibana Configuration
    
    Configure Kibana to use SAML SSO with:
    
    ```
    xpack.security.authc.providers:
      saml.saml1:
        order: 0
        realm: saml1
    ```
    
    ## Additional Considerations
    
    - Ensure the IdP certificate used to sign SAML assertions is current
    - Configure role mappings so SAML assertion attributes map to Elasticsearch roles
    - Enable debug logging if authentication fails: `logger.org.elasticsearch.xpack.security.authc: DEBUG`
    
    For troubleshooting specific SAML authentication errors, the documentation provides detailed guidance on common issues like certificate expiration, clock skew, signature validation failures, and role mapping problems.
    
    BAD CONTEXT ANSWER:
    ----------------------------------------------------------------------
    I do not have enough information in the provided context to answer this question.
    
    The documentation provided covers breaking changes and new features in Elasticsearch 8.15-9.4, but it does not contain information about how to configure SAML authentication. While the context mentions some security-related changes (such as LDAP authentication validation and TLS requirements), it does not include SAML configuration details.
    
    To find information about SAML authentication configuration, you would need to consult the Elasticsearch Security documentation or authentication configuration guides.
    
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
    
    Based on the documentation provided, here's how to configure SAML authentication:
    
    ## Basic SAML Realm Configuration
    
    SAML authentication is configured in the `xpack.security.authc.realms.saml` namespace in `elasticsearch.yml`. [Source 1] Key settings include:
    
    - **`xpack.security.authc.realms.saml.saml1.idp.metadata.path`**: Path to the Identity Provider (IdP) metadata file containing the signing certificate and other IdP configuration [Source 1]
    
    - **`xpack.security.authc.realms.saml.saml1.sp.entity_id`**: The Service Provider (SP) entity ID that must match what the IdP expects [Source 1]
    
    - **`xpack.security.authc.realms.saml.saml1.sp.acs`**: The Assertion Consumer Service URL where the IdP sends SAML responses [Source 1]
    
    - **`xpack.security.authc.realms.saml.saml1.attributes.principal`**: Points to the SAML attribute carrying the username (e.g., NameID or a custom attribute) [Source 1]
    
    - **`xpack.security.authc.realms.saml.saml1.nameid_format`**: The NameID format expected in SAML responses [Source 1]
    
    - **`xpack.security.authc.realms.saml.saml1.allowed_clock_skew`**: Tolerance for clock differences between Elasticsearch and the IdP [Source 1]
    
    ## Kibana Configuration
    
    To enable SAML SSO in Kibana, configure: [Source 2]
    
    ```
    xpack.security.authc.providers:
      saml.saml1:
        order: 0
        realm: saml1
    ```
    
    The documentation provided does not contain complete example configurations for all SAML settings. For comprehensive configuration details, you would need to consult the full Elasticsearch SAML authentication documentation.
    
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
    Based on the provided documentation, here are the key ways to monitor shard allocation in Elasticsearch:
    
    **Check Cluster Health:**
    ```
    GET /_cluster/health
    ```
    This shows the overall cluster status (green, yellow, or red) and the number of unassigned shards. A healthy cluster displays `status: green` and `unassigned_shards: 0`.
    
    **View Unassigned Shards:**
    ```
    GET /_cat/shards?v&h=index,shard,prirep,state,unassigned.reason
    ```
    This command displays shard details including state and unassigned reasons. Unassigned shards show `state: UNASSIGNED`, and the `prirep` value indicates whether it's a primary (p) or replica (r) shard.
    
    **Get Root Cause for Specific Unassigned Shards:**
    ```
    POST /_cluster/allocation/explain
    { "index": "my-index", "shard": 0, "primary": false }
    ```
    This provides detailed information about why a specific shard is unassigned.
    
    **Monitor Disk Watermarks:**
    Watch your disk usage against the allocation watermarks:
    - Low watermark (85% default): No new shards allocated
    - High watermark (90% default): Existing shards relocated away
    - Flood stage (95% default): Indices become read-only
    
    The documentation also recommends using ILM (Index Lifecycle Management) to automate lifecycle management and prevent disk saturation issues that can affect shard allocation.


## Multi-hop retrieval agent

A single-turn RAG pipeline answers one question from one retrieval. But some questions require multiple lookups — find an answer, then follow up on something in that answer, then follow up again.

The cell below implements a minimal multi-hop agent: it asks the LLM whether a follow-up retrieval is needed, and if so, what to retrieve next. The LLM uses the Inference API (same API key) to decide.

This runs entirely against your Elastic project — no extra infrastructure.


```python
AGENT_SYSTEM = (
    "You are a retrieval agent. Given a question and some context, either:\n"
    "1. Answer the question if the context is sufficient. Start your response with ANSWER:  \n"
    "2. Ask for more information if needed. Start with LOOKUP: followed by the next search query.\n"
    "\nUse LOOKUP only once — if the second context doesn't answer the question, say so."
)

def agent_turn(question, context_docs, history=""):
    """One turn of the agent loop."""
    ctx = build_prompt(context_docs, question)
    user_msg = (f"Previous context:\n{history}\n\n" if history else "") + ctx
    resp = requests.post(
        f"{ES_ENDPOINT}/_inference/chat_completion/{LLM_INFERENCE_ID}/_stream",
        headers={"Authorization": f"ApiKey {ES_API_KEY}", "Content-Type": "application/json"},
        json={"messages": [
            {"role": "system", "content": AGENT_SYSTEM},
            {"role": "user",   "content": user_msg},
        ]},
        stream=True,
        timeout=60,
    )
    resp.raise_for_status()
    chunks = []
    for line in resp.iter_lines():
        if not line: continue
        line = line.decode("utf-8")
        if not line.startswith("data: "): continue
        data_str = line[6:]
        if data_str.strip() == "[DONE]": break
        try:
            delta = json.loads(data_str).get("choices", [{}])[0].get("delta", {})
            if "content" in delta: chunks.append(delta["content"])
        except json.JSONDecodeError:
            pass
    return "".join(chunks)

def multi_hop_agent(question, max_hops=2):
    """Minimal multi-hop RAG agent."""
    print(f"Question: {question!r}\n")
    history = ""
    for hop in range(1, max_hops + 1):
        print(f"--- Hop {hop}: retrieving ---")
        docs = hybrid_search(question)
        for i, d in enumerate(docs[:3], 1):
            print(f"  {i}. {d['title']}")
        response = agent_turn(question, docs, history)
        print(f"\nAgent: {response}\n")
        if response.startswith("ANSWER:"):
            return response[7:].strip()
        elif response.startswith("LOOKUP:"):
            follow_up = response[7:].strip()
            print(f"  → Following up with: {follow_up!r}")
            history += f"\n\n[Hop {hop} retrieved context]\n" + build_prompt(docs, question)
            question = follow_up
        else:
            return response  # agent answered without prefix
    return "(max hops reached)"

# Try it:
multi_hop_agent("What are the security requirements for setting up Kibana?")
```

    Question: 'What are the security requirements for setting up Kibana?'
    
    --- Hop 1: retrieving ---
      1. Set up security in self-managed Elasticsearch deployments
      2. Authentication in Kibana
      3. SAML authentication troubleshooting
    
    Agent: # ANSWER:
    
    Based on the provided context, here are the security requirements for setting up Kibana:
    
    ## Authentication Configuration
    Kibana requires configuring an authentication mechanism after setting up authentication in Elasticsearch. The supported options include:
    
    1. **Basic authentication** - Username and password via login form (based on Native, LDAP, or Active Directory realms)
    2. **Token authentication** - Uses Elasticsearch token APIs
    3. **PKI authentication** - X.509 client certificates
    4. **SAML single sign-on** - External Identity Provider authentication
    5. **OpenID Connect (OIDC)** - OIDC Provider authentication
    6. **Kerberos** - SPNEGO-based single sign-on
    7. **Anonymous authentication** - Access without credentials (useful for embedded dashboards)
    8. **HTTP authentication** - ApiKey, Bearer, Basic, or custom schemes for machine-to-machine access
    
    ## TLS/Encryption Requirements
    - **HTTPS/TLS is optional but recommended** for the Kibana HTTP layer (port 5601)
    - If Elasticsearch uses TLS for its HTTP layer, Kibana must be configured to trust it via:
      ```
      elasticsearch.ssl.certificateAuthorities: /path/to/ca.crt
      ```
    - Note: PKI authentication does not work if Kibana is behind a TLS termination proxy
    
    ## Session Management
    For SAML and OIDC providers, session lifetime is controlled by:
    - `xpack.security.session.idleTimeout`
    - `xpack.security.session.lifespan`
    
    ## Multiple Providers
    Multiple authentication providers can be configured simultaneously with order priorities, allowing users to select their preferred authentication method via the Login Selector UI.
    





    '# ANSWER:\n\nBased on the provided context, here are the security requirements for setting up Kibana:\n\n## Authentication Configuration\nKibana requires configuring an authentication mechanism after setting up authentication in Elasticsearch. The supported options include:\n\n1. **Basic authentication** - Username and password via login form (based on Native, LDAP, or Active Directory realms)\n2. **Token authentication** - Uses Elasticsearch token APIs\n3. **PKI authentication** - X.509 client certificates\n4. **SAML single sign-on** - External Identity Provider authentication\n5. **OpenID Connect (OIDC)** - OIDC Provider authentication\n6. **Kerberos** - SPNEGO-based single sign-on\n7. **Anonymous authentication** - Access without credentials (useful for embedded dashboards)\n8. **HTTP authentication** - ApiKey, Bearer, Basic, or custom schemes for machine-to-machine access\n\n## TLS/Encryption Requirements\n- **HTTPS/TLS is optional but recommended** for the Kibana HTTP layer (port 5601)\n- If Elasticsearch uses TLS for its HTTP layer, Kibana must be configured to trust it via:\n  ```\n  elasticsearch.ssl.certificateAuthorities: /path/to/ca.crt\n  ```\n- Note: PKI authentication does not work if Kibana is behind a TLS termination proxy\n\n## Session Management\nFor SAML and OIDC providers, session lifetime is controlled by:\n- `xpack.security.session.idleTimeout`\n- `xpack.security.session.lifespan`\n\n## Multiple Providers\nMultiple authentication providers can be configured simultaneously with order priorities, allowing users to select their preferred authentication method via the Login Selector UI.'


