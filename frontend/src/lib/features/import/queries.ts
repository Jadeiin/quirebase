import { queryOptions, replaceEqualDeep, type QueryClient } from '@tanstack/svelte-query';
import { ApiError, createWorkspaceApi } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';
import { invalidateUnavailableImportBatch } from '#lib/query/invalidation.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export type ImportBatch = components['schemas']['ImportBatchPreview'];

export const importKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'imports'] as const,
	lists: (workspaceId: string) => [...importKeys.all(workspaceId), 'list'] as const,
	batch: (workspaceId: string, batchId: string) =>
		[...importKeys.all(workspaceId), batchId] as const
};

export function importBatchesQuery(
	workspaceId: string,
	view: 'uncommitted' | 'committed',
	page: number,
	pageSize: number
) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: [...importKeys.lists(workspaceId), view, page, pageSize] as const,
		queryFn: async ({ signal, client, queryKey }) => {
			try {
				return await api.request('GET', '/workspaces/{workspace_id}/imports', {
					params: { query: { view, limit: pageSize, offset: (page - 1) * pageSize } },
					signal
				});
			} catch (reason) {
				if (reason instanceof ApiError && [401, 403, 404].includes(reason.status))
					client.setQueryData(queryKey, null, { updatedAt: 0 });
				throw reason;
			}
		},
		retry: false
	});
}

async function requestImportBatch(
	client: QueryClient,
	workspaceId: string,
	batchId: string,
	signal?: AbortSignal
) {
	const queryKey = importKeys.batch(workspaceId, batchId);
	const cache = client.getQueryCache();
	const query = cache.find({ queryKey, exact: true });
	try {
		return await createWorkspaceApi(workspaceId).request(
			'GET',
			'/workspaces/{workspace_id}/imports/{batch_id}',
			{ params: { path: { batch_id: batchId } }, signal }
		);
	} catch (reason) {
		if (
			reason instanceof ApiError &&
			[401, 403, 404].includes(reason.status) &&
			query &&
			cache.get(query.queryHash) === query
		) {
			client.setQueryData(queryKey, null, { updatedAt: 0 });
			await invalidateUnavailableImportBatch(client, workspaceId, batchId);
		}
		throw reason;
	}
}

export function importBatchQuery(workspaceId: string, batchId: string) {
	return queryOptions({
		queryKey: importKeys.batch(workspaceId, batchId),
		enabled: Boolean(batchId),
		queryFn: ({ signal, client }): Promise<ImportBatch | null> =>
			requestImportBatch(client, workspaceId, batchId, signal),
		retry: false,
		structuralSharing: (previous, next) => {
			const previousBatch = previous as ImportBatch | null | undefined;
			const incoming = next as ImportBatch | null;
			// A read started before commit may finish after its authoritative response.
			if (previousBatch?.status === 'committed' && incoming && incoming.status !== 'committed')
				return previousBatch;
			return replaceEqualDeep(previous, next);
		},
		// The batch read owns preparation recovery, including shared previews without a workflow ID.
		refetchInterval: (query) =>
			query.state.status !== 'error' && query.state.data?.status === 'pending' ? 2000 : false,
		refetchIntervalInBackground: false
	});
}

/** Command recovery owns its fresh request independently of preview observers. */
export async function readImportBatch(
	client: QueryClient,
	workspaceId: string,
	batchId: string
): Promise<ImportBatch> {
	const options = importBatchQuery(workspaceId, batchId);
	await client.cancelQueries({ queryKey: options.queryKey, exact: true });
	const cache = client.getQueryCache();
	const query = cache.build<unknown>(client, { queryKey: options.queryKey });
	const initial = query.state.dataUpdateCount;
	const batch = await requestImportBatch(client, workspaceId, batchId);
	const current = client.getQueryData(options.queryKey);
	// Fresh reads can recover an existing null, but cannot undo a newer retirement.
	if (
		cache.get(query.queryHash) === query &&
		(query.state.dataUpdateCount === initial ||
			(batch.status === 'committed' && current !== null)) &&
		(batch.status === 'committed' || current?.status !== 'committed')
	)
		client.setQueryData(options.queryKey, batch);
	const latest = client.getQueryData<ImportBatch | null>(options.queryKey);
	if (latest === null) throw new Error('Import Batch unavailable');
	return latest ?? batch;
}

/** New batches seed unread keys; known commands preserve newer snapshots and retirement. */
export async function importBatchResponseWriter(
	client: QueryClient,
	workspaceId: string,
	batchId?: string
) {
	const cache = client.getQueryCache();
	if (batchId === undefined) {
		return (batch: ImportBatch): boolean => {
			const { queryKey } = importBatchQuery(workspaceId, batch.id);
			// Discovery or a read of the new ID is already more recent than its creation.
			if (cache.find({ queryKey, exact: true })) return false;
			client.setQueryData(queryKey, batch);
			return true;
		};
	}
	const options = importBatchQuery(workspaceId, batchId);
	const query = cache.build<unknown>(client, { queryKey: options.queryKey });
	// Only reads predating the command are obsolete. Later reads may recover a deletion.
	await client.cancelQueries({ queryKey: options.queryKey, exact: true });
	const initial = query.state.data;
	return (batch: ImportBatch): boolean => {
		if (query.state.data === null || cache.get(query.queryHash) !== query) return false;
		return (
			client.setQueryData<ImportBatch | null>(options.queryKey, (current) => {
				if (current === null) return undefined;
				if (
					batch.status !== 'committed' &&
					(current?.status === 'committed' || current !== initial)
				)
					return undefined;
				return batch;
			}) !== undefined
		);
	};
}
