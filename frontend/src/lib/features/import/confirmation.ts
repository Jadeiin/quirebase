import type { QueryClient } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import { readImportBatch, importBatchResponseWriter, type ImportBatch } from './queries.js';

export type ImportConfirmation =
	| { status: 'committed'; batch: ImportBatch }
	| { status: 'uncommitted'; batch: ImportBatch; error: unknown }
	| { status: 'unknown'; error: unknown };

export async function confirmImportBatch(
	client: QueryClient,
	workspaceId: string,
	batchId: string,
	basicSourceIds: string[] = []
): Promise<ImportConfirmation> {
	const cacheBatch = await importBatchResponseWriter(client, workspaceId, batchId);
	let committed: ImportBatch;
	try {
		committed = await createWorkspaceApi(workspaceId).request(
			'POST',
			'/workspaces/{workspace_id}/imports/{batch_id}/commit',
			{
				params: { path: { batch_id: batchId } },
				body: { basic_source_ids: basicSourceIds }
			}
		);
	} catch (error) {
		try {
			const latest = await readImportBatch(client, workspaceId, batchId);
			return latest.status === 'committed'
				? { status: 'committed', batch: latest }
				: { status: 'uncommitted', batch: latest, error };
		} catch (error) {
			return { status: 'unknown', error };
		}
	}
	cacheBatch(committed);
	return { status: 'committed', batch: committed };
}
