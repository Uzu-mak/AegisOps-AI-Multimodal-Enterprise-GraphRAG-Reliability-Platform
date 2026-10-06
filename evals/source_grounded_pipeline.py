from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DATA_DIR = Path("data/evaluation")
QUERY_PATH = DATA_DIR / "source_grounded_queries.json"
MEMORY_PATH = DATA_DIR / "source_grounded_memories.json"
MANIFEST_PATH = DATA_DIR / "source_manifest.json"
SOURCE_GROUNDED_COLLECTION = "aegisops_source_grounded_eval"
DISCLAIMER = (
    "These metrics come from a source-grounded / weakly-supervised benchmark. "
    "Relevance labels were derived from manufacturer troubleshooting records "
    "rather than independently authored human judgments."
)

SOURCE = {
    "manufacturer": "KEYENCE",
    "document": "Vision Sensor with Built-in AI IV4 Series",
    "source_url": "https://www.keyence.com/products/vision/vision-sensor/iv4/",
    "sections": [
        "AI-Based Imaging: Delivering the Best Image Quality for Detection",
        "Background Removal and Extraction of Only the Detection Target",
        "Easy Installation",
    ],
}

# Each record is a short, weakly supervised interpretation of a stated KEYENCE
# IV4 behavior, not a claim that the source is a service manual or alarm catalog.
SOURCE_RECORDS: list[dict[str, Any]] = [
    {
        "record_key": "keyence-background-false-detection",
        "fault_family": "vision_false_detection",
        "title": "Vision false detection from background noise",
        "symptom": "false detections when background elements enter the image",
        "cause": "background noise or surrounding elements can be mistaken for the detection target",
        "remedy": "use AI Target Extraction to remove surrounding sources of false detection",
        "source_section": "Background Removal and Extraction of Only the Detection Target",
        "evidence": "KEYENCE states that background noise or other surrounding elements can cause false detections, and describes AI Target Extraction as removing sources of false detection from the surroundings.",
    },
    {
        "record_key": "keyence-suboptimal-detection-image",
        "fault_family": "vision_image_quality",
        "title": "Detection instability from a suboptimal inspection image",
        "symptom": "inspection features are not clearly separated in the captured image",
        "cause": "manual image setup may not produce an image where the key target features stand out",
        "remedy": "run AI Imaging II to test imaging conditions and recommend an optimal image for detection",
        "source_section": "AI-Based Imaging: Delivering the Best Image Quality for Detection",
        "evidence": "KEYENCE says AI Imaging II tests over 10,000 conditions and extracts images in which key features stand out clearly to recommend optimal images for detection.",
    },
    {
        "record_key": "keyence-ambient-change-detection",
        "fault_family": "vision_environmental_variation",
        "title": "Detection changes with ambient lighting or surface finish",
        "symptom": "inspection results vary after a small ambient-light or surface-finish change",
        "cause": "environmental factors such as slight ambient-light changes or surface finishes can affect conventional image conditions",
        "remedy": "use the IV4 AI imaging functions to configure image settings for stable detection",
        "source_section": "AI-Based Imaging: Delivering the Best Image Quality for Detection",
        "evidence": "KEYENCE describes IV4 detection stability under environmental factors including slight changes in ambient lighting or surface finishes, and says AI helps configure optimal image settings.",
    },
    {
        "record_key": "keyence-target-variation",
        "fault_family": "vision_target_variation",
        "title": "Detection changes across product variations",
        "symptom": "a vision inspection becomes inconsistent across individual product variations",
        "cause": "product-to-product variation changes the appearance of the target",
        "remedy": "register an image with AI Identify, which KEYENCE says can provide stable detection despite environmental changes or individual product variations",
        "source_section": "Extensive Detection Tools That Simplify Previously Difficult Detection Tasks / AI Identify",
        "evidence": "KEYENCE states that registering a single image with AI Identify can ensure stable detection regardless of environmental changes or individual product variations.",
    },
    {
        "record_key": "keyence-target-position-deviation",
        "fault_family": "vision_position_deviation",
        "title": "False detection when a passing target is misaligned",
        "symptom": "a passing part is misaligned and a point sensor produces false detections",
        "cause": "point-based photoelectric sensing can be affected by target position deviation",
        "remedy": "use image-based vision detection to analyze the target position and orientation across the captured area",
        "source_section": "Frequently Asked Questions About Vision Sensors / Is detection possible if the passing target is misaligned?",
        "evidence": "KEYENCE explains that misaligned products can cause false detections with point-detection sensors, while vision sensors analyze target features to determine position and orientation.",
    },
    {
        "record_key": "keyence-glare-false-detection",
        "fault_family": "vision_glare",
        "title": "False detection from glare on glossy surfaces",
        "symptom": "a glossy metal target produces false detections from reflected light",
        "cause": "glare from strong reflected light on polished metal can cause false detection",
        "remedy": "use IV4 automatic focus and brightness adjustment to determine suitable detection conditions when glare is present",
        "source_section": "Frequently Asked Questions About Vision Sensors / Is detection affected by glossy surfaces?",
        "evidence": "KEYENCE describes false detections from glare on polished metal and states that IV4 automatic focus and brightness adjustment enable stable detection even when glare is present.",
    },
]

