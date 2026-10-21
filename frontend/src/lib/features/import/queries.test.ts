// @vitest-environment jsdom
import { CancelledError, QueryClient } from '@tanstack/svelte-query';
import { afterEach, expect, it, vi } from 'vitest';
import {
	libraryFacetsQuery,
	libraryListQuery,
	type LibraryFacets,
	type LibrarySearch
} from '#lib/features/library/queries.js';
import { deleteImportBatch } from './mutations.js';
import { importBatchQuery, importBatchResponseWriter, type ImportBatch } from './queries.js';

const batch: ImportBatch = {
	id: 'batch-1',
	file_format: 'metadata',
	status: 'committed',
	workflow_id: null,
	records: [],
	errors: [],
	committed_item_ids: ['item-1'],
	created_at: '2026-10-21T00:00:00Z'
};
const snapshot: LibrarySearch = {
	items: [
		{
			id: 'item-1',
			title_html: 'Imported Item',
			authors: [],
			publication_date: null,
			publication_title: null,
			doi: null,
			version: 1
		}
	],
	total: 1,
	limit: 25,
	offset: 0
};
const facets: LibraryFacets = { authors: [], keywords: [], reference_types: [] };
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

function receiptCaches(workspaceId: string, batchId: string) {
	return [
		{
			key: libraryListQuery(workspaceId, { import_batch: batchId }, 1).queryKey,
			data: snapshot
		},
		{
			key: libraryListQuery(
				workspaceId,
				{ import_batch: batchId, sort: 'title', project: 'project-1' },
				2,
				10
			).queryKey,
			data: snapshot
		},
		{ key: libraryFacetsQuery(workspaceId, { import_batch: batchId }).queryKey, data: facets },
		{
			key: libraryFacetsQuery(
				workspaceId,
				{ import_batch: batchId, year: '2025', sort: 'author', direction: 'asc' },
				3,
				50
			).queryKey,
			data: facets
		}
	];
}

it.each(['ready', 'failed'] as const)(
	'keeps a newer %s preparation snapshot when its retry response arrives late',
	async (status) => {
		const client = queryClient();
		const preview = importBatchQuery('workspace-1', batch.id);
		const failed: ImportBatch = {
			...batch,
			status: 'failed',
			workflow_id: 'old-attempt',
			committed_item_ids: []
		};
		client.setQueryData(preview.queryKey, failed);
		const acceptRetry = await importBatchResponseWriter(client, 'workspace-1', batch.id);
		const pending: ImportBatch = { ...failed, status: 'pending', workflow_id: 'new-attempt' };
		const latest: ImportBatch = { ...pending, status };
		vi.stubGlobal('fetch', async () => new Response(JSON.stringify(latest)));
		await client.fetchQuery(preview);

		expect(acceptRetry(pending)).toBe(false);
		expect(client.getQueryData(preview.queryKey)).toEqual(latest);
		const acceptCreated = await importBatchResponseWriter(client, 'workspace-1');
		expect(acceptCreated(pending)).toBe(false);
		expect(client.getQueryData(preview.queryKey)).toEqual(latest);
	}
);

it('accepts a retry response when the original failed snapshot is unchanged', async () => {
	const client = queryClient();
	const preview = importBatchQuery('workspace-1', batch.id);
	const failed: ImportBatch = { ...batch, status: 'failed', committed_item_ids: [] };
	client.setQueryData(preview.queryKey, failed);
	const acceptRetry = await importBatchResponseWriter(client, 'workspace-1', batch.id);
	const pending: ImportBatch = { ...failed, status: 'pending', workflow_id: 'new-attempt' };
	expect(acceptRetry(pending)).toBe(true);
	expect(client.getQueryData(preview.queryKey)).toEqual(pending);
});

