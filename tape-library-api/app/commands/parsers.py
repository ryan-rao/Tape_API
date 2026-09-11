# -*- coding: utf-8 -*-
"""Parsers: structure raw CLI stdout into JSON objects.

Design: keep raw `stdout` in API responses for audit traceability, and add a
`parsed` object with structured fields. Parsers are regex/line based and must
never raise: on unparseable output they return {"parse_error": ...} or partial
results with a "parsed_ok" flag.
"""
import re

__all__ = ["parse_sg_scan", "parse_sg_map", "parse_sg_inq",
           "parse_mt_status", "parse_mtx_status", "parse_mt_compression",
           "parse_sg_vpd", "parse_sg_modes", "parse_sg_logs", "parse_tur",
           "parse_dd_summary", "parse_dmesg_lines", "parse_lsmod",
           "parse_tapealert", "parse_os_release", "parse_uname",
           "parse_id", "auto_parse"]


def parse_sg_scan(stdout):
    """sg_scan output:
    /dev/sg0: scsi33 channel=0 id=0 lun=0
    """
    devices = []
    for line in stdout.splitlines():
        m = re.match(r"(/dev/sg\d+):\s+scsi(\d+)\s+channel=(\d+)\s+id=(\d+)\s+lun=(\d+)", line.strip())
        if m:
            devices.append({
                "sg_device": m.group(1),
                "scsi_host": int(m.group(2)),
                "channel": int(m.group(3)),
                "id": int(m.group(4)),
                "lun": int(m.group(5)),
            })
    return {"devices": devices, "parsed_ok": bool(devices)}


def parse_sg_map(stdout):
    """sg_map -i output:
    /dev/sg0 /dev/nst0 IBM ULT3580-TDA T3S0
    /dev/sg1 IBM 03584L32 2C02
    """
    mapping = []
    for line in stdout.splitlines():
        if not line.strip() or not line.strip().startswith("/dev/"):
            continue
        parts = line.strip().split()
        entry = {"sg_device": parts[0], "nst_device": None,
                 "vendor": None, "product": None, "revision": None}
        rest = parts[1:]
        if rest and rest[0].startswith("/dev/n"):
            entry["nst_device"] = rest[0]
            rest = rest[1:]
        if len(rest) >= 2:
            entry["vendor"] = rest[0]
            entry["product"] = rest[1]
        if len(rest) >= 3:
            entry["revision"] = rest[2]
        mapping.append(entry)
    return {"mapping": mapping, "parsed_ok": bool(mapping)}


def parse_sg_inq(stdout):
    """sg_inq output lines:
      vendor identification: IBM
      product identification: ULT3580-TDA
      product revision level: T3S0
      device type: tape
    """
    fields = {}
    for line in stdout.splitlines():
        m = re.match(r"\s*([a-zA-Z0-9 _]+?):\s*(.+)$", line)
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            fields[key] = m.group(2).strip()
    # normalize alternate key spellings (mtx inquiry / sg_inq variants)
    alias = {
        "vendor_id": "vendor_identification",
        "vendor": "vendor_identification",
        "product_id": "product_identification",
        "product": "product_identification",
        "revision": "product_revision_level",
        "product_revision": "product_revision_level",
        "product_type": "device_type",
        "attached_changer_api": None,  # keep as extra info below
    }
    norm = {}
    for k, v in fields.items():
        v = v.strip().strip(chr(39)).strip(chr(34)).strip()  # strip quotes/padding
        target = alias.get(k, k)
        if target:
            norm[target] = v
        else:
            norm[k] = v
    alias2 = {"peripheral_device_type": "device_type"}
    for k, v in list(norm.items()):
        if k in alias2 and alias2[k] not in norm:
            norm[alias2[k]] = v
    # collect sg_inq standard INQUIRY flag tokens (PQual=0 PDT=1 RMB=1 ...)
    flags = {}
    for line in stdout.splitlines():
        for m2 in re.finditer(r"\b([A-Za-z][A-Za-z0-9_]*)=(-?\w+)", line):
            fk, fv = m2.group(1), m2.group(2)
            if fk in ("S", "s"):  # skip noise
                continue
            flags[fk] = int(fv) if re.fullmatch(r"-?\d+", fv) else fv
    wanted = ["vendor_identification", "product_identification",
              "product_revision_level", "device_type", "unit_serial_number",
              "attached_changer_api"]
    parsed = {k: norm[k] for k in wanted if k in norm}
    if flags:
        parsed["flags"] = flags
    pdt = re.search(r"Peripheral device type:\s*(\S+)", stdout)
    if pdt and "device_type" not in parsed:
        parsed["device_type"] = pdt.group(1)
    parsed["parsed_ok"] = bool(
        parsed.get("vendor_identification") or parsed.get("product_identification"))
    return parsed


