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
  path: /notebooks/lab3-hybrid-search.ipynb
  port: 8888
difficulty: intermediate
timelimit: 1800
enhanced_loading: null
---
# Lab 3 — Hybrid: Best of Both (RRF + Linear Combination)

**Goal:** Combine BM25 + semantic into a single retriever that wins on all the query types that broke each method individually in Lab 2.

Part 1 — Dev Console
====================
> [!NOTE]
> **How to run queries:** Copy each code block into the **Elastic Cloud Serverless** tab (the Dev Console). Click the green ▶ play button or press **Ctrl+Enter** to execute.

***

## Part A — RRF Hybrid Retriever

**What is RRF?** Reciprocal Rank Fusion combines two ranked result lists into one without needing to compare or normalize their scores. For each document, it computes `1 / (rank_constant + rank)` from each retriever and sums them. A document that ranks #1 in both lists wins. A document that ranks #2 in one and doesn't appear in the other still beats a document that only appears once at #10. Rank position is all that matters — not the raw scores.

Start with Lab 2's **paraphrase** failure — the one BM25 buried. Copy this into the Dev Console and run it:

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
                "query": "notify me when something goes wrong",
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
                "query": "notify me when something goes wrong"
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
  "_source": ["id", "title", "summary"]
}
```

> **What you should see:** the Watcher alerting doc (`doc-049`) — which BM25 buried at ~#5 in Lab 2 — is back at **#1**.
>
> **Why this works:** the semantic sub-retriever ranked `doc-049` #1. BM25 ranked it low, but RRF only needs *one* of the two sub-retrievers to rank a doc highly. The strong semantic rank pulls it to the top of the fused list.

Now test it against Lab 2's **BM25 failure** — the version query where BM25 ranked the wrong doc. Update the `"query"` string in **both** the `multi_match` and `semantic` blocks to `"8.18 breaking changes"`, then run it:

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
                "query": "8.18 breaking changes",
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
                "query": "8.18 breaking changes"
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
  "_source": ["id", "title", "summary", "version_tags"]
}
```

> **What you should see:** `doc-057` (8.18 release notes) is **#1** — even though BM25 alone put the wrong doc (`doc-006`, "breaking changes") first.
>
> **Why this works:** semantic ranked `doc-057` #1 (it understood the intent); BM25 ranked it #2. RRF fuses those two strong ranks and `doc-057` wins. Try one more — change both queries to `"new_primaries"` (where *semantic* picked the wrong doc and BM25 was right): RRF puts `doc-008` at #1 again. **Same retriever structure, different query, whichever sub-retriever was right carries the fusion.**

***

## Part B — Linear Retriever with MinMax Normalization

RRF ignores raw scores. Linear combination uses them — but first normalizes them to the same 0–1 scale using MinMax so scores from different algorithms can be added.

> [!NOTE]
> **What MinMax actually does — with vs without.** A linear retriever combines each sub-retriever's scores into one number. The question is *whose scores* dominate that sum.
>
> - **Without MinMax:** raw scores are combined as-is. The retriever that happens to produce **larger numbers dominates** the final ranking, your weights are hard to interpret, and results get biased by score *scale* rather than actual relevance.
> - **With MinMax:** each retriever's scores are first rescaled to the same **0–1 range**, so weights behave predictably and the combination is balanced by *relative result quality*, not raw magnitude.
>
> **Quick example.** Retriever A scores 0–100; retriever B scores 0–1.
> - *Without MinMax:* A almost always wins — purely because its numbers are bigger.
> - *With MinMax:* A and B are put on the same scale and can contribute fairly.
>
> That's exactly our situation: **BM25 scores run ~0–20, semantic scores run ~0–1.** Without normalization BM25 would dominate every sum. `normalizer: minmax` levels the field so a `0.5/0.5` weight truly means 50/50.

