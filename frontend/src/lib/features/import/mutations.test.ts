// @vitest-environment jsdom
import { QueryClient } from '@tanstack/svelte-query';
import { afterEach, expect, it, vi } from 'vitest';
import { libraryListQuery, type LibrarySearch } from '#lib/features/library/queries.js';
import { deleteImportBatch } from './mutations.js';
import { importBatchQuery, importBatchesQuery, type ImportBatch } from './queries.js';

const ready: ImportBatch = {
	id: 'batch-1',
	file_format: 'metadata',
	status: 'ready',
	workflow_id: null,
	can_retry: false,
	records: [],
	errors: [],
	committed_item_ids: [],
	created_at: '2026-10-21T00:00:00Z'
};
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

it('deletes a batch using the unified endpoint and retires its cached history without touching ordinary Items', async () => {
	const requests: Request[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		requests.push(request);
		return new Response(null, { status: 204 });
	});
	const client = queryClient();
	const preview = importBatchQuery('workspace-1', ready.id);
	const directory = importBatchesQuery('workspace-1', 'committed', 1, 20);
	const library = libraryListQuery('workspace-1', {}, 1);
	const committed: ImportBatch = { ...ready, status: 'committed' };
	client.setQueryData(preview.queryKey, committed);
	client.setQueryData(directory.queryKey, {
		items: [{ ...ready, record_count: 0, diagnostic_count: 0 }],
		total: 1,
		limit: 20,
		offset: 0
	});
	const librarySnapshot: LibrarySearch = {
		items: [],
		total: 0,
		limit: 25,
		offset: 0
	};
	client.setQueryData(library.queryKey, librarySnapshot);
	await deleteImportBatch(client, 'workspace-1', ready.id);
	expect(requests).toHaveLength(1);
	expect(requests[0].method).toBe('DELETE');
	expect(new URL(requests[0].url).pathname).toBe('/api/v1/workspaces/workspace-1/imports/batch-1');
	expect(client.getQueryData(preview.queryKey)).toBeNull();
	expect(client.getQueryData(directory.queryKey)).toBeUndefined();
	expect(client.getQueryData(library.queryKey)).toEqual({
		items: [],
		total: 0,
		limit: 25,
		offset: 0
	});
});

it('retains the authoritative preview and failure when deletion did not complete', async () => {
	const failure = new TypeError('Network lost');
	const methods: string[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		methods.push(request.method);
		if (request.method === 'DELETE') throw failure;
		return new Response(JSON.stringify(ready));
	});
	const client = queryClient();
	await expect(deleteImportBatch(client, 'workspace-1', ready.id)).rejects.toBe(failure);
	expect(client.getQueryData(importBatchQuery('workspace-1', ready.id).queryKey)).toEqual(ready);
	expect(methods).toEqual(['DELETE', 'GET']);
});

it('retains uncertainty when both deletion and the captured status read fail', async () => {
	const failure = new TypeError('Offline');
	vi.stubGlobal('fetch', async () => {
		throw failure;
	});
	const client = queryClient();
	const preview = importBatchQuery('workspace-1', ready.id);
	client.setQueryData(preview.queryKey, ready);
	await expect(deleteImportBatch(client, 'workspace-1', ready.id)).rejects.toBe(failure);
	expect(client.getQueryData(preview.queryKey)).toEqual(ready);
});
