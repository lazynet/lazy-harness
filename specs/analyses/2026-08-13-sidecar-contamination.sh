#!/usr/bin/env bash
# Measure how much of each repo's "SESSIONS" count is compound-loop sidecars
# rather than organic human sessions.
set -uo pipefail

REPOS=(
  ~/repos/flex/mngt/ai-adoption-mgmt ~/repos/lazy/lazy-desktop-manager ~/repos/lazy/lazy-hermes
  ~/repos/lazy/lazy-ansible ~/repos/lazy/lazy-harness ~/repos/lazy/lazy-ai-tools
  ~/repos/flex/mngt/flex-mgmt ~/repos/flex/mngt/supervielle-mgmt ~/repos/flex/mngt/ydi-mgmt
  ~/repos/flex/infra/supervielle-backstage-poc ~/repos/flex/ydi-data-layer
)

printf "%-30s %7s %7s %7s %s\n" REPO RAW SIDECAR ORGANIC "ORGANIC%"

for r in "${REPOS[@]}"; do
  name=$(basename "$r")
  enc=$(echo "$r" | sed "s|^$HOME|/Users/lazynet|" | tr '/' '-')
  dirs=()
  for p in ~/.claude-lazy/projects ~/.claude-flex/projects; do
    while IFS= read -r d; do dirs+=("$d"); done < <(
      find "$p" -maxdepth 1 -type d \( -name "$enc" -o -name "$enc-*" \) 2>/dev/null)
  done
  [ ${#dirs[@]} -eq 0 ] && { printf "%-30s %7s\n" "$name" 0; continue; }

  raw=0; side=0
  while IFS= read -r f; do
    raw=$((raw+1))
    first=$(grep -m1 '"type":"user"' "$f" 2>/dev/null | head -c 500)
    case "$first" in
      *learning*|*compound*|*eval*|*"security-review"*) side=$((side+1)) ;;
    esac
  done < <(find "${dirs[@]}" -name "*.jsonl" 2>/dev/null)

  org=$((raw-side))
  pct=0; [ "$raw" -gt 0 ] && pct=$((org*100/raw))
  printf "%-30s %7s %7s %7s %s%%\n" "$name" "$raw" "$side" "$org" "$pct"
done
