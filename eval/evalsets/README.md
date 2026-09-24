# ADK evaluation sets

These JSON files use the ADK evaluation schema. `gate.evalset.json` selects the release gate; `golden.evalset.json` covers the reference set; the stock and plan sets isolate factual invariants. `test_config.json` supplies scoring criteria and thresholds. Rebuild with `uv run python eval/build_eval_set.py`; see [the evaluation guide](../README.md).
