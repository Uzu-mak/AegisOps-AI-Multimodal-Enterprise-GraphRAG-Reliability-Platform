from uuid import uuid4

from pathlib import Path

from evals.source_grounded_pipeline import (
    DATA_DIR,
    QUERY_PATH,
    SOURCE_RECORDS,
    build_dataset,
    validate_dataset,
)
from evals.validate_queries import validate_query_file


def test_validate_query_file_accepts_valid_jsonl(tmp_path):
    valid_id = str(uuid4())
    query_path = tmp_path / "queries.jsonl"
    query_path.write_text(
        (
            '{"query_id":"q-1","query_text":"pump noisy","fault_family":"pump_failure","relevant_memory_ids":["'
            + valid_id
            + '"],"notes":"keep"}\n'
        ),
        encoding="utf-8",
    )

    rows = validate_query_file(query_path, known_memory_ids={valid_id})
    assert rows[0]["query_id"] == "q-1"
    assert rows[0]["relevant_memory_ids"] == [valid_id]


def test_validate_query_file_rejects_duplicate_and_missing_ids(tmp_path):
    memory_a = str(uuid4())
    memory_b = str(uuid4())
    query_path = tmp_path / "queries.jsonl"
    query_path.write_text(
        (
            '{"query_id":"q-1","query_text":"pump noisy","fault_family":"pump_failure","relevant_memory_ids":["'
            + memory_a
            + '"],"notes":"first"}\n'
            '{"query_id":"q-1","query_text":"duplicate","fault_family":"pump_failure","relevant_memory_ids":["'
            + memory_b
            + '"],"notes":"second"}\n'
        ),
        encoding="utf-8",
    )

    try:
        validate_query_file(query_path, known_memory_ids={memory_a, memory_b})
        assert False, "duplicate query ids should have failed validation"
    except ValueError:
        pass

    missing_path = tmp_path / "missing.jsonl"
    missing_path.write_text(
        '{"query_id":"q-2","query_text":"disk alert","fault_family":"disk_pressure","relevant_memory_ids":["' + str(uuid4()) + '"],"notes":"missing"}\n',
        encoding="utf-8",
    )

    try:
        validate_query_file(missing_path, known_memory_ids={memory_a})
        assert False, "missing memory ids should fail validation"
    except ValueError:
        pass


def test_source_grounded_dataset_has_separate_query_path():
    assert QUERY_PATH == DATA_DIR / "source_grounded_queries.json"
    assert QUERY_PATH != Path("evals/queries.jsonl")


def test_source_grounded_dataset_generates_60_corpus_backed_queries():
    record_ids = {record["record_key"]: str(uuid4()) for record in SOURCE_RECORDS}
    memories, queries = build_dataset(record_ids)

    assert len(memories) == 6
    assert len(queries) == 60
    validate_dataset(queries, memories)
    assert all(query["label_method"] == "source_grounded" for query in queries)


def test_source_grounded_dataset_rejects_memory_ids_outside_corpus():
    record_ids = {record["record_key"]: str(uuid4()) for record in SOURCE_RECORDS}
    memories, queries = build_dataset(record_ids)
    queries[0]["relevant_memory_ids"] = [str(uuid4())]

    try:
        validate_dataset(queries, memories)
        assert False, "dataset validation should reject memory IDs outside the corpus"
    except ValueError as exc:
        assert "outside the corpus" in str(exc)
