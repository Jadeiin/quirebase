// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest';
import { i18n } from '@lingui/core';
import { get } from 'svelte/store';
import { domainLabel } from '#lib/domain-labels.js';
import {
	DEFAULT_LOCALE,
	LOCALE_STORAGE_KEY,
	activeLocale,
	activateLocale,
	detectInitialLocale,
	normalizeLocale,
	storeLocale,
	setLocale,
	syncLocaleAcrossTabs
} from '#lib/locale.js';

function setBrowserLanguage(language: string) {
	Object.defineProperty(navigator, 'language', { value: language, configurable: true });
}

describe('frontend locale metadata', () => {
	afterEach(() => {
		activateLocale('en-US');
		localStorage.clear();
		setBrowserLanguage('en-US');
	});

	it('applies and persists a normalized preference to the application and document', () => {
		expect(setLocale('zh_CN')).toBe('zh-CN');
		expect(i18n.locale).toBe('zh-CN');
		expect(get(activeLocale)).toBe('zh-CN');
		expect(document.documentElement.lang).toBe('zh-CN');
		expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN');
		expect(activateLocale('unsupported')).toBe('en-US');
	});

	it('synchronizes another tab without writing the preference again and stops on cleanup', () => {
		const stop = syncLocaleAcrossTabs();
		try {
			window.dispatchEvent(
				new StorageEvent('storage', { key: 'quirebase:theme', newValue: 'zh-CN' })
			);
			expect(i18n.locale).toBe('en-US');
			window.dispatchEvent(
				new StorageEvent('storage', { key: LOCALE_STORAGE_KEY, newValue: 'zh-CN' })
			);
			expect(i18n.locale).toBe('zh-CN');
			expect(get(activeLocale)).toBe('zh-CN');
			expect(document.documentElement.lang).toBe('zh-CN');
			expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBeNull();
			stop();
			window.dispatchEvent(
				new StorageEvent('storage', { key: LOCALE_STORAGE_KEY, newValue: 'en-US' })
			);
			expect(i18n.locale).toBe('zh-CN');
		} finally {
			stop();
		}
	});

	it('resolves the Project participation label from the committed context-specific catalog', () => {
		activateLocale('zh-CN');
		expect(i18n._(domainLabel('open'))).toBe('开放');
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
});
