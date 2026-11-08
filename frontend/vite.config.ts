import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';
import linguiForSvelte from 'lingui-for-svelte/unplugin/vite';
import linguiMacro from 'unplugin-lingui-macro/vite';
import type { Plugin } from 'vite';

const apiOrigin = process.env.QUIREBASE_DEV_API_ORIGIN ?? 'http://127.0.0.1:9060';

const authorDetailChunks = new Set<string>();
const authorDetailPreloadRecovery: Plugin = {
	name: 'author-detail-preload-recovery',
	apply: 'build',
	generateBundle: {
		order: 'pre',
		handler(_options, bundle) {
			authorDetailChunks.clear();
			for (const chunk of Object.values(bundle)) {
				if (
					chunk.type === 'chunk' &&
					chunk.facadeModuleId?.endsWith(
						'/src/lib/features/item/authors/ItemAuthorDetailsContent.svelte'
					)
				)
					authorDetailChunks.add(chunk.fileName);
			}
		}
	}
};

export default defineConfig({
	build: {
		modulePreload: {
			// Failed WebKit modulepreloads can survive a page refresh. Fetch this entry through
			// native import(), so the explicit Refresh page recovery can start a new module load.
			resolveDependencies: (filename, dependencies) =>
				authorDetailChunks.has(filename)
					? dependencies.filter((dependency) => dependency !== filename)
					: dependencies
		}
	},
	plugins: [
		authorDetailPreloadRecovery,
		linguiMacro(),
		linguiForSvelte(),
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
		setupFiles: ['./vitest.setup.ts'],
		environment: 'node',
		include: ['src/**/*.test.ts'],
		// Cache transforms while retaining Vitest's default per-file module isolation.
		fsModuleCache: true,
		clearMocks: true,
		restoreMocks: true,
		unstubGlobals: true
	}
});
