#!/usr/bin/env bash
# RepoLens AI — stop both servers (backend :8000 + frontend :5173)
for port in 8000 5173; do
  pids=$(netstat -ano 2>/dev/null | grep ":$port" | grep LISTENING | awk '{print $NF}' | sort -u)
  for pid in $pids; do
    echo "[stop] killing process $pid on :$port"
    taskkill //F //PID "$pid" >/dev/null 2>&1
  done
done
echo "[stop] done."
