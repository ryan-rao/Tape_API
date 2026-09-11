import { chromium } from '@playwright/test';

const BASE = 'http://172.16.12.186:8080';
const cases: [string, string, string][] = [
  ['Dashboard', '/', 'Tape Libraries'],
  ['Libraries', '/libraries', '03584L32'],
  ['LibraryDetail', '/libraries/sg1', 'Slot Visualization'],
  ['Drives', '/drives', 'ULT3580-TDA'],
  ['DriveDetail', '/drives/nst1', 'Loaded Tape'],
  ['Tapes', '/tapes', 'IBM00'],
  ['TestCenter', '/tests', 'Operation'],
  ['Operations', '/operations', 'Operation'],
  ['Audit', '/audit', 'Audit'],
];

const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
let fail = 0;
for (const [name, path, text] of cases) {
  const errs: string[] = [];
  const h1 = (m: any) => { if (m.type() === 'error') errs.push(m.text().slice(0, 100)); };
  const h2 = (e: any) => errs.push('PAGEERROR:' + e.message.slice(0, 100));
  page.on('console', h1); page.on('pageerror', h2);
  try {
    await page.goto(BASE + path, { waitUntil: 'domcontentloaded' });
    await page.getByText(text).first().waitFor({ timeout: 20000 });
    console.log(`PASS ${name}`);
  } catch {
    fail++;
    console.log(`FAIL ${name} (no "${text}")`);
  }
  page.off('console', h1); page.off('pageerror', h2);
}
await b.close();
console.log(fail === 0 ? 'ALL_PAGES_OK' : `${fail} FAILED`);
