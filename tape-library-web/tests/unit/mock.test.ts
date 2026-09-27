import { describe, it, expect } from 'vitest';
import { mockApi, tickSessions } from '../../src/api/mock';
import { friendlyError } from '../../src/api/client';
import type { ApiResponse } from '../../src/types';

const CH = 'sg1';

describe('Mock 带库：状态与发现', () => {
  it('列出带库', async () => {
    const r = await mockApi.listLibraries();
    expect(r.success).toBe(true);
    expect(r.data[0].changer).toBe('sg1');
    expect(r.data[0].slot_count).toBe(12);
  });

  it('库状态含槽位与带机', async () => {
    const r = await mockApi.libraryStatus(CH);
    expect(r.success).toBe(true);
    expect(r.data.slots.length).toBe(12);
    expect(r.data.drives.length).toBe(2);
  });

  it('库存清单返回卷列表', async () => {
    const r = await mockApi.libraryInventory(CH);
    expect(r.success).toBe(true);
    expect(r.data.volumes.length).toBe(9);
    expect(r.data.volumes[0].barcode).toBe('IBM006LA');
  });
});

describe('Mount / Unmount 状态机', () => {
  it('装载 IBM015LA（槽6）到 Drive 0（旧字段 slot/drive 兼容）', async () => {
    const r = await mockApi.load(CH, { slot: 6, drive: 0 });
    expect(r.code).toBe('LOAD_SUCCESS');
    expect(r.data.barcode).toBe('IBM015LA');
    expect(r.data.resolved.drive).toBe('DTE0');
    const st = await mockApi.libraryStatus(CH);
    expect(st.data.loaded_drives).toBe(1);
    expect(st.data.slots.find((s: any) => s.slot === 6).barcode).toBeNull();
  });

  it('重复装载同带机 → MEDIA_ALREADY_LOADED', async () => {
    const r = await mockApi.load(CH, { slot: 1, drive: 0 });
    expect(r.success).toBe(false);
    expect(r.code).toBe('MEDIA_ALREADY_LOADED');
  });

  it('装载空槽 → SLOT_EMPTY', async () => {
    const r = await mockApi.load(CH, { slot: 6, drive: 1 });
    expect(r.code).toBe('SLOT_EMPTY');
  });

  it('卸载回槽 6', async () => {
    const r = await mockApi.unload(CH, { slot: 6, drive: 0 });
    expect(r.code).toBe('UNLOAD_SUCCESS');
    const st = await mockApi.libraryStatus(CH);
    expect(st.data.slots.find((s: any) => s.slot === 6).barcode).toBe('IBM015LA');
    expect(st.data.loaded_drives).toBe(0);
  });

  it('卸载空带机 → DRIVE_EMPTY', async () => {
    const r = await mockApi.unload(CH, { slot: 6, drive: 0 });
    expect(r.code).toBe('DRIVE_EMPTY');
  });

  it('无效槽位 → INVALID_SLOT', async () => {
    const r = await mockApi.load(CH, { slot: 99, drive: 0 });
    expect(r.code).toBe('INVALID_SLOT');
  });
});

