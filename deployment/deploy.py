"""Deploy the store-ops agent to Agent Runtime (Vertex AI Agent Engine) for one environment.

    uv run python deployment/release.py
    uv run python deployment/deploy.py --env dev --release release.json [--dry-run]

The config is the documented `client.agent_engines.create(...)` shape
(https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent):
`extra_packages=["agents"]` ships the package directory, `requirements` is the exported lock, `env_vars`
carries the environment name, the namespace and Secret Manager references, and each environment runs under its own
service account. The engine is labelled app=cymbal-store-ops, ns=<WORKSHOP_NAMESPACE>, env=<env>. A deploy updates
the engine named by AGENT_ENGINE_ID or config/envs/<env>.yaml when either is set, else the one engine carrying those
labels (a fresh pipeline checkout finds it the same way a laptop does), else it creates one. Every update creates a
new revision. deployment/deployment_info.<namespace>.<env>.json is a local record of the last deploy, never the
source of truth. Prod refuses a dirty or mismatched checkout.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deployment._common import (  # noqa: E402
    ENVS,
    REPO_ROOT,
    DeployError,
    agent_engine_settings,
    always_latest_traffic_config,
    client_for,
    engine_labels,
    engine_namespace_guard,
    existing_engine_name,
    label_value,
    list_revisions,
    load_config,
    now_iso,
    print_json,
    read_deployment_info,
    read_release,
    service_account_email,
    short_revision,
    staging_bucket,
    staging_dir,
    traffic_view,
    verify_release,
    write_deployment_info,
)


def env_vars_for(cfg) -> dict:
    """Everything else lives in config/envs/<env>.yaml, which ships inside the package."""
    env_vars = {"GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "STORE_OPS_ENV": cfg.env, "WORKSHOP_NAMESPACE": cfg.namespace,
                # Traces, logs and the prompts and responses themselves: online monitors and trace evaluation score
                # the logged conversation, so message content is captured on the model-call spans and as events
                # (the workshop data is synthetic). The monitor reads the system instructions from the call_llm
                # span: with EVENT_ONLY it rejects every trace as "system_instruction not present". Full payloads go to the agent's own bucket instead of being embedded in the spans.
                # https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-online
                "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
                "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
                "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "SPAN_AND_EVENT",
                "OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT": "jsonl",
                "OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK": "upload",
                "OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH":
                    f"gs://{cfg.project}-cymbal-artifacts-{cfg.namespace}-{cfg.env}/genai-payloads",
                # Warm the BigQuery backend while the container starts, not inside the first request.
                "STORE_OPS_PREWARM": "1",
                "CYMBAL_ARTIFACT_BUCKET": f"{cfg.project}-cymbal-artifacts-{cfg.namespace}-{cfg.env}",
                "PLAYWRIGHT_BROWSERS_PATH": "/opt/cymbal-browsers"}
    if os.environ.get("SOP_DATA_STORE", "").strip():
        # policy_lookup is registered when this is set; the engine gets the same value (runtime SA needs
        # roles/discoveryengine.viewer, granted by setup_wif.sh).
        env_vars["SOP_DATA_STORE"] = os.environ["SOP_DATA_STORE"].strip()
    for name in ("MEMORY_BANK_ENGINE", "CYMBAL_MCP_URL", "CYMBAL_MCP_AUDIENCE", "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT",
                 "MODEL_ARMOR_TEMPLATE"):   # screening on the engine needs roles/modelarmor.user on the runtime SA
        if os.environ.get(name, "").strip():
            env_vars[name] = os.environ[name].strip()
    if os.environ.get("CYMBAL_MCP_URL"):
        secret = os.environ.get("CYMBAL_MCP_SCOPE_SECRET", "")
        secret_id, separator, version = secret.rpartition(":")
        if not separator or not secret_id or not version.isdigit():
            raise DeployError("Set CYMBAL_MCP_SCOPE_SECRET=<secret-id>:<version-number> for MCP deployment.")
        env_vars["CYMBAL_MCP_SCOPE_KEY"] = {"secret": secret_id, "version": version}
    for name, ref in (cfg.secret_env_vars or {}).items():
        if not isinstance(ref, dict) or not ref.get("secret") or str(ref.get("version", "")) in ("", "latest"):
            raise DeployError(f"secret_env_vars.{name} must be {{secret: <id>, version: <n>}} in config/envs/{cfg.env}.yaml")
        env_vars[name] = {"secret": ref["secret"], "version": str(ref["version"])}
    return env_vars


def build_config(cfg, release: dict) -> dict:
    ae = agent_engine_settings(cfg)
    config = {
        "display_name": ae["display_name"],
        "description": f"Cymbal Beauty store operations ({cfg.env}) — ADK {release['adk_version']}",
        "requirements": release["requirements"],
        "extra_packages": ["agents", "installation_scripts/install_report_browser.sh"],
        "build_options": {"installation_scripts": ["installation_scripts/install_report_browser.sh"]},
        "staging_bucket": staging_bucket(cfg),
        "gcs_dir_name": staging_dir(cfg),
        "env_vars": env_vars_for(cfg),
        "service_account": service_account_email(cfg),
        "labels": {**engine_labels(cfg), "git-sha": label_value(release["git_sha"][:12]),
                   "data-version": label_value(release["data_version"])},
        "min_instances": int(ae.get("min_instances", 0)),
    }
    if ae["identity"] == "agent":
        # Agent Identity: the engine gets its own SPIFFE identity; the service_account field must not be set
        del config["service_account"]
        config["identity_type"] = "AGENT_IDENTITY"
    if ae["gateway"]:
        config["agent_gateway_config"] = {"agent_to_anywhere_config": {"agent_gateway": ae["gateway"]}}
    if ae["traffic"] == "latest":
        config["traffic_config"] = always_latest_traffic_config()
    return config


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", required=True, choices=ENVS)
    ap.add_argument("--release", type=Path, required=True, help="release.json from deployment/release.py")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    os.chdir(REPO_ROOT)  # extra_packages paths are relative to the working directory
    cfg = load_config(a.env)
    release = read_release(a.release)
    verify_release(release, strict=a.env != "dev")
    config = build_config(cfg, release)
    if not os.environ.get("CYMBAL_MCP_URL", "").strip():
        # The deployed agent reads store data only through the MCP server; without it there is nothing to deploy.
        raise DeployError("CYMBAL_MCP_URL is not set, so this agent would have no store data. Deploy the MCP service "
                          "(uv run python deployment/mcp_deploy.py --help) and set CYMBAL_MCP_URL, CYMBAL_MCP_AUDIENCE, "
                          "CYMBAL_MCP_CALLER_SERVICE_ACCOUNT and CYMBAL_MCP_SCOPE_SECRET; docs/patterns/mcp-service.md.")
    wired = {name: bool(config["env_vars"].get(name)) for name in
             ("CYMBAL_MCP_URL", "MEMORY_BANK_ENGINE", "MODEL_ARMOR_TEMPLATE", "SOP_DATA_STORE")}
    print("integrations: " + ", ".join(f"{name}={'on' if on else 'OFF'}" for name, on in wired.items()))
    if a.env != "dev" and not os.environ.get("DEPLOY_FROM_PIPELINE"):
        raise DeployError(f"{a.env} deploys run from the pipeline (it sets DEPLOY_FROM_PIPELINE=1), not from a laptop")
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()   # the engine lookup below needs it, for a dry run too; an expired sign-in stops here in words
    client = client_for(cfg)
    existing = existing_engine_name(client, cfg)
    print(f"env={cfg.env} project={cfg.project} location={cfg.agent_engine['location']} "
          f"{'update ' + existing if existing else 'create (first deploy)'}")
    if a.dry_run:
        print_json({"config": config, "release": {k: release[k] for k in ("git_sha", "requirements_sha256", "prompt_version")}})
        return 0
    from vertexai.agent_engines import AdkApp

    from agents.cymbal_store_ops.agent import create_app
    from agents.cymbal_store_ops.artifact_storage import create_artifact_service

    # enable_tracing=True keeps the prompt on ADK's call_llm spans: without it the Agent Runtime template sets
    # ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false, and online monitors reject every trace ("system_instruction not
    # present in any call_llm span"). Telemetry itself comes from GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY (env_vars_for).
    adk_app = AdkApp(app=create_app(), artifact_service_builder=create_artifact_service, enable_tracing=True)
    if existing:
        try:
            current_engine = client.agent_engines.get(name=existing)
        except Exception as e:  # noqa: BLE001
            raise DeployError(f"{existing} (from AGENT_ENGINE_ID or agent_engine.agent_engine_id) does not exist in this "
                              f"project: unset it to deploy or update the engine labelled ns={cfg.namespace} ({e})") from e
        engine_namespace_guard(current_engine, cfg)
    before = {r["name"] for r in list_revisions(client, existing)} if existing else set()
    if existing:
        engine = client.agent_engines.update(name=existing, agent=adk_app, config=config)
    elif config.get("identity_type") == "AGENT_IDENTITY":
        # The identity exists only once the engine does, and it must be able to read the staging bucket before the
        # package is deployed: create the engine empty, bind the roles to its identity, then deploy the code.
        from deployment.agent_identity import bind

        shell = {k: v for k, v in config.items() if k not in ("requirements", "extra_packages", "staging_bucket", "gcs_dir_name", "build_options")}
        engine = client.agent_engines.create(config=shell)
        bind(cfg, engine.api_resource.name, apply=True)
        engine = client.agent_engines.update(name=engine.api_resource.name, agent=adk_app, config=config)
    else:
        engine = client.agent_engines.create(agent=adk_app, config=config)
    name = engine.api_resource.name
    revisions = list_revisions(client, name)
    new = [r["name"] for r in revisions if r["name"] not in before]
    current = new[-1] if new else (revisions[-1]["name"] if revisions else "")
    info = {
        "env": cfg.env, "resource_name": name, "revision": current,
        "previous_revision": (read_deployment_info(cfg.env) or {}).get("revision") if existing else None,
        "git_sha": release["git_sha"], "prompt_version": release["prompt_version"],
        "traffic": traffic_view(engine), "deployed_at": now_iso(),
    }
    write_deployment_info(cfg.env, info)
    print_json(info)
    if not existing:
        print(f"\nFirst deploy for {cfg.env}: engine labelled ns={cfg.namespace} env={cfg.env}; later deploys and the "
              f"pipeline find it by those labels. Recorded in deployment/deployment_info.{cfg.namespace}.{cfg.env}.json.")
    if cfg.agent_engine.get("traffic") == "manual":
        print(f"\nManual traffic split: revision {short_revision(current)} receives 0 % until "
              f"`deployment/traffic.py promote --env {cfg.env} --percent N` shifts traffic to it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
