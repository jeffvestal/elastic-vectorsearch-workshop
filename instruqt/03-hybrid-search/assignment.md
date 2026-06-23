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

**Goal:** Combine BM25 + semantic into a single retriever that wins on all the query types that broke each method individually in Lab 2.

> **How to run queries:** Copy each code block into the **Elastic Cloud Serverless** tab (the Dev Console). Click the green ▶ play button or press **Ctrl+Enter** to execute.

***

## Part A — RRF Hybrid Retriever

**What is RRF?** Reciprocal Rank Fusion combines two ranked result lists into one without needing to compare or normalize their scores. For each document, it computes `1 / (rank_constant + rank)` from each retriever and sums them. A document that ranks #1 in both lists wins. A document that ranks #2 in one and doesn't appear in the other still beats a document that only appears once at #10. Rank position is all that matters — not the raw scores.

Copy this into the Dev Console and run it:

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

> **What you should see:** The SAML authentication doc that BM25 missed in Lab 2 is back in the top results.
>
> **Why this works:** The semantic sub-retriever ranked the SAML doc high. Even though BM25 gave it zero score (no token overlap), RRF only needs *one* of the two sub-retrievers to rank a doc. The SAML doc's strong semantic rank pulls it into the combined top-5.

Now test it against Lab 2's BM25 failure mode. **Change both `"query"` values** in the query above to `"exit code 137"` (update the string in the `multi_match` block AND the `semantic` block) and run it again:

> **What you should see:** The OOM-killed processes doc (exit code 137) is now in the top results.
>
> **Why this works:** This time BM25 found it by exact token match, and RRF fused that into the combined ranking. The hybrid retriever wins on both query types that broke the individual methods.

***

## Part B — Linear Retriever with MinMax Normalization

RRF ignores raw scores. Linear combination uses them — but first normalizes them to the same 0–1 scale using MinMax so scores from different algorithms can be added.

Copy this into the Dev Console:

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

> **What you should see:** Similar results to RRF, but the ranking may differ slightly because linear combination weights the *magnitude* of each score, not just rank position.
>
> **Why the normalizer matters:** BM25 scores are typically in the range 0–20. Semantic scores are typically in the range 0–1. Without normalization, BM25 would completely dominate the sum. `normalizer: minmax` scales each retriever's scores to 0–1 before combining, so `weight: 0.5` actually means 50/50.

Now try shifting the weights to favor BM25 for an exact-token query. Change the `"query"` to `"8.18 breaking changes"` and set `"weight": 0.8` for the BM25 retriever and `"weight": 0.2` for semantic:

> **What you should see:** The 8.18-specific docs rank higher than with equal weights, because the BM25 sub-retriever's exact-token match for `8.18` now has more influence on the final score.

***

## RRF vs Linear — Which Should You Use?

| | RRF | Linear |
|---|---|---|
| Normalization needed | No (rank-based) | Yes (MinMax built-in) |
| Weight tuning | None | Per sub-retriever |
| Recalibration when corpus changes | Not needed | Required |
| Production default | Yes | When you have measured weights |

**The practical difference:** RRF works well out of the box and stays stable as your corpus grows or your embedding model changes. Linear combination can outperform RRF *if* you've measured the right weights for your specific data and query distribution — but those weights go stale when things change.

**Next lab:** Wire this hybrid retriever to an LLM and see how retrieval quality directly controls answer quality.

***

## Go deeper — Python Notebook

Open the **Python Notebook** tab and run `lab3-hybrid-search.ipynb` to:
- Compute Recall@K objectively across BM25, semantic, and RRF on all 4 trap queries (so you can see the improvement as a number, not just by eyeballing)
- Build a version-filtered hybrid retriever using `bool.filter` to scope results to a specific Elasticsearch version
- Run linear combination with tunable weights and watch normalization change the ranking
- Try cross-encoder reranking with `text_similarity_reranker` — a second-pass model that re-scores the top-N results more precisely
- Review the full retriever decision framework: which retriever to reach for based on your query type
