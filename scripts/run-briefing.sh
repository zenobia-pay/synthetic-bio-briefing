#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATE="${1:-$(date +%F)}"
TOPIC="${2:-what is happening in the diverse intelligence and emergence engineering space of synthetic biology?}"

if [[ -f "$ROOT/.env" ]]; then
  set -a; source "$ROOT/.env"; set +a
elif [[ -f "$HOME/.openclaw/workspace/twitter-briefing/.env" ]]; then
  set -a; source "$HOME/.openclaw/workspace/twitter-briefing/.env"; set +a
fi

python3 "$ROOT/scripts/run_briefing.py" --repo "$ROOT" --date "$DATE" --topic "$TOPIC"
