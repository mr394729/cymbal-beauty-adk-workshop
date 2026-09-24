# Repository QA

[Workshop home](../README.md) · [Implementation status](MAINTENANCE.md) · [Diagram audit](DIAGRAM_AUDIT.md)

This audit checks the notebook-led learning path and the source it references. It does not deploy services,
change the slide deck, or treat historical live logs as proof of the current checkout.

## Folder review

| Area | Purpose and review outcome |
|---|---|
| Root README and setup | Visual overview, eight notebook labs, direct source links and both local Google Cloud sign-ins |
| `agents/` | Application/package guides, current composition, scoped tools and model-selected queries |
| Agent prompts and configuration | Instructions separated from enforcement; MEDIUM thinking consistent across dev/preprod/prod |
| `data/` and schemas | Generator, fixtures, cloud loading and limits of operational coverage explained |
| `notebooks/` and assets | Seven executable labs; brief setup, current diagrams, governance template walkthrough |
| `quickstarts/` | Twelve source examples, each with a notebook, diagram, tests and service prerequisites |
| Quickstart support folders | Local order API, fixture generators and orchestration scripts identified |
| `eval/` | Standard ADK evaluation sets, factual metrics, breadth checks and grounding review explained |
| `journeys/` | Clearly named multi-turn conversation tests; custom YAML inputs/assertions, not application answers |
| `tests/` | Offline versus live suites explained; stale fixed test counts removed |
| `scripts/` | Commands grouped by purpose; source/syntax checked; cloud commands not claimed as executed |
| `deployment/` and IAM | Label-based engine discovery, release scripts, identities and approval setup |
| `cloudbuild/` | Actual pipeline steps distinguished from Make shortcuts; configuration versus live connection explicit |
| `.github/` | Source CI and authenticated evaluation job documented separately from deployment |
| `skills/`, AGENTS, CLAUDE, GEMINI | Current entry points; domain version, namespace and agent-composition drift corrected |
| `frontend/` | Persona, starter prompts, dynamic activities, trace modal and report behavior documented |
| `docs/` | Attendee references separated from facilitation, maintenance and evidence |
| Agent/pattern cards | Presenter references link use cases to implemented patterns; pending integrations remain explicit |
| Diagram library | Old raster set and prompts replaced by current editable SVGs; disposition recorded per file |
| Research | Role research distinguished from actual customer integrations |
| Evidence | Stale checked-in execution snapshots removed; new runs belong under `build/` with revision context |
| Local generated folders | Caches, `.venv`, build output, installed skills and local credentials excluded from the learning path |

## Verification

- Clean-checkout verification: **637 unit/catalog checks passed**, including every quickstart’s own offline suite.
- That check exposed three tests depending on ignored `data/out` files. They now generate deterministic
  temporary snapshots and pass without local generated data or cloud setup.
- All seven revised workshop notebooks executed successfully with external network access blocked.
- All twelve quickstart walkthroughs executed successfully with external network access blocked.
- Follow-up notebook, environment configuration and catalog checks: 101 passed.
- SVGs are rebuilt from maintained source and checked for XML validity, layout bounds and references.
- 200 Python files parsed and 14 shell scripts passed syntax checks.
- Documentation and skill checks passed with no errors or warnings; local Markdown/notebook links and headings resolved.
- All 23 rendered diagrams were visually inspected.

The older local quickstart live report contains eleven passes and one RAG setup error referencing a retired
configuration field. It is historical evidence only. No new cloud quickstart evaluation was performed by
this audit. Model Armor enforcement, PDF generation, notification inbox and hosted MCP are not claimed as
integrated; see [implementation status](MAINTENANCE.md).
