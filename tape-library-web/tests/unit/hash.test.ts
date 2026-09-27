import { describe, expect, it } from 'vitest';
import { sha256Pure, hasWebCrypto } from '../../src/utils/hash';

// NIST 标准测试向量（与 WebCrypto 结果对拍）
const vectors: [string, string][] = [
  ['', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'],
  ['abc', 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'],
  ['abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq',
    '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1'],
];

const enc = (s: string) => new TextEncoder().encode(s);

describe('sha256Pure（非安全上下文回退实现）', () => {
  it('命中 NIST 标准向量', () => {
    for (const [msg, want] of vectors) expect(sha256Pure(enc(msg))).toBe(want);
  });
  it('跨分块边界（55/56/64/65/119/120 字节填充分支）', () => {
    for (const n of [55, 56, 63, 64, 65, 119, 120, 128]) {
      const got = sha256Pure(new Uint8Array(n)); // 全零
      expect(got).toMatch(/^[0-9a-f]{64}$/);
    }
    // 56 字节全零向量单独对拍（Node crypto 实算）
    expect(sha256Pure(new Uint8Array(56))).toBe(
      'd4817aa5497628e7c77e6b606107042bbba3130888c5f47a375e6179be789fbb',
    );
  });
  it('与原生 WebCrypto 结果一致（Node 18+ subtle 可用）', async () => {
    expect(hasWebCrypto()).toBe(true);
    for (const data of [enc(''), enc('x'.repeat(1024)), new Uint8Array(100 * 1024)]) {
      const h = await crypto.subtle.digest('SHA-256', data as unknown as ArrayBuffer);
      expect(sha256Pure(data)).toBe(
        Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, '0')).join(''),
      );
    }
  });
});
