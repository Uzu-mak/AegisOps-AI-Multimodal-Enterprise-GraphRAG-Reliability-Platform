# Retrieval evaluation harness

This directory contains the reproducible AegisOps retrieval evaluation harness for the real PostgreSQL + Qdrant + Neo4j stack.

## Two separate datasets

`evals/queries.jsonl` remains the human-authored, gold-standard benchmark. The source-grounded pipeline never writes to or replaces that file.

`data/evaluation/source_grounded_queries.json` is the separate weakly supervised dataset. Its canonical source memories are imported through the AegisOps API, projected to Qdrant and Neo4j, and stored in `data/evaluation/source_grounded_memories.json`. Each query carries its manufacturer, document, URL, fault family, and `label_method: "source_grounded"`.

The seed set currently contains six records from one KEYENCE IV4 source page, expanded into ten fixed-template query variants per record. The app's current `DeterministicFakeEmbedding` is hash-based rather than semantic; these results validate the retrieval pipeline and adapters, not production embedding quality. Add independently sourced manufacturer records and use a semantic embedding provider before drawing broader retrieval conclusions.

> **These metrics come from a source-grounded / weakly-supervised benchmark. Relevance labels were derived from manufacturer troubleshooting records rather than independently authored human judgments.**

Generate/import the source-grounded corpus and query dataset:

```bash
python -m evals.source_grounded_dataset
```

Validate and run all three retrieval modes against that dataset:

```bash
python -m evals.run_benchmark --dataset source-grounded --k 10 --repeats 5 --warmup 1
```

Source-grounded run artifacts are written to `results/evaluation/source_grounded/<timestamp>/` and include `summary.json`, `summary.csv`, `per_query_results.csv`, `benchmark_metadata.json`, and `source_manifest.json`.

## Assumptions and constraints

- PostgreSQL is the canonical source of truth; Qdrant and Neo4j are derived indexes.
- Human-labeled relevance judgments are never inferred from Qdrant similarity, Neo4j edges, or retrieval output. The human-authored dataset remains the gold-standard benchmark; weak source-derived labels are reported separately.
- The graph-only adapter uses the production traversal path from Neo4j but selects an anchor memory using the same semantic embedding path as the production hybrid retriever. This is the most conservative adapter that reuses the real graph traversal logic without inventing a text-to-graph search subsystem.
- Human-labeled runs do not run unless their query file contains real PostgreSQL relevance IDs; the template file is intentionally invalid for reporting. Source-grounded runs validate against their imported corpus and canonical PostgreSQL records.

## Labeling workflow

1. Start from the template at `evals/queries.template.jsonl`.
2. Copy it to `evals/queries.jsonl`.
3. Replace each `relevant_memory_ids` array with the actual memory IDs that are relevant for that query.
4. Keep `fault_family` values stable and descriptive, for example `pump_failure`, `network_latency`, or `disk_pressure`.
5. Keep `notes` as free-text context; they are not used as labels.

Example schema:

```json
{"query_id":"q-001","query_text":"Pump P-102 is vibrating above threshold","fault_family":"pump_failure","relevant_memory_ids":["<uuid>","<uuid>"],"notes":"Human-authored relevance judgment for the maintenance team."}
```

## Validate labels

```bash
python -m evals.validate_queries --file evals/queries.jsonl
```

The validator rejects:

- duplicate `query_id` values
- blank or missing fields
- empty `relevant_memory_ids`
- UUID values that do not exist in PostgreSQL
- malformed JSON lines

## Export candidate memories for hand labeling

```bash
python -m evals.export_candidates.py --output evals/candidates.csv
```

This CSV contains only `memory_id`, `memory_type`, and `text` columns. It is a labeling aid only; it does not pre-fill relevance.

## Start the real stack

```bash
docker compose up -d --build
```

The harness is intended to run against the local Docker Compose stack with PostgreSQL, Qdrant, and Neo4j available.

## Run the human-labeled benchmark

```bash
python -m evals.run_benchmark --queries evals/queries.jsonl --k 10 --repeats 5 --warmup 1
```

This writes the output to `evals/results/<timestamp>/` with:

- `results.json`
- `summary.md`

The benchmark exits early in dry-run mode if the query file is still the template or still has empty labels, and tells you exactly what labeling remains to be done.

## Read the results

Open `summary.md` for the headline metrics and `results.json` for per-query rows, metadata, and fault-family breakdowns.

## Make target

```bash
make eval
```

The plain `make eval` target calls the benchmark with the labeled query file once it has been populated.
