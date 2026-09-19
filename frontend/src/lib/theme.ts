export const themePreferenceKey = 'quirebase:theme';

export type ThemePreference = 'system' | 'light' | 'dark';
export type ColorMode = 'light' | 'dark';

export function parseThemePreference(value: string | null): ThemePreference {
	return value === 'light' || value === 'dark' ? value : 'system';
}

export function resolveColorMode(
	preference: ThemePreference,
	systemPrefersDark: boolean
): ColorMode {
	return preference === 'system' ? (systemPrefersDark ? 'dark' : 'light') : preference;
}

export function readThemePreference(): ThemePreference {
	return parseThemePreference(localStorage.getItem(themePreferenceKey));
}

export function saveThemePreference(preference: ThemePreference): void {
	if (preference === 'system') localStorage.removeItem(themePreferenceKey);
	else localStorage.setItem(themePreferenceKey, preference);
}

export function applyTheme(preference: ThemePreference, systemPrefersDark: boolean): void {
	const mode = resolveColorMode(preference, systemPrefersDark);
	document.documentElement.dataset.mode = mode;
	document
		.querySelector('meta[name="theme-color"]')
		?.setAttribute('content', mode === 'dark' ? '#0e1713' : '#f4f6f5');
}
