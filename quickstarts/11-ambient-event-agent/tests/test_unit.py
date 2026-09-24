"""Tools: the stock lookup from the shared contract and a publish-only Pub/Sub toolset."""
from __future__ import annotations

from google.adk.tools.pubsub import PubSubToolset


def test_tools_are_lookup_and_publish_only(quickstart):
    stock, pubsub = quickstart.root_agent.tools
    assert stock.__name__ == "check_store_stock" and isinstance(pubsub, PubSubToolset)
    assert pubsub.tool_filter == ["publish_message"]
    assert "{topic}" not in quickstart.root_agent.instruction  # the topic is rendered into the prompt
    assert "cymbal-store-ops-recommendations-unit" in quickstart.root_agent.instruction


def test_the_event_store_is_read_without_a_signed_in_session(quickstart, fake_backend):
    """An event carries its store_id; the lookup needs no session identity and returns the OSA recommendation."""
    result = quickstart.root_agent.tools[0]("Lumière Hydra Cream", store_id="S-014")
    assert result["status"] == "SUCCESS"
    row = next(r for r in result["rows"] if r["product_id"] == "P-0101")
    assert (row["on_shelf_qty"], row["backroom_qty"], row["on_hand"]) == (0, 7, 7)
    assert row["recommendation"] == "backroom_check"
