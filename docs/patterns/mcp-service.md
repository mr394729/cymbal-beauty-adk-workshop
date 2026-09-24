# Reuse operational tools through MCP

[Pattern pages](README.md) · [Architecture](../ARCHITECTURE.md) · [Governance](../GOVERNANCE.md) · [Service README](../../services/store_mcp/README.md) · [Notebook 06](../../notebooks/06_governance.ipynb)

The deployed store agent reads store data only through one authenticated MCP server on Cloud Run. The server
offers the same 30 read tools the agent uses locally, with the same names, arguments and descriptions, and runs
the same store and role checks before each read. Each agent (the coordinator and every specialist) connects to it
through ADK's `McpToolset` with its own tool list, and the opening plan's three parallel readers call it from code.
Writes stay in the agent, because ADK's confirmation step runs there. The server is listed in the Agent Registry.
This page says what is deployed, how a call is authorised, and how the shape lines up with an enterprise MCP gateway.

## Pattern card

| Field | Content |
|---|---|
| User need | Let several agents use the same reliable catalog and operational reads while respecting each person's store access. |
| Pattern | One authenticated MCP server on Cloud Run, connected to ADK through `McpToolset`, registered in the Agent Registry. |
| What the agent does | Chooses its read tools exactly as before; deployed, every one of them is served by the MCP server. The model never supplies identity or role; a store id other than its own is refused unless the person is a district manager. |
| How | ADK selects a tool → the header provider signs the session's identity, store and role into a short-lived scope → the request carries a Google ID token for the service and the signed scope → the server verifies the caller, the audience, the scope and its expiry → the existing query code runs with that scope → bounded rows come back. |
| Tools | The 30 reads in `agents/cymbal_store_ops/mcp_catalog.py` (stock, inventory, catalog, pickup workload, roster, coverage, tasks, loss, guest feedback, coaching, learning, end-of-day metrics), plus schema discovery and two reads called from code: report rows and the full end-of-day metrics. Stays in the agent: task writes (confirmation), sign-in, memory, and Vertex AI Search for the procedures. |
| Benefit | One implementation of the reads, the counts, the enum checks, the row bounds and the manager-only rules, shared across agents. |
| Trade-off | A network boundary: token minting, one more hop per tool call, and a failure mode to handle. Measure it against the direct tools (`deployment/mcp_probe.py` records timings). |
| Live proof | `deployment/mcp_probe.py` against the sandbox service, eleven cases passed: discovery in 0.24 s; an exact stock read with the same facts remote (3.08 s) and direct (3.23 s); an orders aggregate with equal counts; the associate sees only their own tasks and is denied loss records; a foreign store filter is denied; an anonymous call gets 403, a call without the signed scope 401, a tampered store 403, a wrong namespace 403. The service appears in `gcloud agent-registry mcp-servers list`. These figures are from the six-tool version of 22 Sept; rerun the probe after deploying the 30-tool server. |

## Who may call, and on whose behalf

Two things are checked on every request, and they are deliberately different things.

1. **Which workload is calling.** Cloud Run IAM grants `roles/run.invoker` only to the agent's runtime identity.
   The server also verifies the Google-signed ID token itself (`X-Cymbal-Caller-Token`) and accepts only the
   configured trusted service accounts (`CYMBAL_MCP_TRUSTED_CALLERS`).
2. **Which person, store and role the call is for.** The ADK header provider reads `user:user_id`,
   `user:store_id` and `user:role` from the session state (never from the model or the tool arguments), signs
   them with a key both runtimes hold through pinned Secret Manager versions, and binds the scope to the caller,
   the service audience, the namespace and the environment with a three-minute expiry (`mcp_auth.py`:
   `sign_scope`, `verify_scope`). The server rejects tampering, replay outside the window and any mismatch.

Discovery follows the same rule: `ScopedMcpToolset.get_tools` returns nothing until the session is signed in, so
a conversation without an identity never sees the remote tools.

