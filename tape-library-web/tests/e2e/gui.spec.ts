import { test, expect, type Page } from '@playwright/test';

// E2E：Mock 模式完整用户流程（启动: npm run dev，VITE_API_MODE 默认 mock）
// 注：antd Select 占位符是 span 而非原生 placeholder，需用 getByText

async function gotoTests(page: Page) {
  await page.goto('/tests');
  await expect(page.getByText('Safety Policy').first()).toBeVisible({ timeout: 15000 });
}

async function selectSlot(page: Page, label: string) {
  // antd Select：点 selector（placeholder 元素 pointer-events:none），再点下拉选项
  await page.locator('.ant-select-selector').nth(1).click();
  await page.locator('.ant-select-item-option', { hasText: label }).first().click();
}

async function selectOp(page: Page, label: string) {
  // 第 4 个 Select 是操作类型（①库 ②槽 ③机 ④操作）
  await page.locator('.ant-select-selector').nth(3).click();
  await page.locator('.ant-select-item-option', { hasText: label }).first().click();
}

async function mount(page: Page, slotLabel = 'IBM015LA / Slot 6') {
  await gotoTests(page);
  await selectSlot(page, slotLabel);
  await page.getByRole('button', { name: 'Mount Tape' }).click();
  await page.getByRole('button', { name: 'Confirm Mount' }).click();
  await expect(page.getByText(/Mount PASS/).first()).toBeVisible({ timeout: 30000 });
}

test('01 打开 Dashboard 并显示统计卡片', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Tape Library Management').first()).toBeVisible();
  await expect(page.getByText('Tape Libraries').first()).toBeVisible();
  await expect(page.getByText('Tape Drives').first()).toBeVisible();
});

test('02 查看 Library 列表', async ({ page }) => {
  await page.goto('/libraries');
  await expect(page.getByText('03584L32').first()).toBeVisible();
  await expect(page.getByText('Healthy').first()).toBeVisible();
});

test('03 进入 Library Detail 查看槽位可视化', async ({ page }) => {
  await page.goto('/libraries/sg1');
  await expect(page.getByText('Slot Visualization').first()).toBeVisible({ timeout: 15000 });
  await expect(page.getByText('IBM006LA').first()).toBeVisible();
});

test('04 点击 Slot 弹出详情', async ({ page }) => {
  await page.goto('/libraries/sg1');
  await page.getByText('IBM006LA').first().click({ timeout: 15000 });
  await expect(page.getByText('Slot Information')).toBeVisible();
});

test('05 查看带机列表与详情', async ({ page }) => {
  await page.goto('/drives');
  await expect(page.getByText('ULT3580-TDA').first()).toBeVisible({ timeout: 15000 });
  await page.getByRole('button', { name: 'View' }).first().click();
  await page.waitForURL('**/drives/*', { timeout: 10000 });
  await expect(page.getByText('Loaded Tape').first()).toBeVisible({ timeout: 10000 });
});

test('06 查看 Tape Inventory', async ({ page }) => {
  await page.goto('/tapes');
  await expect(page.getByText('IBM006LA').first()).toBeVisible({ timeout: 15000 });
});

test('07 Test Center 执行 Mount（Mock）', async ({ page }) => {
  await mount(page);
});

test('08 Unmount 归位后切换 Read Test', async ({ page }) => {
  await mount(page);
  await selectOp(page, 'Unmount Tape');
  await page.getByRole('button', { name: 'Unmount Tape' }).click();
  await page.getByRole('button', { name: 'Confirm Unmount' }).click();
  await expect(page.getByText(/Unmount PASS/).first()).toBeVisible({ timeout: 30000 });
});

test('09 Read Test 产生会话并推进', async ({ page }) => {
  await mount(page);
  await selectOp(page, 'Read Test');
  await page.getByRole('button', { name: 'Read Test' }).click();
  await page.getByRole('button', { name: 'Confirm Read' }).click();
  await expect(page.getByText(/Test started/).first()).toBeVisible({ timeout: 10000 });
  // 会话轮询推进（256MiB @ ~270MiB/s ≈ 1~2s）
  await expect(page.getByText('Test Progress').first()).toBeVisible({ timeout: 15000 });
});

test('10 Write Test：错误 Barcode 禁止授权', async ({ page }) => {
  await mount(page);
  await selectOp(page, 'Write Test (verify)');
  await page.getByRole('button', { name: 'Write Test (verify)' }).click();
  const dlg = page.getByRole('dialog');
  await dlg.getByPlaceholder('Enter tape barcode').fill('WRONG-9999');
  await expect(dlg.getByRole('button', { name: 'Authorize Write' })).toBeDisabled();
  // 正确 Barcode 后解除禁用
  await dlg.getByPlaceholder('Enter tape barcode').fill('IBM015LA');
  await expect(dlg.getByRole('button', { name: 'Authorize Write' })).toBeEnabled({ timeout: 5000 });
});

test('11 查看 Operation History 与 Audit', async ({ page }) => {
  await page.goto('/operations');
  await expect(page.getByText('Mount').first()).toBeVisible({ timeout: 15000 });
  await page.goto('/audit');
  await expect(page.getByText('Command ID').first()).toBeVisible();
});
