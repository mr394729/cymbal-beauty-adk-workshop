# Execution evidence

[Evaluation guide](../../eval/README.md) · [Repository QA](../REPOSITORY_QA.md)

Current runs write evidence under ignored `build/`: evaluation histories, conversation transcripts,
remote checks, notebook execution and UI review results. Associate each result with its source revision,
model configuration, dataset and environment.

Old snapshots have been removed from this folder because they did not establish the status of the current
checkout. A README status claim must come from a recorded run, not from the existence of a test or pipeline file.