def parse_mt_status(stdout):
    """mt status output example:
    SCSI 2 tape drive:
    File number=1, block number=0, partition=0.
    Tape block size 0 bytes. Density code 0x58 (LTO-7).
    Soft error count since last status=0
    General status bits on (41000000):
     BOT ONLINE
    """
    parsed = {
        "file_number": None, "block_number": None, "partition": None,
        "block_size": None, "density_code": None, "density_name": None,
        "soft_error_count": None, "flags": [],
    }
    m = re.search(r"File number=(-?\d+), block number=(-?\d+), partition=(\d+)", stdout)
    if m:
        parsed["file_number"], parsed["block_number"], parsed["partition"] = \
            int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r"Tape block size (\d+) bytes", stdout)
    if m:
        parsed["block_size"] = int(m.group(1))
    m = re.search(r"Density code (0x[0-9a-fA-F]+)(?: \(([^)]+)\))?", stdout)
    if m:
        parsed["density_code"] = m.group(1)
        parsed["density_name"] = m.group(2)
    m = re.search(r"Soft error count since last status=(\d+)", stdout)
    if m:
        parsed["soft_error_count"] = int(m.group(1))
    m = re.search(r"General status bits on \([0-9a-fA-F]+\):\s*\n\s*(.+)", stdout)
    if m:
        parsed["flags"] = m.group(1).split()
    parsed["at_bot"] = "BOT" in parsed["flags"]
    parsed["at_eod"] = "EOD" in parsed["flags"] or "EOT" in parsed["flags"]
    parsed["tape_online"] = "ONLINE" in parsed["flags"] or "DR_OPEN" not in parsed["flags"]
    parsed["parsed_ok"] = parsed["file_number"] is not None
    return parsed


def parse_mtx_status(stdout):
    """mtx status output:
    Storage Element 1:Full:VolumeTag = IBM006LA
    Storage Element 2:Full (Storage Element 2 Import/Export):VolumeTag = ...
      Drive 0 (Transfer) Full (Storage Element 6):VolumeTag = IBM015LA
    """
    slots, drives = [], []
    for line in stdout.splitlines():
        s = line.strip()
        m = re.match(r"Storage Element (\d+)( IMPORT/EXPORT)?:(Full|Empty)", s)
        if m:
            slot = {"element": int(m.group(1)), "occupied": m.group(3) == "Full",
                    "import_export": "import/export" in s.lower(), "barcode": None}
            tag = re.search(r"VolumeTag\s*=\s*(\S+)", s)
            if tag:
                slot["barcode"] = tag.group(1)
            slots.append(slot)
            continue
        m = re.match(r"Drive (\d+) .*?(Full|Empty)", s) or \
            re.match(r"Data Transfer Element (\d+):(Full|Empty)", s)
        if m:
            drv = {"drive": int(m.group(1)), "occupied": m.group(2) == "Full",
                   "barcode": None, "source_slot": None}
            tag = re.search(r"VolumeTag\s*=\s*(\S+)", s)
            if tag:
                drv["barcode"] = tag.group(1)
            src = re.search(r"Storage Element (\d+)", s)
            if src:
                drv["source_slot"] = int(src.group(1))
            drives.append(drv)
    return {
        "slots": slots, "drives": drives,
        "occupied_slots": sum(1 for x in slots if x["occupied"]),
        "loaded_drives": sum(1 for x in drives if x["occupied"]),
        "parsed_ok": bool(slots or drives),
    }


def parse_mt_compression(stdout):
    """mt compression output: 'Compression: on' or 'Data compression: on' etc."""
    text = stdout.lower()
    enabled = None
    if "compression" in text:
        enabled = not re.search(r"compression:\s*off", text)
    return {"compression_enabled": enabled, "parsed_ok": enabled is not None}


def _hex_dump_stats(stdout):
    """Common stats for SCSI hex-dump style outputs (vpd/modes/logs)."""
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    hex_lines = sum(1 for ln in lines if re.search(r"\b[0-9a-f]{2}( [0-9a-f]{2}){7,}\b", ln))
    return {"total_lines": len(lines), "hex_dump_lines": hex_lines,
            "text_lines": len(lines) - hex_lines}


def parse_sg_vpd(stdout):
    """sg_vpd output: page header + key=value params + hex dump.
    e.g. 'unit serial number page (0x80)' / 'Device identification page (0x83)'.
    """
    parsed = {"page_code": None, "page_name": None, "fields": {}, "ascii": []}
    m = re.search(r"\(?0x([0-9a-fA-F]{2})\)?", stdout.splitlines()[0] if stdout.splitlines() else "")
    if m:
        parsed["page_code"] = "0x" + m.group(1).lower()
    name = re.match(r"\s*(.+?)\s+page", stdout.splitlines()[0] if stdout.splitlines() else "", re.I)
    if name:
        parsed["page_name"] = name.group(1).strip()
    for line in stdout.splitlines():
        m = re.match(r"\s*([A-Za-z0-9 _/-]+?):\s*(\S.*)$", line)
        if m and not re.match(r"^\s*[0-9a-f]{2}( [0-9a-f]{2})+", line):
            parsed["fields"][m.group(1).strip().lower().replace(" ", "_")] = m.group(2).strip()
        if re.search(r"[!-~]{4,}", line) and not re.search(r"\b[0-9a-f]{2}( [0-9a-f]{2}){7,}\b", line):
            frag = re.findall(r"[!-~]{4,}", line)
            parsed["ascii"].extend(frag)
    parsed.update(_hex_dump_stats(stdout))
    parsed["parsed_ok"] = parsed["page_code"] is not None or bool(parsed["fields"]) or bool(parsed["ascii"])
    return parsed


