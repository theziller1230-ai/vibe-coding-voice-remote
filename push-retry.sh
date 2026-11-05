#!/usr/bin/env bash
# Push main to origin, retrying through the flaky route to github.com.
set -u
cd "$(dirname "$0")"
for i in $(seq 1 40); do
  out=$(timeout 600 git push -u origin main 2>&1)
  code=$?
  echo "[try $i exit=$code] $(echo "$out" | tail -1)"
  if [ $code -eq 0 ]; then
    echo "PUSH_OK"
    exit 0
  fi
  case "$out" in
    *"fatal error in commit_refs"*) sleep 25 ;;
    *) sleep 12 ;;
  esac
done
echo "PUSH_GAVE_UP"
exit 1
