import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: '../../tests/e2e/core', fullyParallel: false, workers: 1, reporter: 'list', use: { headless: true, channel: process.env.OF_BROWSER_CHANNEL, baseURL: 'http://127.0.0.1:64110' } });
