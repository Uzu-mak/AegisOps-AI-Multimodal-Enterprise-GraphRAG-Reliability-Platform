.PHONY: eval

eval:
	python -m evals.run_benchmark --queries evals/queries.jsonl --k 10 --repeats 5 --warmup 1
