---
slug: where-vector-breaks
id: hir00y6ebc0g
type: challenge
title: Lab 2 — Where Vector Breaks (and Lexical's Own Gap)
teaser: Break the Lab 1 high. See semantic search blur exact identifiers, BM25 mis-rank
  a boosted title, and BM25 go blind to paraphrase. Both methods are weak where the
  other is strong.
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

Part 1 — Dev Console
====================
> [!NOTE]
> **How to run queries:** Copy each code block into the **Elastic Cloud Serverless** tab (the Dev Console). Click the green ▶ play button or press **Ctrl+Enter** to execute.

***

## Part A — Watch vector search *blur* an exact identifier

We seeded the corpus with two `distractor` docs that talk about exit codes and process crashes *generically* — neither contains the literal number `137`. Only `doc-007` (JVM / OOMKilled) does. Run the query both ways:

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
  "_source": ["id", "title", "summary"]
}
```

> **What you should see:** `doc-007` is probably #1 — **but by a razor-thin margin** (score ~0.68), with a `distractor` doc at #2 only ~0.001 behind, and the top 5 all crammed within ~0.05. The exact number `137` barely moves the ranking.
>
> **Why this is the real failure:** semantic search isn't "missing" the doc — it *can't reliably rank* it. The model embedded "exit code 137" as the general concept "a process was killed," and in that neighborhood the OOM doc and the generic crash docs are nearly the same point in vector space. Add one more similar doc, re-embed, or change a chunk, and #1 flips to a doc that doesn't even contain `137`. "Usually #1" is not good enough when a user pastes an exact code.

Now a query semantic gets outright **wrong** — a bare config value:

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "new_primaries"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```

> **What you should see:** the #1 result is a *cluster-health troubleshooting* doc — **not** `doc-008`, the shard-allocation settings page where `new_primaries` is actually documented. The model only had a bare token with no sentence around it, guessed the topic ("something about cluster state"), and landed in the right neighborhood but the wrong document.

And the honest counter-example — semantic is **not** always wrong on identifiers:

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "cluster.routing.allocation.enable"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```

> **What you should see:** `doc-008` at #1. A long, distinctive dotted key embeds into its own corner of vector space, so the model nails it.
>
> **The takeaway:** exact identifiers aren't a guaranteed semantic *miss* — they're a **reliability** problem. Sometimes the model nails them, sometimes it blurs them, sometimes it picks a plausible neighbor. You can't predict which.

***

## Part B — BM25 is decisive on exact tokens (and shows its own trap)

BM25 (the classic keyword algorithm) scores exact token matches weighted by rarity (IDF). Run `exit code 137` through it:

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
  "_source": ["id", "title", "summary"]
}
```

> **What you should see:** `doc-007` at #1 by a **wide, decisive margin** (~8 vs ~6 and a cliff after). The rare token `137` appears in exactly one doc; IDF rewards it heavily. Where semantic was a near-tie, BM25 is unambiguous — exactly what you want for an exact identifier.

But BM25 has its *own* blind spot. Run a version query:

```
GET aiewf-workshop-docs/_search
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
  "size": 5,
  "_source": ["id", "title", "summary", "version_tags"]
}
```

> **What you should see:** BM25 ranks `doc-006` *"Elasticsearch breaking changes"* at #1 — the **wrong** doc. The `8.18` release-notes page (`doc-057`), which the user actually wants, is only #2.
>
> **Why BM25 gets it wrong:** `doc-006`'s *title* is literally "breaking changes," and `title` is boosted `^3`, so those two common words score ~6.5 each (~12.9 total). `doc-057` matches the rare token `8.18` strongly (~5.8) but its title lacks "breaking changes," topping out ~7.4. BM25 rewarded the **boosted common-word title** over the **rare token the user cared about**. (This is a field-boost effect, not "term frequency" — `doc-006` doesn't win by repetition.)
>
> Run the same `8.18 breaking changes` query as a `semantic` query and you'll see the opposite: semantic ranks `doc-057` #1, because it understood you wanted the 8.18 page. The two retrievers fail on *opposite* query shapes.

***

## Part C — Break BM25 with a paraphrase

Our corpus has `doc-049` about **Watcher** (Elasticsearch's alerting system). It talks about `trigger`, `condition`, `actions`, `webhook` — but never the words "notify," "something," or "goes wrong." Run a paraphrased query as semantic:

```
GET aiewf-workshop-docs/_search
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
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```

> **What you should see:** `doc-049` (Watcher alerting) at #1. "Notify me when something goes wrong" *is* the meaning of alerting — semantic maps the query and the doc into the same region of vector space despite zero shared words.

Now the same query with BM25:

```
GET aiewf-workshop-docs/_search
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
  "size": 5,
  "_source": ["id", "title", "summary"]
}
```

> **What you should see:** `doc-049` is **buried** — outside the top few. BM25's top hits are docs that happen to share an incidental common word, not docs about alerting.
>
> **Why BM25 fails here:** BM25 only scores query terms that appear in the doc. None of "notify," "something," "goes," "wrong" are in the Watcher page, so its score is tiny and it sinks. (Note: *buried*, not "zero" — a real index still returns it, just too low to be useful.)

***

## The Core Tension

Both methods are strong — and both have a fundamental blind spot:

| Query | Semantic | BM25 |
|-------|----------|------|
| `exit code 137` (exact id) | ⚠️ #1 but by ~0.001 — unreliable | ✅ decisive #1 |
| `new_primaries` (bare value) | ❌ wrong doc at #1 | ✅ pins the right doc |
| `cluster.routing.allocation.enable` | ✅ #1 — sometimes it nails them | ✅ also strong |
| `8.18 breaking changes` (version) | ✅ #1 (understands intent) | ❌ wrong doc #1 (boosted title) |
| `notify me when something goes wrong` | ✅ #1 | ❌ buried (no shared words) |

**The insight:** Neither retriever is safe alone. Semantic blurs the tokens that must stay exact and can mis-rank bare identifiers; BM25 is precise on rare tokens but gets fooled by boosted common words and goes blind to paraphrase. A real user base sends *all* of these query shapes — and you can't know in advance which is coming.

**Next step:** combine both into a single retriever that wins on all query types — but first, the notebook.

***

---

Part 2 — Python Notebook
========================

## Setup:
1. Switch to the [button label="Python Notebook"](tab-1)
2. Open `lab2-where-vector-breaks.ipynb`

Run the cells in order.

- Run all comparisons side-by-side with a `compare()` helper — semantic and BM25 results printed together so the failure is unmissable
- Read the BM25 `_explanation` tree to see exactly how tf/idf scoring assigns the score
- See the full failure-mode table across all trap query types

When you've finished the notebook, **click Next** to move to Lab 3 — where we fix both failure modes at once.
