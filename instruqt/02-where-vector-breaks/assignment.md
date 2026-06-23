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
  path: /
  port: 8888
difficulty: basic
timelimit: 1800
enhanced_loading: null
---
# Lab 2 — Where Vector Breaks (and Lexical's Own Gap)

**Goal:** Find the queries where semantic search fails. Rescue them with BM25. Then find where BM25 fails too.

***

## Part A — Break vector search with exact tokens

Run these queries using `semantic` on `body_semantic`. Check the top results.

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

Also try:
- `"8.18 breaking changes"` — version string (vector blurs 8.15 / 8.18 / 9.0)
- `"xpack.security.authc.realms configuration"` — exact setting name

**Expected behavior:** wrong or irrelevant docs at rank 1. Vector can't distinguish `137` from `136`.

***

## Part B — BM25 rescues exact tokens

Same query, different retriever:

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

BM25 wins here — exact token match, TF-IDF scoring, right doc at rank 1.

***

## Part C — Now break BM25 with a paraphrase

**Semantic wins:**
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
Expected: SAML/auth troubleshooting doc in top 3.

**BM25 fails:**
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
Expected: that doc is NOT in top 5. No matching tokens = zero BM25 score.

***

## The Core Tension

| Method | Wins at | Fails at |
|--------|---------|---------|
| Vector | Natural language, paraphrases, intent | Exact tokens, version numbers, codes |
| BM25 | Exact tokens, version strings, settings | Paraphrases, synonyms, intent |

**Next lab:** combine both into a single retriever that wins on all query types.

***

## Go deeper — Python Notebook

Open the **Python Notebook** tab and run `lab2-where-vector-breaks.ipynb` to:
- Run all comparisons in Python with a side-by-side `compare()` helper
- Read the BM25 `_explanation` tree to understand tf/idf scoring
- See the core-tension table with all failure modes summarized