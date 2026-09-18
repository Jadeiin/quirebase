import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

const apiOrigin = process.env.QUIREBASE_DEV_API_ORIGIN ?? 'http://127.0.0.1:9060';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		strictPort: true,
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
		environment: 'jsdom',
		include: ['src/**/*.test.ts']
	}
});
