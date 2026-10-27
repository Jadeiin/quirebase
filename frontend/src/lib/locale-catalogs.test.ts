import { parsePoFile } from '@lingui/format-po';
import { describe, expect, it } from 'vitest';
import { DEFAULT_LOCALE, SUPPORTED_LOCALES } from '#lib/locale.js';

const sources = import.meta.glob('./locales/*/messages.po', {
	query: '?raw',
	import: 'default',
	eager: true
}) as Record<string, string>;

const UNTRANSLATED_TERMS = new Set([
	'A–Z',
	'BibTeX',
	'CSL XML',
	'CSL-JSON',
	'Commonmeta',
	'DOI',
	'JSON',
	'OpenAPI',
	'PDF',
	'RIS',
	'URL',
	'Z–A',
	'{kind} · {size} KB',
	'{size} KB',
	'{size} MB'
]);

describe('committed locale catalogs', () => {
	it('provides exactly the supported locales, including the default', () => {
		expect(Object.keys(sources).sort()).toEqual(
			SUPPORTED_LOCALES.map((locale) => `./locales/${locale}/messages.po`).sort()
		);
		expect(SUPPORTED_LOCALES).toContain(DEFAULT_LOCALE);
	});

	for (const locale of SUPPORTED_LOCALES) {
		it(`${locale} has no missing or fuzzy translations`, () => {
			const entries = parsePoFile(sources[`./locales/${locale}/messages.po`]).items.filter(
				(entry) => entry.msgid && !entry.obsolete
			);
			expect(entries.length).toBeGreaterThan(0);
			expect(
				entries
					.filter((entry) => !entry.msgstr.length || entry.msgstr.some((text) => !text.trim()))
					.map((entry) => ({ message: entry.msgid, context: entry.msgctxt }))
			).toEqual([]);
			expect(entries.filter((entry) => entry.flags.fuzzy).map((entry) => entry.msgid)).toEqual([]);
		});
	}

	it('translates Chinese copy while allowing technical terms and size units', () => {
		const entries = parsePoFile(sources['./locales/zh-CN/messages.po']).items;
		expect(
			entries
				.filter(
					(entry) =>
						entry.msgid &&
						!entry.obsolete &&
						!UNTRANSLATED_TERMS.has(entry.msgid) &&
						entry.msgstr.some((text) => !/[\u3400-\u9fff]/u.test(text))
				)
				.map((entry) => ({ message: entry.msgid, context: entry.msgctxt }))
		).toEqual([]);
	});
});
