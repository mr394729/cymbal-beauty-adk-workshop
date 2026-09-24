"""Model Armor for the store agent: a prompt/response screening template, and the calls that use it.

Model Armor screens text before it reaches a model and before a model's answer reaches a person. It is separate
from the application controls in callbacks.py (role and store scope) and plugins.py (contact-detail redaction),
and it does not replace them: a screening result cannot authorize a database read.

    uv run python -m agents.cymbal_store_ops.governance.model_armor --project P --location us-central1 --template store-ops-guard

The template is namespaced by name, so every participant creates their own. Screening is switched on per
deployment: with MODEL_ARMOR_TEMPLATE set (projects/P/locations/L/templates/ID) the coordinator screens every
prompt in a before_model_callback (make_screen_before_model) and answers a match with REFUSAL instead of calling
the model. Unset, the agent runs without screening. Notebook 06 creates a template, screens sample prompts and
switches it on for your copy of the agent.

Docs: https://docs.cloud.google.com/model-armor/overview
"""
from __future__ import annotations

import argparse
import json

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import modelarmor_v1 as ma

FILTER_RESULT_FIELDS = ("rai_filter_result", "sdp_filter_result", "pi_and_jailbreak_filter_result", "malicious_uri_filter_result")


def client(location: str) -> ma.ModelArmorClient:
    """Model Armor is regional: the endpoint carries the location."""
    return ma.ModelArmorClient(client_options=ClientOptions(api_endpoint=f"modelarmor.{location}.rep.googleapis.com"))


def store_agent_filters() -> ma.FilterConfig:
    """The filters a store assistant needs: injection and jailbreak attempts, card numbers and credentials,
    harmful content, and links that may be unsafe.

    Thresholds are a starting point to tune on your own prompts. Harmful-content filters run at HIGH: at
    MEDIUM_AND_ABOVE an ordinary coverage sentence ("Her mobile is …") was flagged as explicit in the sandbox.
    The basic sensitive-data filter covers card numbers, account numbers and credentials; phone numbers and
    emails need an advanced (DLP template) configuration, and in this agent they are already masked by
    mask_pii_before_model before the model sees them."""
    return ma.FilterConfig(
        pi_and_jailbreak_filter_settings=ma.PiAndJailbreakFilterSettings(
            filter_enforcement=ma.PiAndJailbreakFilterSettings.PiAndJailbreakFilterEnforcement.ENABLED,
            confidence_level=ma.DetectionConfidenceLevel.MEDIUM_AND_ABOVE),
        sdp_settings=ma.SdpFilterSettings(basic_config=ma.SdpBasicConfig(
            filter_enforcement=ma.SdpBasicConfig.SdpBasicConfigEnforcement.ENABLED)),
        rai_settings=ma.RaiFilterSettings(rai_filters=[
            ma.RaiFilterSettings.RaiFilter(filter_type=kind, confidence_level=ma.DetectionConfidenceLevel.HIGH)
            for kind in (ma.RaiFilterType.HATE_SPEECH, ma.RaiFilterType.HARASSMENT, ma.RaiFilterType.DANGEROUS,
                         ma.RaiFilterType.SEXUALLY_EXPLICIT)]),
        malicious_uri_filter_settings=ma.MaliciousUriFilterSettings(
            filter_enforcement=ma.MaliciousUriFilterSettings.MaliciousUriFilterEnforcement.ENABLED),
    )


def template_name(project: str, location: str, template_id: str) -> str:
    return f"projects/{project}/locations/{location}/templates/{template_id}"


def ensure_template(project: str, location: str, template_id: str, labels: dict | None = None) -> ma.Template:
    """Create the template if it is missing; return the existing one otherwise. Never overwrites a template."""
    api = client(location)
    parent = f"projects/{project}/locations/{location}"
    try:
        return api.get_template(name=template_name(project, location, template_id))
    except NotFound:
        pass
    try:
        return api.create_template(parent=parent, template_id=template_id,
                                   template=ma.Template(filter_config=store_agent_filters(), labels=labels or {}))
    except AlreadyExists:
        return api.get_template(name=template_name(project, location, template_id))


def delete_template(project: str, location: str, template_id: str) -> None:
    client(location).delete_template(name=template_name(project, location, template_id))


