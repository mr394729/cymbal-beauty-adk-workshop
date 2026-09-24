# Registering the store-ops agent in Gemini Enterprise

Gemini Enterprise is where business users meet agents. An ADK agent running on Agent Runtime (formerly Agent Engine) (formerly
Agent Engine) is registered into a Gemini Enterprise app as a *custom agent*; the app then routes the
user's turns to it under the user's own identity and shows the answers in the Gemini Enterprise UI.

## Prerequisites

1. A deployed engine for the environment: `uv run python deployment/release.py && uv run python deployment/deploy.py --env dev --release release.json` (the engine `cymbal-store-ops-<namespace>-dev`; the registration script finds it by its namespace labels).
2. A Gemini Enterprise app (a Discovery Engine *engine* with an assistant). Find its id in the console URL
   or list them:
   ```bash
   curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "x-goog-user-project: $GOOGLE_CLOUD_PROJECT" \
     "https://discoveryengine.googleapis.com/v1alpha/projects/$GOOGLE_CLOUD_PROJECT/locations/global/collections/default_collection/engines" \
     | python3 -c "import sys,json; [print(e['name'].split('/')[-1], '|', e.get('displayName')) for e in json.load(sys.stdin).get('engines',[])]"
   ```
3. The Discovery Engine service agent must be allowed to call the engine: grant
   `roles/aiplatform.user` on the project (or the reasoning engine) to
   `service-<PROJECT_NUMBER>@gcp-sa-discoveryengine.iam.gserviceaccount.com`.

## Register

```bash
uv run python deployment/register_gemini_enterprise.py register --env dev --app-id <engine id>
# = uv run python deployment/register_gemini_enterprise.py register --env dev --app-id <engine id>
```

Expected output: a JSON block with the new agent's resource name, `displayName`, `state` and the
`reasoningEngine` it points at. Then open the Gemini Enterprise app, pick **Cymbal Beauty Concierge** from
the agent list and ask "Is Lumière Hydra Cream in stock near Naperville?".

Other commands: `list --app-id …`, `update --app-id … --agent-id … [--env preprod] [--description …]`,
`delete --app-id … --agent-id …`.

> **Why this matters** — the same engine serves three surfaces without code changes: `adk web` (developers),
> the standalone frontend (a custom app), and Gemini Enterprise (employees). Promotion changes which engine
> the registration points at (`update --env preprod`), not the agent.

## What the registration contains

```json
{
  "displayName": "Cymbal Beauty Concierge",
  "description": "Product advice, store stock, salon bookings and Glow Rewards for Cymbal Beauty guests.",
  "adkAgentDefinition": {
    "toolSettings": {"toolDescription": "…what the router should know to pick this agent…"},
    "provisionedReasoningEngine": {"reasoningEngine": "projects/…/locations/us-central1/reasoningEngines/…"}
  }
}
```

`toolDescription` is what Gemini Enterprise's planner reads when deciding to route a turn to this agent —
write it like a tool docstring, not marketing copy. An optional `icon.uri` must be a public PNG.

## Identity and data access

Gemini Enterprise calls the engine as the service agent; the engine runs as its runtime service account
(`store-ops-<env>-runtime@…`), which is what BigQuery and Secret Manager see. User identity for
account-aware features arrives in session state, never from the chat text — the demo `identify_demo_user`
tool exists only for the workshop and should be removed for a real deployment.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `PERMISSION_DENIED` on register | caller lacks `roles/discoveryengine.admin` on the project | grant it, or run as the project owner |
| agent shows but every turn fails | Discovery Engine service agent cannot invoke the reasoning engine | grant `roles/aiplatform.user` to `service-<PROJECT_NUMBER>@gcp-sa-discoveryengine.iam.gserviceaccount.com` |
| 404 engine not found | wrong app id or location | Discovery Engine is always `global`; check the id from the console URL |

## Further reading

- https://docs.cloud.google.com/gemini-enterprise-agent-platform/ — the platform docs
- https://adk.dev/deploy/agent-runtime/ — deploying ADK agents to Agent Runtime