def parse_sg_modes(stdout):
    """sg_modes -a output: mode data header + multiple mode pages.
    Page headers look like: 'Control mode page (0x0a)' / ' Disconnect-Reconnect mode page (0x02)'.
    """
    MODE_PAGE_DESC = {
        "0x01": ("Read-Write Error Recovery", "读写错误恢复参数"),
        "0x02": ("Disconnect-Reconnect", "SCSI Disconnect/Reconnect 参数"),
        "0x0a": ("Control", "SCSI 控制参数、命令队列等"),
        "0x0f": ("Data Compression", "数据压缩配置"),
        "0x11": ("Medium Partition", "磁带介质分区配置"),
        "0x18": ("LU Control", "Logical Unit 控制"),
        "0x19": ("Port Control", "SCSI Port 控制"),
        "0x1c": ("Informational Exceptions Control", "异常信息/警告控制"),
        "0x1d": ("Medium Configuration", "磁带介质配置"),
        "0x90": ("Device Configuration", "IBM Tape Drive 设备配置"),
        "0x9a": ("Power Condition", "电源/功耗管理参数"),
        "0x2f": ("Vendor Specific", "厂商专用参数"),
        "0x30": ("Vendor Specific", "厂商专用参数"),
    }
    pages = []
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r">>\s+(.+?),\s*page_control:\s*(\w+)", line)
        if not m:
            continue
        name, ctrl = m.group(1).strip(), m.group(2)
        pc = None
        m2 = re.match(r"page_code:\s*(0x[0-9a-fA-F]+)$", name)
        if m2:
            pc = m2.group(1).lower()
            name = MODE_PAGE_DESC.get(pc, ("Vendor Specific", ""))[0]
        else:
            for j in range(i + 1, min(i + 4, len(lines))):
                m3 = re.match(r"\s*\d+\s+([0-9a-f]{2})\s", lines[j])
                if m3:
                    pc = "0x" + m3.group(1)
                    break
        # collect hex data bytes belonging to this page (until next >> or EOF)
        data = []
        for j in range(i + 1, len(lines)):
            if lines[j].lstrip().startswith(">>"):
                break
            mhex = re.match(r"\s*([0-9a-f]+)\s{2,}((?:[0-9a-f]{2}\s*)+)$", lines[j])
            if mhex:
                data.extend(mhex.group(2).split())
        if data and pc is None and data[0]:
            pc = "0x" + data[0]
        entry = {"page_code": pc, "page_name": name, "page_control": ctrl}
        if pc in MODE_PAGE_DESC:
            entry["page_name"], entry["description"] = MODE_PAGE_DESC[pc]
        if data:
            entry["page_length_bytes"] = int(data[1], 16) if len(data) > 1 and re.fullmatch(r"[0-9a-f]{2}", data[1]) else None
            entry["raw_bytes"] = data
            entry["scsi"] = " ".join(data)
            # per-byte layout keyed by data offset (byte_2 = first parameter byte),
            # matching field-interpretation tables: byte_2..byte_N -> "0xXX"
            entry["byte_fields"] = {("byte_%d" % (idx + 2)): ("0x" + b)
                                    for idx, b in enumerate(data[2:])}
            if pc == "0x0f" and len(data) >= 12:
                # SSC Data Compression page
                entry["fields"] = {
                    "compression_control": "0x" + data[2],
                    "decompression_control": "0x" + data[3],
                    "compression_algorithm": "0x" + "".join(data[4:7]),
                    "compression_parameter": "0x" + data[7],
                    "decompression_algorithm": "0x" + "".join(data[8:11]),
                    "decompression_parameter": "0x" + data[11],
                }
        pages.append(entry)
    fields = {}
    for line in stdout.splitlines():
        m = re.match(r"\s*([A-Za-z0-9 _]+)=([^ ]+)", line)
        if m:
            fields[m.group(1).strip().lower().replace(" ", "_")] = m.group(2).strip(",")
    # header line: Mode data length=223, medium type=0x00, specific param=0x10, longlba=0
    mh = re.search(r"medium type=(0x[0-9a-fA-F]+),\s*specific param=(0x[0-9a-fA-F]+),\s*longlba=(\d+)", stdout)
    if mh:
        fields["medium_type"] = mh.group(1)
        fields["specific_param"] = mh.group(2)
        fields["long_lba"] = int(mh.group(3))
    # block descriptor hex line -> number of blocks / block length
    mdb = re.search(r"General mode parameter block descriptors:\s*\n\s*Density code=(0x[0-9a-fA-F]+)\s*\n\s*\d+\s+((?:[0-9a-f]{2}\s*)+)", stdout)
    if mdb:
        dbytes = mdb.group(2).split()
        if len(dbytes) >= 8:
            fields["number_of_blocks"] = str(int("".join(dbytes[1:5]), 16))
            fields["block_length"] = str(int("".join(dbytes[5:8]), 16))
    parsed = {"mode_pages": pages, "header_fields": fields}
    parsed.update(_hex_dump_stats(stdout))
    parsed["parsed_ok"] = bool(pages) or bool(fields)
    return parsed


