#!/bin/bash
# Collect real API call evidence for the usage manual
OUT=/tmp/api-manual
rm -rf $OUT; mkdir -p $OUT
B1=http://127.0.0.1:8001/api/v1   # DIAGNOSTIC mode
B2=http://127.0.0.1:8002/api/v1   # FULL mode (write enabled)

call() { # file, method, url, body
  local f=$1 m=$2 u=$3 b=$4
  {
    echo "### $m $u"
    [ -n "$b" ] && { echo; echo "Request:"; echo '```json'; echo "$b"; echo '```'; }
    echo
    echo "Response:"
    echo '```json'
    if [ "$m" = "GET" ]; then curl -s "$u"; else curl -s -X "$m" "$u" -H 'Content-Type: application/json' -d "$b"; fi
    echo '```'
  } > $OUT/$f
}

# --- 基础与发现 ---
call 01-safety.json GET $B1/safety ""
call 02-system-info.json GET $B1/system/info ""
call 03-dependencies.json GET $B1/dependencies ""
call 04-discovery.json GET $B1/discovery ""

# --- 带库操作 ---
call 10-libraries.json GET $B1/libraries ""
call 11-lib-inquiry.json GET $B1/libraries/sg1/inquiry ""
call 12-lib-status.json GET $B1/libraries/sg1/status ""
call 13-lib-inventory.json GET $B1/libraries/sg1/inventory ""
call 14-lib-load.json POST $B1/libraries/sg1/load '{"slot": 6, "drive": 0, "confirm": true}'
call 15-lib-status-loaded.json GET $B1/libraries/sg1/status ""
call 16-lib-unload.json POST $B1/libraries/sg1/unload '{"slot": 6, "drive": 0, "confirm": true}'
call 17-lib-load-err.json POST $B1/libraries/sg1/load '{"slot": -1, "drive": 0, "confirm": true}'
call 18-lib-load-busy.json POST $B1/libraries/sg9/load '{"slot": 6, "drive": 0, "confirm": true}'

# --- 带机操作 (tape loaded first) ---
call 19-lib-load2.json POST $B1/libraries/sg1/load '{"slot": 6, "drive": 0, "confirm": true}'
call 20-drive-status.json GET $B1/drives/nst1/status ""
call 21-drive-tapealert.json GET $B1/drives/sg2/tapealert ""
call 22-drive-position.json POST $B1/drives/nst1/position '{"operation": "rewind", "confirm": true}'
call 23-drive-fsf.json POST $B1/drives/nst1/position '{"operation": "fsf", "count": 1, "confirm": true}'
call 24-drive-compression.json GET $B1/drives/nst1/compression ""
call 25-drive-err.json POST $B1/drives/nst1/position '{"operation": "format_c", "count": 1, "confirm": true}'
call 26-diag-tape.json GET $B1/diagnostics/tape/sg2 ""

# --- 读写IO (FULL mode server on 8002) ---
call 30-read.json POST $B2/tests/read '{"drive": "/dev/nst1", "block_size": "1M", "confirm": true}'
call 31-write-unauth.json POST $B1/tests/write '{"drive": "/dev/nst1", "size_mb": 256, "allow_write": false, "confirm": true}'
call 32-write.json POST $B2/tests/write '{"drive": "/dev/nst1", "test_media": "IBM015LA", "size_mb": 256, "allow_write": true, "confirm": true}'
call 33-read-after-write.json POST $B2/tests/read '{"drive": "/dev/nst1", "block_size": "1M", "confirm": true}'

# --- 卸载归位 ---
call 34-unload-final.json POST $B1/libraries/sg1/unload '{"slot": 6, "drive": 0, "confirm": true}'

echo DONE; ls $OUT