it.each([401, 403, 404])(
	'purges the unavailable receipt and all its Library projections after HTTP %i',
	async (status) => {
		vi.stubGlobal(
			'fetch',
			async () =>
				new Response(JSON.stringify({ code: 'import_batch_unavailable', message: 'Unavailable' }), {
					status
				})
		);
		const client = queryClient();
		const preview = importBatchQuery('workspace-1', batch.id);
		const related = receiptCaches('workspace-1', batch.id);
		const unrelated = [
			...receiptCaches('workspace-1', 'batch-2'),
			...receiptCaches('workspace-2', batch.id),
			{ key: libraryListQuery('workspace-1', {}, 1).queryKey, data: snapshot },
			{ key: libraryFacetsQuery('workspace-1', { project: 'project-1' }).queryKey, data: facets }
		];
		client.setQueryData(preview.queryKey, batch);
		for (const { key, data } of [...related, ...unrelated])
			client.setQueryData<LibrarySearch | LibraryFacets>(key, data);
		await expect(client.fetchQuery(preview)).rejects.toMatchObject({ status });
		expect(client.getQueryData(preview.queryKey)).toBeNull();
		for (const { key } of related) {
			expect(client.getQueryData(key)).toBeNull();
			expect(client.getQueryState(key)?.dataUpdatedAt).toBe(0);
		}
		for (const { key, data } of unrelated) expect(client.getQueryData(key)).toEqual(data);
	}
);

it('cancels outstanding Library list and facet reads before unavailable receipt data can return', async () => {
	const requests: Request[] = [];
	const releases: Array<() => void> = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		if (new URL(request.url).pathname.endsWith('/imports/batch-1'))
			return new Response(
				JSON.stringify({ code: 'import_batch_unavailable', message: 'Unavailable' }),
				{ status: 404 }
			);
		requests.push(request);
		return new Promise<Response>((resolve) => {
			releases.push(() =>
				resolve(
					new Response(
						JSON.stringify(new URL(request.url).pathname.endsWith('/facets') ? facets : snapshot)
					)
				)
			);
		});
	});
	const client = queryClient();
	const list = libraryListQuery('workspace-1', { import_batch: batch.id }, 1);
	const facetQuery = libraryFacetsQuery('workspace-1', { import_batch: batch.id });
	client.setQueryData(list.queryKey, snapshot);
	client.setQueryData(facetQuery.queryKey, facets);
	const pending = [
		client.fetchQuery(list).catch((reason: unknown) => reason),
		client.fetchQuery(facetQuery).catch((reason: unknown) => reason)
	];
	try {
		await vi.waitFor(() => expect(requests).toHaveLength(2));
		await expect(
			client.fetchQuery(importBatchQuery('workspace-1', batch.id))
		).rejects.toMatchObject({ status: 404 });
		for (const request of requests) expect(request.signal.aborted).toBe(true);
		for (const release of releases) release();
		for (const outcome of await Promise.all(pending))
			expect(outcome).toBeInstanceOf(CancelledError);
		expect(client.getQueryData(list.queryKey)).toBeNull();
		expect(client.getQueryData(facetQuery.queryKey)).toBeNull();
	} finally {
		for (const release of releases) release();
	}
});

it('purges receipt caches when a status read confirms deletion after a lost response', async () => {
	const requests: string[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		requests.push(request.method);
		if (request.method === 'DELETE') throw new TypeError('Response lost');
		return new Response(
			JSON.stringify({ code: 'import_batch_unavailable', message: 'Unavailable' }),
			{ status: 404 }
		);
	});
	const client = queryClient();
	const related = receiptCaches('workspace-1', batch.id);
	for (const { key, data } of related)
		client.setQueryData<LibrarySearch | LibraryFacets>(key, data);
	await expect(deleteImportBatch(client, 'workspace-1', batch.id)).resolves.toBeUndefined();
	expect(requests).toEqual(['DELETE', 'GET']);
	for (const { key } of related) expect(client.getQueryData(key)).toBeNull();
});

it.each([0, 429, 500])(
	'retains previews and Library snapshots after transient failure %i',
	async (status) => {
		vi.stubGlobal('fetch', async () => {
			if (!status) throw new TypeError('Offline');
			return new Response(
				JSON.stringify({ code: 'request_failed', message: 'Temporary failure' }),
				{
					status
				}
			);
		});
		const client = queryClient();
		const preview = importBatchQuery('workspace-1', batch.id);
		const related = receiptCaches('workspace-1', batch.id);
		client.setQueryData(preview.queryKey, batch);
		for (const { key, data } of related)
			client.setQueryData<LibrarySearch | LibraryFacets>(key, data);
		await expect(client.fetchQuery(preview)).rejects.toBeInstanceOf(Error);
		expect(client.getQueryData(preview.queryKey)).toEqual(batch);
		for (const { key, data } of related) expect(client.getQueryData(key)).toEqual(data);
	}
);
