import { afterEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { activateLocale, msg, setLocale, t } from '$lib/i18n';
import { LOCALE_STORAGE_KEY } from '$lib/locale';

describe('frontend localization', () => {
	afterEach(() => {
		activateLocale('en-US');
		localStorage.clear();
	});

	it('reactively activates the compiled gettext catalog', () => {
		expect(get(t)('Library')).toBe('Library');

		expect(activateLocale('zh-CN')).toBe('zh-CN');
		expect(get(t)('Library')).toBe('文献库');
		expect(document.documentElement.lang).toBe('zh-CN');
	});

	it('falls back to the source locale and preserves marked messages', () => {
		expect(activateLocale('unsupported')).toBe('en-US');
		expect(msg('Dashboard')).toBe('Dashboard');
		expect(get(t)(msg('Dashboard'))).toBe('Dashboard');
	});

	it('persists an explicit locale selection for the browser', () => {
		expect(setLocale('zh-CN')).toBe('zh-CN');
		expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe('zh-CN');
		expect(get(t)('Library')).toBe('文献库');
	});

	it('translates marked domain labels through the active catalog', () => {
		activateLocale('zh-CN');
		expect(get(t)(msg('Owner'))).toBe('所有者');
		expect(get(t)(msg({ message: 'Editor', comment: 'Project member role.' }))).toBe('编辑者');
		expect(get(t)(msg('Viewer'))).toBe('查看者');
		expect(get(t)('Owner')).toBe('所有者');
	});

	it('interpolates ICU values from the active catalog', () => {
		expect(get(t)('Page {page} of {pageCount}', { page: 2, pageCount: 5 })).toBe('Page 2 of 5');

		activateLocale('zh-CN');
		expect(get(t)('Page {page} of {pageCount}', { page: 2, pageCount: 5 })).toBe(
			'第 2 页，共 5 页'
		);
	});

	it('applies ICU plural rules from the active catalog', () => {
		expect(get(t)('{count, plural, one {# Item} other {# Items}}', { count: 1 })).toBe('1 Item');
		expect(get(t)('{count, plural, one {# Item} other {# Items}}', { count: 4 })).toBe('4 Items');

		activateLocale('zh-CN');
		expect(get(t)('{count, plural, one {# Item} other {# Items}}', { count: 4 })).toBe('4 条文献');
	});
});