describe('位置参数（barcode / tape_position / drive_position）', () => {
  it('barcode 自动定位槽位 + nst1 设备名定位带机', async () => {
    const r = await mockApi.load(CH, { barcode: 'IBM015LA', drive_position: 'nst1' });
    expect(r.code).toBe('LOAD_SUCCESS');
    expect(r.data.resolved.tape_method).toBe('barcode_lookup');
    expect(r.data.resolved.drive_method).toBe('device_name');
    expect(r.data.resolved.drive).toBe('DTE0');
    expect(r.data.resolved.mtx_command).toContain('load');
  });

  it('drive_position 回卸 + tape_position=S006 显式目标槽', async () => {
    const r = await mockApi.unload(CH, { drive_position: 'nst1', tape_position: 'S006' });
    expect(r.code).toBe('UNLOAD_SUCCESS');
    expect(r.data.resolved.target_method).toBe('tape_position');
    expect(r.data.resolved.target).toBe('S006');
  });

  it('tape_position=S006 + Drive-01(1基序号) 再装载', async () => {
    const r = await mockApi.load(CH, { tape_position: 'S006', drive_position: 'Drive-01' });
    expect(r.code).toBe('LOAD_SUCCESS');
    expect(r.data.resolved.tape).toBe('S006');
    expect(r.data.resolved.tape_method).toBe('tape_position');
    await mockApi.unload(CH, { drive: 0, slot: 6 });
  });

  it('目标槽被占 → SLOT_OCCUPIED', async () => {
    await mockApi.load(CH, { barcode: 'IBM015LA', drive_position: 'nst1' });
    const r = await mockApi.unload(CH, { drive_position: 'nst1', slot: 1 });
    expect(r.code).toBe('SLOT_OCCUPIED');
    await mockApi.unload(CH, { drive: 0, slot: 6 });
  });

  it('无法解释的 drive_position → DRIVE_NOT_FOUND', async () => {
    const r = await mockApi.load(CH, { slot: 6, drive_position: 'xx9' });
    expect(r.code).toBe('DRIVE_NOT_FOUND');
  });

  it('缺全部定位参数 → INVALID_REQUEST', async () => {
    const r = await mockApi.load(CH, {});
    expect(r.code).toBe('INVALID_REQUEST');
    const u = await mockApi.unload(CH, {});
    expect(u.code).toBe('INVALID_REQUEST');
  });
});

describe('v1.2 参数（drive_sn / barcode+slot / 动作前状态检查 / slots 聚合）', () => {
  it('load barcode+drive_sn 成功，checks.* 回显双状态检查', async () => {
    const r = await mockApi.load(CH, { barcode: 'IBM015LA', drive_sn: '78P0123' });
    expect(r.code).toBe('LOAD_SUCCESS');
    expect(r.data.resolved.drive_method).toBe('drive_sn');
    expect(r.data.checks.tape).toMatchObject({ barcode: 'IBM015LA', state: 'in_slot', position: 'S006' });
    expect(r.data.checks.drive).toMatchObject({ serial: '78P0123', nst: 'nst1', dte: 0, state: 'ready' });
    // unload barcode+slot 回原槽
    const u = await mockApi.unload(CH, { barcode: 'IBM015LA', slot: 6 });
    expect(u.code).toBe('UNLOAD_SUCCESS');
    expect(u.data.checks.tape).toMatchObject({ barcode: 'IBM015LA', state: 'in_drive', dte: 0 });
    expect(u.data.checks.slot).toMatchObject({ position: 'S006', state: 'empty', method: 'slot' });
  });

  it('drive_sn 不存在 → DRIVE_NOT_FOUND（未动磁带）', async () => {
    const r = await mockApi.load(CH, { barcode: 'IBM006LA', drive_sn: 'BOGUS0000' });
    expect(r.code).toBe('DRIVE_NOT_FOUND');
    expect(r.message).toContain('78P0123'); // 拦截消息附已知 SN 列表
  });

  it('load 磁带已在带机 → MEDIA_IN_DRIVE', async () => {
    await mockApi.load(CH, { barcode: 'IBM015LA', drive_sn: '78P0123' });
    const r = await mockApi.load(CH, { barcode: 'IBM015LA', drive_sn: '78P0456' });
    expect(r.code).toBe('MEDIA_IN_DRIVE');
    await mockApi.unload(CH, { barcode: 'IBM015LA', slot: 6 });
  });

  it('unload 磁带在槽不在机 → MEDIA_NOT_IN_DRIVE', async () => {
    const r = await mockApi.unload(CH, { barcode: 'IBM006LA', slot: 10 });
    expect(r.code).toBe('MEDIA_NOT_IN_DRIVE');
  });

  it('unload 目标槽被占 → SLOT_OCCUPIED（不卸带）', async () => {
    await mockApi.load(CH, { barcode: 'IBM015LA', drive_sn: '78P0123' });
    const r = await mockApi.unload(CH, { barcode: 'IBM015LA', slot: 1 }); // S001=IBM006LA
    expect(r.code).toBe('SLOT_OCCUPIED');
    const st = await mockApi.libraryStatus(CH);
    expect(st.data.loaded_drives).toBe(1); // 仍在带机
    await mockApi.unload(CH, { barcode: 'IBM015LA', slot: 6 });
  });

  it('load 不存在的条码 → MEDIA_NOT_FOUND', async () => {
    const r = await mockApi.load(CH, { barcode: 'ZZZ999ZZ', drive_sn: '78P0123' });
    expect(r.code).toBe('MEDIA_NOT_FOUND');
  });

  it('slotsList 聚合：占用过滤 / 条码过滤 / summary', async () => {
    const r = await mockApi.slotsList(CH, { occupied_only: true });
    expect(r.success).toBe(true);
    expect(r.data.summary.slots_total).toBe(12);
    expect(r.data.summary.occupied).toBe(9);
    expect(r.data.slots.every((s: any) => s.occupied && s.barcode)).toBe(true);
    const row = r.data.slots.find((s: any) => s.barcode === 'IBM015LA');
    expect(row.position).toBe('S006');
    expect(row.media.registered).toBe(true);
    const f = await mockApi.slotsList(CH, { barcode: 'ibm006la' }); // 大小写不敏感
    expect(f.data.slots.length).toBe(1);
    expect(f.data.slots[0].position).toBe('S001');
    const pg = await mockApi.slotsList(CH, { limit: 3 });
    expect(pg.data.slots.length).toBe(3);
    expect(pg.data.summary.total_filtered).toBe(12);
  });
});

