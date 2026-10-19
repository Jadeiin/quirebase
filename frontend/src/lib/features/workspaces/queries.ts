import { queryOptions } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export type GovernanceMember = components['schemas']['WorkspaceGovernanceMemberView'];
export type MemberRow = components['schemas']['WorkspaceMemberDirectoryView'] & {
	governance?: GovernanceMember;
};

export function workspaceMembersQuery(
	workspaceId: string,
	governance: boolean,
	page: number,
	pageSize: number,
	search: string
) {
	const api = createWorkspaceApi(workspaceId);
	const query = { limit: pageSize, offset: (page - 1) * pageSize, search };
	return queryOptions({
		queryKey: [
			...(governance
				? workspaceKeys.governanceMembers(workspaceId)
				: workspaceKeys.members(workspaceId)),
			query
		],
		queryFn: async ({ signal }) => {
			if (governance) {
				const result = await api.request('GET', '/workspaces/{workspace_id}/governance/members', {
					params: { query },
					signal
				});
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
		}
	});
}

export function workspaceInvitationsQuery(workspaceId: string) {
	const api = createWorkspaceApi(workspaceId);
	return queryOptions({
		queryKey: workspaceKeys.invitations(workspaceId),
		queryFn: ({ signal }) =>
			api.request('GET', '/workspaces/{workspace_id}/invitations', { signal })
	});
}
