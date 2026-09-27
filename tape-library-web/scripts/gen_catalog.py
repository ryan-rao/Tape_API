#!/usr/bin/env python3
# 从 openapi.json 生成 src/api/catalog.ts（API Playground 数据源）
import json
import re
import sys

SRC = 'openapi.json'
DST = 'src/api/catalog.ts'

GROUP_LABELS = [
    ('Meta', 'Meta 元信息'),
    ('System', 'System 系统'),
    ('Dependencies', 'Deps 依赖'),
    ('Discovery', 'Discovery 设备发现'),
    ('SCSI', 'SCSI 诊断'),
    ('Library', 'Library 带库'),
    ('Inventory', 'Inventory 清单'),
    ('Drive', 'Drive 带机'),
    ('Diagnostics', 'Diag 诊断'),
    ('Tests', 'Tests 读写测试'),
    ('Jobs', 'Jobs 任务'),
    ('Audit', 'Audit 审计'),
    ('Archive', 'Archive 归档网关'),
]
HIDDEN = set()  # upload/download 已支持 multipart/二进制，全部放开

# 端点中文摘要覆盖（重新生成时保持）
SUMMARY_OVERRIDES = {
    '/api/v1/archive/upload': '① 上传到指定目录(dir=)',
    '/api/v1/archive/files': '② 文件列表查询(name/state过滤)',
    '/api/v1/archive/files/{file_id}': '② 文件详情(位置/磁带/容器)',
    '/api/v1/archive/files/{file_id}/archive': '③ 手动归档(封箱→落带)',
    '/api/v1/archive/files/{file_id}/recall': '④ 召回(热同步/冷202异步, dir=)',
    '/api/v1/archive/files/{file_id}/download': '⑤ 下载文件流(二进制落盘)',
    '/api/v1/libraries/{changer}/load': '装带：barcode+drive_sn(带机序列号)，动作前双状态检查',
    '/api/v1/libraries/{changer}/unload': '卸带：barcode+slot(目标槽)，动作前状态检查',
    '/api/v1/libraries/{changer}/slots/list': '槽位清单：位置/占用/条码+介质台账(过滤分页)',
    '/api/v1/archive/tree': '缓存目录树(含封箱虚拟节点)',
    '/api/v1/archive/cache': '缓存明细(递归分目录)',
    '/api/v1/archive/tasks': '后台任务列表(flusher/归档)',
    '/api/v1/archive/gw-config': '网关预配置：读=全貌+pending_diff；写=存文件层(>env)，apply=true 立即重启生效',
    '/api/v1/archive/gw-config/apply': '按已存 gw-config 原地重启网关(有 running job 则 409)',
}
# 按方法区分的摘要（优先于 SUMMARY_OVERRIDES）：同路径 GET/POST 变体语义不同时用
METHOD_SUMMARY_OVERRIDES = {
    'GET /api/v1/archive/gw-config': '读取 config：运行值/文件层/重启后预览+pending_diff(网关未运行也可查)',
    'POST /api/v1/archive/gw-config': '设置 config：存 gateway-config.json(文件层>env，confirm 必需)，apply=true 写后立即重启生效',
}
ARCHIVE_L2 = {'/api/v1/archive/files/{file_id}/archive',
              '/api/v1/archive/files/{file_id}/recall',
              '/api/v1/archive/upload',
              '/api/v1/archive/containers/{container_id}/seal',
              '/api/v1/archive/containers/{container_id}/retry',
              '/api/v1/archive/evict',
              '/api/v1/archive/selfheal',
              '/api/v1/archive/media',
              '/api/v1/archive/gw-config',
              '/api/v1/archive/gw-config/apply'}
