#!/usr/bin/env bash
# install.sh — Link the managing-google-workspace skill into canonical agent paths.
#
# Canonical targets (never ~/src/agent-config directly):
#   ~/.codex/skills/managing-google-workspace/   — Codex
#   ~/.copilot/skills/managing-google-workspace/ — VS Code Copilot
#
# ~/src/agent-config/setup.sh also picks these up automatically on its
# next run via the ~/src/*/skills/ scan in link_codex_skills / link_copilot_skills.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$SCRIPT_DIR/skills/managing-google-workspace"

if [ ! -d "$SKILL_SRC" ]; then
    echo "ERROR: Skill source not found: $SKILL_SRC" >&2
    exit 1
fi

link_skill() {
    local target_dir="$1"
    local label="$2"
    local target="$target_dir/managing-google-workspace"

    mkdir -p "$target_dir"
    ln -sfn "$SKILL_SRC" "$target"
    echo "  Linked $label: $target → $SKILL_SRC"
}

echo "==> google_workspace_mcp skill installer"
link_skill "${CODEX_HOME:-$HOME/.codex}/skills" "Codex"
link_skill "$HOME/.copilot/skills"              "Copilot"
echo ""
echo "==> Done. Run ~/src/agent-config/setup.sh to refresh all managed links."
