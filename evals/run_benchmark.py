from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import statistics
import sys
import time

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models.memory import MemoryRecord
from app.db.session import SessionLocal
from app.embeddings.fake import DeterministicFakeEmbedding
from evals.metrics import mrr_at_k, percentile, recall_at_k
from evals.retrievers import GraphRetriever, HybridRetriever, VectorRetriever
from evals.source_grounded_pipeline import SOURCE_GROUNDED_COLLECTION
from evals.validate_queries import validate_query_file


DEFAULT_QUERY_FILE = Path("evals/queries.jsonl")
SOURCE_GROUNDED_QUERY_FILE = Path("data/evaluation/source_grounded_queries.json")
SOURCE_GROUNDED_MEMORY_FILE = Path("data/evaluation/source_grounded_memories.json")
SOURCE_GROUNDED_MANIFEST_FILE = Path("data/evaluation/source_manifest.json")
TEMPLATE_QUERY_FILE = Path("evals/queries.template.jsonl")
RESULTS_ROOT = Path("evals/results")
SOURCE_GROUNDED_RESULTS_ROOT = Path("results/evaluation/source_grounded")
SOURCE_GROUNDED_DISCLAIMER = (
    "These metrics come from a source-grounded / weakly-supervised benchmark. "
    "Relevance labels were derived from manufacturer troubleshooting records "
    "rather than independently authored human judgments."
)
DEFAULT_K = 10
DEFAULT_REPEATS = 5
DEFAULT_WARMUP = 1


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def _load_query_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("queries")
        if not isinstance(payload, list):
            raise ValueError(f"JSON query dataset must be an array: {path}")
        return payload
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            rows.append(json.loads(raw_line))
    return rows


def _is_template_only(path: Path | None, rows: list[dict] | None = None) -> bool:
    if path is not None and path.name.lower().endswith("template.jsonl"):
        return True
    if rows is None:
        rows = _load_query_rows(path or DEFAULT_QUERY_FILE)
    if not rows:
        return True
    if all(len(str(row.get("relevant_memory_ids", []))) == 2 for row in rows):
        return True
    return any("example" in str(row.get("notes", "")).lower() for row in rows) or all(
        not row.get("relevant_memory_ids", []) for row in rows
    )


def _memory_count() -> int:
    with SessionLocal() as session:
        return int(session.scalar(select(func.count(MemoryRecord.id))))


def _available_memory_ids() -> set[str]:
    with SessionLocal() as session:
        rows = session.execute(select(MemoryRecord.id)).scalars().all()
    return {str(memory_id) for memory_id in rows}


def _validate_source_grounded_dataset(queries_path: Path) -> tuple[list[dict], list[dict]]:
    queries = _load_query_rows(queries_path)
    memories_path = SOURCE_GROUNDED_MEMORY_FILE
    manifest_path = SOURCE_GROUNDED_MANIFEST_FILE
    if not memories_path.exists() or not manifest_path.exists():
        raise FileNotFoundError(
            "Source-grounded memories or source manifest are missing. Run "
            "python -m evals.source_grounded_pipeline first."
        )
    memories = json.loads(memories_path.read_text(encoding="utf-8"))
    if not isinstance(memories, list) or not memories:
        raise ValueError("The generated source-grounded memory corpus is empty or malformed.")
    corpus_ids = {str(memory.get("id")) for memory in memories}
    if len(corpus_ids) != len(memories):
        raise ValueError("The source-grounded memory corpus contains duplicate IDs.")
    database_ids = _available_memory_ids()
    seen_query_ids: set[str] = set()
    required = {
        "query_id", "query_text", "fault_family", "relevant_memory_ids",
        "source_manufacturer", "source_document", "source_url", "label_method",
    }
    for row_number, query in enumerate(queries, start=1):
        if not isinstance(query, dict):
            raise ValueError(f"Query {row_number} must be a JSON object.")
        missing = required - query.keys()
        if missing:
            raise ValueError(f"Query {row_number} is missing fields: {sorted(missing)}")
        query_id = query["query_id"]
        if not isinstance(query_id, str) or not query_id.strip() or query_id in seen_query_ids:
            raise ValueError(f"Query {row_number} has an empty or duplicate query_id: {query_id!r}")
        seen_query_ids.add(query_id)
        if not isinstance(query["query_text"], str) or not query["query_text"].strip():
            raise ValueError(f"Query {query_id} has an empty question.")
        if not isinstance(query["fault_family"], str) or not query["fault_family"].strip():
            raise ValueError(f"Query {query_id} has no fault family.")
        if not query["source_manufacturer"] or not query["source_document"] or not str(query["source_url"]).startswith("https://"):
            raise ValueError(f"Query {query_id} has incomplete source metadata.")
        if query["label_method"] != "source_grounded":
            raise ValueError(f"Query {query_id} has an unexpected label_method.")
        relevant_ids = query["relevant_memory_ids"]
        if not isinstance(relevant_ids, list) or not relevant_ids:
            raise ValueError(f"Query {query_id} must have at least one relevant memory ID.")
        if set(map(str, relevant_ids)) - corpus_ids:
            raise ValueError(f"Query {query_id} references a memory outside the generated corpus.")
        if set(map(str, relevant_ids)) - database_ids:
            raise ValueError(f"Query {query_id} references a memory missing from canonical PostgreSQL.")
    if not queries:
        raise ValueError("The source-grounded query dataset is empty.")
    return queries, memories