# 请求体示例覆盖：机器人操作（v1.2 推荐 barcode+drive_sn / barcode+slot；旧 slot/drive/*_position 仍兼容）
BODY_DEFAULT_OVERRIDES = {
    '/api/v1/libraries/{changer}/load':
        '{"confirm": true, "barcode": "IBM006LA", "drive_sn": "607B811E03"}',
    '/api/v1/libraries/{changer}/unload':
        '{"confirm": true, "barcode": "IBM015LA", "slot": 7}',
    '/api/v1/archive/gw-config':
        '{"confirm": true, "apply": false, "small_file_mb": 64, "container_target_mb": 1024, "cache_quota_gb": 200, "watermarks_pct": [70, 85], "drive": "/dev/nst1", "changer": "/dev/sg1", "dte_map": {"0": "/dev/nst0", "2": "/dev/nst1"}, "auto_load": true}',
    '/api/v1/archive/gw-config/apply':
        '{"confirm": true}',
}
KNOWN_ASYNC = ('/dependencies/install', '/libraries/', '/write', '/read',
               '/tests/', '/erase', '/robot/', '/scsi/', '/drives/',
               '/position', '/seek', '/retension', '/eod', '/seod',
               '/offline', '/rewoffl', '/eject', '/lock', '/unlock',
               '/compression', '/block-size', '/density', '/partition',
               '/recall')
SYNC_EXCEPTIONS = ('/drives/{d}/rewind', '/drives/{d}/offline', '/drives/{d}/rewoffl',
                   '/drives/{d}/eject', '/drives/{d}/load', '/drives/{d}/lock',
                   '/drives/{d}/unlock', '/drives/{d}/compression',
                   '/drives/{d}/block-size', '/drives/{d}/density',
                   '/drives/{d}/partition', '/scsi/{device}/reset',
                   '/api/v1/archive/files/{file_id}/recall')
PATH_DEFAULT_VALUES = {
    'changer': 'sg1', 'ch': 'sg1', 'sg': 'sg2', 'device': 'sg2',
    'd': 'nst1', 'nst': 'nst1', 'name': 'mt-st',
    # 演示实体（186 实例）：五步全链路 demo 文件 + 已封箱容器
    'file_id': '7192fa6a-e7b2-4200-bc3a-2f924d00aff5',
    'container_id': '11c0f998-335d-4146-bdd0-e17572942d66',
}


def resolve(spec, schema):
    if not isinstance(schema, dict):
        return {}
    if '$ref' in schema:
        ref = schema['$ref'].split('/')[-1]
        return spec.get('components', {}).get('schemas', {}).get(ref, {})
    return schema


def props_of_body(spec, op):
    rb = op.get('requestBody', {})
    if not rb:
        return {}
    content = rb.get('content', {})
    for ct in ('application/json',):
        if ct in content:
            sch = resolve(spec, content[ct].get('schema', {}))
            return sch.get('properties', {})
    for ct, c in content.items():
        sch = resolve(spec, c.get('schema', {}))
        return sch.get('properties', {})
    return {}


