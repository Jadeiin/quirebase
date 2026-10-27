import babelExtractor from '@lingui/cli/api/extractors/babel';
import { formatter } from '@lingui/format-po';
import { defineConfig } from 'lingui-for-svelte/config';
import { svelteExtractor } from 'lingui-for-svelte/extractor';
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
	extractors: [svelteExtractor, babelExtractor]
});
