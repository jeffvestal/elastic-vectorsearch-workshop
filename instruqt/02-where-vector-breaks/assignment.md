---
slug: where-vector-breaks
id: aiewf2026-lab2
type: challenge
title: "Lab 2 — Where Vector Breaks (and Lexical's Own Gap)"
teaser: Break the Lab 1 high. Discover where pure vector search fails, rescue it with BM25 — then watch BM25 fail at something vector got right.
tabs:
- id: kibana-console
  title: Kibana Dev Console
  type: service
  hostname: serverless
  path: /app/dev_tools#/console
  port: 443
difficulty: basic
timelimit: 1800
---

# Lab 2 — Where Vector Breaks (and Lexical's Own Gap)

**Time budget: ~25 minutes**

---

## The Setup

In Lab 1, vector search looked like magic. It matched intent, not keywords. By the end you were probably thinking "why would I ever use keyword search?"

Lab 2 answers that question by breaking vector search three different ways — then breaks BM25 one way.

The thesis: **each method is strongest exactly where the other is weakest.** That tension motivates Lab 3.

---

## Part A — Where Vector Fails (3 adversarial queries)

Vector search encodes *semantic meaning* — which is exactly its weakness when the query is not about meaning. Exact numbers, version strings, error codes, and dotted setting names are **tokens with no semantic neighborhood**. Vector search approximates them. BM25 nails them.

### Part A, Query 1 — Exit Code

Run the `exit code 137` semantic query from queries.md.

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
  "_source": ["id", "title"]
}
```

**What you'll see:** The top results are docs about JVM memory, cluster health, or OOM errors — thematically related. But the *specific* doc that mentions `exit code 137` by name (doc-007) may not be at rank 1.

**Why:** Vector embeds "exit code 137" into a neighborhood near "memory error", "OOM", "JVM crash" — semantically reasonable, but the wrong kind of match for this query. The user wants the *exact* doc, not topically similar docs.

---

### Part A, Query 2 — Version String

Run the `8.18 breaking changes` semantic query.

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
  "_source": ["id", "title", "version_tags"]
}
```

**What you'll see:** The 8.15, 8.18, and 9.0 release notes all surface with similar scores — they're semantically near-identical (all about "breaking changes, deprecated APIs, migration"). Vector can't pin a specific version.

**Why:** "8.18" is a version token. Semantically, 8.15, 8.18, and 9.0 are in the same neighborhood. The number itself carries no semantic weight.

---

### Part A, Query 3 — Exact Setting Name

Run the `xpack.security.authc.realms configuration` semantic query.

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
  "_source": ["id", "title"]
}
```

**What you'll see:** Generic security/configuration docs. Vector maps the dotted setting name to "security" and "authentication" concepts — misses the pages that actually reference this specific setting.

**Why:** Dotted setting names like `xpack.security.authc.realms` are high-specificity tokens. They're rare. BM25's IDF scoring rewards exact rare matches; vector doesn't.

---

## Part B — Lexical Rescue (BM25 wins on exact tokens)

Now rewrite the same three queries using a `standard` retriever with `multi_match`. Run each from the Part B section of queries.md.

The `multi_match` query does BM25: tokenize the query, find docs containing those tokens, score by TF-IDF.

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
  "_source": ["id", "title"]
}
```

**What you'll see:** doc-007 (JVM settings / exit code 137) ranks #1. Run the same pattern for the version string and setting name queries — BM25 nails all three.

**Why:** BM25 tokenizes your query and scores by term frequency / inverse document frequency. `exit code 137` → tokens {exit, code, 137} → the doc that contains "exit code 137" verbatim gets a high IDF-weighted score. Precision on exact matches is BM25's superpower.

---

## Part C — BM25's Gap (the paraphrase query)

Now we flip it. This is the highest-stakes moment in Lab 2.

Run the `user can't log in` query — **first as semantic, then as BM25**.

### Step 1: Semantic (vector wins)

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

**Expected:** doc-001 (SAML authentication troubleshooting) should rank in the top 2.

**Why vector wins:** Jina v5 encodes "user can't log in" into the same semantic neighborhood as "authentication failure", "credential error", "realm configuration". The doc never says "log in" — it says "authentication failure" and "realm configuration" — but those are semantically equivalent.

### Step 2: BM25 (lexical fails)

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

**Expected:** doc-001 is NOT in the top 5. BM25 returns docs that contain "user", "in", or other query tokens — but doc-001's body contains none of the words "log", "login", or "can't" as they relate to authentication. BM25 score = 0 for doc-001.

**The aha moment:** doc-001 says exactly what the user is experiencing. The vocabulary just doesn't match. BM25's strength (exact tokens) is also its weakness (vocabulary mismatch).

---

## The Core Tension

| Method | Wins at | Fails at |
|--------|---------|---------|
| Vector | Natural language, paraphrases, intent | Exact tokens, version numbers, codes, settings |
| BM25 | Exact tokens, version strings, codes | Natural language, paraphrases, synonyms |

**Each method is strongest exactly where the other is weakest.** This is why you need both.

**Next: Lab 3 — Hybrid: Best of Both**
