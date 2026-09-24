# Eval checks

[All test suites](../README.md)

The pytest wrapper runs ADK evaluation and turns threshold failures into a failing exit code. `uv run pytest tests/eval -q -k test_golden_gate_passes` requires your configured cloud dataset, credentials and model access.
