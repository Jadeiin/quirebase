import { defineConfig } from '@playwright/test';

export default defineConfig({
	testDir: './e2e',
	use: { baseURL: 'http://127.0.0.1:4173' },
	expect: { timeout: 10_000 },
	webServer: {
		command: 'bun run build && bunx vite preview --host 127.0.0.1 --port 4173',
		port: 4173,
		reuseExistingServer: !process.env.CI
	}
});
