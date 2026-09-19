// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest';
import {
	DEFAULT_LOCALE,
	LOCALE_STORAGE_KEY,
	detectInitialLocale,
	normalizeLocale,
	storeLocale
} from '$lib/locale';

function setBrowserLanguage(language: string) {
	Object.defineProperty(navigator, 'language', { value: language, configurable: true });
}

describe('frontend locale metadata', () => {
	afterEach(() => {
		localStorage.clear();
		setBrowserLanguage('en-US');
	});

	it('normalizes supported BCP 47 tags and falls back to the default locale', () => {
		expect(DEFAULT_LOCALE).toBe('en-US');
		expect(normalizeLocale('zh_CN')).toBe('zh-CN');
		expect(normalizeLocale('zh-Hans-CN')).toBe('zh-CN');
		expect(normalizeLocale('EN')).toBe('en-US');
		expect(normalizeLocale('fr-FR')).toBe('en-US');
		expect(normalizeLocale('')).toBe('en-US');
	});

	it('detects the stored locale before the browser language', () => {
		setBrowserLanguage('zh-CN');
		storeLocale('en-US');
		expect(detectInitialLocale()).toBe('en-US');
	});

	it('falls back to the browser language and then the default locale', () => {
		setBrowserLanguage('zh-CN');
		expect(detectInitialLocale()).toBe('zh-CN');

		localStorage.setItem(LOCALE_STORAGE_KEY, 'unsupported');
		expect(detectInitialLocale()).toBe('zh-CN');

		setBrowserLanguage('fr-FR');
		expect(detectInitialLocale()).toBe('en-US');
	});

	it('round-trips the locale through browser storage', () => {
		storeLocale('zh-CN');
		expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN');
	});
});
