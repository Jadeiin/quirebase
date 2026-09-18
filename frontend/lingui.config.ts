import { defineConfig } from '@lingui/cli';
import { formatter } from '@lingui/format-po';
import { svelteExtractor, typescriptExtractor } from './src/lib/i18n-extractor';

export default defineConfig({
	locales: ['en-US', 'zh-CN'],
	sourceLocale: 'en-US',
	compileNamespace: 'es',
	orderBy: 'message',
	format: formatter({ lineNumbers: false }),
	catalogs: [
		{
			path: '<rootDir>/src/lib/locales/{locale}/messages',
			include: [
				'<rootDir>/src/**/*.svelte',
				'<rootDir>/src/lib/domain-labels.ts',
				'<rootDir>/src/lib/api/errors.ts'
			]
		}
	],
	extractors: [svelteExtractor, typescriptExtractor]
});