def main():
    spec = json.load(open(SRC, encoding='utf-8'))
    seen_groups, endpoints = [], []
    for p, ms in sorted(spec['paths'].items()):
        for m in ('get', 'post'):
            if m not in ms:
                continue
            op = ms[m]
            tag = (op.get('tags') or ['Other'])[0]
            if tag not in [g[0] for g in GROUP_LABELS]:
                continue
            if tag not in seen_groups:
                seen_groups.append(tag)
            desc = (op.get('description') or '') + ' ' + (op.get('summary') or '')
            bprops = props_of_body(spec, op)
            params = []
            body_default = None
            for prm in op.get('parameters', []):
                if prm.get('in') in ('path', 'query'):
                    params.append({
                        'name': prm['name'], 'in': prm['in'],
                        'required': bool(prm.get('required')),
                        'default': (prm.get('schema') or {}).get('default'),
                    })
            if bprops:
                sample = {}
                for k in bprops:
                    if k == 'confirm':
                        sample[k] = True
                    elif k == 'allow_write':
                        sample[k] = True
                    elif 'default' in bprops[k]:
                        sample[k] = bprops[k]['default']
                if p in BODY_DEFAULT_OVERRIDES:
                    body_default = BODY_DEFAULT_OVERRIDES[p]
                elif sample:
                    body_default = json.dumps(sample, ensure_ascii=False)
            lvl = '-'
            if m == 'get' and p in ARCHIVE_L2:
                # 路径白名单命中时 GET 变体不应被误标 L2（只读）
                lvl = 'L1'
            elif 'LEVEL_3' in desc or 'L3' in desc:
                lvl = 'L3'
            elif 'LEVEL_2' in desc or 'L2' in desc or p in ARCHIVE_L2:
                lvl = 'L2'
            is_async = False
            if any(p.endswith(sfx) or sfx in p for sfx in KNOWN_ASYNC):
                is_async = True
            if p in SYNC_EXCEPTIONS:
                is_async = False
            if m == 'get':
                is_async = False
            eid = re.sub(r'[^a-z0-9]+', '-', ('%s %s' % (m, p)).lower()).strip('-')
            eid = re.sub(r'-([a-z])-([a-z])-', r'-\1\2-', eid)
            endpoints.append({
                'id': eid, 'group': tag, 'method': m.upper(), 'path': p,
                'summary': METHOD_SUMMARY_OVERRIDES.get('%s %s' % (m.upper(), p))
                    or SUMMARY_OVERRIDES.get(p) or (op.get('summary') or '')[:60],
                'level': lvl, 'async': is_async,
                'hidden': p in HIDDEN,
                'params': params,
                'hasBody': bool(bprops),
                'bodyDefault': body_default,
            })

    order = {g[0]: i for i, g in enumerate(GROUP_LABELS)}
    endpoints.sort(key=lambda e: (order[e['group']], e['path'], e['method']))
    groups = [g for g in GROUP_LABELS if g[0] in seen_groups]

    def js(v):
        return json.dumps(v, ensure_ascii=False)

    out = []
    out.append('// 自动生成：scripts/gen_catalog.py <- openapi.json（勿手改；重新生成即可）')
    out.append('// eslint-disable-next-line @typescript-eslint/no-explicit-any')
    out.append("export type AnyObj = Record<string, any>;")
    out.append('')
    out.append('export interface EndpointParam {')
    out.append('  name: string;')
    out.append("  in: 'path' | 'query';")
    out.append('  required?: boolean;')
    out.append('  default?: unknown;')
    out.append('}')
    out.append('')
    out.append('export interface Endpoint {')
    out.append('  id: string;')
    out.append('  group: string;')
    out.append("  method: 'GET' | 'POST';")
    out.append('  path: string;')
    out.append('  summary: string;')
    out.append("  level: 'L1' | 'L2' | 'L3' | '-';")
    out.append('  isAsync?: boolean;')
    out.append('  hidden?: boolean;')
    out.append('  params: EndpointParam[];')
    out.append('  hasBody?: boolean;')
    out.append('  bodyDefault?: string | null;')
    out.append('}')
    out.append('')
    out.append('export const GROUPS: { key: string; label: string }[] = [')
    for k, label in groups:
        out.append('  { key: %s, label: %s },' % (js(k), js(label)))
    out.append('];')
    out.append('')
    out.append('export const CATALOG: Endpoint[] = [')
    for e in endpoints:
        out.append('  {')
        out.append("    id: %s, group: %s, method: '%s', path: %s," % (
            js(e['id']), js(e['group']), e['method'], js(e['path'])))
        out.append('    summary: %s, level: %s,' % (js(e['summary']), js(e['level'])))
        extra = []
        if e['async']:
            extra.append('isAsync: true')
        if e['hidden']:
            extra.append('hidden: true')
        if e['hasBody']:
            extra.append('hasBody: true')
        if e['bodyDefault']:
            extra.append('bodyDefault: %s' % js(e['bodyDefault']))
        if extra:
            out.append('    %s,' % ', '.join(extra))
        out.append('    params: %s,' % js(e['params']))
        out.append('  },')
    out.append('];')
    out.append('')
    path_params = sorted({p['name'] for e in endpoints for p in e['params'] if p['in'] == 'path'})
    out.append('export const PATH_DEFAULTS: Record<string, string> = {')
    for name in path_params:
        out.append('  %s: %s,' % (js(name), js(PATH_DEFAULT_VALUES.get(name, ''))))
    out.append('};')
    open(DST, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print('groups:', len(groups), 'endpoints:', len(endpoints),
          'hidden:', sum(1 for e in endpoints if e['hidden']),
          'async:', sum(1 for e in endpoints if e['async']))


if __name__ == '__main__':
    sys.exit(main())