**Step 1 — Baseline: equal weights on the paraphrase query**

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
                  "query": "notify me when something goes wrong",
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
                  "query": "notify me when something goes wrong"
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
  "_source": ["id", "title", "summary"]
}
```

> **What you should see:** at equal `0.5/0.5` weights a lexical `distractor` doc can edge out the Watcher doc (`doc-049`) at #1 — equal weighting lets BM25's noise compete with semantic's correct signal. Now bump the **semantic** weight to `0.7` and BM25 down to `0.3` and re-run: `doc-049` moves to #1.
>
> **Why the normalizer matters:** see the With/Without MinMax explainer at the top of Part B — `normalizer: minmax` is what makes `0.5/0.5` truly mean 50/50 here. And unlike RRF, linear weighs score *magnitude*, not just rank, which is why the weight you choose changes the winner.

**Step 2 — A query where leaning the "obvious" way *backfires***

Update **both** `"query"` strings to `"8.18 breaking changes"` (leave both weights at `0.5`). Run it:

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
                  "query": "8.18 breaking changes",
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
                  "query": "8.18 breaking changes"
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
  "_source": ["id", "title", "summary", "version_tags"]
}
```

> **What you should see:** at `0.5/0.5` the **wrong** doc (`doc-006`, "Elasticsearch breaking changes") sits at or near #1, with the 8.18 release-notes doc (`doc-057`) behind it. BM25 loves `doc-006`'s boosted title (Lab 2, Part B), and at equal weight it drags the fused ranking with it.
>
> **Note the exact ranking.** You're about to change only the weights — and the "obvious" choice will make it *worse*.

**Step 3 — Change only the weights, keep the same query**

Your instinct might be "it's a version string, lean on BM25." Try it: keep the query `"8.18 breaking changes"`, set BM25 `"weight": 0.8` and semantic `"weight": 0.2`, and run it:

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
                  "query": "8.18 breaking changes",
                  "fields": ["title^3", "body"],
                  "type": "best_fields"
                }
              }
            }
          },
          "weight": 0.8
        },
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
          "weight": 0.2
        }
      ],
      "normalizer": "minmax",
      "rank_window_size": 100
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary", "version_tags"]
}
```

> **What you should see:** the **wrong** doc (`doc-006`) is *still* #1 — leaning on BM25 made the problem worse, because BM25 itself is wrong here (its boosted-title match favors `doc-006`). Now flip it: set BM25 `"weight": 0.2` and semantic `"weight": 0.8` and re-run. `doc-057` (8.18) climbs to #1, because semantic understood you wanted the 8.18 page.
>
> **Why this matters:** there is no single weight that's right for every query. "Version string → trust BM25" is exactly the wrong call here. Linear lets you tune, but the right weights depend on the query *and* the corpus — and MinMax's min/max shift as documents or the embedding model change, so weights need recalibration. That's why RRF (which uses only rank, no weights, no normalization) is the robust production default; reach for linear only with a calibrated, stable workload.

***

## RRF vs Linear — Which Should You Use?

| | RRF | Linear |
|---|---|---|
| Normalization needed | No (rank-based) | Yes (MinMax built-in) |
| Weight tuning | None | Per sub-retriever |
| Recalibration when corpus changes | Not needed | Required |
| Production default | Yes | When you have measured weights |

**The practical difference:** RRF works well out of the box and stays stable as your corpus grows or your embedding model changes. Linear combination can outperform RRF *if* you've measured the right weights for your specific data and query distribution — but those weights go stale when things change.

**Next step:** wire this retriever to an LLM — but first, the notebook.

***

---

Part 2 — Python Notebook
========================

## Setup:
1. Switch to the [button label="Python Notebook"](tab-1)
2. Open `lab3-hybrid-search.ipynb`

Run the cells in order.

- Report the **rank** of the known-good doc across BM25, semantic, and RRF on the trap queries — see RRF land #1 on every one, even where an individual retriever mis-ranked it
- Build a version-filtered hybrid retriever using `bool.filter` to scope results to a specific Elasticsearch version
- Run linear combination with tunable weights and watch the winner change — including a query where the "obvious" weight choice backfires
- Try cross-encoder reranking with `text_similarity_reranker` — a second-pass model that re-scores the top-N results (and see why it shines at scale, not on a toy corpus)
- Review the full retriever decision framework

When you've finished the notebook, **click Next** to move to Lab 4.
