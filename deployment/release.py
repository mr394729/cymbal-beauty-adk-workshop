"""Write the release manifest every environment deploys from.

    uv run python deployment/release.py [--out release.json]

Exports the resolved lock (`uv export --frozen`) to build/requirements.txt and records what identifies a
release: git sha, requirements digest, prompt and config digests, pinned ADK / SDK versions, data version,
and the model and secret versions per environment (never `latest`). deploy.py refuses a checkout that differs
from the manifest it is given; that check does not prevent an older approved build from running after a newer
release (there is no engine lock here).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import json
import re
import subprocess

import yaml

from deployment._common import (  # noqa: E402
    BUILD_DIR,
    ENVS,
    RELEASE_JSON,
    REPO_ROOT,
    DeployError,
    git_dirty,
    git_sha,
    now_iso,
    sha256_file,
    sha256_tree,
)

AGENT_DIR = REPO_ROOT / "agents" / "cymbal_store_ops"
REQUIREMENTS = BUILD_DIR / "requirements.txt"


def export_requirements() -> Path:
    """The lock as pip pins, the form Agent Runtime installs (`requirements` accepts a file path)."""
    BUILD_DIR.mkdir(exist_ok=True)
    cmd = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes", "--no-editable",
           "--no-header", "--no-annotate", "-o", str(REQUIREMENTS)]   # plain `name==version` lines
    p = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True)
    if p.returncode != 0:
        raise DeployError(f"uv export failed: {p.stderr.strip()}")
    return REQUIREMENTS


def pinned(package: str) -> str:
    m = re.search(rf"^{re.escape(package)}==([^\s;]+)", REQUIREMENTS.read_text(), re.M)
    if not m:
        raise DeployError(f"{package} is not pinned in {REQUIREMENTS}")
    return m.group(1)


def per_env() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Model and secret versions per environment, straight from config/envs/*.yaml."""
    models, secrets = {}, {}
    for env in ENVS:
        raw = yaml.safe_load((AGENT_DIR / "config" / "envs" / f"{env}.yaml").read_text()) or {}
        models[env] = str(raw.get("model", ""))
        secrets[env] = {}
        for name, ref in (raw.get("secret_env_vars") or {}).items():
            version = str((ref or {}).get("version", ""))
            if not version or version == "latest":
                raise DeployError(f"config/envs/{env}.yaml secret_env_vars.{name}.version must be a pinned number")
            secrets[env][name] = f"{ref['secret']}:{version}"
    return models, secrets


def build_release(out: Path) -> dict:
    from agents.cymbal_store_ops.fixtures import DATA_VERSION

    export_requirements()
    models, secrets = per_env()
    release = {
        "built_at": now_iso(),
        "git_sha": git_sha(),
        "git_dirty": git_dirty(),
        "requirements": str(REQUIREMENTS.relative_to(REPO_ROOT)),
        "requirements_sha256": sha256_file(REQUIREMENTS),
        "adk_version": pinned("google-adk"),
        "aiplatform_version": pinned("google-cloud-aiplatform"),
        "prompt_version": sha256_tree(sorted((AGENT_DIR / "prompts").glob("*.md"))),
        "config_version": sha256_tree(sorted((AGENT_DIR / "config" / "envs").glob("*.yaml"))),
        "data_version": DATA_VERSION,
        "model": models,
        "secret_versions": secrets,
    }
    out.write_text(json.dumps(release, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out}")
    return release


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=RELEASE_JSON)
    release = build_release(ap.parse_args().out)
    print(json.dumps({k: release[k] for k in ("git_sha", "git_dirty", "requirements_sha256", "adk_version", "data_version")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
