import { derived } from 'svelte/store';
import { activeLocale } from '$lib/i18n';

export const dateFormat = derived(
	activeLocale,
	(locale) => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' })
);

export const dateTimeFormat = derived(
	activeLocale,
	(locale) => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' })
);

export const numberFormat = derived(activeLocale, (locale) => new Intl.NumberFormat(locale));

export function kilobytes(bytes: number): number {
	return Math.ceil(bytes / 1024);
}

export function megabytes(bytes: number): number {
	return Math.ceil(bytes / 1048576);
}
