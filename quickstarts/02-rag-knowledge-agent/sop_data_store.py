"""Create, verify or delete your store procedures data store in Vertex AI Search (quickstart 02 and the store agent's policy_lookup).

    uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py setup
    uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py verify
    uv run python quickstarts/02-rag-knowledge-agent/sop_data_store.py teardown

setup    creates the unstructured data store `cymbal-store-sops-<namespace>` in `global` (content required, layout
         parser with layout-based chunking, so policy_lookup can search in CHUNKS mode), uploads docs/*.md as HTML to
         gs://<staging bucket>/sops/<namespace>/, imports them with FULL reconciliation (re-running replaces the set; a
         removed file disappears), waits for the import, waits until policy_lookup returns results, and writes
         `SOP_DATA_STORE=...` into .env.
verify   searches for every procedure and reports whether each comes back with its citation. It reads only.
teardown deletes the data store and the uploaded pages, and clears SOP_DATA_STORE in .env when it names that store.

The value goes into .env because the agent and `adk web` read .env; a value set there, even empty, replaces an exported
one.

The procedures are Markdown, and the layout parser that chunking needs does not read Markdown; it reads HTML. So each
file is converted to a small HTML document (headings, lists, paragraphs) and imported from Cloud Storage as text/html,
with its first heading as the <title>. Every step stops with the reason and the fix when something is missing.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google.api_core.exceptions import FailedPrecondition, NotFound, PermissionDenied  # noqa: E402
from google.cloud import discoveryengine_v1 as de  # noqa: E402

from agents.cymbal_store_ops.config import load_env_config  # noqa: E402
from agents.cymbal_store_ops.tools.policy_lookup import (  # noqa: E402
    COLLECTION,
    LOCATION,
    make_policy_lookup,
    sop_data_store_id,
    sop_data_store_name,
)
from deployment._common import staging_bucket  # noqa: E402

DOCS = Path(__file__).with_name("docs")
CHUNK_SIZE = 300                  # tokens per chunk; layout-based chunking accepts 100-500
OPERATION_TIMEOUT_S = 900
SEARCHABLE_TIMEOUT_S = 900
PROBE_QUERY = "BOPIS hold time for ready orders"
API_HINT = "gcloud services enable discoveryengine.googleapis.com --project {project}; the identity needs roles/discoveryengine.admin"
ENV_FILE = ROOT / ".env"


def set_env_value(key: str, value: str, env_file: Path = ENV_FILE) -> None:
    """Set KEY=value in .env, replacing an existing line (empty or not) or appending one."""
    if not env_file.exists():
        raise SystemExit(f"{env_file} does not exist: cp .env.example .env first")
    text = env_file.read_text()
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{line}\n"
    env_file.write_text(text)


def markdown_to_html(markdown: str) -> tuple[str, str]:
    """(title, html) for the small Markdown subset the SOPs use: #/## headings, '- ' list items with indented
    continuation lines, paragraphs and `code`."""
    def inline(text: str) -> str:
        return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text.strip()))

    title, body, paragraph, items = "", [], [], []

    def flush() -> None:
        if paragraph:
            body.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph.clear()
        if items:
            body.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in markdown.splitlines():
        heading = re.match(r"^(#{1,3}) (.+)$", line)
        if heading:
            flush()
            level, text = len(heading.group(1)), heading.group(2).strip()
            title = title or text
            body.append(f"<h{level}>{inline(text)}</h{level}>")
        elif line.startswith("- "):
            if paragraph:
                flush()
            items.append(line[2:])
        elif line.startswith("  ") and items and line.strip():
            items[-1] += " " + line.strip()
        elif not line.strip():
            flush()
        else:
            if items:
                flush()
            paragraph.append(line)
    flush()
    if not title:
        raise ValueError("an SOP document must start with a '# ' heading (it becomes the search result title)")
    page = (f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{html.escape(title)}</title></head>"
            f"<body>{''.join(body)}</body></html>")
    return title, page


def html_pages(docs_dir: Path = DOCS) -> list[tuple[str, str]]:
    """(file stem, HTML page) for every docs/*.md, in name order."""
    pages = [(path.stem, markdown_to_html(path.read_text(encoding="utf-8"))[1]) for path in sorted(docs_dir.glob("*.md"))]
    if not pages:
        raise SystemExit(f"no SOP documents in {docs_dir}")
    return pages


def sop_prefix(namespace: str) -> str:
    """Where this namespace's SOP pages live in the staging bucket."""
    return f"sops/{namespace}/"


def upload_pages(bucket_uri: str, namespace: str, pages: list[tuple[str, str]]) -> list[str]:
    """Upload current SOP pages without deleting old objects; return the explicit import URI set."""
    from google.cloud import storage

    bucket_name = bucket_uri.removeprefix("gs://").strip("/")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    try:
        bucket.reload()
    except NotFound as e:
        raise SystemExit(f"staging bucket {bucket_uri} does not exist. Fix: deployment/iam/setup_wif.sh creates it, or "
                         f"gcloud storage buckets create {bucket_uri} --location=us-central1") from e
    for stem, page in pages:
        bucket.blob(f"{sop_prefix(namespace)}{stem}.html").upload_from_string(page, content_type="text/html")
    return [f"gs://{bucket_name}/{sop_prefix(namespace)}{stem}.html" for stem, _ in pages]


def data_store_spec(namespace: str) -> de.DataStore:
    """An unstructured search data store whose documents are parsed by layout and chunked (CHUNKS search mode)."""
    cfg = de.DocumentProcessingConfig
    return de.DataStore(
        display_name=sop_data_store_id(namespace),
        industry_vertical=de.IndustryVertical.GENERIC,
        solution_types=[de.SolutionType.SOLUTION_TYPE_SEARCH],
        content_config=de.DataStore.ContentConfig.CONTENT_REQUIRED,
        document_processing_config=cfg(
            default_parsing_config=cfg.ParsingConfig(layout_parsing_config=cfg.ParsingConfig.LayoutParsingConfig()),
            chunking_config=cfg.ChunkingConfig(layout_based_chunking_config=cfg.ChunkingConfig.LayoutBasedChunkingConfig(
                chunk_size=CHUNK_SIZE, include_ancestor_headings=True))),
    )


def import_request(data_store: str, gcs_pattern: str | list[str]) -> de.ImportDocumentsRequest:
    """Import the uploaded pages as unstructured content, replacing the whole set (a removed SOP disappears).

    Cloud Storage, not an inline import: inline documents need structured data ("document.data is a required field")
    and cannot use FULL reconciliation, both seen live on 2026-09-16."""
    return de.ImportDocumentsRequest(
        parent=f"{data_store}/branches/default_branch",
        gcs_source=de.GcsSource(input_uris=[gcs_pattern] if isinstance(gcs_pattern, str) else gcs_pattern, data_schema="content"),
        reconciliation_mode=de.ImportDocumentsRequest.ReconciliationMode.FULL,
    )


def ensure_data_store(project: str, namespace: str) -> str:
    """Create the data store unless it exists; an existing one must have layout-based chunking."""
    name = sop_data_store_name(project, namespace)
    stores = de.DataStoreServiceClient()
    try:
        existing = stores.get_data_store(name=name)
    except NotFound:
        print(f"creating data store {sop_data_store_id(namespace)} (about ten minutes the first time, including indexing)")
        try:
            stores.create_data_store(parent=f"projects/{project}/locations/{LOCATION}/collections/{COLLECTION}",
                                     data_store=data_store_spec(namespace),
                                     data_store_id=sop_data_store_id(namespace)).result(timeout=OPERATION_TIMEOUT_S)
        except FailedPrecondition as e:
            if "being deleted" not in str(e):
                raise
            # A torn-down store keeps its name for a while (the service says up to a couple of hours).
            raise SystemExit(f"{sop_data_store_id(namespace)} was deleted recently and Vertex AI Search is still removing it, "
                             "so the name cannot be reused yet (this can take a couple of hours).\n"
                             "Fix: run `sop_data_store.py setup` again later, or use another namespace (set WORKSHOP_NAMESPACE, "
                             "load its data, then run setup).") from e
        return name
    chunking = de.DocumentProcessingConfig.ChunkingConfig.pb(existing.document_processing_config.chunking_config)
    if not chunking.HasField("layout_based_chunking_config"):
        raise SystemExit(f"{name} exists without layout-based chunking, so CHUNKS search cannot work. "
                         "Delete it with `sop_data_store.py teardown` and run `setup` again.")
    print(f"data store exists: {name}")
    return name


def verify(data_store: str, docs_dir: Path = DOCS) -> dict:
    """Read-only proof that every expected source is retrievable, with citations; no model calls."""
    from agents.cymbal_store_ops.tools.policy_lookup import validate_data_store

    validate_data_store(data_store)
    store = de.DataStoreServiceClient().get_data_store(name=data_store, timeout=20, retry=None)
    chunked = bool(store.document_processing_config.chunking_config.layout_based_chunking_config)
    checks = []
    search = make_policy_lookup(data_store).func
    for path in sorted(docs_dir.glob("*.md")):
        title, _ = markdown_to_html(path.read_text(encoding="utf-8"))
        result = search(title)
        matches = [r for r in result["rows"] if r["title"] == title and r.get("source_uri", "").endswith(
            f"/{path.stem}.html") and r.get("chunk_name")]
        checks.append({"source": path.name, "title": title, "searchable_with_citation": bool(matches),
                       "local_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "citations": [{k: r[k] for k in ("title", "source_uri", "chunk_name")} for r in matches]})
    return {"data_store": data_store, "layout_chunking": chunked,
            "passed": chunked and bool(checks) and all(c["searchable_with_citation"] for c in checks),
            "checks": checks,
            "verification_scope": "Source identity and retrieval only; local hash is not a remote-content checksum."}


def setup() -> int:
    cfg = load_env_config()
    try:
        name = ensure_data_store(cfg.project, cfg.namespace)
    except PermissionDenied as e:
        raise SystemExit(f"Vertex AI Search refused: {e.message}\nFix: {API_HINT.format(project=cfg.project)}") from e

    pages = html_pages()
    pattern = upload_pages(staging_bucket(cfg), cfg.namespace, pages)
    print(f"importing {len(pages)} SOP documents as text/html from {pattern}")
    operation = de.DocumentServiceClient().import_documents(request=import_request(name, pattern))
    response = operation.result(timeout=OPERATION_TIMEOUT_S)
    failures = int(getattr(operation.metadata, "failure_count", 0) or 0)
    if response.error_samples or failures:
        samples = "; ".join(s.message for s in response.error_samples) or "no samples returned"
        raise SystemExit(f"import finished with {failures} failed document(s): {samples}")

    search = make_policy_lookup(name).func
    deadline = time.time() + SEARCHABLE_TIMEOUT_S
    while not search(PROBE_QUERY)["rows"]:
        if time.time() > deadline:
            raise SystemExit(f"imported, but a search still returns nothing after {SEARCHABLE_TIMEOUT_S} s; "
                             "indexing can lag: run `sop_data_store.py setup` again in a few minutes (it is idempotent)")
        print("waiting for the documents to become searchable ...")
        time.sleep(20)
    evidence = verify(name)
    if not evidence["passed"]:
        raise SystemExit("Not every SOP is searchable with citations yet. Re-run the read-only verify command after indexing; "
                         + json.dumps(evidence))
    print(json.dumps(evidence, indent=2))
    set_env_value("SOP_DATA_STORE", name)
    print(f"wrote SOP_DATA_STORE={name} into .env; restart the agent so it registers policy_lookup")
    return 0


def delete_data_store(name: str) -> bool:
    """Delete the data store and wait until it is gone; False when it did not exist.

    The delete operation can finish with neither a response nor an error ("Unexpected state: Long-running operation
    had neither response nor error set", seen live on 2026-09-16) although the store is deleted, so completion is
    confirmed by reading the store back until it returns NotFound, not by the operation result."""
    stores = de.DataStoreServiceClient()
    try:
        stores.delete_data_store(name=name)
    except NotFound:
        return False
    deadline = time.time() + OPERATION_TIMEOUT_S
    while time.time() < deadline:
        try:
            stores.get_data_store(name=name)
        except NotFound:
            return True
        time.sleep(10)
    raise SystemExit(f"{name} still exists {OPERATION_TIMEOUT_S} s after the delete request; check the console and run `sop_data_store.py teardown` again")


def teardown() -> int:
    cfg = load_env_config()
    name = sop_data_store_name(cfg.project, cfg.namespace)
    if delete_data_store(name):
        print(f"deleted {name}")
    else:
        print(f"nothing to delete: {name} does not exist")
    from google.cloud import storage

    bucket_name = staging_bucket(cfg).removeprefix("gs://").strip("/")
    try:
        blobs = list(storage.Client().list_blobs(bucket_name, prefix=sop_prefix(cfg.namespace)))
    except NotFound:
        blobs = []
    for blob in blobs:
        blob.delete()
    if blobs:
        print(f"deleted {len(blobs)} page(s) under gs://{bucket_name}/{sop_prefix(cfg.namespace)}")
    if ENV_FILE.exists() and re.search(rf"^SOP_DATA_STORE={re.escape(name)}\s*$", ENV_FILE.read_text(), flags=re.M):
        set_env_value("SOP_DATA_STORE", "")
        print("cleared SOP_DATA_STORE in .env; policy_lookup is no longer registered")
    return 0


def main(argv: list[str]) -> int:
    from agents.cymbal_store_ops.preflight import require_sign_in

    require_sign_in()   # an expired sign-in stops here, in words, not as a stack trace later
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["setup", "teardown", "verify"])
    args = ap.parse_args(argv)
    if args.action == "verify":
        from agents.cymbal_store_ops.tools.policy_lookup import configured_data_store
        cfg = load_env_config()
        name = configured_data_store() or sop_data_store_name(cfg.project, cfg.namespace)
        result = verify(name)
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    return setup() if args.action == "setup" else teardown()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