def _service_versions() -> dict[str, str]:
    versions = {
        "python": sys.version.split()[0],
        "postgres": "postgres:16-alpine",
        "qdrant": "qdrant/qdrant:latest",
        "neo4j": "neo4j:5.26-community",
    }
    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.yml"
    if compose_path.exists():
        content = compose_path.read_text(encoding="utf-8")
        for service_name, default in (("postgres", "postgres:16-alpine"), ("qdrant", "qdrant/qdrant:latest"), ("neo4j", "neo4j:5.26-community")):
            marker = f"{service_name}:"
            start = content.find(marker)
            if start != -1:
                image_start = content.find("image:", start)
                if image_start != -1:
                    line = content[image_start + len("image:") :].splitlines()[0].strip()
                    if line:
                        versions[service_name] = line
    return versions


def _build_retrievers(semantic_collection: str | None = None):
    settings = get_settings()
    embedding_provider = DeterministicFakeEmbedding()
    qdrant_client = None
    QdrantSemanticIndex = None
    try:
        from qdrant_client import QdrantClient
        from app.semantic.qdrant_impl import QdrantSemanticIndex as QdrantSemanticIndexImpl

        QdrantSemanticIndex = QdrantSemanticIndexImpl
        qdrant_client = QdrantClient(settings.QDRANT_URL)
        qdrant_client.get_collections()
    except Exception:
        qdrant_client = None

    semantic_index = None
    if qdrant_client is not None and QdrantSemanticIndex is not None:
        semantic_index = QdrantSemanticIndex(
            qdrant_client=qdrant_client,
            embedding_provider=embedding_provider,
            collection_name=semantic_collection or settings.QDRANT_COLLECTION_NAME,
        )

    graph_index = None
    Neo4jGraphMemoryIndex = None
    try:
        from neo4j import GraphDatabase
        from app.graph.neo4j_impl import Neo4jGraphMemoryIndex as Neo4jGraphMemoryIndexImpl

        Neo4jGraphMemoryIndex = Neo4jGraphMemoryIndexImpl
        driver = GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD))
        driver.verify_connectivity()
        graph_index = Neo4jGraphMemoryIndex(driver=driver, database=settings.NEO4J_DATABASE)
        graph_index.bootstrap_constraints()
    except Exception:
        graph_index = None

    prod_hybrid = None
    if semantic_index is not None and graph_index is not None:
        from app.api.deps import get_hybrid_retriever

        prod_hybrid = get_hybrid_retriever(
            semantic_index=semantic_index,
            graph_index=graph_index,
            embedding_provider=embedding_provider,
        )

    return {
        "vector": VectorRetriever(semantic_index=semantic_index, embedding_provider=embedding_provider) if semantic_index else None,
        "graph": GraphRetriever(graph_index=graph_index, semantic_index=semantic_index, embedding_provider=embedding_provider) if graph_index else None,
        "hybrid": HybridRetriever(
            semantic_index=semantic_index,
            graph_index=graph_index,
            embedding_provider=embedding_provider,
            production_retriever=prod_hybrid,
        ) if (semantic_index or graph_index) else None,
    }


