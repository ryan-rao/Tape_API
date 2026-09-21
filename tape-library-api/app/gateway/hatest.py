"""HATest playground — gateway 性能/高可用压测控制器（v1.4.0）。

HA 语义：
- 测试脚本以独立会话（setsid）脱离网关进程：网关重启压测不死
- 全部状态落盘（run.sh / run.log / pid / meta.json / metrics.jsonl）
  → 网关重启后 status()/log() 自动重附着，GUI 无感重连
- 指标出口：脚本每轮一行 JSONL（setup/round/done/error 事件），
  status() 解析尾部聚合出图表序列与汇总
- 脚本韧性：API 连接级失败指数退避重试（总窗口 1800s，输出
  WAIT_GATEWAY 心跳）——网关重启窗口内压测等待而非失败
"""
import json
import os
import signal
import subprocess
import time


class HATestError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


DEFAULT_SCRIPT = r'''#!/usr/bin/env bash
# HATest v1.0 — 归档网关性能/高可用压测（curl-only + python3 解析 JSON，无 jq 依赖）
# 主循环：创建→上传→归档→清缓存→召回→下载→清缓存→sha256 比对→删除，直至写满介质
# 并行/串行：多带机并行（每带机一 worker），带内多磁带串行
set -u
API="${HATEST_API:-http://127.0.0.1:8001/api/v1}"
ROUNDS="${HATEST_ROUNDS:-0}"
BIG_MB="${HATEST_BIG_MB:-100}"
BIG_COUNT="${HATEST_BIG_COUNT:-10}"
SMALL_MB="${HATEST_SMALL_MB:-1}"
SMALL_COUNT="${HATEST_SMALL_COUNT:-0}"
FILL="${HATEST_FILL:-1}"
BASE="${HATEST_BASE:-/home/tape_api/hatest}"
MET="$BASE/metrics.jsonl"
WORK="$BASE/work"
PY="${HATEST_PY:-python3}"
mkdir -p "$WORK"

ts_ms() { date +%s%3N; }
log()   { echo "[$(date '+%F %T')] $*"; }
emit()  { printf '%s\n' "$1" >> "$MET"; }

jget() { # jget <json> <a.b.0.c> —— 命中返回值；缺失返回空串
  printf '%s' "$1" | "$PY" -c '
import json,sys
try:
    d=json.loads(sys.stdin.read() or "{}")
    for k in sys.argv[1].split("."):
        d=d[int(k)] if isinstance(d,list) else d[k]
    if isinstance(d,(dict,list)): print(json.dumps(d,separators=(",",":")))
    else: print(d)
except Exception:
    pass' "$2" 2>/dev/null
}

RC=0; BODY=""
api() { # api METHOD PATH OUTFILE(空=收 body) [curl_extra...]
  # 全局产出：RC(http 码) BODY(响应体) API_MS(耗时)；连接失败退避重试 ≤1800s
  local m="$1" p="$2" out="$3"; shift 3
  local waited=0 backoff=2 code all
  API_MS=$(ts_ms)
  while :; do
    if [ -n "$out" ]; then
      code=$(curl -sS -m 900 -X "$m" -o "$out" -w '%{http_code}' "$API$p" "$@" 2>/dev/null) || code=000
      BODY=""
    else
      all=$(curl -sS -m 900 -X "$m" -w '\n%{http_code}' "$API$p" "$@" 2>/dev/null) || all=$'\n000'
      code="${all##*$'\n'}"; BODY="${all%$'\n'*}"
    fi
    case "$code" in
      000|502|503|504)
        if [ "$waited" -ge 1800 ]; then RC="$code"; return 1; fi
        log "WAIT_GATEWAY http=$code waited=${waited}s（网关不可达，退避重试——HA 观测点）"
        sleep "$backoff"; waited=$((waited+backoff))
        backoff=$((backoff*2)); [ "$backoff" -gt 30 ] && backoff=30
        ;;
      *) RC="$code"; API_MS=$(( $(ts_ms) - API_MS )); return 0 ;;
    esac
  done
}

TASK_STATE=""; TASK_S=0
task_wait() { # task_wait <task_id> —— 轮询至终态；产出 TASK_STATE / TASK_S(秒)
  local tid="$1" t0=$(date +%s.%N) n=0
  [ -n "$tid" ] || { TASK_STATE=invalid_empty_id; return 1; }
  TASK_STATE=""; TASK_S=0
  while :; do
    api GET "/archive/tasks/$tid" '' || return 1
    TASK_STATE=$(jget "$BODY" data.state)
    case "$TASK_STATE" in succeeded|failed|cancelled) break ;; esac
    sleep 2; n=$((n+2)); [ "$n" -gt 7200 ] && { TASK_STATE=timeout; break; }
  done
  TASK_S=$("$PY" -c "print(round($(date +%s.%N)-$t0,2))" 2>/dev/null || echo 0)
}

JOB_STATE=""; JOB_S=0
job_wait() { # job_wait <job_id> —— recall 冷路径异步 job 轮询（/api/v1/jobs）
  local jid="$1" t0=$(date +%s.%N) n=0
  [ -n "$jid" ] || { JOB_STATE=invalid_empty_id; return 1; }
  JOB_STATE=""; JOB_S=0
  while :; do
    api GET "/jobs/$jid" '' || return 1
    JOB_STATE=$(jget "$BODY" data.state)
    case "$JOB_STATE" in succeeded|failed|cancelled) break ;; esac
    sleep 2; n=$((n+2)); [ "$n" -gt 7200 ] && { JOB_STATE=timeout; break; }
  done
  JOB_S=$("$PY" -c "print(round($(date +%s.%N)-$t0,2))" 2>/dev/null || echo 0)
}

FW_STATE=""; FW_S=0
file_wait_archived() { # file_wait_archived <file_id> —— 轮询文件终态（覆盖 CONTAINER_SEALED 无任务信封）
  local fid="$1" t0=$(date +%s.%N) n=0
  FW_STATE=""; FW_S=0
  while :; do
    api GET "/archive/files/$fid" '' || return 1
    FW_STATE=$(jget "$BODY" data.file.state)  # 实测：GET /files/{id} 走 resolve()，state 嵌套在 data.file 下
    case "$FW_STATE" in archived|failed) break ;; esac
    sleep 2; n=$((n+2)); [ "$n" -gt 7200 ] && { FW_STATE=timeout; break; }
  done
  FW_S=$("$PY" -c "print(round($(date +%s.%N)-$t0,2))" 2>/dev/null || echo 0)
}

arch_one() { # arch_one <file_id> —— 请求归档并等文件终态；已随容器连带归档则跳过
  local f="$1" pre c
  api GET "/archive/files/$f" '' || return 1
  pre=$(jget "$BODY" data.file.state)
  if [ "$pre" = archived ]; then log "文件 ${f:0:8} 已随容器归档，跳过"; FW_S=0; return 0; fi
  api POST "/archive/files/$f/archive" '' || return 1
  c=$(jget "$BODY" data.container_id); [ -n "$c" ] && cid="$c"
  log "归档请求: ${f:0:8} route=$(jget "$BODY" data.route) code=$(jget "$BODY" code)"
  file_wait_archived "$f" || return 1
  [ "$FW_STATE" = archived ] || { log "归档未完成: ${f:0:8} -> $FW_STATE"; return 1; }
  return 0
}

media_probe() { # media_probe <barcode> —— 产出 MU_USED MU_CAP MU_STATE
  MU_USED=0; MU_CAP=0; MU_STATE=unknown
  api GET "/archive/media" '' || return 1
  eval "$("$PY" -c '
import json,sys
try: items=json.loads(sys.argv[1] or "{}")["data"]["items"]
except Exception: items=[]
for m in items:
    if m.get("barcode")==sys.argv[2]:
        print("MU_USED=%d\nMU_CAP=%d\nMU_STATE=%s" % (
            int(m.get("used_bytes") or 0), int(m.get("capacity_bytes") or 0), m.get("state","")))
        break' "$BODY" "$1" 2>/dev/null)" || true
}

CACHE_PCT=0
cache_clear() { # cache_clear <container_ids 空格分隔> —— 清自有缓存 + selfheal + 水线
  local cids="$1" cache_dir="" tot="" quota=""
  api GET "/archive/cache?limit=1000" '' || true
  cache_dir=$(jget "$BODY" data.config.cache_dir)
  [ -n "$cache_dir" ] && [ -d "$cache_dir" ] || return 0
  # 缓存文件名带哈希前缀（如 4c0d0c5c90d3_hatest-*.bin），必须用 *hatest-* 通配
  find "$cache_dir" -type f -name '*hatest-*' -delete 2>/dev/null
  for cid in $cids; do
    [ -n "$cid" ] || continue
    find "$cache_dir" -type f -name "*${cid}*" -delete 2>/dev/null
  done
  api POST "/archive/selfheal" '' || true
  api GET "/archive/stats" '' || true
  tot=$(jget "$BODY" data.cache.total_bytes); quota=$(jget "$BODY" data.cache.quota_bytes)
  CACHE_PCT=$("$PY" -c "q=int('${quota:-0}' or 0);t=int('${tot:-0}' or 0);print(round(t*100.0/q,1) if q else 0.0)" 2>/dev/null || echo 0)
}

tape_pick() { # tape_pick <format> —— 按格式列出可写介质条码（读 $BODY）
  printf '%s' "$BODY" | "$PY" -c '
import json,sys
try: items=json.loads(sys.stdin.read() or "{}")["data"]["items"]
except Exception: items=[]
print(" ".join(m["barcode"] for m in items
               if m.get("format","raw")==sys.argv[1]
               and m.get("state") in ("appendable","scratch")))' "$1" 2>/dev/null
}

ND=1; TAPECSV=""; PREF="raw"
setup() {
  log "== HATest setup =="
  api GET "/safety" '' || { log "FATAL safety 不可达（$RC）"; return 1; }
  log "safety: ${BODY:0:200}"
  api GET "/libraries" '' || true
  log "libraries: ${BODY:0:300}"
  api GET "/archive/gw-config" '' || true
  # 实测：preferred_format/dte_map 在 data.live.*（running 是布尔标志）
  PREF=$(jget "$BODY" data.live.preferred_format)
  local dmap; dmap=$(jget "$BODY" data.live.dte_map)
  ND=$("$PY" -c 'import json,sys
try: d=json.loads(sys.argv[1] or "{}"); print(max(1,len(d)))
except Exception: print(1)' "$dmap" 2>/dev/null || echo 1)
  api GET "/archive/media" '' || true
  TAPECSV=$(tape_pick "$PREF")
  # 兜底：preferred_format 缺失/无匹配时，尝试另一格式的可写介质（按介质推断）
  if [ -z "$TAPECSV" ]; then
    local alt; [ "$PREF" = ltfs ] && alt=raw || alt=ltfs
    TAPECSV=$(tape_pick "$alt")
    [ -n "$TAPECSV" ] && PREF=$alt
  fi
  [ -n "$PREF" ] || PREF=raw
  log "计划: drives=$ND tapes=[$TAPECSV] format=$PREF rounds=$ROUNDS big=${BIG_COUNT}x${BIG_MB}MB smalls=${SMALL_COUNT}x${SMALL_MB}MB fill=$FILL"
  emit "{\"event\":\"setup\",\"ts\":$(ts_ms),\"api\":\"$API\",\"drives\":$ND,\"tapes\":\"$TAPECSV\",\"format\":\"$PREF\",\"rounds\":$ROUNDS,\"big_mb\":$BIG_MB,\"big_count\":$BIG_COUNT,\"small_mb\":$SMALL_MB,\"small_count\":$SMALL_COUNT,\"fill\":$FILL}"
}

round_one() { # round_one <drive> <tape> <round> —— 一轮全链：N×big 批量上传/归档 + 逐件冷召回校验；emit round 事件
  local d="$1" tape="$2" r="$3" dir tag f i t0 tid cid sha_dl
  local up_ms=0 arc_s=0 arcsm_s=0 rec_s=0 dl_ms=0 created=0 downloaded=0 verify=PASS
  local -a files=() shas=() fids=() sfiles=() sshas=() sfids=()
  dir="$WORK/d$d/$tape/r$r"; mkdir -p "$dir"
  tag="hatest-d${d}-r${r}-$(date +%s)"
  local wall0=$(date +%s.%N)
  log "---- round=$r drive=$d tape=$tape files=${BIG_COUNT}x${BIG_MB}MB smalls=${SMALL_COUNT} ----"
  for ((i=1; i<=BIG_COUNT; i++)); do
    f="$dir/${tag}-b${i}.bin"
    dd if=/dev/urandom of="$f" bs=1M count="$BIG_MB" 2>/dev/null || return 1
    shas[i]=$(sha256sum "$f" | cut -d' ' -f1); files[i]="$f"
    created=$(( created + $(stat -c%s "$f") ))
  done
  for ((i=1; i<=SMALL_COUNT; i++)); do
    f="$dir/${tag}-s${i}.bin"
    dd if=/dev/urandom of="$f" bs=1M count="$SMALL_MB" 2>/dev/null || return 1
    sshas[i]=$(sha256sum "$f" | cut -d' ' -f1); sfiles[i]="$f"
    created=$(( created + $(stat -c%s "$f") ))
  done
  cid=""
  for ((i=1; i<=BIG_COUNT; i++)); do
    t0=$(ts_ms)
    api POST "/archive/upload" '' -F "file=@${files[i]}" || { log "上传 b$i 失败 rc=$RC"; return 1; }
    up_ms=$(( up_ms + $(ts_ms) - t0 ))
    fids[i]=$(jget "$BODY" data.file_id)
    [ -n "${fids[i]}" ] || { log "上传 b$i 无 file_id: ${BODY:0:200}"; return 1; }
  done
  for ((i=1; i<=SMALL_COUNT; i++)); do
    api POST "/archive/upload" '' -F "file=@${sfiles[i]}" || return 1
    sfids[i]=$(jget "$BODY" data.file_id)
    [ -n "${sfids[i]}" ] || { log "上传 s$i 无 file_id"; return 1; }
  done
  log "上传 ok: big=${BIG_COUNT}x${BIG_MB}MB(${up_ms}ms) smalls=${SMALL_COUNT}"
  for ((i=1; i<=BIG_COUNT; i++)); do
    arch_one "${fids[i]}" || return 1
    arc_s=$(awk -v a="$arc_s" -v b="$FW_S" 'BEGIN{printf "%.2f", a+b}')
  done
  for ((i=1; i<=SMALL_COUNT; i++)); do
    arch_one "${sfids[i]}" || return 1
    arcsm_s=$(awk -v a="$arcsm_s" -v b="$FW_S" 'BEGIN{printf "%.2f", a+b}')
  done
  log "归档 ok: ${BIG_COUNT}xbig(${arc_s}s) smalls(${arcsm_s}s) cid=$cid"
  # 逐件召回校验：每件召回前清缓存保证冷读；recall→download→sha256→删本地
  for ((i=1; i<=BIG_COUNT; i++)); do
    cache_clear "$cid"
    api POST "/archive/files/${fids[i]}/recall" '' || return 1
    tid=$(jget "$BODY" data.job_id)
    if [ -n "$tid" ]; then
      job_wait "$tid" || return 1
      [ "$JOB_STATE" = succeeded ] || { log "召回 b$i 失败: $JOB_STATE"; return 1; }
      rec_s=$(awk -v a="$rec_s" -v b="$JOB_S" 'BEGIN{printf "%.2f", a+b}')
    else
      log "召回 b$i 立即返回（温路径: $(jget "$BODY" code)）"
    fi
    t0=$(ts_ms)
    api GET "/archive/files/${fids[i]}/download" "$dir/dl-b${i}.bin" || return 1
    dl_ms=$(( dl_ms + $(ts_ms) - t0 ))
    downloaded=$(( downloaded + $(stat -c%s "$dir/dl-b${i}.bin" 2>/dev/null || echo 0) ))
    sha_dl=$(sha256sum "$dir/dl-b${i}.bin" 2>/dev/null | cut -d' ' -f1)
    if [ "$sha_dl" = "${shas[i]}" ]; then log "召回校验 b$i/$BIG_COUNT: PASS rec累计=${rec_s}s"
    else verify=FAIL; log "召回校验 b$i/$BIG_COUNT: FAIL"; fi
    rm -f "$dir/dl-b${i}.bin"
  done
  for ((i=1; i<=SMALL_COUNT; i++)); do api DELETE "/archive/files/${sfids[i]}" '' || log "删除 s$i rc=$RC"; done
  for ((i=1; i<=BIG_COUNT; i++)); do api DELETE "/archive/files/${fids[i]}" '' || log "删除 b$i rc=$RC"; done
  rm -rf "$dir"
  media_probe "$tape"
  local wall=$("$PY" -c "print(round($(date +%s.%N)-$wall0,2))" 2>/dev/null || echo 0)
  local up_avg=0 dl_avg=0
  up_avg=$(( up_ms / BIG_COUNT )); dl_avg=$(( dl_ms / BIG_COUNT ))
  emit "{\"event\":\"round\",\"ts\":$(ts_ms),\"drive\":$d,\"tape\":\"$tape\",\"round\":$r,\"files\":$BIG_COUNT,\"api_ms\":{\"upload\":$up_avg,\"download\":$dl_avg},\"task_s\":{\"archive\":$arc_s,\"archive_small\":$arcsm_s,\"recall\":$rec_s},\"bytes\":{\"created\":$created,\"downloaded\":$downloaded},\"verify\":\"$verify\",\"cache_pct\":$CACHE_PCT,\"media_used_bytes\":$MU_USED,\"media_capacity_bytes\":$MU_CAP,\"wall_s\":$wall}"
  log "round=$r verify=$verify files=$BIG_COUNT up_avg=${up_avg}ms dl_avg=${dl_avg}ms arc=${arc_s}s rec=${rec_s}s bytes=$created cache=${CACHE_PCT}% used=$MU_USED"
  [ "$verify" = PASS ]
}

tape_loop() { # tape_loop <drive> <tape> —— 单带串行轮次直至写满/限轮
  local d="$1" tape="$2" r=0 ok_n=0 fail_n=0 stop=""
  rm -rf "$WORK/d$d/$tape"
  while :; do
    r=$((r+1))
    if [ "$ROUNDS" -gt 0 ] && [ "$r" -gt "$ROUNDS" ]; then stop=max_rounds; break; fi
    if round_one "$d" "$tape" "$r"; then ok_n=$((ok_n+1)); else fail_n=$((fail_n+1)); fi
    media_probe "$tape"
    if [ "$MU_CAP" -gt 0 ] && [ "$MU_USED" -ge $(( MU_CAP * 98 / 100 )) ]; then stop=tape_full; break; fi
    [ "$MU_STATE" = appendable ] || { stop="state_$MU_STATE"; break; }
  done
  log "tape $tape 结束: $stop ok=$ok_n fail=$fail_n"
  echo "$ok_n $fail_n" >> "$WORK/d$d.count"
}

worker() {
  local d="$1" idx=0 t
  : > "$WORK/d$d.count"
  for t in $TAPECSV; do
    [ $(( idx % ND )) -eq "$d" ] && tape_loop "$d" "$t"
    idx=$((idx+1))
  done
}

main() {
  log "== HATest 开始: api=$API rounds=$ROUNDS big=${BIG_COUNT}x${BIG_MB}MB smalls=${SMALL_COUNT}x${SMALL_MB}MB fill=$FILL =="
  setup || { emit "{\"event\":\"error\",\"ts\":$(ts_ms),\"msg\":\"setup_failed\"}"; exit 1; }
  if [ -z "$TAPECSV" ]; then
    log "无可写介质（format=$PREF, state=appendable/scratch）"
    emit "{\"event\":\"done\",\"ts\":$(ts_ms),\"reason\":\"no_media\",\"ok\":0,\"fail\":0}"
    exit 0
  fi
  local pids=() d
  for ((d=0; d<ND; d++)); do worker "$d" & pids+=("$!"); done
  for p in "${pids[@]}"; do wait "$p"; done
  local ok=0 fail=0 cnt
  for cnt in "$WORK"/d*.count; do
    [ -f "$cnt" ] || continue
    read -r a b < "$cnt" || true
    a=${a:-0}; b=${b:-0}
    ok=$((ok+a)); fail=$((fail+b))
  done
  emit "{\"event\":\"done\",\"ts\":$(ts_ms),\"reason\":\"completed\",\"ok\":$ok,\"fail\":$fail}"
  log "== HATest 结束: ok=$ok fail=$fail =="
}
trap 'emit "{\"event\":\"error\",\"ts\":$(ts_ms),\"msg\":\"interrupted\"}"; exit 130' INT TERM
main "$@"
'''

