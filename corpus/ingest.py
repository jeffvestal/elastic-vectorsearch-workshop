#!/usr/bin/env python3
"""
Ingest script for AIEWF 2026 workshop corpus.

Reads docs.json, creates an Elasticsearch index with the correct mapping
(semantic_text + standard BM25 text fields), and bulk-indexes all documents.

Usage:
    ES_ENDPOINT=https://... ES_API_KEY=... python ingest.py

Requirements:
    pip install elasticsearch
"""

import json
import os
import sys
from pathlib import Path

from elasticsearch import Elasticsearch, helpers

# ─── Configuration ────────────────────────────────────────────────────────────

INDEX_NAME = "aiewf-workshop-docs"

DOCS_FILE = Path(__file__).parent / "docs.json"

# ─── Index Mapping ────────────────────────────────────────────────────────────

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "id": {
                "type": "keyword"
            },
            "title": {
                "type": "text",
                "fields": {
                    "keyword": {"type": "keyword"}
                }
            },
            "url": {
                "type": "keyword"
            },
            "body": {
                "type": "text"
            },
            # semantic_text auto-assigns .jina-embeddings-v5-text-small on Serverless — no inference_id needed
            "body_semantic": {
                "type": "semantic_text"
            },
            "product": {
                "type": "keyword"
            },
            "version_tags": {
                "type": "keyword"
            },
            "trap_type": {
                "type": "keyword"
            }
        }
    },
}

# ─── Main ─────────────────────────────────────────────────────────────────────

def get_client() -> Elasticsearch:
    endpoint = os.environ.get("ES_ENDPOINT")
    api_key = os.environ.get("ES_API_KEY")

    if not endpoint or not api_key:
        print("ERROR: Set ES_ENDPOINT and ES_API_KEY environment variables.")
        print("  export ES_ENDPOINT=https://your-project.es.us-east-1.aws.elastic.cloud")
        print("  export ES_API_KEY=your_api_key_here")
        sys.exit(1)

    return Elasticsearch(
        endpoint,
        api_key=api_key,
        request_timeout=60,
    )


def create_index(es: Elasticsearch) -> None:
    if es.indices.exists(index=INDEX_NAME):
        print(f"Index '{INDEX_NAME}' already exists. Deleting and recreating...")
        es.indices.delete(index=INDEX_NAME)

    print(f"Creating index '{INDEX_NAME}'...")
    es.indices.create(
        index=INDEX_NAME,
        mappings=INDEX_MAPPING["mappings"],
    )
    print("Index created.")


def load_docs() -> list[dict]:
    if not DOCS_FILE.exists():
        print(f"ERROR: {DOCS_FILE} not found. Run from the corpus/ directory or provide the correct path.")
        sys.exit(1)

    with open(DOCS_FILE) as f:
        docs = json.load(f)

    print(f"Loaded {len(docs)} documents from {DOCS_FILE}")
    return docs


def generate_actions(docs: list[dict]):
    """Generate bulk index actions. The body_semantic field copies from body."""
    for doc in docs:
        yield {
            "_index": INDEX_NAME,
            "_id": doc["id"],
            "_source": {
                "id": doc["id"],
                "title": doc["title"],
                "url": doc["url"],
                "body": doc["body"],
                # semantic_text: ES will auto-embed this via EIS at index time
                "body_semantic": doc["body"],
                "product": doc.get("product", ""),
                "version_tags": doc.get("version_tags", []),
                "trap_type": doc.get("trap_type", None),
            }
        }


def bulk_index(es: Elasticsearch, docs: list[dict]) -> None:
    print(f"Indexing {len(docs)} documents...")
    print("Note: semantic_text fields are embedded by EIS at index time — this may take a moment.")

    success_count = 0
    error_count = 0

    for ok, result in helpers.streaming_bulk(
        es,
        generate_actions(docs),
        chunk_size=10,
        raise_on_error=False,
    ):
        if ok:
            success_count += 1
            if success_count % 10 == 0:
                print(f"  Indexed {success_count}/{len(docs)}...")
        else:
            error_count += 1
            print(f"  ERROR: {result}")

    print(f"\nDone. {success_count} indexed, {error_count} errors.")


def verify(es: Elasticsearch) -> None:
    """Quick verification — count docs and run a test semantic query."""
    import time
    time.sleep(2)  # let ES catch up

    count = es.count(index=INDEX_NAME)["count"]
    print(f"\nVerification: {count} documents in index.")
    if count == 0:
        print("ERROR: 0 documents indexed — ingest failed. Check logs above.")
        sys.exit(1)

    print("\nRunning test semantic query: 'securing cluster traffic'...")
    result = es.search(
        index=INDEX_NAME,
        retriever={
            "standard": {
                "query": {
                    "semantic": {
                        "field": "body_semantic",
                        "query": "securing cluster traffic"
                    }
                }
            }
        },
        size=3,
        source=["id", "title", "trap_type"],
    )
    hits = result["hits"]["hits"]
    print(f"Top {len(hits)} results:")
    for hit in hits:
        src = hit["_source"]
        print(f"  [{src['id']}] {src['title']} (trap_type: {src.get('trap_type')})")


def main():
    es = get_client()

    info = es.info()
    print(f"Connected to Elasticsearch {info['version']['number']}")

    docs = load_docs()
    create_index(es)
    bulk_index(es, docs)
    verify(es)

    print(f"\nCorpus ready. Index: {INDEX_NAME}")
    print(f"Run lab queries against this index in Kibana Dev Console.")


if __name__ == "__main__":
    main()
