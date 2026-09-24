from pathlib import Path

from eval import compare_models as cm


def test_load_scores_and_aggregate(tmp_path: Path):
    csv_a = tmp_path / "a.csv"
    csv_a.write_text(
        "eval_set_id,eval_id,metric_name,threshold,score,eval_status,prompt\n"
        "gate,osa_explanation,stock_invariant,1.0,1.0,PASSED,p\n"
        "gate,osa_explanation,stock_invariant,1.0,0.0,FAILED,p\n"
        "gate,hr_refusal,data_tool_trajectory,1.0,1.0,PASSED,p\n"
    )
    csv_b = tmp_path / "b.csv"
    csv_b.write_text(
        "eval_set_id,eval_id,metric_name,threshold,score,eval_status,prompt\n"
        "gate,osa_explanation,stock_invariant,1.0,1.0,PASSED,p\n"
        "gate,hr_refusal,data_tool_trajectory,1.0,,NOT_EVALUATED,p\n"
    )
    a, b = cm.load_scores(csv_a), cm.load_scores(csv_b)
    assert a[("osa_explanation", "stock_invariant")] == [1.0, 0.0]
    assert ("hr_refusal", "data_tool_trajectory") not in b  # empty score rows are skipped
    table = cm.aggregate({"m-a": a, "m-b": b})
    assert table[("osa_explanation", "stock_invariant")] == {"m-a": 0.5, "m-b": 1.0}
    assert cm.failed_cases(a, {"stock_invariant": 1.0}) == 1
    md = cm.render_markdown(table, {"m-a": {"passed": False, "seconds": 12.0, "failed_cases": 1},
                                    "m-b": {"passed": True, "seconds": 9.0, "failed_cases": 0}},
                            ["m-a", "m-b"], "gate.evalset.json", 2)
    assert "| `m-a` | FAILED | 1 | 12 s |" in md
    assert "| osa_explanation | stock_invariant | 0.50 | 1.00 |" in md
    assert "| hr_refusal | data_tool_trajectory | 1.00 | — |" in md


def test_empty_csv_is_loud(tmp_path: Path):
    p = tmp_path / "empty.csv"
    p.write_text("eval_set_id,eval_id,metric_name,threshold,score,eval_status,prompt\n")
    try:
        cm.load_scores(p)
    except RuntimeError as e:
        assert "no scores" in str(e)
    else:
        raise AssertionError("expected a RuntimeError for an empty CSV")



def test_probe_names_the_model_the_project_cannot_call():
    import pytest

    from eval.compare_models import probe_models

    class _Models:
        def generate_content(self, *, model, contents, config):
            if model == "gemini-9.9-pro":
                raise RuntimeError("404 NOT_FOUND. Publisher model gemini-9.9-pro was not found")
            return "ok"

    class _Client:
        models = _Models()

    probe_models(["gemini-3.8-flash"], client=_Client())
    with pytest.raises(SystemExit) as stop:
        probe_models(["gemini-3.8-flash", "gemini-9.9-pro"], client=_Client())
    assert "gemini-9.9-pro cannot be called" in str(stop.value) and "--models" in str(stop.value)
