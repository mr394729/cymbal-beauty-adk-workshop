# Facilitator runbook

The notebooks are the workshop labs. Present the slides for context, use the notebooks to inspect and run
examples, and use the tablet app to demonstrate the store experience. Attendees can follow along or run
the same notebooks later. The slide deck is maintained separately.

## Prepare the session

1. Share the [repository](https://github.com/mr394729/cymbal-beauty-adk-workshop),
   [notebook index](../notebooks/README.md) and [pre-work message](PREWORK_EMAIL.md).
2. Select and record the reviewed commit on `main`. Run each of the eight notebooks top to bottom in your own
   namespace, from the `notebooks/` folder, and read every output. For an unattended run:

   ```bash
   cd notebooks
   for nb in 0*.ipynb; do uv run jupyter nbconvert --to notebook --execute "$nb" --output "/tmp/$nb"; done
   ```

3. For live cells, check authentication, the project and namespace, and the current deployment. Follow
   [SETUP.md](../SETUP.md) and [shared-project guidance](SHARED_PROJECT.md). Run `uv run python scripts/check_env.py --stage prereqs` and
   `uv run python scripts/check_env.py --stage ready` in the selected environment. Do not reset a shared dataset during the session.
4. Run a real opening question in the tablet app. Check its answer, follow-up suggestions, tool activity
   and trace. Record observed latency. Then ask an unscripted inventory or product question and confirm
   the agent responds to that request.
5. Review the evaluation results for the release being demonstrated. Keep completed test evidence separate
   from results that are still running or belong to an earlier version.
6. If demonstrating promotion, verify the Cloud Build repository connection, identities and approval
   triggers in advance. Use the [promotion reference](PROMOTION_STRATEGY.md); only show a live pipeline
   when the connection and target environments have been verified.
7. Open the notebooks, tablet app, source editor and relevant cloud console pages before attendees arrive.
   Share the tablet URL and deployment password through the workshop channel. The notebooks need no guide-app login.

## Three-hour walkthrough

| Time | Lab | Walkthrough |
|---|---|---|
| 0:00–0:10 | [00 · Workspace](../notebooks/00_workspace_and_platform.ipynb) | Introductions, outcomes and the three assets: notebooks, source and tablet app. |
| 0:10–0:45 | [00 · Platform](../notebooks/00_workspace_and_platform.ipynb) | Build, scale, govern and optimize. Connect each discussion to the agent and its cloud deployment. |
| 0:45–1:00 | [01 · Store data](../notebooks/01_store_data.ipynb) | Introduce the store roles and decisions. Explore the data, stock distribution, pickup demand and evidence limits. |
| 1:00–1:30 | [02 · Agent patterns](../notebooks/02_agent_patterns.ipynb) | Inspect the actual agent tree. Explain specialist consultation, hand-offs, workflow composition and session state. Open the linked source examples. |
| 1:30–2:00 | [03 · Tools and workflows](../notebooks/03_tools_and_workflows.ipynb) | Call tools with changed inputs, inspect the results and connect them to a tablet conversation. Show the daily briefing's parallel reads and writer in the trace. |
| 2:00–2:15 | [04 · Evaluate and observe](../notebooks/04_evaluate_and_observe.ipynb) | Separate factual checks from answer-quality assessment. Inspect recorded traces and compare model time with tool time. |
| 2:15–2:30 | [05 · Deploy and promote](../notebooks/05_deploy_and_promote.ipynb) | Inspect the release manifest, dev deployment and promotion controls. Use prepared evaluation evidence for longer runs. |
| 2:30–2:50 | [06 · Governance](../notebooks/06_governance.ipynb) | Demonstrate store scope, role boundaries and reviewed writes. Discuss the next operational use case and its evaluation criteria. |
| 2:50–3:00 | [07 · Cost and tokens](../notebooks/07_cost_and_tokens.ipynb) | Read three real turns, price a turn, project a month, read the BigQuery ledger by tool. Close on what leaves the room with them. |

## Demonstrate the agent

Use one manager session for the opening briefing and its follow-up questions. Then change persona to show
an associate's own work. Let attendees suggest questions beyond the starter chips.

For each pattern, show the operational question, the selected agents or tools, the returned evidence and the
result. Use the trace for execution details. Keep confirmation visible before any task write. The
[pattern cards](patterns/cards.md) and [architecture reference](ARCHITECTURE.md) support the explanation.

Optional RAG, memory, document artifacts, events and hosted MCP integrations have different implementation
states. Check the [pattern inventory](patterns/README.md) against the deployed release before presenting
any of them as an integrated capability.

## If a live step cannot run

Keep the error visible, explain what failed, and continue with the notebook's saved output or recorded
execution evidence. Identify a saved example as such. Follow [troubleshooting](TROUBLESHOOTING.md) after
that segment rather than starting an unplanned deployment or dataset reset in the room.

## After the session

Share the reviewed commit, notebook links and any follow-up actions. Attendees can rerun cells or change
inputs in their own namespace. Use the repository's resource listing and documented teardown commands
only for resources whose owners have requested cleanup.