describe('写测试安全控制', () => {
  it('Barcode 不匹配 → TEST_MEDIA_REQUIRED', async () => {
    await mockApi.load(CH, { slot: 6, drive: 0 }); // 装入 IBM015LA
    const r = await mockApi.runTest('write-verify', '/dev/nst1', 64, 'IBM015LA', 'WRONG-BARCODE');
    expect(r.success).toBe(false);
    expect(r.code).toBe('TEST_MEDIA_REQUIRED');
    await mockApi.unload(CH, { slot: 6, drive: 0 });
  });

  it('read 测试创建会话并推进到 PASS', async () => {
    const r = await mockApi.runTest('read', '/dev/nst1', 256);
    expect(r.code).toBe('TEST_STARTED');
    const sid = r.data.session_id;
    // 模拟时间推进（mock 256MiB @ ~270MiB/s ≈ 1s）
    for (let i = 0; i < 5; i++) tickSessions();
    const g = await mockApi.getSession(sid);
    expect(['RUNNING', 'PASS']).toContain(g.data.status);
    expect(g.data.progress).toBeGreaterThan(0);
  });

  it('未知会话 → NOT_FOUND', async () => {
    const r = await mockApi.getSession('TL-MOCK-999');
    expect(r.code).toBe('NOT_FOUND');
  });
});

describe('审计链', () => {
  it('操作产生审计记录与 request_id', async () => {
    await mockApi.load(CH, { slot: 1, drive: 0 });
    const a = await mockApi.auditList();
    expect(a.data.length).toBeGreaterThan(0);
    const rec: any = a.data[0];
    expect(rec.command_id).toMatch(/^CMD-MOCK-/);
    expect(rec.request_id).toMatch(/^REQ-MOCK-/);
    const ops = await mockApi.operations();
    expect(ops.data[0].operation).toBe('Mount');
    expect(ops.data[0].request_id).toMatch(/^REQ-MOCK-/);
    const cmd = await mockApi.command(rec.command_id);
    expect(cmd.data.stdout).toContain('mtx');
    await mockApi.unload(CH, { slot: 1, drive: 0 });
  });
});

describe('错误码友好提示', () => {
  it('DEVICE_NOT_FOUND 映射', () => {
    const f = friendlyError({ success: false, code: 'DEVICE_NOT_FOUND', message: 'x' } as ApiResponse);
    expect(f.title).toBe('Device Not Found');
  });
  it('WRITE_NOT_ALLOWED 映射', () => {
    const f = friendlyError({ success: false, code: 'WRITE_NOT_ALLOWED', message: 'x' } as ApiResponse);
    expect(f.title).toBe('Write Not Allowed');
  });
  it('未知错误回退 message', () => {
    const f = friendlyError({ success: false, code: 'WEIRD', message: 'boom' } as ApiResponse);
    expect(f.detail).toBe('boom');
  });
});
