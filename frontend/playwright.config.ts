import { defineConfig } from '@playwright/test';

const testPort = Number(process.env.E2E_PORT ?? 4173);
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;

export default defineConfig({
	testDir: './e2e',
	use: {
		launchOptions: executablePath ? { executablePath } : undefined,
		baseURL: `http://127.0.0.1:${testPort}`,
		trace: process.env.CI ? 'retain-on-failure' : 'off',
		screenshot: 'only-on-failure'
	},
	expect: { timeout: 10_000 },
	webServer: {
		command: `bun run build && bunx vite preview --host 127.0.0.1 --port ${testPort}`,
		port: testPort,
		reuseExistingServer: !process.env.CI
	}
});
