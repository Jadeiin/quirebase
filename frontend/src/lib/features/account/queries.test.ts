// @vitest-environment jsdom
import { QueryClient } from '@tanstack/svelte-query';
import { afterEach, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/client.js';
import { exportCitationStyleQuery, exportCitationStylesQuery } from './queries.js';

const clients: QueryClient[] = [];
function queryClient() {
	const client = new QueryClient({
		defaultOptions: { queries: { retry: false, staleTime: Infinity } }
	});
	clients.push(client);
	return client;
}
afterEach(() => {
	for (const client of clients.splice(0)) client.clear();
	vi.unstubAllGlobals();
});

function style(key: string, name = key) {
	return { key, name, scope: 'builtin' as const };
}

it('keeps candidate searches and Workspaces in independent paginated directory caches', async () => {
	const received: URL[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		const url = new URL(request.url);
		received.push(url);
		return new Response(JSON.stringify({ items: [style('apa')], total: 1, offset: 0, limit: 30 }));
	});
	const client = queryClient();
	await client.fetchInfiniteQuery(exportCitationStylesQuery('workspace-1', 'Nature & 特刊'));
	await client.fetchInfiniteQuery(exportCitationStylesQuery('workspace-1', 'IEEE'));
	await client.fetchInfiniteQuery(exportCitationStylesQuery('workspace-2', 'IEEE'));
	await client.fetchInfiniteQuery(exportCitationStylesQuery('workspace-1', 'IEEE'));
	expect(received.map((url) => url.pathname)).toEqual([
		'/api/v1/workspaces/workspace-1/citation-styles',
		'/api/v1/workspaces/workspace-1/citation-styles',
		'/api/v1/workspaces/workspace-2/citation-styles'
	]);
	expect(received.map((url) => Object.fromEntries(url.searchParams))).toEqual([
		{ query: 'Nature & 特刊', sort: 'name', direction: 'asc', limit: '30', offset: '0' },
		{ query: 'IEEE', sort: 'name', direction: 'asc', limit: '30', offset: '0' },
		{ query: 'IEEE', sort: 'name', direction: 'asc', limit: '30', offset: '0' }
	]);
});

it('loads additional candidate pages at server offsets and deduplicates refreshed styles', async () => {
	const offsets: string[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		const url = new URL(request.url);
		const offset = url.searchParams.get('offset')!;
		offsets.push(offset);
		return new Response(
			JSON.stringify({
				items:
					offset === '0'
						? [style('apa'), style('house', 'Old name')]
						: [style('house', 'Renamed style'), style('style-31')],
				total: 31,
				offset: Number(offset),
				limit: 30
			})
		);
	});
	const client = queryClient();
	const options = exportCitationStylesQuery('workspace-1', 'Style');
	const data = await client.fetchInfiniteQuery({ ...options, pages: 2 });
	expect(offsets).toEqual(['0', '30']);
	expect(options.select?.(data)).toEqual({
		workspaceId: 'workspace-1',
		query: 'Style',
		items: [style('apa'), style('house', 'Renamed style'), style('style-31')]
	});
});

it('resolves an exact selected key separately from candidate search and Workspace caches', async () => {
	const received: URL[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		const url = new URL(request.url);
		received.push(url);
		const key = url.searchParams.get('key');
		return new Response(
			JSON.stringify({
				items: key ? [style(key)] : [],
				total: key ? 1 : 0,
				offset: 0,
				limit: key ? 1 : 30
			})
		);
	});
	const client = queryClient();
	const selection = exportCitationStyleQuery('workspace-1', 'beyond-first-page');
	expect(await client.fetchQuery(selection)).toEqual({
		workspaceId: 'workspace-1',
		key: 'beyond-first-page',
		items: [style('beyond-first-page')],
		total: 1,
		offset: 0,
		limit: 1
	});
	await client.fetchInfiniteQuery(exportCitationStylesQuery('workspace-1', 'No matches'));
	await client.fetchQuery(exportCitationStyleQuery('workspace-2', 'beyond-first-page'));
	await client.fetchQuery(exportCitationStyleQuery('workspace-1', 'ieee'));
	await client.fetchQuery(selection);
	expect(
		received
			.filter((url) => url.searchParams.has('key'))
			.map((url) => [url.pathname, Object.fromEntries(url.searchParams)])
	).toEqual([
		[
			'/api/v1/workspaces/workspace-1/citation-styles',
			{ key: 'beyond-first-page', limit: '1', offset: '0' }
		],
		[
			'/api/v1/workspaces/workspace-2/citation-styles',
			{ key: 'beyond-first-page', limit: '1', offset: '0' }
		],
		['/api/v1/workspaces/workspace-1/citation-styles', { key: 'ieee', limit: '1', offset: '0' }]
	]);
	expect(client.getQueryData(selection.queryKey)?.items).toEqual([style('beyond-first-page')]);
});

it('distinguishes an unavailable selected key from a failed refresh without clearing its snapshot', async () => {
	let failing = false;
	vi.stubGlobal('fetch', async (request: Request) => {
		if (failing)
			return new Response(JSON.stringify({ code: 'internal_error', message: 'Unavailable' }), {
				status: 500
			});
		const key = new URL(request.url).searchParams.get('key');
		return new Response(
			JSON.stringify({
				items: key === 'deleted-style' ? [] : [style(key!)],
				total: key === 'deleted-style' ? 0 : 1,
				offset: 0,
				limit: 1
			})
		);
	});
	const client = queryClient();
	const current = exportCitationStyleQuery('workspace-1', 'house-style');
	const snapshot = await client.fetchQuery(current);
	const unavailable = exportCitationStyleQuery('workspace-1', 'deleted-style');
	expect(await client.fetchQuery(unavailable)).toMatchObject({
		workspaceId: 'workspace-1',
		key: 'deleted-style',
		items: [],
		total: 0
	});
	failing = true;
	await expect(client.fetchQuery({ ...current, staleTime: 0 })).rejects.toBeInstanceOf(ApiError);
	expect(client.getQueryData(current.queryKey)).toEqual(snapshot);
	expect(client.getQueryState(current.queryKey)?.status).toBe('error');
	expect(client.getQueryState(unavailable.queryKey)?.status).toBe('success');
});
