import { chromium } from '@playwright/test';
const BASE = 'http://172.16.12.186:8080';
const b = await chromium.launch();
const page = await b.newPage({ viewport: { width: 1600, height: 900 } });
page.on('pageerror', (e) => console.log('PAGEERROR:', e.message.slice(0, 150)));

// Drives 页：带机应显示 LOADED + IBM015LA
await page.goto(BASE + '/drives', { waitUntil: 'domcontentloaded' });
await page.getByText('ULT3580-TDA').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(2000);
const loaded = await page.getByText('IBM015LA').count();
console.log('Drives 页出现 IBM015LA 次数:', loaded);
const loadedTag = await page.getByText('LOADED').count();
console.log('LOADED 标签:', loadedTag);
await page.screenshot({ path: 'screenshots/drives-dte.png' });

// Drive 详情页
await page.goto(BASE + '/drives/nst1', { waitUntil: 'domcontentloaded' });
await page.getByText('Loaded Tape').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(1500);
const detail = await page.getByText('IBM015LA').count();
console.log('DriveDetail 显示装载磁带:', detail > 0 ? 'YES' : 'NO');
await page.screenshot({ path: 'screenshots/drivedetail-dte.png' });

// Tapes 页：卷列表应含"在带机"的磁带
await page.goto(BASE + '/tapes', { waitUntil: 'domcontentloaded' });
await page.getByText('IBM006LA').first().waitFor({ timeout: 30000 });
await page.waitForTimeout(2000);
const inDrive = await page.locator('tbody tr').filter({ hasText: 'IBM015LA' }).count();
console.log('Tapes 页 IBM015LA 行:', inDrive);
await page.screenshot({ path: 'screenshots/tapes-dte.png' });
await b.close();
console.log('DTE_VERIFY_DONE');
