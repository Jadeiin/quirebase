import { defineConfig } from '@lingui/cli';
import { formatter } from '@lingui/format-po';
import { svelteExtractor, typescriptExtractor } from './src/lib/i18n-extractor';
import { DEFAULT_LOCALE, SUPPORTED_LOCALES } from './src/lib/locale';

export default defineConfig({
	locales: [...SUPPORTED_LOCALES],
	sourceLocale: DEFAULT_LOCALE,
	compileNamespace: 'es',
	orderBy: 'message',
	format: formatter({ lineNumbers: false }),
	catalogs: [
		{
			path: '<rootDir>/src/lib/locales/{locale}/messages',
			include: ['<rootDir>/src/**/*.svelte', '<rootDir>/src/**/*.ts'],
			exclude: [
				'<rootDir>/src/**/*.test.ts',
				'<rootDir>/src/**/*.d.ts',
				'<rootDir>/src/lib/locales/**'
			]
		}
	],
	extractors: [svelteExtractor, typescriptExtractor]
});