## The enterprise shape

Enterprises that already front APIs with a gateway tend to put MCP behind the same gateway: an API management
layer (Apigee, for example) terminates the client's token, applies rate limits, threat protection and Model
Armor inline, and forwards to the MCP servers; a corporate identity provider (Entra ID, for example) issues the
person's token and the agent exchanges it on-behalf-of the person for the downstream call. This workshop's
service is the same shape with Google Cloud's own pieces, one level down:

| Concern | Enterprise gateway shape | Here |
|---|---|---|
| The client's identity | Gateway validates the caller's token | Cloud Run IAM plus in-service ID-token verification of a trusted service account |
| The person's identity | On-behalf-of token from the identity provider, carried to the tool | Session identity signed into a scope bound to the caller and audience; the person's role and store travel, not their credentials |
| Policy between agent and tool | Gateway policies per API product | Agent Gateway (agent-to-anywhere) with registered destinations and deny-by-default access policies, when `agent_engine.gateway` is set |
| Content screening | Model Armor inline at the gateway | Model Armor in the agent's `before_model_callback`; also available as the Agent Gateway's AI-security policy |
| Discovery | Gateway catalogue | Agent Registry entry with the server's tool specifications |
| Telemetry | Gateway logs and traces | Cloud Run request logs, ADK spans for each MCP tool call, gateway telemetry to Agent Observability when routed |

Moving from here to the gateway shape changes configuration, not the agent: swap the header provider for the
gateway's token exchange, keep the tools and the scope checks. Agent Identity replaces the runtime service
account as the caller when the engine is created with `agent_engine.identity: agent`
([Agent Identity](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-identity)).

## Deploy, probe, register

```bash
uv run python deployment/mcp_deploy.py --project $GOOGLE_CLOUD_PROJECT --namespace $WORKSHOP_NAMESPACE \
  --image us-central1-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/cymbal-store-ops/store-mcp:dev \
  --audience https://cymbal-store-mcp-$WORKSHOP_NAMESPACE-dev-<hash>-uc.a.run.app \
  --runtime-service-account store-mcp-$WORKSHOP_NAMESPACE-dev@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com \
  --caller-service-account store-ops-dev-runtime@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com \
  --scope-secret cymbal-mcp-scope-$WORKSHOP_NAMESPACE:1 --build --apply
uv run python deployment/mcp_probe.py --project $GOOGLE_CLOUD_PROJECT --user U-M014 --store S-014 \
  --role store_manager --product P-0101 --out build/mcp-proof
uv run python deployment/mcp_register.py --project $GOOGLE_CLOUD_PROJECT --namespace $WORKSHOP_NAMESPACE \
  --url https://cymbal-store-mcp-$WORKSHOP_NAMESPACE-dev-<hash>-uc.a.run.app/mcp \
  --toolspec build/mcp-proof/toolspec.json --out build/mcp-registry
```

`mcp_deploy.py` prints its plan and mutates nothing without `--apply`; it refuses a public service. The probe
discovers the tools, runs a scoped read, compares its facts with the direct implementation and records the
timings; the registration uses the discovered tool specifications and then reads the entry back to verify it.
Switching the agent to the service is four variables on its deployment: `CYMBAL_MCP_URL`, `CYMBAL_MCP_AUDIENCE`,
`CYMBAL_MCP_CALLER_SERVICE_ACCOUNT` and the pinned `CYMBAL_MCP_SCOPE_SECRET` (`deployment/deploy.py` passes them
through). Unset, the agent runs its native tools; half-set, it refuses to start. The service README has the full
variable table.

## Sources

[Agent Registry: register MCP servers](https://docs.cloud.google.com/agent-registry/register-mcp-servers) ·
[Cloud Run Agent Platform features](https://docs.cloud.google.com/run/docs/ai/agent-platform-features) ·
[Agent Gateway overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-overview) ·
[ADK MCP tools](https://adk.dev/tools/mcp-tools/)
