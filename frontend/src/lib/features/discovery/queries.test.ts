// @vitest-environment jsdom
import { QueryClient, QueryObserver, hashKey } from '@tanstack/svelte-query';
import { afterEach, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.js';
import { discoverySearchQuery } from './queries.js';
import { defaultDiscoverySearch, type SearchRequest } from './search-state.js';

const clients: QueryClient[] = [];
function queryClient() {
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	clients.push(client);
	return client;
}

afterEach(() => {
	for (const client of clients.splice(0)) client.clear();
	vi.unstubAllGlobals();
});

const request: SearchRequest = {
	...defaultDiscoverySearch(),
	clauses: [{ field: 'title', operator: 'and', term: 'neural networks' }]
};
const result: components['schemas']['CandidatePageView'] = {
	provider: 'openalex',
	results: [],
	total: 0,
	page: 1,
	per_page: 20
};

it('keeps an unsubmitted Discovery query idle without requesting external results', async () => {
	const fetch = vi.fn();
	vi.stubGlobal('fetch', fetch);
	const observer = new QueryObserver(queryClient(), discoverySearchQuery('workspace-1', null));
	const unsubscribe = observer.subscribe(() => {});
	try {
		expect(observer.getCurrentResult()).toMatchObject({
			isPending: true,
			fetchStatus: 'idle',
			isFetching: false
		});
		expect(fetch).not.toHaveBeenCalled();
	} finally {
		unsubscribe();
	}
});

it('scopes search cache keys by Workspace and every submitted criterion', () => {
	const base = hashKey(discoverySearchQuery('workspace-1', request).queryKey);
	const alternatives: SearchRequest[] = [
		{ ...request, provider: 'crossref' },
		{ ...request, clauses: [{ ...request.clauses[0], term: 'different' }] },
		{ ...request, clauses: [{ ...request.clauses[0], field: 'author' }] },
		{ ...request, clauses: [{ ...request.clauses[0], operator: 'not' }] },
		{ ...request, sort: 'published' },
		{ ...request, page: 2 },
		{ ...request, per_page: 10 },
		{ ...request, year_from: 2020 },
		{ ...request, year_to: 2025 }
	];
	for (const alternative of alternatives)
		expect(hashKey(discoverySearchQuery('workspace-1', alternative).queryKey)).not.toBe(base);
	const workspaceKey = discoverySearchQuery('workspace-2', request).queryKey;
	expect(hashKey(workspaceKey)).not.toBe(base);
	expect(workspaceKey.slice(0, 2)).toEqual(['workspace', 'workspace-2']);
});

it('captures the submitted request and reuses successful results when returning shortly after import', async () => {
	const sent: Request[] = [];
	vi.stubGlobal('fetch', async (incoming: Request) => {
		sent.push(incoming);
		return new Response(JSON.stringify(result));
	});
	const draft = { ...request, clauses: request.clauses.map((clause) => ({ ...clause })) };
	const options = discoverySearchQuery('workspace-1', draft);
	draft.page = 3;
	draft.clauses[0].term = 'newer edit';
	const client = queryClient();
	expect(await client.fetchQuery(options)).toEqual(result);
	expect(await client.fetchQuery(discoverySearchQuery('workspace-1', request))).toEqual(result);
	expect(sent).toHaveLength(1);
	expect(sent[0].method).toBe('POST');
	expect(new URL(sent[0].url).pathname).toBe('/api/v1/workspaces/workspace-1/discovery/search');
	expect(await sent[0].json()).toEqual(request);
	expect(options.refetchOnWindowFocus).toBe(false);
	expect(options.refetchOnReconnect).toBe(false);
	expect(options.gcTime).toBe(30 * 60 * 1000);
});

it('does not retry an external search failure automatically and supports an explicit retry', async () => {
	const fetch = vi
		.fn()
		.mockRejectedValueOnce(new TypeError('Offline'))
		.mockResolvedValueOnce(new Response(JSON.stringify(result)));
	vi.stubGlobal('fetch', fetch);
	const client = queryClient();
	const options = discoverySearchQuery('workspace-1', request);
	await expect(client.fetchQuery(options)).rejects.toThrow('Offline');
	expect(fetch).toHaveBeenCalledTimes(1);
	expect(client.getQueryState(options.queryKey)?.status).toBe('error');
	expect(await client.fetchQuery(options)).toEqual(result);
	expect(fetch).toHaveBeenCalledTimes(2);
});
