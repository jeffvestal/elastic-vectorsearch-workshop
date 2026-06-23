---
slug: hybrid-search
id: donwpieuwi7g
type: challenge
title: 'Lab 3 — Hybrid: Best of Both (RRF + Linear Combination)'
teaser: Compose BM25 and semantic under an RRF retriever. Then try linear combination
  with MinMax normalization. Build the production-grade hybrid retriever that wins
  on all query types.
tabs:
- id: qhqkmuhcysfa
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
- id: v0aqmzfyqger
  title: Python Notebook
  type: service
  hostname: kubernetes-vm
  path: /
  port: 8888
difficulty: intermediate
timelimit: 1800
enhanced_loading: null
---
# Lab 3 — Hybrid: Best of Both (RRF + Linear Combination)

**Goal:** Compose BM25 + semantic into a single retriever that wins on all query types from Labs 1 & 2.

***

## Part A — RRF Hybrid Retriever

RRF (Reciprocal Rank Fusion) combines ranked lists without needing score normalization.

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
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
        {
          "standard": {
            "query": {
              "semantic": {
                "field": "body_semantic",
                "query": "user can't log in"
              }
            }
          }
        }
      ],
      "rank_constant": 60,
      "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "trap_type"]
}
```

**Test it against Lab 2's hard queries** — change `"user can't log in"` in BOTH sub-retrievers to:
- `"exit code 137"` — should now find the right doc (BM25 sub-retriever wins)
- `"user can't log in"` — should find SAML doc (semantic sub-retriever wins)

The hybrid wins on both.

***

## Part B — Linear Retriever with MinMax Normalization

Linear combination lets you tune weights per sub-retriever:

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "linear": {
      "retrievers": [
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
          "weight": 0.5
        },
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
          "weight": 0.5
        }
      ],
      "normalizer": "minmax",
      "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```

Try shifting weights — `0.8` BM25 / `0.2` semantic for exact-token-heavy workloads.

***

## RRF vs Linear

| | RRF | Linear |
|---|---|---|
| Normalization | Not needed (rank-based) | MinMax built-in |
| Tuning | None required | Weights per sub-retriever |
| Production default | Yes | When you have calibrated weights |

**Next lab:** wire this retriever to an LLM and prove retrieval quality determines answer quality.

***

## Go deeper — Python Notebook

Open the **Python Notebook** tab and run `lab3-hybrid-search.ipynb` to:
- Compute Recall@K objectively across BM25, semantic, and RRF on all 4 trap queries
- Build a version-filtered hybrid retriever using `bool.filter`
- Run linear combination with tunable weights and see normalization in action
- Try cross-encoder reranking with `text_similarity_reranker`
- Review the full retriever decision framework table