LOG_FIELD_DESC = {
    "Errors corrected without substantial delay": ("Count", "无明显延迟即可纠正的错误"),
    "Errors corrected with possible delays": ("Count", "需额外延迟才能纠正的错误"),
    "Total rewrites or rereads": ("Count", "重写/重读次数"),
    "Total errors corrected": ("Count", "总纠正错误数量"),
    "Total times correction algorithm processed": ("Count", "错误恢复算法处理次数"),
    "Total bytes processed": ("Bytes", "错误处理涉及的数据量"),
    "Total uncorrected errors": ("Count", "无法纠正的错误"),
    "Non-medium error count": ("Count", "非介质错误（设备/接口类）"),
    "Data bytes received with WRITE commands": ("GB", "主机 WRITE 命令发送的数据"),
    "Data bytes written to media by WRITE commands": ("GB", "实际写入磁带的数据量"),
    "Data bytes read from media by READ commands": ("GB", "从磁带读取的数据量"),
    "Data bytes transferred by READ commands": ("GB", "READ 命令传输的数据量"),
    "Maximum native capacity in device object buffer": ("MB", "带机数据缓冲相关容量"),
    "Lifetime media loads": ("Count", "生命周期累计装带次数"),
    "Lifetime cleaning operations": ("Count", "生命周期清洁次数"),
    "Lifetime power on hours": ("Hours", "生命周期上电时间"),
    "Lifetime media motion (head) hours": ("Hours", "磁带头实际运动时间"),
    "Lifetime metres of tape processed": ("m", "生命周期处理磁带长度"),
    "Lifetime power cycles": ("Count", "生命周期电源循环次数"),
    "Volume loads since last parameter reset": ("Count", "参数复位后的装带次数"),
    "Hard write errors": ("Count", "生命周期硬写错误"),
    "Hard read errors": ("Count", "生命周期硬读错误"),
    "Duty cycle sample time": ("ms", "Duty Cycle 统计采样时间"),
    "Read duty cycle": ("%", "读操作占比"),
    "Write duty cycle": ("%", "写操作占比"),
    "Activity duty cycle": ("%", "带机活动占比"),
    "Volume not present duty cycle": ("%", "无介质状态占比"),
    "Ready duty cycle": ("%", "Ready 状态占比"),
    "Medium removal prevented": ("Count", "禁止介质移除次数"),
    "Maximum recommended mechanism temperature exceeded": ("Count", "机构最高建议温度超限次数"),
    "Very high frequency polling delay": ("ms", "高速状态轮询周期"),
    "Very high frequency data": ("", "高频状态数据块"),
    "Page valid": ("Flag", "Volume Statistics 数据有效"),
    "Thread count": ("Count", "Tape thread 数量"),
    "Total data sets written": ("Count", "写入 Dataset 数量"),
    "Total write retries": ("Count", "写重试次数"),
    "Total unrecovered write errors": ("Count", "不可恢复写错误"),
    "Total suspended writes": ("Count", "暂停写操作次数"),
    "Total fatal suspended writes": ("Count", "致命暂停写次数"),
    "Total data sets read": ("Count", "读取 Dataset 数量"),
    "Total read retries": ("Count", "读重试次数"),
    "Total unrecovered read errors": ("Count", "不可恢复读错误"),
    "Total suspended reads": ("Count", "暂停读次数"),
    "Total fatal suspended reads": ("Count", "致命暂停读次数"),
    "Last mount unrecovered write errors": ("Count", "最近一次 Mount 不可恢复写错误"),
    "Last mount unrecovered read errors": ("Count", "最近一次 Mount 不可恢复读错误"),
    "Last mount megabytes written": ("MB", "最近一次 Mount 写入数据"),
    "Last mount megabytes read": ("MB", "最近一次 Mount 读取数据"),
    "Lifetime megabytes written": ("MB", "生命周期写入数据量"),
    "Lifetime megabytes read": ("MB", "生命周期读取数据量"),
    "Last load write compression ratio": ("Ratio", "最近装带写压缩率"),
    "Last load read compression ratio": ("Ratio", "最近装带读压缩率"),
    "Medium mount time": ("Raw", "介质 Mount 时间统计"),
    "Medium ready time": ("Raw", "介质 Ready 时间统计"),
    "Total native capacity": ("MB", "磁带 Native Capacity"),
    "Total used native capacity": ("MB", "已使用 Native Capacity"),
    "Volume serial number": ("String", "Volume 序列号"),
    "Tape lot identifier": ("String", "Tape Lot 标识"),
    "Volume barcode": ("String", "当前/最近 Volume Barcode"),
    "Volume manufacturer": ("String", "磁带制造商"),
    "Volume license code": ("Code", "Volume License Code"),
    "Volume personality": ("String", "磁带格式/介质 Personality"),
    "Write protect": ("Flag", "当前 Volume 是否写保护"),
    "WORM": ("Flag", "是否 WORM 介质"),
    "Maximum recommended tape path temperature exceeded": ("Flag", "磁带路径温度是否超限"),
    "Beginning of medium passes": ("Count", "磁带 BOT 区域通过次数"),
    "Middle of medium passes": ("Count", "磁带中部区域通过次数"),
    "Accumulated transitions to active": ("Count", "转换到 Active 状态次数"),
    "Accumulated transitions to idle_c": ("Count", "转换到 Idle_C 状态次数"),
    "Read compression ratio x100": ("Ratio ×100", "读压缩率"),
    "Write compression ratio x100": ("Ratio ×100", "写压缩率"),
    "MB transferred to server": ("MB", "传输到服务器的数据量"),
    "MB read from tape": ("MB", "从磁带读取数据量"),
    "MB transferred from server": ("MB", "从服务器接收的数据量"),
    "MB written to tape": ("MB", "写入磁带数据量"),
    "Data compression enabled": ("Flag", "数据压缩功能是否启用"),
    "Main partition remaining capacity": ("MiB", "Main Partition 剩余容量"),
    "Alternate partition remaining capacity": ("MiB", "Alternate Partition 剩余容量"),
    "Main partition maximum capacity": ("MiB", "Main Partition 最大容量"),
    "Alternate partition maximum capacity": ("MiB", "Alternate Partition 最大容量"),
    "Read warning": ("Flag", "读警告"),
    "Write warning": ("Flag", "写警告"),
    "Hard error": ("Flag", "硬件/严重错误"),
    "Media": ("Flag", "介质告警"),
    "Read failure": ("Flag", "读失败"),
    "Write failure": ("Flag", "写失败"),
    "Media life": ("Flag", "介质寿命告警"),
    "Cleaning required": ("Flag", "需要清洁"),
    "Cleaning requested": ("Flag", "请求清洁"),
    "Drive temperature": ("Flag", "温度异常"),
    "Drive voltage": ("Flag", "电压异常"),
    "Predictive failure": ("Flag", "预测性故障"),
    "Diagnostics required": ("Flag", "要求诊断"),
    "Loading failure": ("Flag", "装载失败"),
    "Firmware failure": ("Flag", "固件故障"),
}

