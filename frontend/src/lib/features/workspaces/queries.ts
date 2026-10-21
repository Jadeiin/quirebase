import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import { readScopedQuery } from '#lib/api/query-state.js';
import type { WorkspaceInvitationsState, WorkspaceMembersState } from './list-state';

export type GovernanceMember = components['schemas']['WorkspaceGovernanceMemberView'];
export type MemberRow = components['schemas']['WorkspaceMemberDirectoryView'] & {
	governance?: GovernanceMember;
};

export function workspaceMembersQuery(
	workspaceId: string,
	governance: boolean,
	state: WorkspaceMembersState
) {
	const api = createWorkspaceApi(workspaceId);
	const scope = governance
		? workspaceKeys.governanceMembers(workspaceId)
		: workspaceKeys.members(workspaceId);
	const query = {
		limit: state.pageSize,
		offset: (state.page - 1) * state.pageSize,
		search: state.search,
		role: state.role,
		direction: state.direction
	};
	const governanceQuery = { ...query, state: state.state, sort: state.sort };
	return queryOptions({
		queryKey: [...scope, governance ? governanceQuery : query],
		staleTime: 0,
		queryFn: ({ signal, client, queryKey }) =>
			readScopedQuery(
				client,
				scope,
				queryKey,
				(async () => {
					if (governance) {
						const result = await api.request(
							'GET',
							'/workspaces/{workspace_id}/governance/members',
							{
								params: { query: governanceQuery },
								signal
							}
						);
						return {
							...result,
							items: result.items.map((member): MemberRow => ({ ...member, governance: member }))
						};
					}
					const result = await api.request('GET', '/workspaces/{workspace_id}/members', {
						params: { query },
						signal
					});
					return { ...result, items: result.items as MemberRow[] };
				})()
			)
	});
}

export function workspaceInvitationsQuery(workspaceId: string, state: WorkspaceInvitationsState) {
	const api = createWorkspaceApi(workspaceId);
	const scope = workspaceKeys.invitations(workspaceId);
	const query = {
		limit: state.pageSize,
		offset: (state.page - 1) * state.pageSize,
		search: state.search,
		role: state.role,
		sort: state.sort,
		direction: state.direction
	};
	return queryOptions({
		queryKey: [...scope, query],
		staleTime: 0,
		queryFn: ({ signal, client, queryKey }) =>
			readScopedQuery(
				client,
				scope,
				queryKey,
				api.request('GET', '/workspaces/{workspace_id}/invitations', { params: { query }, signal })
			)
	});
}
