// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';
import type { afterNavigate } from '$app/navigation';
import type { ResolvedPathname } from '$app/types';
import { createUrlDraft } from './url-draft.svelte';

type Navigation = Parameters<Parameters<typeof afterNavigate>[0]>[0];
const router = vi.hoisted(() => ({
	goto: vi.fn<(url: string, options: unknown) => Promise<void>>(),
	afterNavigate: vi.fn<(callback: (navigation: Navigation) => void) => void>(),
	url: () => new URL('http://localhost/tools'),
	target: (): object | null => null
}));
vi.mock('$app/navigation', () => router);
vi.mock('$app/state', () => ({
	page: {
		get url() {
			return router.url();
		}
	},
	navigating: {
		get to() {
			return router.target();
		}
	}
}));

let url = $state(new URL('http://localhost/tools'));
let target = $state<object | null>(null);
let destroy: () => void;
let draft: ReturnType<typeof createUrlDraft>;

function arrive(destination: URL, type: Navigation['type'] = 'goto') {
	url = destination;
	router.afterNavigate.mock.lastCall![0]({ to: { url }, type } as Navigation);
	target = null;
	flushSync();
}

async function advance(ms = 200) {
	flushSync();
	await vi.advanceTimersByTimeAsync(ms);
	flushSync();
}

beforeEach(() => {
	vi.useFakeTimers();
	url = new URL('http://localhost/tools');
	target = null;
	router.url = () => url;
	router.target = () => target;
	router.goto.mockImplementation(async (destination) => arrive(new URL(destination, url)));
	destroy = $effect.root(() => {
		draft = createUrlDraft({
			read: (url) => url.searchParams.get('search') ?? '',
			href: (value) => {
				const destination = new URL(url);
				destination.searchParams.set('search', value);
				return `${destination.pathname}${destination.search}` as ResolvedPathname;
			}
		});
	});
	flushSync();
});

afterEach(() => {
	destroy();
	vi.useRealTimers();
});

describe('URL search drafts', () => {
	it('debounces the latest raw input and preserves spaces after its URL acknowledgement', async () => {
		draft.value = 'machine';
		await advance(100);
		draft.value = 'machine ';
		await advance(100);
		expect(router.goto).not.toHaveBeenCalled();
		await advance(100);
		expect(url.searchParams.get('search')).toBe('machine');
		expect(draft.value).toBe('machine ');
		expect(router.goto).toHaveBeenCalledExactlyOnceWith('/tools?search=machine', {
			reset: false,
			replace: true
		});
	});

	it('retains edits made while an earlier draft is being published', async () => {
		const publication = Promise.withResolvers<void>();
		router.goto.mockImplementationOnce(async (destination) => {
			await publication.promise;
			arrive(new URL(destination, url));
		});
		draft.value = 'machine ';
		await advance();
		draft.value = 'machine learning';
		await advance();
		expect(router.goto).toHaveBeenCalledTimes(1);
		publication.resolve();
		await advance(0);
		expect(draft.value).toBe('machine learning');
		await advance();
		expect(url.searchParams.get('search')).toBe('machine learning');
	});

	it('pauses publication throughout navigation and restores even an unchanged history value', async () => {
		draft.value = 'unpublished';
		await advance(100);
		target = {};
		await advance(500);
		expect(router.goto).not.toHaveBeenCalled();
		arrive(new URL('http://localhost/tools?mode=title'), 'popstate');
		await advance();
		expect(draft.value).toBe('');
		expect(router.goto).not.toHaveBeenCalled();
	});

	it('preserves unpublished input across a correction to unrelated URL fields', async () => {
		draft.value = 'machine learning';
		await advance(100);
		arrive(new URL('http://localhost/tools?page=2'));
		await advance();
		expect(draft.value).toBe('machine learning');
		expect(url.searchParams.get('search')).toBe('machine learning');
		expect(url.searchParams.get('page')).toBe('2');
	});

	it('restores an external filter and discards the old debounce', async () => {
		draft.value = 'unpublished';
		await advance(100);
		arrive(new URL('http://localhost/tools?search=restored'));
		await advance();
		expect(draft.value).toBe('restored');
		expect(router.goto).not.toHaveBeenCalled();
	});

	it('retains cancelled navigation input without retrying until another edit', async () => {
		router.goto.mockRejectedValueOnce(new Error('navigation aborted'));
		draft.value = 'machine';
		await advance();
		await advance(1_000);
		expect(router.goto).toHaveBeenCalledTimes(1);
		expect(draft.value).toBe('machine');
		draft.value = 'machine learning';
		await advance();
		expect(url.searchParams.get('search')).toBe('machine learning');
	});

	it('cancels a pending publication when its view is disposed', async () => {
		draft.value = 'unpublished';
		flushSync();
		destroy();
		await advance();
		expect(router.goto).not.toHaveBeenCalled();
	});
});