LOG_PAGE_DESC = {
    "0x00": "支持的 Log Sense 页列表",
    "0x02": "写错误计数页",
    "0x03": "读错误计数页",
    "0x06": "非介质错误页",
    "0x0c": "顺序访问设备页（容量/清洁/厂商参数）",
    "0x11": "DT 设备状态页（标志位/加密/端口）",
    "0x12": "TapeAlert 响应页",
    "0x14": "设备统计页（生命周期/-duty cycle）",
    "0x16": "磁带诊断记录页（错误历史）",
}

# pages whose header line has no [0xNN] suffix
_NAMED_PAGES = [
    ("Non-medium error", "0x06"),
    ("Sequential access device", "0x0c"),
    ("TapeAlert response", "0x12"),
    ("Device statistics", "0x14"),
    ("Volume statistics", "0x17"),
]


def _log_field(name, value, unit=""):
    u, d = LOG_FIELD_DESC.get(name, (unit or "", ""))
    return {"name": name, "value": value, "unit": u, "description": d}


def _logval(tok):
    if re.fullmatch(r"-?\d+", tok):
        return int(tok)
    return tok


def parse_sg_logs(stdout, page=None):
    """Structured sg_logs -a output: device header + log pages -> fields."""
    lines = stdout.splitlines()
    device = {}
    if lines:
        m = re.match(r"\s*(\S+)\s+(\S+)\s+(\S+)\s*$", lines[0])
        if m:
            device = {"vendor": m.group(1), "model": m.group(2),
                      "firmware": m.group(3)}
    pages = []
    cur = None
    hex_target = None  # field dict collecting hex dump

    def new_page(name, code):
        nonlocal cur, hex_target
        cur = {"page_code": code, "page_name": name.strip(),
               "description": LOG_PAGE_DESC.get(code, ""), "fields": [],
               "supported_pages": [], "records": []}
        pages.append(cur)
        hex_target = None

    hdr = re.compile(r"^(\S.*?)\s+\[0x([0-9a-fA-F]{1,2})\]\s*:?$")
    param_hdr = re.compile(r"\s*(Reserved|Vendor specific)\s*\[(?:or vendor specific\s*)?\[?(?:parameter_code=)?0x([0-9a-fA-F]+)\]?\]?\s*(?:value)?\s*[:=]?\s*(\S*)\s*$")

    for line in lines[1:]:
        if not line.strip():
            hex_target = None
            continue
        # ---- page headers: unindented ----
        if not line[0].isspace():
            m = hdr.match(line.strip())
            if m:
                new_page(re.sub(r"\s+page.*$", "", m.group(1)), "0x%02x" % int(m.group(2), 16))
                continue
            hit = [c for pre, c in _NAMED_PAGES if line.startswith(pre)]
            if hit:
                new_page(re.sub(r"\s+page.*$", "", line.strip()), hit[0])
                continue
            mud = re.match(r"^Unable to decode page\s*=\s*0x([0-9a-fA-F]+)", line.strip())
            if mud:
                new_page("Undecoded page", "0x%02x" % int(mud.group(1), 16))
                cur["decode_status"] = "unable_to_decode"
                f = {"name": "Raw data", "value": "", "unit": "Hex",
                     "description": "sg3_utils 无法解析该页，原始数据"}
                cur["fields"].append(f)
                hex_target = f
                continue
            continue
        if cur is None:
            continue
        body = line.strip()
        # hex dump continuation
        if hex_target is not None:
            mh = re.match(r"^([0-9a-f]+)\s+((?:[0-9a-f]{2}\s*)+)", body)
            if mh:
                hex_target["value"] = (hex_target.get("value") or "") + " ".join(mh.group(2).split()) + " "
                continue
            hex_target = None
        # supported-pages list inside 0x00
        ms = re.match(r"^(0x[0-9a-fA-F]{2})\s+(.+?)\s*\[[a-z_]+\]$", body)
        if ms and cur.get("page_code") == "0x00":
            cur["supported_pages"].append({"page_code": ms.group(1).lower(),
                                           "page_name": ms.group(2).strip()})
            continue
        # hex-only parameter header e.g. 'Reserved [parameter_code=0x200]:'
        mph = re.match(r"^(Reserved|Vendor specific)(?:\s+\[parameter_code=(0x[0-9a-fA-F]+)\])?:$", body)
        if not mph:
            mph = re.match(r"^(Reserved \[parameter_code=(0x[0-9a-fA-F]+)\]|Vendor specific \[parameter_code=(0x[0-9a-fA-F]+)\]):$", body)
        if not mph:
            mph = re.match(r"^Reserved parameter code \(0x([0-9a-fA-F]+)\), payload in hex$", body)
            if mph:
                code = "0x" + mph.group(1).lower()
                f = {"name": "Reserved " + code, "value": "", "unit": "Hex",
                     "description": "保留参数（原始 hex）"}
                cur["fields"].append(f)
                hex_target = f
                continue
        mpr = re.match(r"^partition number:\s*(\d+), partition record data counter:\s*(\S+)$", body)
        if mpr:
            cur["fields"].append({"name": "Partition %s record data counter" % mpr.group(1),
                                  "value": _logval(mpr.group(2)), "unit": "Counter",
                                  "description": "分区位置/容量计数"})
            continue
        if mph:
            code = "0x" + (mph.group(2) or mph.group(3) or "0").lower()
            f = {"name": "Parameter " + code, "value": "", "unit": "Hex",
                 "description": "保留/厂商专用参数（原始 hex）"}
            cur["fields"].append(f)
            hex_target = f
            continue
        # parameter block inside 0x16: 'Parameter code: 0'
        mpc = re.match(r"^Parameter code:\s*(\d+)$", body)
        if mpc:
            rec = {"parameter_code": int(mpc.group(1)), "fields": []}
            cur["records"].append(rec)
            continue
        # multiple flag tokens on one line: 'PAMR=0 HUI=0 ...' or 'Flag01h: 0  02h: 0'
        toks = re.findall(r"(\w+)=([0-9a-fA-Fx]+)", body)
        flags = re.findall(r"(Flag[0-9A-Fa-f]{2}h):\s*(\d+)", body)
        if len(toks) >= 3 and "=" in body:
            for k, v in toks:
                cur["fields"].append({"name": k, "value": int(v, 16) if v.startswith("0x") else int(v),
                                      "unit": "Flag", "description": "状态标志位"})
            continue
        if len(flags) >= 4:
            for k, v in flags:
                cur["fields"].append({"name": "TapeAlert " + k, "value": int(v),
                                      "unit": "Flag", "description": "TapeAlert 标志",
                                      "health": "warning" if v != "0" else "ok"})
            continue
        # named field forms
        m = re.match(r"^(.+?)\s*=\s*(\S+)$", body)  # name = value
        if not m:
            m = re.match(r"^(.+?):\s+(.+)$", body)     # name: value [unit]
        if m:
            name, val = m.group(1).strip(), m.group(2).strip()
            unit = ""
            mnu = re.match(r"^(.+?)\s*\[([A-Za-z]+)\]$", name)
            if mnu:
                name, unit = mnu.group(1).strip(), mnu.group(2)
            mu = re.match(r"^(\d+(?:\.\d+)?)\s*(GB|MB|ms|milliseconds|hours|m|%)$", val)
            if mu:
                val, unit = mu.group(1), mu.group(2)
            # vendor/reserved specific with code
            mv = re.match(r"^(Reserved or vendor specific|Vendor specific parameter)\s*\[0x([0-9a-fA-F]+)\]?(?:\s+value)?$", name)
            if mv:
                name = "Vendor Specific " + mv.group(2)
            f = _log_field(name, _logval(val), unit)
            # 0x16 record member
            if cur["records"] and line.startswith("    ") and cur["page_code"] == "0x16":
                cur["records"][-1]["fields"].append(f)
                continue
            # health quick rules
            if f["name"] in ("Total write retries", "Total read retries",
                             "Total suspended writes") and f["value"]:
                f["health"] = "warning"
            if f["name"] in ("Hard write errors", "Hard read errors") and f["value"]:
                f["health"] = "warning"
            cur["fields"].append(f)
            continue
        # 0x14 per-density motion hours
        md = re.match(r"^Density code:\s*(0x[0-9a-fA-F]+),\s*Medium type:\s*(0x[0-9a-fA-F]+)$", body)
        if md:
            f = _log_field("Density %s / Medium %s motion" % (md.group(1), md.group(2)), None, "Hours")
            f["_pending"] = True
            cur["fields"].append(f)
            continue
        mm = re.match(r"^Medium motion hours:\s*(\d+)$", body)
        if mm and cur["fields"]:
            for f in reversed(cur["fields"]):
                if f.get("_pending"):
                    f["value"] = int(mm.group(1))
                    del f["_pending"]
                    break
            continue

    # health summary
    summary = []
    for pg in pages:
        bad = [f for f in pg.get("fields", []) if f.get("health") == "warning"]
        if bad:
            summary.append({"page_code": pg["page_code"], "warnings": [f["name"] for f in bad]})
        for rec in pg.get("records", []):
            for f in rec.get("fields", []):
                if f["name"] == "Additional sense" and f["value"]:
                    summary.append({"page_code": pg["page_code"],
                                    "record": rec.get("parameter_code"),
                                    "warnings": [f"{f['name']}: {f['value']}"]})

    parsed = {"device": device, "requested_page": page or "all",
              "log_pages": pages, "health_summary": summary}
    parsed["parsed_ok"] = bool(pages)
    return parsed

