#!/usr/bin/env bash
set -uo pipefail

REPOS=(
  ~/repos/lazy/lazy-ai-tools ~/repos/lazy/lazy-ansible ~/repos/lazy/lazy-desktop-manager
  ~/repos/lazy/lazy-everythingapp ~/repos/lazy/lazy-harness ~/repos/lazy/lazy-hermes
  ~/repos/lazy/lazy-knowledge
  ~/repos/flex/mngt/ai-adoption-mgmt ~/repos/flex/mngt/flex-mgmt ~/repos/flex/mngt/flexigopay-mgmt
  ~/repos/flex/mngt/infra-mgmt ~/repos/flex/mngt/supervielle-mgmt ~/repos/flex/mngt/tb-ydi-delivery
  ~/repos/flex/mngt/urus-mgmt ~/repos/flex/mngt/ydi-mgmt
  ~/repos/flex/supervielle-mesh-poc ~/repos/flex/infra/supervielle-backstage-poc
  ~/repos/flex/ydi-data-layer
)

printf "%-32s %6s %7s %7s %6s %s\n" REPO SKILLS MCPs SESSIONS INVOCS UNUSED_SKILLS

for r in "${REPOS[@]}"; do
  name=$(basename "$r")
  [ -d "$r" ] || { printf "%-32s %6s\n" "$name" "MISSING"; continue; }

  # local surface
  skills=$(find -L "$r/.claude/skills" -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l | tr -d ' ')
  mcps=$(jq -r '.mcpServers // {} | keys | length' "$r/.mcp.json" 2>/dev/null || echo 0)

  # transcript dirs: encoded path + its worktrees (prefix match, guarded by boundary)
  enc=$(echo "$r" | sed "s|^$HOME|/Users/lazynet|" | tr '/' '-')
  dirs=()
  for p in ~/.claude-lazy/projects ~/.claude-flex/projects; do
    while IFS= read -r d; do dirs+=("$d"); done < <(
      find "$p" -maxdepth 1 -type d \( -name "$enc" -o -name "$enc-*" \) 2>/dev/null)
  done

  if [ ${#dirs[@]} -eq 0 ]; then
    printf "%-32s %6s %7s %7s %6s %s\n" "$name" "$skills" "$mcps" 0 0 "-"
    continue
  fi

  sessions=$(find "${dirs[@]}" -name "*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
  invocs=$(grep -ho '"skill":"[^"]*"' -r "${dirs[@]}" --include="*.jsonl" 2>/dev/null \
           | sed 's/.*"skill":"//;s/"//' | sort > "/tmp/_used_$name.txt"; wc -l < "/tmp/_used_$name.txt" | tr -d ' ')

  # local skills never invoked
  unused="-"
  if [ "$skills" -gt 0 ]; then
    u=$(comm -23 <(find -L "$r/.claude/skills" -maxdepth 2 -name SKILL.md -exec dirname {} \; 2>/dev/null | xargs -n1 basename | sort) <(sort -u "/tmp/_used_$name.txt") | tr '\n' ',' | sed 's/,$//')
    [ -n "$u" ] && unused="$u"
  fi

  printf "%-32s %6s %7s %7s %6s %s\n" "$name" "$skills" "$mcps" "$sessions" "$invocs" "$unused"
done
