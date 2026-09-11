import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60000,
  use: { baseURL: 'http://localhost:5173' },
  webServer: {
    command: 'npm run dev',
    port: 5173,
    reuseExistingServer: true,
    timeout: 60000,
  },
  reporter: [['html', { outputFolder: 'test-results/e2e-report', open: 'never' }], ['json', { outputFile: 'test-results/e2e-summary.json' }]],
});
