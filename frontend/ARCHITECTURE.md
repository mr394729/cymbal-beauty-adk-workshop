# Tablet app: how it is built and how it talks to the agent

[Workshop home](../README.md) · [Tablet app README](README.md) · [Agent architecture](../docs/ARCHITECTURE.md) · [Notebook 03](../notebooks/03_tools_and_workflows.ipynb)

The tablet app is a small FastAPI service and one static page. It exists so a person can use the store agent
without a terminal, and so the room can see what the agent did on each turn: tool calls, specialist hand-offs,
confirmations and the execution trace. It is deliberately thin. Everything about the store lives in the agent;
the app holds credentials, signs people in, owns sessions and shapes events for display.

![The store agent and the tablet app](../docs/diagrams/store-agent-architecture.png)

## The pieces

| Piece | File | What it does |
|---|---|---|
| Server | `frontend/server.py` | FastAPI app: sign-in, sessions, chat and confirmation streams, history, reports, notifications. |
| Browser identity | `frontend/session_access.py` | A signed cookie per browser; the ADK user id is derived from it and the persona. |
| Page | `frontend/static/index.html`, `app.css` | One page, no build step. |
| Chat | `frontend/static/app.js` | Sends messages, reads the event stream, renders the conversation and the activity panel. |
| Workspace | `frontend/static/workspace.js` | Conversation list, history, report downloads, notifications, the pickup event trigger. |
| Reports and trace | `frontend/static/reports.js`, `trace.js` | The searchable report table and the span timeline. |
| Starter questions | `frontend/scenarios.yaml` | Per-persona prompt pools shown on a new conversation. |
| Engine streaming | `deployment/streaming.py` | `stream_query`: the `:streamQuery?alt=sse` call to Agent Runtime and its SSE/NDJSON parser. |
| Engine lookup | `deployment/_common.py` | `resolve_engine_name`: finds the engine by its `ns` and `env` labels. |
| Container and deploy | `frontend/Dockerfile`, `deployment/deploy_frontend.sh`, `cloudbuild/frontend.yaml` | Build, push, deploy to Cloud Run with a per-deployment password in Secret Manager. |

## Two targets, one agent

The server runs the same ADK `App` in one of two places. `--target` picks which; nothing else changes.

```bash
uv run python frontend/server.py --target local --port 8080                      # LocalTarget: InMemoryRunner over agents/cymbal_store_ops/agent.py, in this process
uv run python frontend/server.py --target agent-engine --env dev --port 8080       # AgentEngineTarget: the engine deployed for your namespace and environment
```

| | `LocalTarget` | `AgentEngineTarget` |
|---|---|---|
| Runs the agent | In process, `InMemoryRunner(app=adk_app)` | On Agent Runtime, the engine labelled `ns=<namespace> env=<env>` |
| Sessions | The runner's in-memory session service | The engine's session service (`async_create_session`, `async_get_session`, `async_list_sessions`) |
| One turn | `runner.run_async(...)` yields ADK `Event` objects | `stream_query(...)` yields the same events as JSON, over HTTPS |
| Reads store data | This process, with your ADC | The engine, with its own runtime identity; the app never touches BigQuery |
| Credentials | Your ADC | `store-ops-frontend@<project>` on Cloud Run, or your ADC when run locally with `frontend-remote` |

The engine is found by labels, not by a resource name in a file. `AgentEngineTarget.resolve()` loads
`config/envs/<env>.yaml`, asks Agent Runtime for the one engine carrying this namespace and environment, and keeps
its name. The lookup is lazy: deploying the app before the engine is a normal order to do a lab in, so the service
starts, reports the problem on `/api/config`, and picks the engine up on the next request once it exists. A
redeploy of the agent (a new revision on the same engine) needs no change here.

## A turn, end to end

1. **Sign in.** `GET /api/config` says whether a password is in force. `POST /api/login` checks it against
   `FRONTEND_PASSWORD` and sets two cookies: `cymbal_frontend` (proof of sign-in, derived from the password, so
   rotating the secret signs everyone out) and `cymbal_browser` (a random browser id, signed). Locally, with no
   password set, the app is open.
