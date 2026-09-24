# Repository commands

[Workshop home](../README.md) · [Notebook labs](../notebooks/README.md) · [Checks](../tests/README.md)

These scripts support setup, validation and examples. Each is run directly with `uv run python scripts/<name>.py`;
`--help` prints its options.

| Area | Scripts | Purpose |
|---|---|---|
| Setup | `check_env.py`, `namespace.py`, `resources.py` | Check prerequisites and identify namespace resources |
| Source checks | `check_docs.py`, `check_skills.py` | Validate documentation, links and skill contracts |
| Diagrams | (none) | The workshop visuals are rendered PNGs in `docs/diagrams/`, briefed in `docs/diagrams/prompts/`; there is no renderer in this repo |
| Tablet prompts | `screen_starter_prompts.py` | Screen every tablet starter prompt through a Model Armor template |
| Quickstarts | `quickstart_apps.py`, `eval_quickstarts.py` | Stage importable apps for `adk web` and run each quickstart's evaluation |
| Data | `probe_data_contract.py` | Exercise the shared data contract |
| Agent/UI checks | `smoke_local.py`, `check_tablet_experience.py`, `check_live_tablet.py`, `check_trace_fixture.py` | Inspect local or deployed behavior and traces |
| Evidence | `evidence.py`, `rehearse.sh` | Collect release/demo evidence and run the rehearsal sequence |
| Developer setup | `install_skills.sh` | Install optional repository skills |

Read each script's help and source before running cloud checks or rehearsal. Some commands require services,
model quota or fixture changes; they are not all offline checks. Generated evidence belongs under ignored `build/`.
