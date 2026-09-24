# Authenticated operational MCP service

This package exposes six existing read capabilities over stateless Streamable HTTP at `/mcp`: schema discovery, structured operational queries, scoped catalog search and details, exact SKU balances, and whole-store inventory summaries. It preserves the existing database query implementation, counts, enum validation, row bounds, manager-only loss access and associate task ownership. Catalog details are limited to products present in the store's inventory records, including zero-stock products.

The model chooses the remote tools and query fields. Tool schemas contain no identity, role, store, namespace, SQL, report-delivery or write parameters. This initial service does not transport frontend state, reports, confirmations or writes.

## Authentication and configuration

Cloud Run IAM grants `roles/run.invoker` only to the intended agent service account. The server additionally verifies the original Google-signed ID token in `X-Cymbal-Caller-Token`; Cloud Run can remove the signature from its normal authorization header. Only configured service-account emails with verified email claims are accepted.

The ADK header provider derives identity/store/role from `ReadonlyContext.state`, signs a short-lived scope envelope, and binds it to that caller, service audience, namespace and environment. The server verifies all these bindings on every HTTP request. The signing secret is shared only by the trusted agent runtime and MCP runtime through pinned Secret Manager versions. It is never a browser password or model argument. Valid read requests can be replayed within their maximum three-minute expiry window; this is not an end-user login system.

| Variable | Agent | Server |
| --- | --- | --- |
| `CYMBAL_MCP_URL` | HTTPS origin plus `/mcp`; explicitly enables integration | — |
| `CYMBAL_MCP_AUDIENCE` | Cloud Run HTTPS origin | Same origin; configured as an accepted Cloud Run audience |
| `CYMBAL_MCP_SCOPE_KEY` | Secret Manager reference resolving to at least 32 random bytes | Same pinned secret version |
| `CYMBAL_MCP_CALLER_SERVICE_ACCOUNT` | Agent runtime service-account email | — |
| `CYMBAL_MCP_TRUSTED_CALLERS` | — | Comma-separated trusted service-account emails |
| `WORKSHOP_NAMESPACE`, `STORE_OPS_ENV` | Explicit current namespace/environment | Exact database deployment namespace/environment |
| `GOOGLE_CLOUD_PROJECT` | Existing runtime configuration | Explicit database project |

The production token provider uses Google workload identity credentials, refreshed before expiry. An operator running the separate probe uses explicit service-account impersonation and needs the applicable token-creator permission. Neither path creates a service-account key.

## Integrate with ADK

Import `make_operational_mcp_toolset` from `agents.cymbal_store_ops.mcp_connection`, call it in the existing agent factory, and append the result when non-null. The tool prefix is `store_mcp`, avoiding collisions with current native tools. The factory returns `None` only when MCP is unconfigured. Missing nonsecret connection configuration fails immediately; the signing secret is required on the first runtime request. Connection errors propagate. App serialization captures no secret, token client or lock. Close the toolset when the application's lifecycle ends.

The factory modules live inside `agents/`, so the existing engine package layout can carry them. The service package is required only in its Cloud Run container. Set the agent's MCP URL/audience/caller/namespace/environment and a pinned scope-key secret reference in its deployment configuration; the factory alone does not deploy or enable anything.

## Build and deploy

Prerequisites: an existing Artifact Registry repository, a dedicated MCP runtime service account, an agent caller service account, and a pinned Secret Manager secret containing a securely generated random signing key. Grant the MCP runtime `bigquery.jobUser` in the project and `bigquery.dataViewer` only on `cymbal_beauty_<namespace>_<env>`. Both runtime identities need access to their pinned signing secret. Do not grant dataset writes.

Run from the labs repo after integrating these new files:

