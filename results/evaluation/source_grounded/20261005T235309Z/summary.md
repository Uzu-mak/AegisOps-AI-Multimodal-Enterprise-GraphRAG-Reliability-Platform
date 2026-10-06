# AegisOps retrieval evaluation
> **These metrics come from a source-grounded / weakly-supervised benchmark. Relevance labels were derived from manufacturer troubleshooting records rather than independently authored human judgments.**

Corpus size: 6 memories | Query count: 60

Latency is measured per-query with a warm-up pass discarded, then median latency over repeated runs. Query embedding time is included for all methods, because the graph-only adapter chooses its anchor via the same semantic embedding path used in production.

| Method | Recall@5 | Recall@10 | MRR | p50 latency (ms) | p95 latency (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| vector | 0.8500 | 1.0000 | 0.4328 | 50.058 | 59.743 |
| graph | 0.8167 | 0.8167 | 0.3833 | 9.379 | 16.022 |
| hybrid | 0.8500 | 1.0000 | 0.4328 | 59.782 | 66.330 |

## Per fault-family breakdown
| Fault family | Query count |
| --- | ---: |
| vision_environmental_variation | 10 |
| vision_false_detection | 10 |
| vision_glare | 10 |
| vision_image_quality | 10 |
| vision_position_deviation | 10 |
| vision_target_variation | 10 |

## Limitations
- Label quality: source-grounded labels are weak supervision from manufacturer documentation, not independently authored human judgments.
- Sample size: the benchmark is limited to the number of labeled queries in the current file, which can be small.
- Source coverage: this seed corpus contains six records derived from one KEYENCE IV4 source page; the 60 queries are ten fixed-template variants per record, not 60 independent field incidents.
- Embeddings: the current stack is configured with DeterministicFakeEmbedding, a hash-based test embedding that is not semantic. Vector and hybrid relevance numbers validate retrieval plumbing, not production semantic quality.
- Single-machine latency: timings reflect the local Docker Compose host, not a distributed or production cluster.
