#!/usr/bin/env bash
set -euo pipefail
DATE="${1:-$(date +%F)}"
TOPIC="${2:-what is happening in the diverse intelligence and emergence engineering space of synthetic biology?}"
python3 "$(dirname "$0")/run_briefing.py" --date "$DATE" --topic "$TOPIC"
