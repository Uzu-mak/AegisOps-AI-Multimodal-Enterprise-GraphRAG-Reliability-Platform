# Context header in search text: measured, not adopted

**Date:** 30 Oct 2026
**Question set:** MaintNet engines v1. It has 13 questions: 10 labelled and 3 with no answer. The assistant proposed the labels, the owner was Jeremiah Afari Opoku-Acheampong, and Bismark Mensah approved the set.
**Data:** 6,183 MaintNet aviation work orders (Kaggle MaintNet logbook data).
**Embedding:** OpenAI, 1536 dimensions. The top k was 10, and the investigation answer reads 5 records.
**Runs:** `082c33e7` used the plain text index, and `56a98220` used the context header index. Each index was rebuilt over all records with no failures, and no mixing was detected.

## What was compared

| | Plain | Context header |
|---|---|---|
| Text that is embedded | title + content | "Maintenance action on asset/component/incident …." + title + content |

## Results (mean over the 10 labelled questions)

| Mode | Recall at 5 | Recall at 10 | MRR at 10 |
|---|---|---|---|
| Meaning | 0.50 → 0.42 | 0.67 → 0.60 | 0.55 → 0.63 |
| Both | 0.50 → 0.42 | 0.72 → 0.65 | 0.55 → 0.63 |
| Relationships | 0.14 → 0.19 | 0.14 → 0.19 | 0.25 → 0.25 |
| Investigation | 0.47 → 0.42 | — | 0.53 → 0.60 |

Retrieval is deterministic. Two separate plain-text runs scored identically, so the differences above come from the search-text change, not from noise between runs.

Most of the change comes from three questions:

- **Vibration:** recall at 10 fell from 1.0 to 0.
- **Overspeed:** the first relevant record moved to rank 1.
- **Sticking valve:** the first relevant record also moved to rank 1, but fewer relevant records reached the top 5.

## Decision

The **plain** format stays the default (`DEFAULT_TEXT_FORMAT` in `app/services/semantic_service.py`).

MaintNet records have no asset or component, so the header was mostly the same boilerplate on every record, plus an incident ID that carries no meaning. That made the records look more alike to the search, and recall dropped.

A leaner header is worth retesting on data that has real asset context. It should contain only asset and component names, with no record type and no incident IDs.

## Limits

These results come from 10 labelled questions. They settle the default for this data. They don't support a general claim about context headers.

The answer-level figures are not a measurement. They come from only 3 no-answer questions and varied between identical runs. In both runs the assistant answered all three no-answer questions instead of saying so. That weakness is separate and needs its own fix.