def findings(result: ma.SanitizationResult) -> dict:
    """The per-filter verdicts as plain values: which filters matched, and what the SDP filter found."""
    out = {"match": result.filter_match_state == ma.FilterMatchState.MATCH_FOUND, "filters": {}}
    for key, item in result.filter_results.items():
        for field in FILTER_RESULT_FIELDS:
            if item._pb.HasField(field):
                inner = getattr(item, field)
                if field == "sdp_filter_result":   # the SDP result wraps an inspect result (basic config) or a de-identify result
                    inspect = inner.inspect_result if inner._pb.HasField("inspect_result") else None
                    entry = {"match": bool(inspect) and inspect.match_state == ma.FilterMatchState.MATCH_FOUND,
                             "findings": sorted({f.info_type for f in inspect.findings}) if inspect else []}
                else:
                    entry = {"match": inner.match_state == ma.FilterMatchState.MATCH_FOUND}
                if field == "rai_filter_result":
                    entry["types"] = sorted(t for t, r in inner.rai_filter_type_results.items()
                                            if r.match_state == ma.FilterMatchState.MATCH_FOUND)
                out["filters"][key] = entry
    return out


def screen_prompt(project: str, location: str, template_id: str, text: str) -> dict:
    result = client(location).sanitize_user_prompt(
        request=ma.SanitizeUserPromptRequest(name=template_name(project, location, template_id),
                                             user_prompt_data=ma.DataItem(text=text)))
    return findings(result.sanitization_result)


def screen_response(project: str, location: str, template_id: str, text: str) -> dict:
    result = client(location).sanitize_model_response(
        request=ma.SanitizeModelResponseRequest(name=template_name(project, location, template_id),
                                                model_response_data=ma.DataItem(text=text)))
    return findings(result.sanitization_result)


ENV_VAR = "MODEL_ARMOR_TEMPLATE"      # projects/<project>/locations/<location>/templates/<id>
REFUSAL = ("I can't help with that request: I work only with your own store's records and can't act on instructions that "
           "change how I work. Ask me about the store's stock, pickups, team coverage, loss records or learning.")


def configured_template() -> tuple[str, str, str] | None:
    """(project, location, template id) from MODEL_ARMOR_TEMPLATE, or None when screening is not switched on."""
    import os

    value = os.environ.get(ENV_VAR, "").strip()
    if not value:
        return None
    parts = value.split("/")
    if len(parts) != 6 or parts[0] != "projects" or parts[2] != "locations" or parts[4] != "templates":
        raise RuntimeError(f"{ENV_VAR} must be projects/<project>/locations/<location>/templates/<id>, got {value!r}")
    return parts[1], parts[3], parts[5]


def make_screen_before_model(project: str, location: str, template_id: str):
    """A before_model_callback: screen the latest user turn; on a match, answer with a fixed refusal and make no
    model call. Register it on the coordinator (see agent.py) to turn screening on for one deployment."""
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    def screen_before_model(callback_context, llm_request):
        latest = next((c for c in reversed(llm_request.contents or []) if c.role == "user"), None)
        text = "\n".join(p.text for p in (latest.parts if latest else []) or [] if p.text)
        if not text.strip():
            return None
        from agents.cymbal_store_ops.trace import finish_span, start_span

        try:      # the span is for View trace; a context without an invocation (tests, notebooks) still screens
            span = start_span(callback_context, kind="tool", name="model_armor_screen", inputs={"template": template_id})
        except AttributeError:
            span = None
        result = screen_prompt(project, location, template_id, text)
        if span:
            finish_span(callback_context, span, output=result, status="blocked" if result["match"] else "ok")
        callback_context.state["temp:model_armor"] = result
        if result["match"]:
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=REFUSAL)]))
        return None

    return screen_before_model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--template", required=True, help="template id, e.g. store-ops-guard-<namespace>")
    parser.add_argument("--prompt", help="screen one prompt and print the findings")
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()
    if args.delete:
        delete_template(args.project, args.location, args.template)
        print("deleted", args.template)
        return 0
    template = ensure_template(args.project, args.location, args.template)
    print("template", template.name)
    if args.prompt:
        print(json.dumps(screen_prompt(args.project, args.location, args.template, args.prompt), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
