import { queryOptions, type CreateQueryResult } from '@tanstack/svelte-query';
import { createContext } from 'svelte';
import { apiRequest, type SessionView } from '$lib/api/client';

export function sessionQuery() {
	return queryOptions({
		queryKey: ['session'],
		queryFn: () => apiRequest('GET', '/session'),
		retry: false
	});
}

export type SessionContext = {
	query: CreateQueryResult<SessionView>;
	logout: () => Promise<void>;
};

const [getSession, setSession] = createContext<SessionContext>();

export { getSession, setSession };