2. **Choose a role.** `POST /api/sessions` with `demo_identity: manager | associate`. The server seeds the session
   state the way an authenticated app would after device sign-in: `user:user_id`, `user:store_id`, `user:role`,
   `user:first_name` from `DEMO_IDENTITIES`, plus `_frontend_owner` and `_frontend_persona`. The ADK user id is
   `browser-<browser id>-<persona>`, so a manager conversation and an associate conversation in the same browser
   are different ADK users and never share state or memory. Nothing about identity is ever taken from the chat.
3. **Send a message.** `POST /api/chat` with the session id and text. The server checks the cookie, checks the
   session belongs to this browser and persona (`owned_session`), and opens a `StreamingResponse`.
4. **Run the agent.** Locally, `runner.run_async` runs the coordinator in this process. Remotely, `stream_query`
   POSTs `{"classMethod": "async_stream_query", "input": {user_id, session_id, message}}` to
   `https://<region>-aiplatform.googleapis.com/v1beta1/<engine>:streamQuery?alt=sse` with an ADC bearer token and
   reads the response line by line. It never retries a turn: a retried turn could run a tool twice.
5. **Shape the events.** Each ADK event becomes typed UI events (`shape()`): `tool_call`, `tool_result`, `transfer`,
   `confirmation`, `artifact`, `state`, `trace`, and `text` or `agent_note`. Model thought parts are dropped, never
   forwarded. The whole tool result travels, not a preview, which is what lets the page render tables and cards
   from what the tools already return without the agent knowing about the display.
6. **Stream to the page.** `sse()` writes `data: {...}` frames. Tool activity and confirmations go out immediately.
   Text is held briefly: a specialist's working note that is followed by another tool call is published as
   `agent_note`, and the one completed answer from the coordinator (or `associate_development`, the transfer
   target) is published as `text` at the end. One request, one answer in the conversation; everything else in
   Agent activity.
7. **Render.** `app.js` reads the stream with a `ReadableStream` reader, appends activity as it arrives, and
   renders the final answer as Markdown. `ui:next_actions` in a state delta becomes the suggested-action chips;
   `ui:report` opens the report card; `ui:trace:*` snapshots feed the trace view.

## Confirmations

Creating, assigning, completing or blocking a task calls a tool that ADK pauses with `adk_request_confirmation`
(a long-running function call). The server turns it into a `confirmation` event carrying `fc_id`,
`invocation_id`, the original tool name and arguments, and the hint. The page shows the proposed write; the
person answers; `POST /api/confirm` sends a `FunctionResponse` for that `fc_id` with `{"confirmed": true|false}`
back into the **same invocation** (`invocation_id`), so the paused tool resumes or is abandoned. A "no" writes
nothing. The agent side is in `agents/cymbal_store_ops/sub_agents/store_tasks.py` and
[pattern 7](../docs/patterns/07-human-in-the-loop.md).

## The execution trace

The trace in the app is not a Cloud Trace link. `agents/cymbal_store_ops/trace.py` is an ADK plugin that records
bounded agent, model and tool spans (start, duration, status, redacted input and output) and writes them into
session state under `ui:trace:<agent>` as ordinary state deltas. That is why nested work is visible: the opening
briefing runs inside an `AgentTool`, and its nested runner's deltas are carried back into the calling
conversation like any other state. The server's `shape_trace()` keeps only known fields and drops anything that
looks like a thought or a credential (`trace_payload`); `trace.js` draws the spans on a timeline. Cloud Trace and
the Agent Observability console still receive the full OpenTelemetry trace from the engine; the in-app view is
the bounded, person-safe subset.

## Reports and artifacts

Two kinds of report leave the agent, and the app treats them differently.

- **Query reports.** When `deliver_store_report` runs, the rows (at most 5,000, marked partial when more match)
  go into session state as `ui:report` and the model sees only the metadata. The `state` event carries the table
  to the page; `reports.js` renders it searchable and sortable and builds the CSV download in the browser. No
  artifact is involved.