def parse_os_release(stdout):
    """/etc/os-release: KEY=value lines."""
    fields = {}
    for line in stdout.splitlines():
        m = re.match(r"([A-Z_]+)=(?:\"([^\"]*)\"|(\S*))", line)
        if m:
            fields[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3)
    return {"name": fields.get("name"), "version": fields.get("version"),
            "version_id": fields.get("version_id"), "id": fields.get("id"),
            "pretty_name": fields.get("pretty_name"), "all_fields": fields,
            "parsed_ok": bool(fields)}


def parse_uname(stdout):
    """uname -a: 'Linux node186 5.14.0-570.12.1.el9_6.x86_64 #1 SMP ... x86_64 x86_64'"""
    parts = stdout.split()
    if len(parts) < 4:
        return {"parsed_ok": False}
    return {"kernel_name": parts[0], "hostname": parts[1], "kernel_release": parts[2],
            "kernel_version": parts[3] if "#" in parts[3] else None,
            "machine": parts[-1], "parsed_ok": True}


def parse_id(stdout):
    """id: 'uid=0(root) gid=0(root) groups=0(root) context=...'"""
    parsed = {"uid": None, "user": None, "gid": None, "group": None, "groups": []}
    m = re.search(r"uid=(\d+)\(([^)]+)\)", stdout)
    if m:
        parsed["uid"], parsed["user"] = int(m.group(1)), m.group(2)
    m = re.search(r"gid=(\d+)\(([^)]+)\)", stdout)
    if m:
        parsed["gid"], parsed["group"] = int(m.group(1)), m.group(2)
    m = re.search(r"groups=(.+)", stdout)
    if m:
        parsed["groups"] = [g.strip() for g in m.group(1).split()]
    parsed["parsed_ok"] = parsed["uid"] is not None
    return parsed


