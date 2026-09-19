import prettier from 'eslint-config-prettier';
import path from 'node:path';
import js from '@eslint/js';
import lingui from 'eslint-plugin-lingui';
import svelte from 'eslint-plugin-svelte';
import { defineConfig, includeIgnoreFile } from 'eslint/config';
import globals from 'globals';
import ts from 'typescript-eslint';
import svelteConfig from './svelte.config.js';

const gitignorePath = path.resolve(import.meta.dirname, '.gitignore');

export default defineConfig(
	includeIgnoreFile(gitignorePath),
	js.configs.recommended,
	ts.configs.recommended,
	svelte.configs.recommended,
	prettier,
	svelte.configs.prettier,
	{
		languageOptions: { globals: { ...globals.browser, ...globals.node } },
		rules: {
			// typescript-eslint strongly recommend that you do not use the no-undef lint rule on TypeScript projects.
			// see: https://typescript-eslint.io/troubleshooting/faqs/eslint/#i-get-errors-from-the-no-undef-rule-about-global-variables-not-being-defined-even-though-there-are-no-typescript-errors
			'no-undef': 'off'
		}
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
		languageOptions: {
			parserOptions: {
				projectService: true,
				extraFileExtensions: ['.svelte'],
				parser: ts.parser,
				svelteConfig
			}
		}
	},
	{
		files: ['src/**/*.ts'],
		ignores: ['src/**/*.test.ts', 'src/lib/api/schema.d.ts'],
		plugins: { lingui },
		rules: {
			'lingui/no-unlocalized-strings': [
				'warn',
				{
					ignore: [
						'^(?![A-Z])\\S+$',
						'^[A-Z0-9_-]+$',
						'^[A-Z][A-Za-z0-9]*$',
						'^Content-Disposition$',
						'^btn\\b',
						'^auth\\.capitalize',
						'^Times-Roman$'
					],
					ignoreNames: [
						'className',
						'styleName',
						'src',
						'data-testid',
						'type',
						'name',
						'message',
						'comment',
						'key'
					],
					ignoreFunctions: ['console.*', '$t', 'translate', 'Error', 'DOMException']
				}
			]
		}
	}
);
