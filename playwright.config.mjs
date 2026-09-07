import {defineConfig} from '@playwright/test';

const localChrome = process.platform === 'win32' ? 'chrome' : undefined;

export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: {timeout: 5_000},
  outputDir: './output/playwright',
  reporter: [['list']],
  use: {
    browserName: 'chromium',
    channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL || localChrome,
    headless: true,
    viewport: {width: 1280, height: 900},
    screenshot: 'only-on-failure',
  },
});
