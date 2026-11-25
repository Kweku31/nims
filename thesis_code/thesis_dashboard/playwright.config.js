import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: '*.spec.js',
  use: { baseURL: process.env.DASHBOARD_BASE_URL || 'http://127.0.0.1:8765', headless: true,
    launchOptions: { executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome', args:['--no-sandbox'] } },
  workers: 1,
  reporter: 'list',
});
