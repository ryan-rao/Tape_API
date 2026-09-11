import { chromium } from '@playwright/test';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 200)));

const t0 = Date.now();
const done: string[] = [];
page.on('requestfinished', (r) => {
  try {
    const len = r.response()?.headers()['content-length'] || '-';
    done.push(`+${String(Date.now()-t0).padStart(6)}ms ${r.resourceType().padEnd(8)} ${String(len).padStart(9)}B ${r.url().slice(0, 85)}`);
  } catch {}
});
page.on('requestfailed', (r) => done.push(`+${String(Date.now()-t0).padStart(6)}ms FAILED  ${r.url().slice(0, 85)}`));

await page.goto('http://172.16.12.186:8080/', { waitUntil: 'commit' });
await page.getByText('Tape Libraries').first().waitFor({ timeout: 60000 });
console.log(`>>> 首屏可见总耗时: ${Date.now()-t0}ms`);
done.sort((a, b2) => parseInt(a.slice(1)) - parseInt(b2.slice(1))).forEach((l) => console.log(l));
await page.waitForTimeout(12000);
const vis = await page.getByText('Tape Drives').first().isVisible().catch(() => false);
console.log(`>>> 12 秒后页面仍响应: ${vis}`);
await page.screenshot({ path: 'screenshots/chrome-trace.png' });
await b.close();
