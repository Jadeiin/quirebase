import { hashKey, type QueryClient, type QueryKey } from '@tanstack/svelte-query';
import { ApiError } from './client.js';

export function isUnavailableReadError(error: unknown): error is ApiError {
	return error instanceof ApiError && [401, 403, 404].includes(error.status);
}

/** Keep transient snapshots, but cancel and clear the feature-owned scope after access loss. */
export async function readScopedQuery<Data>(
	client: QueryClient,
	scope: QueryKey,
	queryKey: QueryKey,
	request: Promise<Data>
): Promise<Data | null> {
	try {
		return await request;
	} catch (error) {
		if (isUnavailableReadError(error)) {
			await client.cancelQueries(
				{ queryKey: scope, predicate: (query) => query.queryHash !== hashKey(queryKey) },
				{ revert: false }
			);
			client.setQueriesData({ queryKey: scope }, null, { updatedAt: 0 });
		}
		throw error;
	}
}