- **End-of-day PDF.** `create_end_of_day_dashboard` renders a PDF and saves it as an ADK artifact with
  `store_id`, `business_date` and a metrics digest as custom metadata. The `artifact` event tells the page a file
  exists; `GET /api/sessions/{id}/artifacts` lists a session's PDFs and `GET .../artifacts/{filename}?version=N`
  streams one. Both are manager-only (`artifact_scope`), and the server checks the artifact's `store_id` against
  the session's store before serving it. Locally the runner's artifact service holds the files; deployed, they
  live in the `CYMBAL_ARTIFACT_BUCKET` bucket through `agents/cymbal_store_ops/artifact_storage.py`.

## History, conversations and notifications

`GET /api/sessions?persona=` lists this browser's conversations for the persona (filtered by `_frontend_owner`
and `_frontend_persona` in state). `GET /api/sessions/{id}` replays a session's stored events through the same
`shape()` and `sse()` path used live, so history looks exactly like the live stream; historical confirmation
requests become a note rather than a live control. Engine sessions arrive in camelCase and local ones in
snake_case, so events are normalised through ADK's `Event` model first.

`POST /api/events` and `GET /api/notifications` are the optional pickup-event workflow
([docs/EVENT_WORKFLOW.md](../docs/EVENT_WORKFLOW.md)): only present when `EVENTS_PROJECT`, `EVENTS_DATABASE`
and `EVENTS_TOPIC` are all set, and `/api/config` tells the page whether they are.

## Security model

- The browser never holds a Google credential and never calls Agent Runtime or BigQuery. It talks to this server
  only, and the server talks to the engine with its own identity.
- Deployed, the service runs as `store-ops-frontend@<project>` with `roles/aiplatform.user` (wider than "may call
  this engine": narrow it to the one engine before this leaves a sandbox, see `deployment/deploy_frontend.sh`) and
  `secretmanager.secretAccessor` on its own password secret. The store data is read by the engine's runtime
  identity, never by this service; [docs/IAM_MATRIX.md](../docs/IAM_MATRIX.md) has the full table.
- The URL is public; the password is the gate, one per deployment, created by the deploy script, kept in
  Secret Manager and never printed (`gcloud secrets versions access latest --secret=cymbal-frontend-$WORKSHOP_NAMESPACE-dev-password` reads it back). For real data, require a
  Google sign-in as well: the deploy script prints the two `gcloud run` commands.
- Sessions are owned: every session route checks the signed browser cookie, the persona and the `_frontend_owner`
  state key, and answers 404 rather than 403 for someone else's conversation.
- Cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` whenever `PORT` is set (a container host means TLS).
- Nothing falls back. A missing engine, a bad target or a failed query is an `error` event on the stream or a 503
  with the fix in the message, never a quiet degradation.

## Deploying it

```bash
uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json             # the engine first
bash deployment/deploy_frontend.sh dev    # deployment/deploy_frontend.sh dev
```

The script checks the engine exists and belongs to this namespace, builds `frontend/Dockerfile` with Cloud Build
(`cloudbuild/frontend.yaml`), pushes it to Artifact Registry, creates the service account and the password
secret when they are missing, and deploys `cymbal-frontend-<namespace>-<env>` to Cloud Run: one instance always
warm (`--min-instances 1 --no-cpu-throttling`), at most three, 512 MiB, environment `GOOGLE_CLOUD_PROJECT`,
`WORKSHOP_NAMESPACE`, `STORE_OPS_ENV`, `CYMBAL_ARTIFACT_BUCKET` and the password from Secret Manager. The
container binds `0.0.0.0:$PORT`; locally the server binds `127.0.0.1:8080`.

## Reading order

`frontend/server.py` top to bottom (backends, event shaping, routes), then `deployment/streaming.py` for the
engine call, then `frontend/static/app.js` for how the stream becomes a conversation. Notebook 03 sends a
question to the same agent from a cell, without the app, if you want to see the raw events first.
