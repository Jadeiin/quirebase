import { fromNavigator, fromStorage, multipleDetect } from '@lingui/detect-locale';
import { i18n } from '@lingui/core';
import { writable } from 'svelte/store';

export const SUPPORTED_LOCALES = ['en-US', 'zh-CN'] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = 'en-US';
export const LOCALE_STORAGE_KEY = 'quirebase:locale';
export const activeLocale = writable<Locale>(DEFAULT_LOCALE);

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

export function activateLocale(requestedLocale: string): Locale {
	const selected = normalizeLocale(requestedLocale);
	i18n.activate(selected);
	activeLocale.set(selected);
	if (typeof document !== 'undefined') document.documentElement.lang = selected;
	return selected;
}

export function setLocale(requestedLocale: string): Locale {
	const selected = activateLocale(requestedLocale);
	storeLocale(selected);
	return selected;
}

export function syncLocaleAcrossTabs(): () => void {
	const listener = (event: StorageEvent) => {
		if (event.key === LOCALE_STORAGE_KEY && event.newValue) activateLocale(event.newValue);
	};
	window.addEventListener('storage', listener);
	return () => window.removeEventListener('storage', listener);
}