QUERY_TEMPLATES = [
    "How should I diagnose {symptom}?",
    "What is the likely cause of {symptom}?",
    "What corrective action is recommended for {symptom}?",
    "Which inspection setting should I check for {symptom}?",
    "How can I reduce {symptom} without replacing the vision sensor?",
    "The line reports {symptom}. What source-backed remedy should I try?",
    "What condition can lead to {symptom}, and how should it be addressed?",
    "Which IV4 function addresses {symptom}?",
    "What should maintenance verify first for {symptom}?",
    "How can the inspection be made more stable given {symptom}?",
]


def _request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AegisOps API returned HTTP {exc.code}: {response_text}") from exc


def _api_memory_ids(api_url: str) -> dict[str, str]:
    query = urllib.parse.urlencode({"source_type": "manufacturer_document", "limit": 1000})
    response = _request_json(f"{api_url.rstrip('/')}/api/v1/memories?{query}")
    return {
        str(item.get("metadata", {}).get("source_record_key")): str(item["id"])
        for item in response.get("items", [])
        if item.get("metadata", {}).get("dataset") == "source_grounded"
        and item.get("metadata", {}).get("source_record_key")
    }


def import_memories(api_url: str) -> dict[str, str]:
    existing = _api_memory_ids(api_url)
    record_ids: dict[str, str] = {}
    for record in SOURCE_RECORDS:
        key = record["record_key"]
        memory_id = existing.get(key)
        if memory_id is None:
            metadata = {
                "dataset": "source_grounded",
                "source_record_key": key,
                "fault_family": record["fault_family"],
                "symptom": record["symptom"],
                "cause": record["cause"],
                "remedy": record["remedy"],
                "source_manufacturer": SOURCE["manufacturer"],
                "source_document": SOURCE["document"],
                "source_url": SOURCE["source_url"],
                "source_section": record["source_section"],
                "source_evidence": record["evidence"],
                "label_method": "source_grounded",
            }
            created = _request_json(
                f"{api_url.rstrip('/')}/api/v1/memories",
                method="POST",
                payload={
                    "memory_type": "document_fact",
                    "title": record["title"],
                    "content": (
                        f"Symptom: {record['symptom']}. Cause: {record['cause']}. "
                        f"Remedy: {record['remedy']}"
                    ),
                    "source_type": "manufacturer_document",
                    "source_id": SOURCE["source_url"],
                    "confidence": 0.7,
                    "importance": 0.7,
                    "is_synthetic": False,
                    "metadata": metadata,
                },
            )
            memory_id = str(created["id"])
        record_ids[key] = memory_id
    return record_ids


def index_source_memories(record_ids: dict[str, str], qdrant_url: str) -> None:
    from datetime import datetime, timezone
    from uuid import UUID

    from qdrant_client import QdrantClient

    from app.embeddings.fake import DeterministicFakeEmbedding
    from app.semantic.index import VectorRecord
    from app.semantic.qdrant_impl import QdrantSemanticIndex

    embedding_provider = DeterministicFakeEmbedding()
    client = QdrantClient(qdrant_url)
    semantic_index = QdrantSemanticIndex(
        qdrant_client=client,
        embedding_provider=embedding_provider,
        collection_name=SOURCE_GROUNDED_COLLECTION,
    )
    indexed_at = datetime.now(timezone.utc)
    for record in SOURCE_RECORDS:
        record_id = UUID(record_ids[record["record_key"]])
        semantic_index.index_memory(
            memory_id=record_id,
            text=f"{record['title']} {record['symptom']} {record['cause']} {record['remedy']}",
            record=VectorRecord(
                memory_id=record_id,
                memory_type="document_fact",
                status="active",
                asset_id=None,
                facility_id=None,
                source_type="manufacturer_document",
                created_at=indexed_at,
                importance=0.7,
                confidence=0.7,
            ),
        )

    points, _ = client.scroll(
        collection_name=SOURCE_GROUNDED_COLLECTION,
        limit=1000,
        with_payload=True,
        with_vectors=False,
    )
    indexed_ids = {str(point.payload["memory_id"]) for point in points}
    expected_ids = set(record_ids.values())
    if indexed_ids != expected_ids:
        raise RuntimeError(
            "The isolated source-grounded Qdrant collection contains unexpected or missing memory IDs. "
            f"Expected {len(expected_ids)}, found {len(indexed_ids)}."
        )


