#!/bin/bash
# Restart launcher: replays the environment captured from the original uvicorn
# process (/proc/<pid>/environ -> /home/tape_api/gw.env), then execs uvicorn.
while IFS= read -r line; do
  case "$line" in
    [A-Za-z_][A-Za-z0-9_]*=*) export "$line" ;;
  esac
done < /home/tape_api/gw.env
cd /home/tape_api/tape-library-api
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8001
