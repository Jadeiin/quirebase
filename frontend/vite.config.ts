import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

const apiOrigin = process.env.QUIREBASE_DEV_API_ORIGIN ?? 'http://127.0.0.1:9060';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			preprocess: vitePreprocess(),
			adapter: adapter({ fallback: 'index.html' }),
			csp: {
				mode: 'hash',
				directives: {
					'default-src': ['self'],
					'script-src': ['self', 'wasm-unsafe-eval'],
					'style-src': ['self', 'unsafe-inline'],
					'img-src': ['self', 'data:', 'blob:'],
					'connect-src': ['self', 'https:', 'http:'],
					'worker-src': ['self', 'blob:'],
					'object-src': ['none'],
					'frame-ancestors': ['none']
				}
			}
		})
	],
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
