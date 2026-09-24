"""The real ADK writer gets the current request and one copy of source facts."""
import json

import pytest
from google.adk.models import LlmResponse
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.cymbal_store_ops.sub_agents.daily_briefing import make_daily_briefing


class CaptureWriter(BaseLlm):
    model: str = "capture-writer"
    requests: list[dict] = []

    async def generate_content_async(self, llm_request, stream=False):
        self.requests.append({"contents": [content.model_dump(mode="json") for content in llm_request.contents],
                              "instruction": str(llm_request.config.system_instruction)})
        plan = {"items": [{"area": "inventory", "headline": "Review stock", "evidence": ["Review the recorded stock."]}],
                "next_actions": [{"label": f"Read {i}", "prompt": f"Review source {i}"} for i in range(3)]}
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(plan))]))


@pytest.mark.asyncio
async def test_writer_keeps_request_and_source_facts_without_duplicate_tool_history(fake_backend):
    model = CaptureWriter()
    runner = InMemoryRunner(agent=make_daily_briefing(model), app_name="writer_context")
    request = "Opening priorities. Priya is unavailable until 10:15; preserve cashier coverage."
    try:
        session = await runner.session_service.create_session(app_name="writer_context", user_id="manager",
            state={"user:user_id": "U-M014", "user:store_id": "S-014", "user:role": "store_manager"})
        events = [event async for event in runner.run_async(user_id="manager", session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=request)]))]
        saved = await runner.session_service.get_session(app_name="writer_context", user_id="manager",
                                                        session_id=session.id)
    finally:
        await runner.close()

    assert len(model.requests) == 1
    sent = model.requests[0]
    contents = sent["contents"]
    assert len(contents) == 1 and contents[0]["parts"][0]["text"] == request
    assert not any(part.get("function_response") or part.get("function_call")
                   for content in contents for part in content["parts"])
    instruction = sent["instruction"]
    encoded = json.dumps(instruction)
    # Source-specific information from all branches remains available to the writer.
    assert all(marker in encoded for marker in ("P-0101", "P-0420", "A-1004", "09:30", "10:30"))
    assert all(encoded.count(heading) == 1 for heading in
               ("Inventory signals:", "Coverage signals:", "Shrink signals:"))
    responses = [part.function_response for event in events for part in
                 (event.content.parts if event.content else []) or [] if part.function_response]
    # Removing history from one model request must not remove evidence from the session.
    assert len(responses) == 13
    assert any(r.name == "get_inventory_context" and r.response["rows"] for r in responses)
    assert len([e for e in saved.events if e.get_function_responses()]) >= 13
    assert saved.state["action_plan"]["store_id"] == "S-014"
