import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';
import type { components } from '$lib/api/schema';

export type AdminSection =
	'overview' | 'users' | 'workspaces' | 'audit' | 'workflows' | 'settings' | 'maintenance';

export type AdminFilters = {
	page: number;
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
		queryFn: ({ signal }) => apiRequest('GET', '/admin/overview', { signal })
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
						page: filters.page,
						search: filters.search,
						role: filters.filterA,
						active: filters.filterB ? filters.filterB === 'true' : undefined
					}
				},
				signal
			})
	});
}

export function adminWorkspacesQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('workspaces', filters),
		enabled,
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
						page: filters.page,
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
		queryFn: ({ signal }) =>
			apiRequest('GET', '/admin/workflows', {
				params: { query: { state: filters.filterA } },
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
export type AdminAudit = components['schemas']['AdminAuditView'];
export type AdminWorkflows = components['schemas']['AdminWorkflowsView'];
export type AdminSettings = components['schemas']['AdminSettingsView'];
export type AdminMaintenance = components['schemas']['AdminMaintenanceView'];
