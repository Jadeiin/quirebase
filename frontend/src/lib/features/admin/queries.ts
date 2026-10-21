import { hashKey, queryOptions, type QueryClient, type QueryKey } from '@tanstack/svelte-query';
import { ApiError, apiRequest } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';
import { isAdminUnavailableError } from './read-state';

export type AdminSection =
	| 'overview'
	| 'users'
	| 'invitations'
	| 'workspaces'
	| 'audit'
	| 'workflows'
	| 'settings'
	| 'maintenance';

import type { AdminFilters } from './list-state';
export type { AdminFilters } from './list-state';

export const adminKeys = {
	section: (section: AdminSection, filters: AdminFilters) => ['admin', section, filters] as const,
	workflowDetail: (workflowId: string) => ['admin', 'workflows', 'detail', workflowId] as const,
	workspace: (workspaceId: string) => ['admin', 'workspaces', 'detail', workspaceId] as const,
	workspaceOptions: (search: string) => ['admin', 'workspaces', 'options', search] as const
};

// A denied administrative read cannot leave other cached pages looking successful.
async function readAdmin<Data>(
	client: QueryClient,
	section: AdminSection,
	queryKey: QueryKey,
	request: Promise<Data>,
	notFoundScope: 'section' | 'query' = 'section'
): Promise<Data | null> {
	try {
		return await request;
	} catch (error) {
		if (isAdminUnavailableError(error)) {
			const missingResource =
				notFoundScope === 'query' && error instanceof ApiError && error.status === 404;
			const scope = { queryKey: missingResource ? queryKey : ['admin', section] };
			await client.cancelQueries(
				{ ...scope, predicate: (query) => query.queryHash !== hashKey(queryKey) },
				{ revert: false }
			);
			client.setQueriesData(scope, null, { updatedAt: 0 });
		}
		throw error;
	}
}

export function adminOverviewQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('overview', filters),
		enabled,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(
				client,
				'overview',
				queryKey,
				apiRequest('GET', '/admin/overview', {
					params: {
						query: { limit: filters.pageSize, offset: (filters.page - 1) * filters.pageSize }
					},
					signal
				})
			)
	});
}

export function adminUsersQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('users', filters),
		enabled,
		staleTime: 0,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(
				client,
				'users',
				queryKey,
				apiRequest('GET', '/admin/users', {
					params: {
						query: {
							limit: filters.pageSize,
							offset: (filters.page - 1) * filters.pageSize,
							search: filters.search,
							sort: filters.sort === 'created' ? 'created' : 'username',
							direction: filters.direction,
							role: filters.role,
							active: filters.active ? filters.active === 'true' : undefined
						}
					},
					signal
				})
			)
	});
}

export type InvitationState = components['schemas']['AdminInvitationView']['state'];

export function adminInvitationsQuery(filters: AdminFilters) {
	return queryOptions({
		queryKey: adminKeys.section('invitations', filters),
		staleTime: 0,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(
				client,
				'invitations',
				queryKey,
				apiRequest('GET', '/admin/invitations', {
					params: {
						query: {
							limit: filters.pageSize,
							offset: (filters.page - 1) * filters.pageSize,
							state: filters.invitationState as InvitationState | '',
							search: filters.search,
							role: filters.role,
							sort:
								filters.sort === 'expires' || filters.sort === 'username'
									? filters.sort
									: 'created',
							direction: filters.direction
						}
					},
					signal
				})
			)
	});
}

export function adminWorkspacesQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('workspaces', filters),
		enabled,
		staleTime: 0,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(
				client,
				'workspaces',
				queryKey,
				apiRequest('GET', '/admin/workspaces', {
					params: {
						query: {
							search: filters.search,
							state: filters.workspaceState,
							frozen: filters.frozen ? filters.frozen === 'true' : undefined,
							owner_active: filters.ownerActive ? filters.ownerActive === 'true' : undefined,
							sort: filters.sort === 'owner' || filters.sort === 'created' ? filters.sort : 'name',
							direction: filters.direction,
							limit: filters.pageSize,
							offset: (filters.page - 1) * filters.pageSize
						}
					},
					signal
				})
			)
	});
}

export function adminWorkspaceQuery(workspaceId: string, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.workspace(workspaceId),
		enabled: enabled && Boolean(workspaceId),
		staleTime: 0,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(
				client,
				'workspaces',
				queryKey,
				apiRequest('GET', '/admin/workspaces/{workspace_id}', {
					params: { path: { workspace_id: workspaceId } },
					signal
				})
			)
	});
}

export function adminWorkspaceOptionsQuery(search: string, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.workspaceOptions(search),
		enabled,
		staleTime: 0,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(
				client,
				'workspaces',
				queryKey,
				apiRequest('GET', '/admin/workspaces', {
					params: { query: { search, limit: 20, offset: 0, sort: 'name', direction: 'asc' } },
					signal
				})
			)
	});
}

export function adminAuditQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('audit', filters),
		enabled,
		staleTime: 0,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(
				client,
				'audit',
				queryKey,
				apiRequest('GET', '/admin/audit', {
					params: {
						query: {
							limit: filters.pageSize,
							offset: (filters.page - 1) * filters.pageSize,
							search: filters.search,
							direction: filters.direction,
							action: filters.action,
							target_type: filters.targetType
						}
					},
					signal
				})
			)
	});
}

export function adminWorkflowsQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('workflows', filters),
		enabled,
		// Workflow states and totals can change while navigating history.
		staleTime: 0,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(
				client,
				'workflows',
				queryKey,
				apiRequest('GET', '/admin/workflows', {
					params: {
						query: {
							state: filters.workflowState,
							name: filters.workflowName,
							direction: filters.direction,
							limit: filters.pageSize,
							offset: (filters.page - 1) * filters.pageSize
						}
					},
					signal
				})
			)
	});
}

export function adminWorkflowDetailQuery(workflowId: string) {
	return queryOptions({
		queryKey: adminKeys.workflowDetail(workflowId),
		staleTime: 0,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(
				client,
				'workflows',
				queryKey,
				apiRequest('GET', '/admin/workflows/{workflow_id}', {
					params: { path: { workflow_id: workflowId } },
					signal
				}),
				'query'
			),
		retry: (count, error) => !isAdminUnavailableError(error) && count < 2
	});
}

export function adminSettingsQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('settings', filters),
		enabled,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(client, 'settings', queryKey, apiRequest('GET', '/admin/settings', { signal }))
	});
}

export function adminMaintenanceQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('maintenance', filters),
		enabled,
		queryFn: ({ signal, client, queryKey }) =>
			readAdmin(
				client,
				'maintenance',
				queryKey,
				apiRequest('GET', '/admin/maintenance', { signal })
			)
	});
}

export type AdminOverview = components['schemas']['AdminOverviewView'];
export type AdminUsers = components['schemas']['AdminUsersView'];
export type AdminWorkspaces = components['schemas']['OffsetPagination_AdminWorkspaceView_'];
export type AdminAudit = components['schemas']['OffsetPagination_AdminAuditEventView_'];
export type AdminWorkflows = components['schemas']['OffsetPagination_WorkflowSummaryView_'];
export type AdminSettings = components['schemas']['AdminSettingsView'];
export type AdminMaintenance = components['schemas']['StorageMetricsView'];
