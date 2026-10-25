#!/usr/bin/env bash
# PreToolUse guard: any command that can destroy data on the user's PC
# must get explicit user approval, in every permission mode.
# Reads the hook payload on stdin; emits an "ask" decision when a
# destructive pattern is present, otherwise stays silent (allow).

input=$(cat)

patterns='(^|[[:space:];&|(`$"'"'"'])(rm|rmdir|unlink|shred|srm)([[:space:]]|$)'
patterns+='|[Rr]emove-Item|Remove-ItemProperty|Clear-Content|Clear-Disk|Clear-Item'
patterns+='|Format-Volume|Remove-Partition|Remove-PSDrive'
patterns+='|(^|[[:space:];&|(`$"'"'"'])(del|erase)[[:space:]]'
patterns+='|(^|[[:space:];&|(`$"'"'"'])rd[[:space:]]+/[sS]'
patterns+='|format[[:space:]]+[a-zA-Z]:'
patterns+='|mkfs|fdisk|diskpart'
patterns+='|dd[[:space:]].*of=/dev/'
patterns+='|git[[:space:]]+clean'
patterns+='|git[[:space:]]+reset[[:space:]]+--hard'
patterns+='|git[[:space:]]+branch[[:space:]]+-D'
patterns+='|git[[:space:]]+push[[:space:]].*--force'
patterns+='|truncate[[:space:]]+-s[[:space:]]*0'
patterns+='|docker[[:space:]]+(system[[:space:]]+prune|volume[[:space:]]+rm|image[[:space:]]+prune|rm[[:space:]])'
patterns+='|(DROP|TRUNCATE)[[:space:]]+(TABLE|DATABASE|SCHEMA)'
patterns+='|Reset-Computer|Remove-Computer'

if printf '%s' "$input" | grep -Eq "$patterns"; then
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"Data-deleting command detected. Global rule: deletion of data on this PC always requires explicit user approval. Review the exact command and target path before approving."}}'
fi

exit 0