def build_dataset(record_ids: dict[str, str]) -> tuple[list[dict], list[dict]]:
    memories: list[dict] = []
    queries: list[dict] = []
    for record in SOURCE_RECORDS:
        key = record["record_key"]
        memory_id = record_ids[key]
        memory = {
            "id": memory_id,
            "record_key": key,
            "memory_type": "document_fact",
            "title": record["title"],
            "content": f"Symptom: {record['symptom']}. Cause: {record['cause']}. Remedy: {record['remedy']}",
            "fault_family": record["fault_family"],
            "symptom": record["symptom"],
            "cause": record["cause"],
            "remedy": record["remedy"],
            "source_manufacturer": SOURCE["manufacturer"],
            "source_document": SOURCE["document"],
            "source_url": SOURCE["source_url"],
            "source_section": record["source_section"],
            "source_evidence": record["evidence"],
        }
        memories.append(memory)
        for template_index, template in enumerate(QUERY_TEMPLATES, start=1):
            queries.append(
                {
                    "query_id": f"{key}-q{template_index:02d}",
                    "query_text": template.format(symptom=record["symptom"]),
                    "fault_family": record["fault_family"],
                    "relevant_memory_ids": [memory_id],
                    "source_manufacturer": SOURCE["manufacturer"],
                    "source_document": SOURCE["document"],
                    "source_url": SOURCE["source_url"],
                    "source_section": record["source_section"],
                    "label_method": "source_grounded",
                    "notes": DISCLAIMER,
                }
            )
    validate_dataset(queries, memories)
    return memories, queries


def validate_dataset(queries: list[dict], memories: list[dict]) -> None:
    memory_ids = {str(memory["id"]) for memory in memories}
    if len(memory_ids) != len(memories):
        raise ValueError("Source memory corpus contains duplicate memory IDs.")
    seen_query_ids: set[str] = set()
    required = {
        "query_id", "query_text", "fault_family", "relevant_memory_ids",
        "source_manufacturer", "source_document", "source_url", "label_method",
    }
    for row_number, query in enumerate(queries, start=1):
        missing = required - query.keys()
        if missing:
            raise ValueError(f"Query {row_number} is missing fields: {sorted(missing)}")
        query_id = query["query_id"]
        if query_id in seen_query_ids:
            raise ValueError(f"Duplicate query ID: {query_id}")
        seen_query_ids.add(query_id)
        if not isinstance(query["query_text"], str) or not query["query_text"].strip():
            raise ValueError(f"Query {query_id} has an empty question.")
        if not isinstance(query["fault_family"], str) or not query["fault_family"].strip():
            raise ValueError(f"Query {query_id} has no fault family.")
        if not query["source_manufacturer"] or not query["source_document"] or not query["source_url"].startswith("https://"):
            raise ValueError(f"Query {query_id} has incomplete source metadata.")
        if query["label_method"] != "source_grounded":
            raise ValueError(f"Query {query_id} has an unexpected label method.")
        relevant_ids = query["relevant_memory_ids"]
        if not isinstance(relevant_ids, list) or not relevant_ids:
            raise ValueError(f"Query {query_id} has no relevant memories.")
        missing_ids = {str(memory_id) for memory_id in relevant_ids} - memory_ids
        if missing_ids:
            raise ValueError(f"Query {query_id} references memories outside the corpus: {sorted(missing_ids)}")


def write_dataset(
    api_url: str,
    output_dir: Path = DATA_DIR,
    qdrant_url: str = "http://localhost:6333",
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    record_ids = import_memories(api_url)
    index_source_memories(record_ids, qdrant_url)
    memories, queries = build_dataset(record_ids)
    memory_path = output_dir / MEMORY_PATH.name
    query_path = output_dir / QUERY_PATH.name
    manifest_path = output_dir / MANIFEST_PATH.name
    memory_path.write_text(json.dumps(memories, indent=2), encoding="utf-8")
    query_path.write_text(json.dumps(queries, indent=2), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "source": SOURCE,
                "records": [
                    {
                        "record_key": record["record_key"],
                        "fault_family": record["fault_family"],
                        "source_section": record["source_section"],
                        "evidence": record["evidence"],
                        "memory_id": record_ids[record["record_key"]],
                    }
                    for record in SOURCE_RECORDS
                ],
                "query_count": len(queries),
                "memory_count": len(memories),
                "disclaimer": DISCLAIMER,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"memories": memory_path, "queries": query_path, "manifest": manifest_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import source-grounded manufacturer records and generate a separate runnable evaluation dataset.")
    parser.add_argument("--api-url", default="http://localhost:8000", help="AegisOps API base URL.")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="Qdrant URL for the isolated source-grounded collection.")
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR, help="Directory for source-grounded dataset artifacts.")
    args = parser.parse_args(argv)
    paths = write_dataset(args.api_url, args.output_dir, args.qdrant_url)
    print(f"Imported or reused {len(SOURCE_RECORDS)} canonical source memories.")
    print(f"Generated {len(SOURCE_RECORDS) * len(QUERY_TEMPLATES)} source-grounded queries.")
    print(f"Queries: {paths['queries']}")
    print(f"Memories: {paths['memories']}")
    print(f"Source manifest: {paths['manifest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
