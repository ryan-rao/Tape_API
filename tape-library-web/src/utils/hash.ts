// SHA-256 纯 TS 实现 + WebCrypto 优先封装。
// 背景：WebCrypto 的 crypto.subtle 只在安全上下文（HTTPS / localhost）暴露；
// 通过 http://172.16.12.186:8080 这类明文地址访问时 crypto.subtle 为 undefined，
// 直接调用会抛 "Cannot read properties of undefined (reading 'digest')"（2026-09-20 场景 F 中断根因）。
// crypto.getRandomValues 不受此限制，各上下文均可用。

const K = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

const rotr = (x: number, n: number) => (x >>> n) | (x << (32 - n));

/** 纯 JS SHA-256，返回小写 hex。输入任意字节。 */
export function sha256Pure(input: ArrayBuffer | Uint8Array): string {
  const msg = input instanceof Uint8Array ? input : new Uint8Array(input);
  const len = msg.length;
  // 填充：消息 + 0x80 + 补零 + 64bit 比特长度
  const bitLen = len * 8;
  const padLen = ((len + 8) >> 6) + 1; // 总块数
  const buf = new Uint8Array(padLen * 64);
  buf.set(msg);
  buf[len] = 0x80;
  const dv = new DataView(buf.buffer);
  dv.setUint32(padLen * 64 - 4, bitLen >>> 0);
  dv.setUint32(padLen * 64 - 8, Math.floor(bitLen / 4294967296));

  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
  const w = new Uint32Array(64);

  for (let blk = 0; blk < padLen; blk++) {
    const off = blk * 64;
    for (let i = 0; i < 16; i++) w[i] = dv.getUint32(off + i * 4);
    for (let i = 16; i < 64; i++) {
      const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;
    for (let i = 0; i < 64; i++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[i] + w[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      h = g; g = f; f = e; e = (d + t1) >>> 0;
      d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0;
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0;
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7].map((x) => x.toString(16).padStart(8, '0')).join('');
}

/** 是否走原生 WebCrypto（安全上下文才为 true，用于 UI 提示实现来源）。 */
export function hasWebCrypto(): boolean {
  return typeof crypto !== 'undefined' && !!crypto.subtle && typeof crypto.subtle.digest === 'function';
}

/** 归一化为自有 ArrayBuffer（TS 5.7+ BufferSource 收紧，SharedArrayBuffer 不再兼容）。 */
function toArrayBuffer(input: ArrayBuffer | Uint8Array): ArrayBuffer {
  if (input instanceof Uint8Array) return input.slice().buffer as ArrayBuffer;
  return input;
}

/**
 * SHA-256 hex：安全上下文优先 WebCrypto；HTTP 明文访问（crypto.subtle 不可用）自动回退纯 JS。
 * 两者结果一致（有单测对拍），回退不影响校验正确性。
 */
export async function sha256Hex(buf: ArrayBuffer | Uint8Array): Promise<string> {
  if (hasWebCrypto()) {
    try {
      const h = await crypto.subtle.digest('SHA-256', toArrayBuffer(buf));
      return Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, '0')).join('');
    } catch {
      /* 极端环境 subtle 存在但调用失败，同样回退 */
    }
  }
  return sha256Pure(buf);
}

/** 填充随机字节：getRandomValues 各上下文均可用；仅极端缺失时回退 Math.random。 */
export function fillRandom(bytes: Uint8Array): void {
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    for (let off = 0; off < bytes.length; off += 65536) {
      crypto.getRandomValues(bytes.subarray(off, Math.min(off + 65536, bytes.length)));
    }
    return;
  }
  for (let i = 0; i < bytes.length; i++) bytes[i] = (Math.random() * 256) | 0;
}
