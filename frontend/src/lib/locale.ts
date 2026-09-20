import { fromNavigator, fromStorage, multipleDetect } from '@lingui/detect-locale';

export const SUPPORTED_LOCALES = ['en-US', 'zh-CN'] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = 'en-US';
export const LOCALE_STORAGE_KEY = 'quirebase:locale';

function matchLocale(value: string): Locale | undefined {
	const normalized = value.trim().replace('_', '-').toLowerCase();
	for (const locale of SUPPORTED_LOCALES) {
		if (normalized === locale.toLowerCase() || normalized.split('-')[0] === locale.split('-')[0]) {
			return locale;
		}
	}
	return undefined;
}

export function normalizeLocale(value: string): Locale {
	return matchLocale(value) ?? DEFAULT_LOCALE;
}

function storedLocale(): string | undefined {
	try {
		return fromStorage(LOCALE_STORAGE_KEY) || undefined;
	} catch {
		return undefined;
	}
}

function browserLocale(): string | undefined {
	try {
		return fromNavigator() || undefined;
	} catch {
		return undefined;
	}
}

export function detectInitialLocale(): Locale {
	for (const candidate of multipleDetect(storedLocale, browserLocale)) {
		const matched = matchLocale(candidate);
		if (matched) return matched;
	}
	return DEFAULT_LOCALE;
}

export function storeLocale(locale: Locale): void {
	try {
		globalThis.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
	} catch {
		return;
	}
}
