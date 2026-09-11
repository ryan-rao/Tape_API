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
  it('装载 IBM015LA（槽6）到 Drive 0', async () => {
    const r = await mockApi.load(CH, 6, 0);
    expect(r.code).toBe('LOAD_SUCCESS');
    expect(r.data.tape).toBe('IBM015LA');
    const st = await mockApi.libraryStatus(CH);
    expect(st.data.loaded_drives).toBe(1);
    expect(st.data.slots.find((s: any) => s.slot === 6).barcode).toBeNull();
  });

  it('重复装载同带机 → MEDIA_ALREADY_LOADED', async () => {
    const r = await mockApi.load(CH, 1, 0);
    expect(r.success).toBe(false);
    expect(r.code).toBe('MEDIA_ALREADY_LOADED');
  });

  it('装载空槽 → MEDIA_NOT_FOUND', async () => {
    const r = await mockApi.load(CH, 6, 1);
    expect(r.code).toBe('MEDIA_NOT_FOUND');
  });

  it('卸载回槽 6', async () => {
    const r = await mockApi.unload(CH, 6, 0);
    expect(r.code).toBe('UNLOAD_SUCCESS');
    const st = await mockApi.libraryStatus(CH);
    expect(st.data.slots.find((s: any) => s.slot === 6).barcode).toBe('IBM015LA');
    expect(st.data.loaded_drives).toBe(0);
  });

  it('卸载空带机 → MEDIA_NOT_FOUND', async () => {
    const r = await mockApi.unload(CH, 6, 0);
    expect(r.code).toBe('MEDIA_NOT_FOUND');
  });

  it('无效槽位 → INVALID_SLOT', async () => {
    const r = await mockApi.load(CH, 99, 0);
    expect(r.code).toBe('INVALID_SLOT');
  });
});

describe('写测试安全控制', () => {
  it('Barcode 不匹配 → TEST_MEDIA_REQUIRED', async () => {
    await mockApi.load(CH, 6, 0); // 装入 IBM015LA
    const r = await mockApi.runTest('write-verify', '/dev/nst1', 64, 'IBM015LA', 'WRONG-BARCODE');
    expect(r.success).toBe(false);
    expect(r.code).toBe('TEST_MEDIA_REQUIRED');
    await mockApi.unload(CH, 6, 0);
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
    await mockApi.load(CH, 1, 0);
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
    await mockApi.unload(CH, 1, 0);
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
