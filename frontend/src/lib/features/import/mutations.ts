import type { QueryClient } from '@tanstack/svelte-query';
import { ApiError, createWorkspaceApi, type ApiResponse } from '#lib/api/client.js';
import { invalidateUnavailableImportReceipt } from '#lib/query/invalidation.js';
import { importBatchQuery, importKeys, readImportBatch } from './queries.js';

type BatchList = ApiResponse<'/workspaces/{workspace_id}/imports', 'get'>;

async function retireBatch(client: QueryClient, workspaceId: string, batchId: string) {
	const preview = importBatchQuery(workspaceId, batchId);
	const lists = { queryKey: importKeys.lists(workspaceId) };
	await Promise.all([
		client.cancelQueries({ queryKey: preview.queryKey, exact: true }),
		client.cancelQueries(lists)
	]);
	client.setQueryData(preview.queryKey, null, { updatedAt: 0 });
	await invalidateUnavailableImportReceipt(client, workspaceId, batchId);
	client.setQueriesData<BatchList | null>(lists, (data) => {
		if (!data) return data;
		const items = data.items.filter((row) => row.id !== batchId);
		return { ...data, items, total: data.total - (data.items.length - items.length) };
	});
	// Other pages need a new server read because deletion changes their boundaries.
	client.removeQueries({ ...lists, type: 'inactive' });
	void client.invalidateQueries(lists);
}

/** Reconcile the captured batch even if the initiating page has unmounted. */
export async function deleteImportBatch(client: QueryClient, workspaceId: string, batchId: string) {
	try {
		await createWorkspaceApi(workspaceId).request(
			'DELETE',
			'/workspaces/{workspace_id}/imports/{batch_id}',
			{ params: { path: { batch_id: batchId } } }
		);
	} catch (error) {
		try {
			await readImportBatch(client, workspaceId, batchId);
		} catch (reason) {
			if (reason instanceof ApiError && reason.code === 'import_batch_unavailable') {
				await retireBatch(client, workspaceId, batchId);
				return;
			}
		}
		void client.invalidateQueries({ queryKey: importKeys.lists(workspaceId) });
		throw error;
	}
	await retireBatch(client, workspaceId, batchId);
}