```bash
python deployment/mcp_deploy.py --project PROJECT --namespace NAMESPACE \
  --image REGION-docker.pkg.dev/PROJECT/REPOSITORY/store-mcp:RELEASE \
  --audience https://SERVICE-PROJECT_NUMBER.REGION.run.app \
  --runtime-service-account MCP_RUNTIME@PROJECT.iam.gserviceaccount.com \
  --caller-service-account AGENT_RUNTIME@PROJECT.iam.gserviceaccount.com \
  --scope-secret MCP_SCOPE_SECRET:1 --build
```

Default is a printed plan with no cloud mutations. Add `--apply` after reviewing it. Only dev is accepted by this workstation script. The build uploads an isolated context containing `agents/` and `services/store_mcp/`, excluding environment files and generated artifacts. The Docker process runs as an unprivileged user. Deploy verifies no public IAM principals and grants invocation on this service to the named caller.

Use the intended canonical Cloud Run service URL as the audience and URL. The deployment explicitly registers that custom audience. The service name is `cymbal-store-mcp-<namespace>-dev`. Deployment does not create service accounts, secrets or broad database permissions.

## Probe, then register separately

With the client environment populated through trusted configuration, run:

```bash
python deployment/mcp_probe.py --project PROJECT --user USER_ID --store STORE_ID \
  --role store_manager --product PRODUCT_ID --out build/mcp-proof
python deployment/mcp_register.py --project PROJECT --namespace NAMESPACE \
  --url https://SERVICE-PROJECT_NUMBER.REGION.run.app/mcp \
  --toolspec build/mcp-proof/toolspec.json --out build/mcp-registry
```

The probe performs a real authenticated initialization, tools/list and optional exact-SKU read without a model call. It records discovery and warm-read latency, actual facts and the advertised schemas, without tokens or signed headers. Compare those facts with the existing direct tool before enabling a workshop scenario. Repeat under an associate identity and verify task self-scope. Cold-start latency requires a separately observed cold instance; the script does not pretend that its first call is necessarily cold.

The registry script defaults to a plan. `--apply` creates the manual Service entry and independently checks the projected MCP Server endpoint and every tool name. `--operation update` updates an existing entry deliberately. It fails if the expected listing is not visible after a bounded polling period. It rejects specifications larger than 10 KB.

Manual registration is deliberate: Cloud Run automatic MCP registration advertises the server, while the manual path uploads the actual authenticated tool specification. Registry discovery is not an authorization grant and is not the data-call path. These scripts have been checked against the installed CLI and current official documentation; live registration still requires execution and verification.

Official references: [MCP registration](https://docs.cloud.google.com/agent-registry/register-mcp-servers), [registry verification](https://docs.cloud.google.com/agent-registry/manage-mcp-tools), [Cloud Run Agent Platform features](https://docs.cloud.google.com/run/docs/ai/agent-platform-features), [ADK MCP tools](https://adk.dev/tools-custom/mcp-tools/).

## Tests and current proof boundary

The isolated suite uses the actual MCP SDK transport, actual ADK McpToolset and real relational queries over FakeBackend data. Only Google's external certificate/caller boundary is supplied locally for transport tests; separate tests exercise Google ID-token signature verification against a generated certificate.

Tests cover advertised capabilities, schema size, scope tampering, expiry, caller/audience/namespace/environment binding, manager-only resources, associate ownership, product membership, changed facts, failed sources, persona isolation and registry verification.

Run `python -m pytest tests/unit/test_store_mcp.py -q` after integration. No model call is needed. Verified on 2026-09-21: 20 local checks passed; Cloud Run revision `cymbal-store-mcp-demo-dev-00001-88w` is live; 11 live transport/scope checks passed, including exact stock and order-aggregate parity with BigQuery. Separate live ADK toolset calls preserved manager/store scope and associate/self scope. Agent Registry independently returned the exact endpoint and all six tool names. Evidence is in `build/mcp-proof/` and `build/mcp-registry/`. These operator probes impersonated the configured agent runtime; the main deployed agent still needs its optional toolset enabled and its own runtime-metadata authentication checked.