def auto_parse(command, stdout="", stderr="", exit_code=0):
    """Dispatch parser by executable name in the command string (audit endpoint)."""
    if not command:
        return {"parsed_ok": False, "reason": "empty command"}
    cmd = command.split()
    exe = cmd[0].rsplit("/", 1)[-1]
    out = (stdout or "").strip()
    err = (stderr or "").strip()
    try:
        if exe == "sg_inq":
            return parse_sg_inq(out)
        if exe == "sg_vpd":
            return parse_sg_vpd(out)
        if exe == "sg_modes":
            return parse_sg_modes(out)
        if exe == "sg_logs":
            if "0x2e" in command:
                return parse_tapealert(out)
            page = None
            m = re.search(r"-p (0x[0-9a-fA-F]+)", command)
            if m:
                page = m.group(1)
            return parse_sg_logs(out, page)
        if exe == "sg_turs":
            return parse_tur(out, err, exit_code)
        if exe == "sg_scan":
            return parse_sg_scan(out)
        if exe == "sg_map":
            return parse_sg_map(out)
        if exe == "lsscsi":
            return {"devices": [ln.strip() for ln in out.splitlines() if ln.strip()],
                    "parsed_ok": bool(out)}
        if exe == "mtx":
            if " status" in command or " inventory" in command:
                return parse_mtx_status(out)
            if " inquiry" in command:
                return parse_sg_inq(out)
            return {"subcommand": cmd[1] if len(cmd) > 1 else None,
                    "exit_code": exit_code, "parsed_ok": True,
                    "note": "robot action (load/unload/transfer/position): success = exit_code 0"}
        if exe == "mt":
            sub = cmd[2] if len(cmd) > 2 else ""
            if sub == "status":
                return parse_mt_status(out)
            if sub == "compression":
                return parse_mt_compression(out)
            if sub == "weof":
                return {"filemarks_written": "count arg", "parsed_ok": exit_code == 0,
                        "note": "weof success = exit_code 0"}
            return {"operation": sub, "parsed_ok": exit_code == 0,
                    "note": "tape motion command: success = exit_code 0"}
        if exe == "dd":
            return parse_dd_summary(err or out)
        if exe == "lsmod":
            return parse_lsmod(out)
        if exe in ("dmesg", "journalctl"):
            return parse_dmesg_lines(out)
        if exe == "cat" and "os-release" in command:
            return parse_os_release(out)
        if exe == "uname":
            return parse_uname(out)
        if exe == "id":
            return parse_id(out)
        if exe == "hostname":
            return {"hostname": out, "parsed_ok": bool(out)}
        return {"parsed_ok": False, "reason": "no dedicated parser for %s" % exe}
    except Exception as exc:  # parsers must never break audit responses
        return {"parsed_ok": False, "reason": "parser error: %s" % exc}


