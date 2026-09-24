# Tablet store experience

[Workshop home](../README.md) · [How it is built](ARCHITECTURE.md) · [Notebook 03](../notebooks/03_tools_and_workflows.ipynb)

A tablet chat interface for the Cymbal Beauty store operations agents. The conversation is the main view;
Agent activity opens an optional panel with tool calls, results and session details. The frame can be expanded
for smaller screens. Static assets are served by FastAPI with no frontend build step.

```bash
uv run python frontend/server.py --target local --port 8080                      # local runner at http://localhost:8080
uv run python frontend/server.py --target agent-engine --env dev --port 8080        # local UI connected to the deployed dev engine
```

The role selector creates a conversation with the corresponding identity in session state. Scenarios follow
the selected persona. Each of eight scenarios has a pool of six standard and four complex starters; the UI
draws two standard and one complex prompt. Starter prompts are examples; the agent selects tools from the current request. Validation status stays in the scenario definitions;
displaying a starter is not evidence that its journey passed.

Supported conversations supply three to five model-generated suggested actions. Pure refusals and
cancellations clear the activities instead of filling the space with unrelated work. Task approvals resume the original invocation. If a confirmation response
is interrupted, check task status before submitting another action.

Inventory, product reviews and other structured queries can return a report card. **Open report** shows the delivered
records in a searchable, sortable table; **Download CSV** exports those records. The card states the
delivered and total matching counts. A report contains at most 5,000 rows and is marked partial when
more records match. The table travels in the `ui:report` state event; the model receives only report
metadata. Store and role checks apply to report delivery just as they do to ordinary queries.

In Agent activity, **View trace** opens the current request's ADK execution trace. Recorded parent/child
spans show agents, model calls and tools on a measured timeline; expanding a span shows the recorded,
bounded input/output and invocation details. The trace includes nested briefing work when the deployed
agent supplies those spans. Empty and in-progress states show only the data received. This view uses
ADK instrumentation supplied by the agent, not a Cloud Trace console link. New requests, confirmations
and persona changes clear the previous trace. Escape closes the dialog and restores keyboard focus.

## API

| Route | Body | Returns |
|---|---|---|
| `POST /api/sessions` | `{user_id, demo_identity?: manager|associate}` | `{session_id, state}` |
| `POST /api/chat` | `{user_id, session_id, text}` | SSE: `text`, `agent_note`, `tool_call`, `tool_result`, `transfer`, `state`, `trace`, `confirmation`, `error`, `done` |
| `POST /api/confirm` | `{user_id, session_id, invocation_id, fc_id, confirmed}` | SSE (same event types) |
| `GET /api/target` | – | `{kind: local|agent-engine, name}` |

The server holds the credentials (ADC locally; a service account when deployed). The browser only ever
talks to this server. No fallbacks: a missing engine id or a failed query surfaces as an `error` event.

## Deploying it

Deploy each participant’s frontend to their namespace:

```bash
uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json            # deploy the engine first
bash deployment/deploy_frontend.sh dev   # builds frontend/Dockerfile, pushes it, deploys it to Cloud Run
```

The deployment prints its Cloud Run URL and the command to retrieve its password. The network endpoint is
public; conversation and scenario endpoints require a password stored in Secret Manager, unique to the deployment. The existing
password is retained on redeployment. For real data, require Google sign-in and appropriate IAM access.

The frontend uses `store-ops-frontend@<project>` to call Agent Runtime and read its deployment password from
Secret Manager. The engine uses its own runtime identity to read BigQuery. Credentials stay on the server.

The container binds `0.0.0.0` on `$PORT` when a host sets one, and `127.0.0.1:8080` when you run it locally.

Specialist working answers remain in Activity; the conversation displays one final answer per request.
Task completion and blocker reporting are limited to the signed-in associate’s assigned work and require confirmation.
