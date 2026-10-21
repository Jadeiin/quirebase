import { afterNavigate, goto } from '$app/navigation';
import { navigating, page } from '$app/state';
import type { ResolvedPathname } from '$app/types';

type UrlDraftOptions = {
	read: (url: Pick<URL, 'href'> & { searchParams: Pick<URLSearchParams, 'get'> }) => string;
	href: (value: string) => ResolvedPathname;
};

/**
 * Keep raw search text local and publish its trimmed value after 200 ms.
 * The feature builds the complete URL, including dependent changes such as page one.
 * History restores the URL's value and cancels unpublished edits. A publication's
 * acknowledgement preserves both whitespace and edits made while it was navigating.
 * Call during component initialization so navigation and timers share its lifetime.
 */
export function createUrlDraft({ read, href }: UrlDraftOptions) {
	let committed = read(page.url);
	let value = $state(committed);
	let publishing = $state(false);
	let composing = $state(false);
	let failed = $state(false);
	let publishedHref: string | undefined;

	afterNavigate(({ to, type }) => {
		if (!to) return;
		const submitted = read(to.url);
		if (type === 'popstate' || (to.url.href !== publishedHref && submitted !== committed)) {
			value = submitted;
		}
		committed = submitted;
		publishedHref = undefined;
		failed = false;
	});

	$effect(() => {
		const submitted = read(page.url);
		const draft = value.trim();
		if (navigating.to || publishing || composing || failed || draft === submitted) return;
		const timeout = setTimeout(() => {
			const target = href(draft);
			// eslint-disable-next-line svelte/prefer-svelte-reactivity -- only the immutable href string is retained
			publishedHref = new URL(target, page.url.href).href;
			publishing = true;
			void goto(target, { reset: false, replace: true })
				.catch(() => {
					// Keep the draft if navigation is cancelled; retry on the next edit.
					failed = true;
				})
				.finally(() => {
					publishedHref = undefined;
					publishing = false;
				});
		}, 200);
		return () => clearTimeout(timeout);
	});

	return {
		compositionStart() {
			composing = true;
		},
		compositionEnd() {
			composing = false;
		},
		get value() {
			return value;
		},
		set value(next: string) {
			value = next;
			failed = false;
		}
	};
}
