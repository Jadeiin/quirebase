import { i18n, type Messages } from '@lingui/core';
import { derived, writable } from 'svelte/store';
import { messages as englishMessages } from '$lib/locales/en-US/messages';
import { messages as chineseMessages } from '$lib/locales/zh-CN/messages';

declare const messageKey: unique symbol;
export type MessageKey = string & { readonly [messageKey]: true };

type Translator = {
	<Message extends string>(message: string extends Message ? never : Message): string;
	(message: MessageKey): string;
};

const catalogs: Record<string, Messages> = {
	'en-US': englishMessages,
	'zh-CN': chineseMessages
};

i18n.loadAndActivate({ locale: 'en-US', messages: catalogs['en-US'] });
const locale = writable('en-US');

export const t = derived(
	locale,
	(activeLocale) => ((message: string) => translate(message, activeLocale)) as Translator
);

export function msg(message: string): MessageKey {
	return message as MessageKey;
}

export function activateLocale(requestedLocale: string): string {
	const selected = requestedLocale in catalogs ? requestedLocale : 'en-US';
	i18n.loadAndActivate({ locale: selected, messages: catalogs[selected] });
	locale.set(selected);
	document.documentElement.lang = selected;
	return selected;
}

export function translate(message: string, activeLocale = i18n.locale): string {
	if (!(activeLocale in catalogs)) return message;
	return i18n._(message);
}