def parse_tapealert(stdout):
    """sg_logs -p 0x2e TapeAlert output: full flag matrix.
    Each line: ' Read warning: 0'. Value 0 = not triggered, 1 = triggered (bool flag),
    some counters may exceed 1. Severity per SSC spec: critical flags (hard error,
    failures) = CRITICAL, warnings = WARNING, informational = INFO.
    """
    _CRITICAL = {"hard error", "read failure", "write failure",
                 "unrecoverable mechanical cartridge failure",
                 "memory chip in cartridge failure", "hardware a", "hardware b",
                 "interface", "power supply failure", "firmware failure",
                 "worm medium - integrity check failed"}
    flags, triggered = [], []
    device = None
    page = None
    for line in stdout.splitlines():
        m = re.match(r"\s*(.+?):\s*(\d+)\s*$", line)
        if m:
            name, value = m.group(1).strip(), int(m.group(2))
            severity = "CRITICAL" if name.lower() in _CRITICAL else "WARNING"
            entry = {"name": name, "value": value, "severity": severity,
                     "triggered": value != 0}
            flags.append(entry)
            if value != 0:
                triggered.append(entry)
            continue
        if not device and re.match(r"\s*IBM\s+\S+", line):
            device = line.strip()
        if page is None and re.search(r"Tape alert page", line, re.I):
            page = line.strip()
    return {"device": device, "page": page,
            "flags": flags,
            "total_flags": len(flags),
            "triggered_alerts": triggered,
            "triggered_count": len(triggered),
            "all_clear": len(triggered) == 0,
            "parsed_ok": bool(flags)}


def parse_tur(stdout, stderr, exit_code):
    """sg_turs: usually empty output; ready implied by exit code."""
    return {"ready": exit_code == 0, "stdout_text": stdout.strip(),
            "stderr_text": stderr.strip(), "parsed_ok": True}


def parse_dd_summary(stderr):
    """dd stderr summary:
    '1048576+0 records in\n1048576+0 records out\n1073741824 bytes (1.1 GB, 1.0 GiB) copied, 4.4 s, 243 MB/s'
    """
    parsed = {"bytes": None, "bytes_human": None, "seconds": None,
              "throughput": None, "records_in": None, "records_out": None}
    m = re.search(r"(\d+)\+(\d+) records in", stderr)
    if m:
        parsed["records_in"] = int(m.group(1)) + int(m.group(2))
    m = re.search(r"(\d+)\+(\d+) records out", stderr)
    if m:
        parsed["records_out"] = int(m.group(1)) + int(m.group(2))
    m = re.search(r"(\d+) bytes \(([^)]+)\) copied, ([\d.]+) s, ([\d.]+ [kMG]B/s)", stderr)
    if m:
        parsed["bytes"] = int(m.group(1))
        parsed["bytes_human"] = m.group(2)
        parsed["seconds"] = float(m.group(3))
        parsed["throughput"] = m.group(4)
    parsed["parsed_ok"] = parsed["bytes"] is not None or parsed["records_out"] is not None
    return parsed


def parse_dmesg_lines(stdout):
    """dmesg/journalctl kernel log: split to line array (latest last)."""
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    tape_related = [ln for ln in lines if re.search(r"st\d|sg\d|tape|changer|lin_tape|scsi", ln, re.I)]
    return {"total_lines": len(lines), "tape_related_lines": len(tape_related),
            "tape_related_tail": tape_related[-20:], "parsed_ok": True}


def parse_lsmod(stdout):
    """lsmod: 'module size used_by' per line."""
    modules = []
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] != "Module":
            modules.append({"module": parts[0], "size": int(parts[1]) if parts[1].isdigit() else parts[1],
                            "used_by": int(parts[2]) if parts[2].isdigit() else parts[2]})
    return {"modules": modules, "parsed_ok": bool(modules)}


def parse_dmesg_device_map(stdout):
    """Extract sg <-> st/ch <-> scsi address <-> type mapping from dmesg."""
    import re as _re
    sg_by_addr, blk_by_addr = {}, {}
    for line in stdout.splitlines():
        m = _re.search(r"\b(\d+:\d+:\d+:\d+): Attached scsi generic (sg\d+) type (\d+)", line)
        if m:
            sg_by_addr[m.group(1)] = (m.group(2), int(m.group(3)))
        m = _re.search(r"\b(\d+:\d+:\d+:\d+): Attached scsi (tape|changer) ((?:st|ch)\d+)", line)
        if m:
            blk_by_addr.setdefault(m.group(1), m.group(3))
    TYPE_NAME = {1: "Tape Drive", 8: "Medium Changer"}
    entries = []
    for addr, (sgn, tcode) in sg_by_addr.items():
        entries.append({"sg_device": sgn, "block_device": blk_by_addr.get(addr),
                        "scsi_address": addr,
                        "device_type": TYPE_NAME.get(tcode, "Unknown (type %d)" % tcode)})
    entries.sort(key=lambda e: int(e["sg_device"][2:]))
    return entries


def parse_lsscsi_g_entries(stdout):
    """Parse `lsscsi -g` lines into structured entries.
    Line: [33:0:0:0]  tape    IBM      ULT3580-TDA      T3S0  /dev/st0   /dev/sg0
    """
    import re as _re
    entries = []
    for line in stdout.splitlines():
        m = _re.match(r"^\[(\d+:\d+:\d+:\d+)\]\s+(\S+)\s+(\S+)\s+(\S.*?)\s+(\S+)\s+(/dev/\S+)\s+(/dev/sg\d+)$", line.strip())
        if m:
            addr, tword, vendor, model, rev, blk, sg = m.groups()
            entries.append({"scsi_address": addr, "type_word": tword,
                            "vendor": vendor, "model": model.strip(),
                            "firmware": rev, "block_device": blk, "sg_device": sg})
    return entries
