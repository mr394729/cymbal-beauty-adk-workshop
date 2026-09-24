#!/usr/bin/env bash
# Install the workshop's developer skills into a coding agent's skill directory.
#
#   scripts/install_skills.sh --agent antigravity|gemini-cli|claude|all [--global] [--copy|--link] [--uninstall] [--dry-run]
#
# Source of truth: skills/<name>/SKILL.md. Targets (project scope unless --global):
#   antigravity  .agents/skills/        (global: ~/.gemini/config/skills/)      docs: antigravity.google/docs/skills/
#   gemini-cli   .agents/skills/        (global: ~/.gemini/skills/)             docs: geminicli.com/docs/cli/skills/
#   claude       .claude/skills/  (link) (global: ~/.claude/skills/)            docs: code.claude.com/docs/en/skills
# Only names present in skills/ are ever created or removed. Idempotent. Never touches other skills.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT=""; GLOBAL=0; MODE=""; UNINSTALL=0; DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="$2"; shift 2 ;;
    --global) GLOBAL=1; shift ;;
    --copy) MODE=copy; shift ;;
    --link) MODE=link; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$AGENT" ]] || { echo "usage: --agent antigravity|gemini-cli|claude|all" >&2; exit 2; }
[[ -f "$ROOT/AGENTS.md" && -d "$ROOT/skills" ]] || { echo "run from the workshop repo (AGENTS.md + skills/ not found)" >&2; exit 2; }
if [[ "$DRY" == 0 ]]; then
  uv run python "$ROOT/scripts/check_skills.py" >/dev/null || { echo "skills lint failed — fix skills/ before installing" >&2; exit 1; }
fi
run() { if [[ "$DRY" == 1 ]]; then echo "  (dry-run) $*"; else eval "$@"; fi; }

install_one() {
  local agent="$1" target default_mode
  case "$agent" in
    antigravity) target=$([[ $GLOBAL == 1 ]] && echo "$HOME/.gemini/config/skills" || echo "$ROOT/.agents/skills"); default_mode=copy ;;
    gemini-cli)  target=$([[ $GLOBAL == 1 ]] && echo "$HOME/.gemini/skills" || echo "$ROOT/.agents/skills"); default_mode=copy ;;
    claude)      target=$([[ $GLOBAL == 1 ]] && echo "$HOME/.claude/skills" || echo "$ROOT/.claude/skills"); default_mode=link ;;
    *) echo "unknown agent: $agent" >&2; exit 2 ;;
  esac
  local mode="${MODE:-$default_mode}"
  run mkdir -p "$target"
  for src in "$ROOT"/skills/*/; do
    local name; name="$(basename "$src")"
    [[ -f "$src/SKILL.md" ]] || continue
    local dst="$target/$name"
    if [[ "$UNINSTALL" == 1 ]]; then
      [[ -e "$dst" || -L "$dst" ]] && run rm -rf "$dst" && echo "  removed $dst" || true
      continue
    fi
    if [[ "$mode" == link ]]; then
      if [[ -L "$dst" && "$(readlink "$dst")" == "$src" || "$(readlink -f "$dst" 2>/dev/null)" == "$(readlink -f "$src")" ]]; then echo "  $name -> $dst (unchanged link)"; continue; fi
      run rm -rf "$dst"; run ln -s "$src" "$dst"; echo "  $name -> $dst (linked)"
    else
      if [[ -d "$dst" && ! -L "$dst" ]] && diff -rq "$src" "$dst" >/dev/null 2>&1; then echo "  $name -> $dst (unchanged copy)"; continue; fi
      run rm -rf "$dst"; run cp -R "$src" "$dst"; echo "  $name -> $dst (copied)"
    fi
  done
}

if [[ "$AGENT" == all ]]; then for a in antigravity gemini-cli claude; do echo "== $a"; install_one "$a"; done; else install_one "$AGENT"; fi
[[ "$UNINSTALL" == 1 ]] && exit 0
cat <<'MSG'

Now open the repo in your coding agent and ask: "Which skills do you have?"
  Antigravity IDE: prompt "What skills are available?"    Antigravity CLI: /skills
  Gemini CLI:      gemini skills list   (or /skills list)  Claude Code:     /skills  (or /context)
Expected: the seven workshop skills, agent-platform-runtime … google-adk, then read AGENTS.md.
MSG
