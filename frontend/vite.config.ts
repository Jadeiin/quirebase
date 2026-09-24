import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

const apiOrigin = process.env.QUIREBASE_DEV_API_ORIGIN ?? 'http://127.0.0.1:9060';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		strictPort: true,
		origin: process.env.QUIREBASE_EXTERNAL_ORIGIN,
		proxy: {
			'/api': { target: apiOrigin },
			'/docs': { target: apiOrigin },
			'/healthz': { target: apiOrigin },
			'/metrics': { target: apiOrigin },
			'/mcp': { target: apiOrigin },
			'/openapi.json': { target: apiOrigin }
		}
	},
	preview: {
		proxy: {}
	},
	test: {
		environment: 'node',
		include: ['src/**/*.test.ts'],
		// Cache transforms while retaining Vitest's default per-file module isolation.
		fsModuleCache: true,
		clearMocks: true,
		restoreMocks: true,
		unstubGlobals: true
	}
});
