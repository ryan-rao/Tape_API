#!/bin/bash
# Collect evidence for CLI-parity APIs
OUT=/tmp/api-manual2
rm -rf $OUT; mkdir -p $OUT
B1=http://127.0.0.1:8001/api/v1
B2=http://127.0.0.1:8002/api/v1

call() {
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

# 新增只读接口
call 40-system-kernel.json GET $B1/system/kernel ""
call 41-system-ibm.json GET $B1/system/ibm ""
call 42-discovery-detail.json GET $B1/discovery/detail ""
call 43-logs-page11.json GET "$B1/devices/sg2/logs?page=0x11" ""
call 44-modes.json GET $B1/devices/sg2/modes ""

# 读写IO新增: 装载 -> write-verify (含 weof/读回/cmp) -> 卸载
call 45-load.json POST $B1/libraries/sg1/load '{"slot": 6, "drive": 0, "confirm": true}'
call 46-write-verify.json POST $B2/tests/write-verify '{"drive": "/dev/nst1", "test_media": "IBM015LA", "size_mb": 256, "allow_write": true, "confirm": true}'
call 47-weof-unauth.json POST $B1/drives/nst1/weof '{"count": 1, "confirm": true}'
call 48-unload.json POST $B1/libraries/sg1/unload '{"slot": 6, "drive": 0, "confirm": true}'

echo DONE; ls $OUT
