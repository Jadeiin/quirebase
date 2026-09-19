import { i18n, type Messages } from '@lingui/core';
import { derived, writable } from 'svelte/store';
import { messages as englishMessages } from '$lib/locales/en-US/messages';
import { messages as chineseMessages } from '$lib/locales/zh-CN/messages';
import {
	LOCALE_STORAGE_KEY,
	detectInitialLocale,
	normalizeLocale,
	storeLocale,
	type Locale
} from '$lib/locale';

declare const messageKey: unique symbol;
export type MessageKey = string & { readonly [messageKey]: true };
export type TranslationValues = Record<string, string | number>;

type Translator = {
	<Message extends string>(
		message: string extends Message ? never : Message,
		values?: TranslationValues
	): string;
	(message: MessageKey, values?: TranslationValues): string;
};

const catalogs: Record<Locale, Messages> = {
	'en-US': englishMessages,
	'zh-CN': chineseMessages
};

const initialLocale = detectInitialLocale();

i18n.loadAndActivate({ locale: initialLocale, messages: catalogs[initialLocale] });
export const activeLocale = writable<Locale>(initialLocale);
if (typeof document !== 'undefined') document.documentElement.lang = initialLocale;

export const t = derived(
	activeLocale,
	() => ((message: string, values?: TranslationValues) => translate(message, values)) as Translator
);

export type MessageSource = { message: string; comment?: string };

export function msg(message: string): MessageKey;
export function msg(source: MessageSource): MessageKey;
export function msg(source: string | MessageSource): MessageKey {
	return (typeof source === 'string' ? source : source.message) as MessageKey;
}

export function activateLocale(requestedLocale: string): Locale {
	const selected = normalizeLocale(requestedLocale);
	i18n.loadAndActivate({ locale: selected, messages: catalogs[selected] });
	activeLocale.set(selected);
	if (typeof document !== 'undefined') document.documentElement.lang = selected;
	return selected;
}

export function setLocale(requestedLocale: string): Locale {
	const selected = activateLocale(requestedLocale);
	storeLocale(selected);
	return selected;
}

if (typeof window !== 'undefined') {
	window.addEventListener('storage', (event) => {
		if (event.key === LOCALE_STORAGE_KEY && event.newValue) activateLocale(event.newValue);
	});
}

const reportedMissingMessages = new Set<string>();

export function translate(message: string, values?: TranslationValues): string {
	if (import.meta.env.DEV && !(message in i18n.messages) && !reportedMissingMessages.has(message)) {
		reportedMissingMessages.add(message);
		console.warn(
			`Missing ${i18n.locale} translation for "${message}"; add it to the committed catalog`
		);
	}
	return i18n._(message, values);
}
