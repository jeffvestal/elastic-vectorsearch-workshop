---
slug: where-vector-breaks
id: hir00y6ebc0g
type: challenge
title: Lab 2 — Where Vector Breaks (and Lexical's Own Gap)
teaser: Break the Lab 1 high. Discover where pure semantic search fails on exact tokens.
  BM25 rescues it — then falls on paraphrases. Both methods are weak where the other
  is strong.
tabs:
- id: nyzkqbhzqoo7
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
- id: sdsrjzcqbzki
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /notebooks/lab2-where-vector-breaks.ipynb
  port: 8888
difficulty: basic
timelimit: 1800
enhanced_loading: null
---
# Lab 2 — Where Vector Breaks (and Lexical's Own Gap)

**Goal:** Find the queries where semantic search fails. Rescue them with BM25. Then find where BM25 fails too.

# Part 1 — Dev Console

> **How to run queries:** Copy each code block into the **Elastic Cloud Serverless** tab (the Dev Console). Click the green ▶ play button or press **Ctrl+Enter** to execute.

***

## Part A — Break vector search with exact tokens

Let's start with a query for a specific error code. Copy this into the Dev Console and run it:

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "exit code 137"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

> **What you should see:** The document about OOM-killed processes (exit code 137 = kernel killed the process) is **not** in the top results. You'll see generic memory or crash docs instead.
>
> **Why this fails:** Semantic search compresses text into a meaning vector. The number `137` gets compressed into a general "error/crash" region of vector space — indistinguishable from `136`, `139`, or any other exit code. The exact integer is lost. Semantic search is great at meaning, but meaning can't distinguish `137` from `138`.

Now run these two more to see the same pattern:

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "8.18 breaking changes"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type", "version_tags"]
}
```

> **What you should see:** Results include docs about 8.15, 8.17, or 9.0 breaking changes — not specifically 8.18.
>
> **Why this fails:** `8.18` and `8.15` are semantically identical (both mean "a specific Elasticsearch version"). The vector model can't tell them apart because they *mean* the same thing. Only exact token matching can distinguish version strings.

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "xpack.security.authc.realms configuration"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

> **What you should see:** Generic security/auth docs, but not the specific `xpack.security.authc.realms` settings reference.
>
> **Why this fails:** That dotted config key is a precise identifier. Semantic search sees "something about realm configuration" and returns broadly related security docs — it doesn't anchor on the exact string.

***

## Part B — BM25 rescues exact tokens

BM25 (the classic keyword search algorithm) works on exact token matching and term frequency. Copy this into the Dev Console:

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "multi_match": {
          "query": "exit code 137",
          "fields": ["title^3", "body"],
          "type": "best_fields"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

> **What you should see:** The OOM-killed processes doc is now at rank 1 (or very close to it).
>
> **Why BM25 wins here:** BM25 tokenizes `exit code 137` into three separate tokens and scores documents that contain those exact tokens. Documents containing all three — especially `137` — score highest. The exact number is preserved, not compressed.
>
> **The difference from semantic:** BM25 is a counting algorithm. It asks "how often does this exact word appear in this document, relative to the corpus?" Semantic asks "how similar is the meaning of this query to this document?" For exact codes and identifiers, counting wins.

***

## Part C — Now break BM25 with a paraphrase

Run this semantic query:

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "user can't log in"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

> **What you should see:** A SAML / authentication troubleshooting doc in the top 3 results.
>
> **Why semantic wins:** The user said "log in" but the doc talks about "authentication failure" and "identity provider." Different words, same concept. Semantic search maps both into the same region of vector space.

Now run the same query with BM25:

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "multi_match": {
          "query": "user can't log in",
          "fields": ["title^3", "body"],
          "type": "best_fields"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

> **What you should see:** The SAML authentication doc is **not** in the top 5. Completely different results.
>
> **Why BM25 fails here:** BM25 looks for the tokens `user`, `can't`, `log`, `in`. The SAML troubleshooting doc doesn't contain any of those words — it uses "authentication," "principal," "identity provider." Zero token overlap = zero BM25 score. The doc is invisible to keyword search no matter how relevant it actually is.

***

## The Core Tension

Both methods are strong — and both have a fundamental blind spot:

| Method | Wins at | Fails at |
|--------|---------|---------|
| Semantic (vector) | Natural language, paraphrases, intent | Exact tokens, version numbers, error codes |
| BM25 (lexical) | Exact tokens, version strings, config keys | Paraphrases, synonyms, intent |

**The insight:** A real user base sends both query types. You can't know in advance which kind is coming.

**Next step:** combine both into a single retriever that wins on all query types — but first, the notebook.

***

---

# Part 2 — Python Notebook

**Switch to the Python Notebook tab now and open `lab2-where-vector-breaks.ipynb`.**

Run the cells in order:

- Run all comparisons side-by-side with a `compare()` helper — semantic and BM25 results printed together so the failure is unmissable
- Read the BM25 `_explanation` tree to see exactly how tf/idf scoring assigns the score
- See the full failure-mode table across all trap query types

When you've finished the notebook, **click Next** to move to Lab 3 — where we fix both failure modes at once.
