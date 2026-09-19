import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: './e2e-fullstack',
	workers: 1,
	timeout: 60_000,
	expect: { timeout: 15_000 },
	use: {
		baseURL: 'http://127.0.0.1:9060',
		trace: 'retain-on-failure'
	},
	webServer: {
		command: 'bun run build && ../scripts/fullstack-e2e-server.sh',
		url: 'http://127.0.0.1:9060/healthz',
		timeout: 120_000,
		reuseExistingServer: false
	}
});
