#!/usr/bin/env bash
# Agent Runtime executes this before installing the application's requirements.
set -euo pipefail
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/cymbal-browsers}"
report_installer_dir=$(mktemp -d)
trap 'rm -rf "$report_installer_dir"' EXIT
# Keep this version aligned with uv.lock: browser revisions depend on Playwright.
python -m pip install --no-cache-dir --target "$report_installer_dir" 'playwright==1.63.0'
export PYTHONPATH="$report_installer_dir${PYTHONPATH:+:$PYTHONPATH}"
python -m playwright install --with-deps chromium
chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"
python - <<'PY'
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    executable = Path(p.chromium.executable_path)
    if not executable.is_file() or not os.access(executable, os.R_OK | os.X_OK):
        raise RuntimeError(f"Report browser is not executable: {executable}")
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page()
    page.set_content("<!doctype html><html><body>Report renderer verification</body></html>")
    pdf = page.pdf(format="A4")
    browser.close()
    if not pdf.startswith(b"%PDF-"):
        raise RuntimeError("Report browser failed its PDF render check")
    print(f"REPORT_BROWSER_VERIFIED executable={executable} pdf_bytes={len(pdf)}", flush=True)
PY