def _query_metadata(query: dict) -> tuple[str, str, set[str], str]:
    return (
        str(query["query_id"]),
        str(query["fault_family"]),
        {str(item) for item in query["relevant_memory_ids"]},
        str(query["notes"]),
    )


def _latency_ms_for_retriever(retriever, query_text: str, k: int, warmup: int, repeats: int) -> tuple[list[float], list[str]]:
    if warmup > 0:
        for _ in range(warmup):
            retriever.retrieve(query_text, k)

    timings: list[float] = []
    outputs: list[list[str]] = []
    for _ in range(repeats):
        start = time.perf_counter()
        output = retriever.retrieve(query_text, k)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings.append(elapsed_ms)
        outputs.append(output)

    median_index = int(sorted(range(len(timings)), key=lambda index: timings[index])[len(timings) // 2])
    return timings, outputs[median_index]


def run_benchmark(
    queries_path: Path,
    k: int = DEFAULT_K,
    repeats: int = DEFAULT_REPEATS,
    warmup: int = DEFAULT_WARMUP,
    dataset: str = "human-labeled",
) -> dict:
    source_grounded = dataset == "source-grounded"
    if source_grounded:
        queries, source_memories = _validate_source_grounded_dataset(queries_path)
    else:
        queries = _load_query_rows(queries_path)
        source_memories = []
    if not source_grounded and _is_template_only(queries_path, queries):
        return {
            "dry_run": True,
            "message": (
                "No labeled evaluation file was found. Copy evals/queries.template.jsonl to evals/queries.jsonl, "
                "fill in real relevant_memory_ids, then rerun this benchmark."
            ),
        }

    validated = queries if source_grounded else validate_query_file(
        queries_path,
        known_memory_ids=_available_memory_ids(),
    )
    if not validated:
        raise ValueError("No labeled queries were found. Add at least one real query with non-empty relevant_memory_ids.")

    retrievers = _build_retrievers(
        semantic_collection=SOURCE_GROUNDED_COLLECTION if source_grounded else None,
    )
    if not any(retriever is not None for retriever in retrievers.values()):
        raise RuntimeError("No AegisOps retrieval backends were available. Start the Docker Compose stack before benchmarking.")
    if source_grounded and any(retrievers.get(name) is None for name in ("vector", "graph", "hybrid")):
        raise RuntimeError("Source-grounded runs require all three retrieval backends: vector, graph, and hybrid.")

    method_scores: dict[str, list[float]] = defaultdict(list)
    method_recall5: dict[str, list[float]] = defaultdict(list)
    method_recall10: dict[str, list[float]] = defaultdict(list)
    method_mrr: dict[str, list[float]] = defaultdict(list)
    method_latency_medians: dict[str, list[float]] = defaultdict(list)
    query_rows: list[dict] = []
    zero_result_queries: list[str] = []
    fault_family_counts: dict[str, int] = defaultdict(int)
    query_count_by_method_family: dict[str, dict[str, list[dict[str, float]]]] = defaultdict(lambda: defaultdict(list))

    for query in validated:
        query_id = str(query["query_id"])
        fault_family = str(query["fault_family"])
        fault_family_counts[fault_family] += 1
        relevant = {str(item) for item in query["relevant_memory_ids"]}
        query_row = {
            "query_id": query_id,
            "fault_family": fault_family,
            "query_text": query["query_text"],
            "relevant_memory_ids": sorted(relevant),
            "notes": query["notes"],
            "method_results": {},
            "all_zero_relevant_results": True,
        }

        for method_name in ("vector", "graph", "hybrid"):
            retriever = retrievers.get(method_name)
            if retriever is None:
                method_results = {"recall@5": 0.0, "recall@10": 0.0, "mrr@10": 0.0, "latency_ms": 0.0, "candidate_ids": []}
                query_row["method_results"][method_name] = method_results
                continue

            timings, candidate_ids = _latency_ms_for_retriever(retriever, query["query_text"], k, warmup, repeats)
            method_latency_medians[method_name].append(statistics.median(timings))
            candidate_ids = list(dict.fromkeys(candidate_ids))
            if source_grounded:
                allowed_ids = {str(memory["id"]) for memory in source_memories}
                unexpected_ids = set(candidate_ids) - allowed_ids
                if unexpected_ids:
                    raise RuntimeError(
                        f"{method_name} retrieval returned IDs outside the source-grounded corpus: "
                        f"{sorted(unexpected_ids)}"
                    )

            recall5 = recall_at_k(candidate_ids, relevant, k=5)
            recall10 = recall_at_k(candidate_ids, relevant, k=10)
            mrr10 = mrr_at_k(candidate_ids, relevant, k=10)
            method_recall5[method_name].append(recall5)
            method_recall10[method_name].append(recall10)
            method_mrr[method_name].append(mrr10)
            query_count_by_method_family[fault_family][method_name].append(
                {"recall5": recall5, "recall10": recall10, "mrr": mrr10}
            )

            if recall5 > 0.0 or recall10 > 0.0 or mrr10 > 0.0:
                query_row["all_zero_relevant_results"] = False
                query_row["method_results"][method_name] = {
                    "recall@5": recall5,
                    "recall@10": recall10,
                    "mrr@10": mrr10,
                    "latency_ms": statistics.median(timings),
                    "candidate_ids": candidate_ids,
                }
            else:
                query_row["method_results"][method_name] = {
                    "recall@5": 0.0,
                    "recall@10": 0.0,
                    "mrr@10": 0.0,
                    "latency_ms": statistics.median(timings),
                    "candidate_ids": candidate_ids,
                }

        if query_row["all_zero_relevant_results"]:
            zero_result_queries.append(query_id)

        query_rows.append(query_row)

    method_summary = {}
    for method_name in ("vector", "graph", "hybrid"):
        method_summary[method_name] = {
            "Recall@5": round(sum(method_recall5[method_name]) / len(method_recall5[method_name]), 6) if method_recall5[method_name] else 0.0,
            "Recall@10": round(sum(method_recall10[method_name]) / len(method_recall10[method_name]), 6) if method_recall10[method_name] else 0.0,
            "MRR": round(sum(method_mrr[method_name]) / len(method_mrr[method_name]), 6) if method_mrr[method_name] else 0.0,
            "p50_latency_ms": round(percentile(method_latency_medians[method_name], 50), 3) if method_latency_medians[method_name] else 0.0,
            "p95_latency_ms": round(percentile(method_latency_medians[method_name], 95), 3) if method_latency_medians[method_name] else 0.0,
        }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results_root = SOURCE_GROUNDED_RESULTS_ROOT if source_grounded else RESULTS_ROOT
    results_dir = results_root / timestamp
    results_dir.mkdir(parents=True, exist_ok=True)

    relevant_memory_count = len({
        str(memory_id)
        for query in validated
        for memory_id in query["relevant_memory_ids"]
    })
    by_fault_family = {}
    for family_name, methods in sorted(query_count_by_method_family.items()):
        family_summary = {}
        for method_name in ("vector", "graph", "hybrid"):
            values = methods.get(method_name, [])
            family_summary[method_name] = {
                "Recall@5": round(sum(item["recall5"] for item in values) / len(values), 6) if values else 0.0,
                "Recall@10": round(sum(item["recall10"] for item in values) / len(values), 6) if values else 0.0,
                "MRR": round(sum(item["mrr"] for item in values) / len(values), 6) if values else 0.0,
            }
        by_fault_family[family_name] = {"query_count": fault_family_counts[family_name], "summary_by_method": family_summary}

    payload = {
        "dataset": "source-grounded" if source_grounded else "human-labeled",
        "disclaimer": SOURCE_GROUNDED_DISCLAIMER if source_grounded else "Human-labeled relevance judgments.",
        "timestamp": timestamp,
        "commit": _git_commit(),
        "corpus_size": _memory_count(),
        "query_count": len(validated),
        "relevant_memory_count": relevant_memory_count,
        "fault_family_count": len(fault_family_counts),
        "queries_per_fault_family": dict(sorted(fault_family_counts.items())),
        "by_fault_family": by_fault_family,
        "retriever_configs": {
            "top_k": k,
            "fusion_constant_k": 60,
            "embedding_model": "DeterministicFakeEmbedding(dimension=128)",
            "latency_includes_query_embedding": True,
            "warmup_runs": warmup,
            "repeats_per_query": repeats,
        },
        "service_versions": _service_versions(),
        "summary_by_method": method_summary,
        "query_rows": query_rows,
        "zero_result_queries": zero_result_queries,
        "notes": "Latency measurements include query embedding and retrieval for the method under test, matching the real production path.",
    }

    if source_grounded:
        payload["source_memory_count"] = len(source_memories)
        payload["source_manifest"] = str(SOURCE_GROUNDED_MANIFEST_FILE)
        payload["query_dataset_sha256"] = hashlib.sha256(queries_path.read_bytes()).hexdigest()

    results_path = results_dir / ("summary.json" if source_grounded else "results.json")
    results_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if source_grounded:
        with (results_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["dataset", "method", "Recall@5", "Recall@10", "MRR", "p50_latency_ms", "p95_latency_ms", "query_count", "relevant_memory_count", "fault_family_count", "disclaimer"],
            )
            writer.writeheader()
            for method_name in ("vector", "graph", "hybrid"):
                writer.writerow({
                    "dataset": payload["dataset"],
                    "method": method_name,
                    **method_summary[method_name],
                    "query_count": len(validated),
                    "relevant_memory_count": relevant_memory_count,
                    "fault_family_count": len(fault_family_counts),
                    "disclaimer": SOURCE_GROUNDED_DISCLAIMER,
                })
        with (results_dir / "per_query_results.csv").open("w", encoding="utf-8", newline="") as handle:
            fieldnames = ["query_id", "fault_family", "query_text", "relevant_memory_ids", "method", "recall_at_5", "recall_at_10", "mrr_at_10", "median_latency_ms", "candidate_ids", "source_manufacturer", "source_document", "source_url", "label_method"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for query_row in query_rows:
                query = next(item for item in validated if item["query_id"] == query_row["query_id"])
                for method_name, result in query_row["method_results"].items():
                    writer.writerow({
                        "query_id": query_row["query_id"],
                        "fault_family": query_row["fault_family"],
                        "query_text": query_row["query_text"],
                        "relevant_memory_ids": json.dumps(query_row["relevant_memory_ids"]),
                        "method": method_name,
                        "recall_at_5": result["recall@5"],
                        "recall_at_10": result["recall@10"],
                        "mrr_at_10": result["mrr@10"],
                        "median_latency_ms": result["latency_ms"],
                        "candidate_ids": json.dumps(result["candidate_ids"]),
                        "source_manufacturer": query.get("source_manufacturer", ""),
                        "source_document": query.get("source_document", ""),
                        "source_url": query.get("source_url", ""),
                        "label_method": query.get("label_method", "human_labeled"),
                    })
        metadata = {
            "dataset": payload["dataset"],
            "timestamp": timestamp,
            "commit": payload["commit"],
            "query_dataset": str(queries_path),
            "query_dataset_sha256": payload["query_dataset_sha256"],
            "query_count": len(validated),
            "source_memory_count": len(source_memories),
            "relevant_memory_count": relevant_memory_count,
            "fault_family_count": len(fault_family_counts),
            "retriever_configs": payload["retriever_configs"],
            "service_versions": payload["service_versions"],
            "disclaimer": SOURCE_GROUNDED_DISCLAIMER,
        }
        (results_dir / "benchmark_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        (results_dir / "source_manifest.json").write_text(SOURCE_GROUNDED_MANIFEST_FILE.read_text(encoding="utf-8"), encoding="utf-8")

    summary_lines = [
        "# AegisOps retrieval evaluation",
        *([f"> **{SOURCE_GROUNDED_DISCLAIMER}**", ""] if source_grounded else []),
        f"Corpus size: {_memory_count()} memories | Query count: {len(validated)}",
        "",
        "Latency is measured per-query with a warm-up pass discarded, then median latency over repeated runs. Query embedding time is included for all methods, because the graph-only adapter chooses its anchor via the same semantic embedding path used in production.",
        "",
        "| Method | Recall@5 | Recall@10 | MRR | p50 latency (ms) | p95 latency (ms) |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method_name in ("vector", "graph", "hybrid"):
        values = method_summary[method_name]
        summary_lines.append(
            f"| {method_name} | {values['Recall@5']:.4f} | {values['Recall@10']:.4f} | {values['MRR']:.4f} | {values['p50_latency_ms']:.3f} | {values['p95_latency_ms']:.3f} |"
        )

    if zero_result_queries:
        summary_lines.extend(["", "## Queries with zero relevant results across all methods", ", ".join(zero_result_queries)])

    summary_lines.extend(["", "## Per fault-family breakdown", "| Fault family | Query count |"])
    summary_lines.append("| --- | ---: |")
    for family_name, count in sorted(fault_family_counts.items()):
        summary_lines.append(f"| {family_name} | {count} |")

    summary_lines.extend([
        "",
        "## Limitations",
        "- Label quality: source-grounded labels are weak supervision from manufacturer documentation, not independently authored human judgments." if source_grounded else "- Label quality: relevance judgments are human-authored; no automatic labels are inferred from Qdrant or Neo4j outputs.",
        "- Sample size: the benchmark is limited to the number of labeled queries in the current file, which can be small.",
        *(["- Source coverage: this seed corpus contains six records derived from one KEYENCE IV4 source page; the 60 queries are ten fixed-template variants per record, not 60 independent field incidents.", "- Embeddings: the current stack is configured with DeterministicFakeEmbedding, a hash-based test embedding that is not semantic. Vector and hybrid relevance numbers validate retrieval plumbing, not production semantic quality."] if source_grounded else []),
        "- Single-machine latency: timings reflect the local Docker Compose host, not a distributed or production cluster.",
    ])

    summary_path = results_dir / "summary.md"
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    payload["results_dir"] = str(results_dir)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the AegisOps retrieval benchmark against the real Docker Compose stack.")
    parser.add_argument("--dataset", choices=("human-labeled", "source-grounded"), default="human-labeled", help="Select the human gold-standard dataset or separate weakly supervised source-grounded dataset.")
    parser.add_argument("--queries", type=Path, default=None, help="Optional query file override. The selected dataset's default file is used otherwise.")
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="Top-k candidate list to evaluate.")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS, help="Number of runs per query after warm-up.")
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP, help="Warm-up passes to discard before measuring latency.")
    args = parser.parse_args(argv)

    queries_path = args.queries or (SOURCE_GROUNDED_QUERY_FILE if args.dataset == "source-grounded" else DEFAULT_QUERY_FILE)
    rows = _load_query_rows(queries_path)
    if args.dataset == "human-labeled" and _is_template_only(queries_path, rows):
        print(
            "Dry run: the query file is still a template or has empty labels. "
            "Please copy evals/queries.template.jsonl to evals/queries.jsonl, fill in your real relevance IDs, "
            "and rerun the benchmark."
        )
        return 0

    try:
        payload = run_benchmark(queries_path, k=args.k, repeats=max(1, args.repeats), warmup=max(0, args.warmup), dataset=args.dataset)
    except Exception as exc:
        print(f"BENCHMARK FAILED: {exc}", file=sys.stderr)
        return 1

    if payload.get("dry_run"):
        print(payload["message"])
        return 0

    print(f"Benchmark complete. Results written to {payload['results_dir']}.")
    if args.dataset == "source-grounded":
        print(SOURCE_GROUNDED_DISCLAIMER)
    print("| Method | Recall@5 | Recall@10 | MRR | p50 latency (ms) | p95 latency (ms) |")
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for method_name in ("vector", "graph", "hybrid"):
        values = payload["summary_by_method"][method_name]
        print(f"| {method_name} | {values['Recall@5']:.4f} | {values['Recall@10']:.4f} | {values['MRR']:.4f} | {values['p50_latency_ms']:.3f} | {values['p95_latency_ms']:.3f} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
