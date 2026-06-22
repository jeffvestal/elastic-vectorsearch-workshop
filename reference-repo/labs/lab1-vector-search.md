# Lab 1 — Vector Search: The Thing Everyone Reaches For

See `instruqt/01-vector-search/assignment.md` for the full walkthrough.
All Dev Console snippets are in `instruqt/01-vector-search/queries.md`.

---

## Quick Reference

### Check the index mapping

```
GET aiewf-workshop-docs/_mapping
```

Look for `body_semantic.type: "semantic_text"` and `body_semantic.inference_id`.

### Inspect the EIS inference endpoint

```
GET _inference/text_embedding/.jina-embeddings-v5-text-small
```

### Run semantic queries (standard retriever wrapping semantic query)

```
GET aiewf-workshop-docs/_search
{
  "retriever": {
    "standard": {
      "query": {
        "semantic": {
          "field": "body_semantic",
          "query": "securing cluster traffic"
        }
      }
    }
  },
  "size": 5,
  "_source": ["id", "title"]
}
```

Change the `"query"` string to any natural language question.

### Key teaching beat

When you run a `semantic` query:
1. ES sends your query TEXT to EIS
2. EIS runs Jina v5 text embedding → returns a vector
3. ES runs ANN search over the `body_semantic` field
4. Returns semantically relevant docs

No client-side embedding code. No model hosting. Just a `semantic` query.
