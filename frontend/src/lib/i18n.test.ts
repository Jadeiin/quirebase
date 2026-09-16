import { afterEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { activateLocale, msg, t } from '$lib/i18n';

describe('frontend localization', () => {
	afterEach(() => activateLocale('en-US'));

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
});
