"""The agent is built on the shared policy_lookup tool without touching the cloud; the setup script's documents, data
store spec and import request are what Vertex AI Search chunking needs. A missing or foreign data store is loud."""
from __future__ import annotations

import importlib
import re

import pytest
from google.cloud import discoveryengine_v1 as de

UNIT_STORE = "projects/unit-test-project/locations/global/collections/default_collection/dataStores/cymbal-store-sops-unit"


def store_module():
    return importlib.import_module("02-rag-knowledge-agent.sop_data_store")


def test_one_policy_lookup_tool_and_no_credentials_needed_to_build(quickstart, monkeypatch):
    import google.auth

    def no_adc(*args, **kwargs):
        raise AssertionError("building the agent must not read credentials")

    monkeypatch.setattr(google.auth, "default", no_adc)
    agent = quickstart.make_root_agent()
    (tool,) = agent.tools
    assert tool.name == "policy_lookup" and "policy_lookup" in agent.instruction


def test_missing_or_foreign_data_store_is_loud(quickstart, monkeypatch):
    monkeypatch.delenv("SOP_DATA_STORE")
    with pytest.raises(RuntimeError, match="SOP_DATA_STORE is not set: run `(make sops|uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup)`"):
        quickstart.make_root_agent()
    monkeypatch.setenv("SOP_DATA_STORE", UNIT_STORE.replace("sops-unit", "sops-alex"))
    with pytest.raises(RuntimeError, match="namespace 'alex', not your WORKSHOP_NAMESPACE='unit'"):
        quickstart.make_root_agent()


def test_every_sop_becomes_an_html_document_titled_by_its_heading(quickstart):
    pages = store_module().html_pages()
    assert [stem for stem, _ in pages] == ["bopis_picking_and_holds", "cycle_counts", "damaged_goods_and_shrink",
                                           "locked_fragrance_case", "planogram_reset", "product_guidance", "promo_signage_compliance"]
    for _, page in pages:
        assert re.search(r"<title>SOP 0\d — [^<]+</title>", page) and page.count("<h1>") == 1


def test_markdown_conversion_keeps_list_items_whole_and_escapes(quickstart):
    title, page = store_module().markdown_to_html(
        "# SOP 09 — Test\n\nIntro line one\nline two.\n- first item\n  continues here\n- uses `code` & <b>\n")
    assert title == "SOP 09 — Test"
    assert "<p>Intro line one line two.</p>" in page
    assert "<li>first item continues here</li>" in page
    assert "<li>uses <code>code</code> &amp; &lt;b&gt;</li>" in page
    with pytest.raises(ValueError, match="heading"):
        store_module().markdown_to_html("no heading here")


def test_data_store_is_chunked_by_layout_so_chunks_mode_works(quickstart):
    spec = store_module().data_store_spec("unit")
    assert spec.display_name == "cymbal-store-sops-unit"
    assert spec.content_config == de.DataStore.ContentConfig.CONTENT_REQUIRED
    assert list(spec.solution_types) == [de.SolutionType.SOLUTION_TYPE_SEARCH]
    processing = de.DocumentProcessingConfig.pb(spec.document_processing_config)
    assert processing.default_parsing_config.HasField("layout_parsing_config")
    assert processing.chunking_config.layout_based_chunking_config.include_ancestor_headings is True


def test_import_replaces_the_whole_set_from_cloud_storage(quickstart):
    """Inline imports were rejected live (no FULL, 'document.data is required'): pages go through Cloud Storage."""
    m = store_module()
    pattern = f"gs://bucket/{m.sop_prefix('unit')}*.html"
    request = m.import_request(UNIT_STORE, pattern)
    assert request.parent == f"{UNIT_STORE}/branches/default_branch"
    assert request.reconciliation_mode == de.ImportDocumentsRequest.ReconciliationMode.FULL
    assert list(request.gcs_source.input_uris) == [pattern] and request.gcs_source.data_schema == "content"
    assert len(m.html_pages()) == 7 and m.sop_prefix("unit") == "sops/unit/"


def test_setup_writes_sop_data_store_into_env_file(tmp_path):
    """make sops must set the value where make reads it: a key in .env, even empty, replaces an exported value."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("sop_data_store", Path(__file__).parents[1] / "sop_data_store.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env = tmp_path / ".env"
    env.write_text("GOOGLE_CLOUD_PROJECT=p\nSOP_DATA_STORE=\nWORKSHOP_NAMESPACE=unit\n")
    mod.set_env_value("SOP_DATA_STORE", "projects/p/locations/global/collections/default_collection/dataStores/cymbal-store-sops-unit", env)
    assert "SOP_DATA_STORE=projects/p/locations/global/collections/default_collection/dataStores/cymbal-store-sops-unit\n" in env.read_text()
    assert env.read_text().count("SOP_DATA_STORE=") == 1
    mod.set_env_value("SOP_DATA_STORE", "", env)
    assert "SOP_DATA_STORE=\n" in env.read_text()


def test_a_store_name_still_being_deleted_stops_with_a_fix(quickstart, monkeypatch):
    """Tearing down and running setup again within a couple of hours: the service refuses the name; say so and how
    to get past it, not a stack trace."""
    from google.api_core.exceptions import FailedPrecondition, NotFound

    mod = store_module()

    class Stores:
        def get_data_store(self, name):
            raise NotFound("DataStore not found.")

        def create_data_store(self, **kwargs):
            raise FailedPrecondition("DataStore cymbal-store-sops-unit is being deleted, please wait for deletion to "
                                     "complete before recreating with the same ID.")

    monkeypatch.setattr(mod.de, "DataStoreServiceClient", Stores)
    with pytest.raises(SystemExit) as stop:
        mod.ensure_data_store("unit-test-project", "unit")
    assert "still removing it" in str(stop.value) and "Fix:" in str(stop.value) and "another namespace" in str(stop.value)


def test_verify_requires_every_document_and_actual_source_citation(quickstart, monkeypatch, tmp_path):
    from types import SimpleNamespace
    m = store_module()
    (tmp_path / "example.md").write_text("# SOP 01 — Test\n\nText")
    spec = m.data_store_spec("unit")
    monkeypatch.setattr(m.de, "DataStoreServiceClient", lambda: SimpleNamespace(get_data_store=lambda **kw: spec))
    rows = [{"title": "SOP 01 — Test", "source_uri": "gs://b/sops/unit/example.html", "chunk_name": "chunks/1"}]
    monkeypatch.setattr(m, "make_policy_lookup", lambda name: SimpleNamespace(func=lambda query: {"rows": rows}))
    assert m.verify(UNIT_STORE, tmp_path)["passed"]
    rows[0]["source_uri"] = ""
    assert not m.verify(UNIT_STORE, tmp_path)["passed"]
    rows.clear()
    assert not m.verify(UNIT_STORE, tmp_path)["passed"]


def test_explicit_import_paths_do_not_include_old_uploaded_pages(quickstart):
    m = store_module()
    uris = ["gs://b/sops/unit/a.html", "gs://b/sops/unit/b.html"]
    assert list(m.import_request(UNIT_STORE, uris).gcs_source.input_uris) == uris