_PARAM_LIMITS = {"rounds": (0, 100000), "big_mb": (1, 16384),
                 "big_count": (1, 1000), "small_mb": (1, 1024),
                 "small_count": (0, 1000), "fill": (0, 1)}


class HATestRunner:
    """文件化状态的单例压测控制器：start/status/log/stop。"""

    def __init__(self, base=None):
        self.base = base or os.environ.get("TAPEGW_HATEST_DIR",
                                           "/home/tape_api/hatest")

    # ---------- paths ----------
    def _p(self, name):
        return os.path.join(self.base, name)

    # ---------- lifecycle ----------
    def _pid(self):
        try:
            with open(self._p("pid")) as fh:
                return int(fh.read().strip())
        except (OSError, ValueError):
            return None

    def alive(self):
        pid = self._pid()
        if not pid:
            return False
        # /proc 状态优先：uvicorn 不 wait 子进程，脚本退出后可能成僵尸
        # （僵尸响应 kill(pid,0) 会误报存活）
        try:
            with open("/proc/%d/stat" % pid) as fh:
                state = fh.read().rsplit(")", 1)[1].split()[0]
            return state not in ("Z", "X", "x")
        except (OSError, IndexError):
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False

    def start(self, script, params):
        if self.alive():
            raise HATestError("HATEST_RUNNING",
                              "a HATest run is already active (pid %d)" % self._pid())
        p = {"api": "http://127.0.0.1:8001/api/v1", "rounds": 0,
             "big_mb": 100, "big_count": 10, "small_mb": 1,
             "small_count": 0, "fill": 1}
        p.update(params or {})
        if not str(p["api"]).startswith(("http://", "https://")):
            raise HATestError("HATEST_BAD_PARAM", "api must be http(s) url")
        for k, (lo, hi) in _PARAM_LIMITS.items():
            v = int(p[k])
            if not lo <= v <= hi:
                raise HATestError("HATEST_BAD_PARAM",
                                  "%s out of range [%d,%d]" % (k, lo, hi))
            p[k] = v
        body = script or DEFAULT_SCRIPT
        if not body.strip():
            raise HATestError("HATEST_BAD_PARAM", "empty script")
        if len(body) > 262144:
            raise HATestError("HATEST_BAD_PARAM", "script too large (>256KB)")
        if int(p["rounds"]) == 0 and int(p["fill"]) != 1:
            raise HATestError("HATEST_BAD_PARAM",
                              "no stop condition: rounds=0 requires fill=1")
        os.makedirs(self.base, exist_ok=True)
        os.makedirs(os.path.join(self.base, "work"), exist_ok=True)
        met = self._p("metrics.jsonl")
        if os.path.exists(met):
            os.replace(met, met + ".%d.old" % int(time.time()))
        exports = "".join("export HATEST_%s='%s'\n" % (k.upper(), p[k])
                           for k in ("api", "rounds", "big_mb", "big_count",
                                     "small_mb", "small_count", "fill"))
        exports += "export HATEST_BASE='%s'\n" % self.base
        if body.startswith("#!"):
            body = body.split("\n", 1)[1] if "\n" in body else ""
        run_sh = self._p("run.sh")
        with open(run_sh, "w") as fh:
            # 参数导出必须位于脚本体之前：脚本顶部即读取 HATEST_*
            fh.write("#!/usr/bin/env bash\n" + exports + "\n" + body)
        os.chmod(run_sh, 0o700)
        log_fh = open(self._p("run.log"), "w")
        proc = subprocess.Popen(["bash", run_sh], stdout=log_fh,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL,
                                start_new_session=True, cwd=self.base)
        log_fh.close()
        with open(self._p("pid"), "w") as fh:
            fh.write(str(proc.pid))
        run_id = time.strftime("%Y%m%d-%H%M%S")
        meta = {"run_id": run_id, "pid": proc.pid,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "params": p}
        with open(self._p("meta.json"), "w") as fh:
            json.dump(meta, fh)
        return meta

    def stop(self):
        pid = self._pid()
        if not pid:
            return {"stopped": False, "reason": "no active run"}
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(15):
            time.sleep(0.2)
            if not self.alive():
                break
        else:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            os.unlink(self._p("pid"))
        except OSError:
            pass
        return {"stopped": True, "pid": pid}

    # ---------- observation ----------
    def _events(self, tail=800):
        try:
            with open(self._p("metrics.jsonl")) as fh:
                lines = fh.readlines()[-tail:]
        except OSError:
            return []
        out = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out

    def status(self):
        meta = {}
        try:
            with open(self._p("meta.json")) as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            pass
        evs = self._events()
        setup = next((e for e in reversed(evs) if e.get("event") == "setup"), None)
        done = next((e for e in reversed(evs)
                     if e.get("event") in ("done", "error")), None)
        rounds = [e for e in evs if e.get("event") == "round"][-500:]
        ok = sum(1 for r in rounds if r.get("verify") == "PASS")
        fail = len(rounds) - ok
        bytes_created = sum(int(r.get("bytes", {}).get("created") or 0)
                            for r in rounds)
        wall_sum = sum(float(r.get("wall_s") or 0) for r in rounds)
        thr = round(bytes_created / 1048576.0 / wall_sum, 2) if wall_sum > 0 else 0.0
        try:
            log_size = os.path.getsize(self._p("run.log"))
        except OSError:
            log_size = 0
        return {
            "active": self.alive(), "pid": self._pid(),
            "meta": meta, "setup": setup, "done": done,
            "summary": {"rounds": len(rounds), "rounds_ok": ok,
                        "rounds_fail": fail,
                        "bytes_created": bytes_created,
                        "mb_created": round(bytes_created / 1048576.0, 1),
                        "throughput_mb_s": thr},
            "rounds": rounds,
            "log_size": log_size,
        }

    def log(self, offset=0, limit=65536):
        try:
            size = os.path.getsize(self._p("run.log"))
        except OSError:
            return {"text": "", "offset": 0, "next_offset": 0, "size": 0}
        offset = max(0, min(int(offset), size))
        with open(self._p("run.log")) as fh:
            fh.seek(offset)
            chunk = fh.read(limit)
        return {"text": chunk, "offset": offset,
                "next_offset": offset + len(chunk.encode("utf-8", "replace")),
                "size": size}
