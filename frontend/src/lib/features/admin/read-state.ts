import { ApiError } from '#lib/api/client.js';

export function isAdminUnavailableError(error: unknown): boolean {
	return error instanceof ApiError && [401, 403, 404].includes(error.status);
}

export function adminReadState({
	loading,
	failed,
	available,
	error
}: {
	loading: boolean;
	failed: boolean;
	available?: boolean;
	error?: unknown;
}): 'loading' | 'unavailable' | 'stale' | 'ready' {
	if (isAdminUnavailableError(error)) return 'unavailable';
	if (available ?? (!loading && !failed)) return failed ? 'stale' : 'ready';
	return loading ? 'loading' : 'unavailable';
}
