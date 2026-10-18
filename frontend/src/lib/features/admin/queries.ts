import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '#lib/api/client.js';
import type { components } from '#lib/api/schema.js';

export type AdminSection =
	| 'overview'
	| 'users'
	| 'invitations'
	| 'workspaces'
	| 'audit'
	| 'workflows'
	| 'settings'
	| 'maintenance';

export type AdminFilters = {
	page: number;
	pageSize: number;
	search: string;
	filterA: string;
	filterB: string;
};

export const adminKeys = {
	section: (section: AdminSection, filters: AdminFilters) => ['admin', section, filters] as const
};

export function adminOverviewQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('overview', filters),
		enabled,
		queryFn: ({ signal }) =>
			apiRequest('GET', '/admin/overview', {
				params: {
					query: { limit: filters.pageSize, offset: (filters.page - 1) * filters.pageSize }
				},
				signal
			})
	});
}

export function adminUsersQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('users', filters),
		enabled,
		queryFn: ({ signal }) =>
			apiRequest('GET', '/admin/users', {
				params: {
					query: {
						limit: filters.pageSize,
						offset: (filters.page - 1) * filters.pageSize,
						search: filters.search,
						role: filters.filterA,
						active: filters.filterB ? filters.filterB === 'true' : undefined
					}
				},
				signal
			})
	});
}

export type InvitationState = components['schemas']['AdminInvitationView']['state'];

export function adminInvitationsQuery(page: number, pageSize: number, state: InvitationState | '') {
	return queryOptions({
		queryKey: ['admin', 'invitations', page, pageSize, state],
		staleTime: 0,
		queryFn: ({ signal }) =>
			apiRequest('GET', '/admin/invitations', {
				params: { query: { limit: pageSize, offset: (page - 1) * pageSize, state } },
				signal
			})
	});
}

export function adminWorkspacesQuery() {
	return queryOptions({
		queryKey: ['admin', 'workspaces'],
		queryFn: ({ signal }) => apiRequest('GET', '/admin/workspaces', { signal })
	});
}

export function adminAuditQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('audit', filters),
		enabled,
		queryFn: ({ signal }) =>
			apiRequest('GET', '/admin/audit', {
				params: {
					query: {
						limit: filters.pageSize,
						offset: (filters.page - 1) * filters.pageSize,
						search: filters.search,
						action: filters.filterA,
						target_type: filters.filterB
					}
				},
				signal
			})
	});
}

export function adminWorkflowsQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('workflows', filters),
		enabled,
		// Workflow states and totals can change while navigating history.
		staleTime: 0,
		queryFn: ({ signal }) =>
			apiRequest('GET', '/admin/workflows', {
				params: {
					query: {
						state: filters.filterA,
						limit: filters.pageSize,
						offset: (filters.page - 1) * filters.pageSize
					}
				},
				signal
			})
	});
}

export function adminSettingsQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('settings', filters),
		enabled,
		queryFn: ({ signal }) => apiRequest('GET', '/admin/settings', { signal })
	});
}

export function adminMaintenanceQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('maintenance', filters),
		enabled,
		queryFn: ({ signal }) => apiRequest('GET', '/admin/maintenance', { signal })
	});
}

export type AdminOverview = components['schemas']['AdminOverviewView'];
export type AdminUsers = components['schemas']['AdminUsersView'];
export type AdminWorkspaces = components['schemas']['AdminWorkspaceView'][];
export type AdminAudit = components['schemas']['OffsetPagination_AdminAuditEventView_'];
export type AdminWorkflows = components['schemas']['OffsetPagination_WorkflowSummaryView_'];
export type AdminSettings = components['schemas']['AdminSettingsView'];
export type AdminMaintenance = components['schemas']['AdminMaintenanceView'];
