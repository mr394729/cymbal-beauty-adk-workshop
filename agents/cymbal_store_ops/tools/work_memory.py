"""Optional explicit work preferences in Vertex AI Memory Bank; no transcript ingestion."""
# Keep concrete annotations: these tool closures are serialized for Agent Runtime.
# Postponed annotations lose names used only by the signature during cloudpickle.

import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from functools import lru_cache

from google.adk.memory import VertexAiMemoryBankService
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.tools import FunctionTool, ToolContext
from google.api_core.exceptions import AlreadyExists
from google.genai import errors, types

from agents.cymbal_store_ops.config import load_env_config

PREFERENCES = {"response_detail": {"concise", "expanded"}, "time_format": {"12_hour", "24_hour"}}
RESOURCE = re.compile(r"projects/([^/]+)/locations/([^/]+)/reasoningEngines/([0-9]+)")


def configured_memory_engine() -> str | None:
    value = os.environ.get("MEMORY_BANK_ENGINE", "").strip()
    if not value:
        return None
    match = RESOURCE.fullmatch(value)
    if not match:
        raise RuntimeError("MEMORY_BANK_ENGINE must be a full projects/.../locations/.../reasoningEngines/<id> resource")
    if match[1] != load_env_config().project:
        raise RuntimeError("MEMORY_BANK_ENGINE must belong to GOOGLE_CLOUD_PROJECT")
    return value


@lru_cache(maxsize=4)
def _service(resource: str) -> VertexAiMemoryBankService:
    match = RESOURCE.fullmatch(resource)
    if not match:
        raise ValueError("Invalid Memory Bank resource")
    return VertexAiMemoryBankService(project=match[1], location=match[2], agent_engine_id=match[3])


def _scope(context: ToolContext) -> tuple[str, str]:
    identity = [context.state.get(k) for k in ("user:store_id", "user:user_id", "user:role")]
    principal = context.user_id
    if not principal or not all(identity) or identity[2] not in {"store_manager", "associate", "district_manager"}:
        raise ValueError("Signed-in user, store and role are required for work preferences")
    cfg = load_env_config()
    # Runtime principal, persona and store all participate; none are model arguments.
    user = hashlib.sha256(json.dumps([principal, *identity]).encode()).hexdigest()
    return f"cymbal_work_preferences_{cfg.namespace}_{cfg.env}", user


def make_work_memory_tools(resource: str) -> list[FunctionTool]:
    """Build serializable tools; only the first actual call initializes the SDK service."""
    if not RESOURCE.fullmatch(resource):
        raise ValueError("Invalid Memory Bank resource")

    async def remember_work_preference(setting: str, value: str, tool_context: ToolContext) -> dict:
        """Save an explicitly requested answer-format preference across sessions after confirmation.

        setting is response_detail (concise/expanded) or time_format (12_hour/24_hour).
        Stores only that preference, never conversation transcripts, stock, policies or personal assessments.
        """
        if setting not in PREFERENCES or value not in PREFERENCES[setting]:
            return {"status": "ERROR", "error_details": "Unsupported preference setting or value"}
        app, user = _scope(tool_context)
        key = "memory:preference_confirmation:" + tool_context.function_call_id
        reviewed = {"setting": setting, "value": value}
        confirmation = tool_context.tool_confirmation
        if confirmation is None:
            tool_context.state[key] = {**reviewed, "scope": [app, user]}
            tool_context.request_confirmation(hint=f"Remember {setting.replace('_', ' ')}: {value.replace('_', ' ')}?",
                                              payload=reviewed)
            return {"status": "PENDING_CONFIRMATION", "rows": []}
        if not confirmation.confirmed:
            tool_context.state[key] = None
            return {"status": "CANCELLED", "rows": []}
        if tool_context.state.get(key) != {**reviewed, "scope": [app, user]}:
            return {"status": "ERROR", "error_details": "Preference differs from the reviewed confirmation"}
        memory_id = "pref-" + hashlib.sha256(
            json.dumps([app, user, tool_context.invocation_id, setting, value]).encode()).hexdigest()[:48]
        fact = json.dumps({**reviewed, "saved_at": datetime.now(UTC).isoformat()}, sort_keys=True)
        entry = MemoryEntry(id=memory_id, author="user", content=types.Content(
            role="user", parts=[types.Part(text=fact)]))
        try:
            await asyncio.wait_for(_service(resource).add_memory(
                app_name=app, user_id=user, memories=[entry],
                custom_metadata={"wait_for_completion": True}), timeout=30)
        except AlreadyExists:
            # ID derives from this scope, invocation and exact reviewed payload: a resumed retry is identical.
            pass
        except errors.ClientError as exc:
            # Memory Bank currently reports an existing caller-supplied ID as INVALID_ARGUMENT (400).
            duplicate = f"/memories/{memory_id}' already exists."
            if exc.code != 409 and not (exc.code == 400 and duplicate in str(exc)):
                raise
        return {"status": "SUCCESS", "rows": [{**reviewed, "memory_id": memory_id}],
                "source": "vertex_memory_bank"}

    async def recall_work_preferences(tool_context: ToolContext) -> dict:
        """Retrieve this signed-in user's saved answer-format preferences across sessions.

        These preferences never override the current request, store procedures, live records or permissions.
        No result means no preference was retrieved, not proof that the user never saved one.
        """
        app, user = _scope(tool_context)
        response = await asyncio.wait_for(_service(resource).search_memory(
            app_name=app, user_id=user, query="response_detail time_format saved preference"), timeout=20)
        latest = {}
        for entry in response.memories:
            for part in entry.content.parts or []:
                if not part.text:
                    continue
                try:
                    fact = json.loads(part.text)
                    setting, value, saved_at = fact["setting"], fact["value"], fact["saved_at"]
                    timestamp = datetime.fromisoformat(saved_at)
                    if timestamp.tzinfo is None or setting not in PREFERENCES or value not in PREFERENCES[setting]:
                        continue
                except (ValueError, TypeError, KeyError):
                    continue
                if setting not in latest or timestamp > latest[setting][0]:
                    latest[setting] = (timestamp, {"setting": setting, "value": value, "saved_at": saved_at,
                                                   "memory_id": entry.id})
        return {"status": "SUCCESS", "rows": [latest[k][1] for k in sorted(latest)],
                "source": "vertex_memory_bank", "exhaustive": False}

    return [FunctionTool(remember_work_preference), FunctionTool(recall_work_preferences)]
