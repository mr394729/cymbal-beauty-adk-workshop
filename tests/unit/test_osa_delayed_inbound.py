"""A delayed inbound shipment is named as delayed, not reported as absent."""
from agents.cymbal_store_ops.tools.domain_tools import osa_recommendation

ROW = {"product_id": "P-0101", "on_hand": 7, "on_shelf_qty": 0, "backroom_qty": 7, "reorder_point": 12}


def test_delayed_shipment_is_named():
    result = osa_recommendation(ROW, [{"product_id": "P-0101", "status": "delayed"}])
    assert result["replenishment_delayed"] is True
    assert "inbound shipment is delayed, not in transit" in result["reason"]
    assert result["recommended_actions"] == ["backroom_check", "replenish"]


def test_no_shipment_says_none_in_transit():
    result = osa_recommendation(ROW, [])
    assert "no replenishment is in transit" in result["reason"] and result["replenishment_delayed"] is False
