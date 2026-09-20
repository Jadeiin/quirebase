import { describe, expect, it } from 'vitest';
import { parseThemePreference, resolveColorMode } from './theme';

describe('theme preference', () => {
	it('treats missing and unknown stored values as system', () => {
		expect(parseThemePreference(null)).toBe('system');
		expect(parseThemePreference('sepia')).toBe('system');
	});

	it('resolves system and explicit preferences', () => {
		expect(resolveColorMode('system', false)).toBe('light');
		expect(resolveColorMode('system', true)).toBe('dark');
		expect(resolveColorMode('light', true)).toBe('light');
		expect(resolveColorMode('dark', false)).toBe('dark');
	});
});
