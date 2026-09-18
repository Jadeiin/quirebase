import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';
import type { components } from '$lib/api/schema';

export type AdminSection =
	'overview' | 'users' | 'projects' | 'items' | 'audit' | 'workflows' | 'settings' | 'maintenance';

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
		queryFn: () => apiRequest('GET', '/admin/overview')
	});
}

export function adminUsersQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('users', filters),
		enabled,
		queryFn: () =>
			apiRequest('GET', '/admin/users', {
				params: {
					query: {
						page: filters.page,
						search: filters.search,
						role: filters.filterA,
						active: filters.filterB ? filters.filterB === 'true' : undefined
					}
				}
			})
	});
}

export function adminProjectsQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('projects', filters),
		enabled,
		queryFn: () =>
			apiRequest('GET', '/admin/projects', {
				params: {
					query: {
						page: filters.page,
						search: filters.search,
						state: filters.filterA,
						visibility: filters.filterB
					}
				}
			})
	});
}

export function adminItemsQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('items', filters),
		enabled,
		queryFn: () =>
			apiRequest('GET', '/admin/items', {
				params: {
					query: {
						page: filters.page,
						search: filters.search,
						has_pdf: filters.filterA ? filters.filterA === 'true' : undefined
					}
				}
			})
	});
}

export function adminAuditQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('audit', filters),
		enabled,
		queryFn: () =>
			apiRequest('GET', '/admin/audit', {
				params: {
					query: {
						page: filters.page,
						search: filters.search,
						action: filters.filterA,
						target_type: filters.filterB
					}
				}
			})
	});
}

export function adminWorkflowsQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('workflows', filters),
		enabled,
		queryFn: () =>
			apiRequest('GET', '/admin/workflows', {
				params: { query: { state: filters.filterA } }
			})
	});
}

export function adminSettingsQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('settings', filters),
		enabled,
		queryFn: () => apiRequest('GET', '/admin/settings')
	});
}

export function adminMaintenanceQuery(filters: AdminFilters, enabled = true) {
	return queryOptions({
		queryKey: adminKeys.section('maintenance', filters),
		enabled,
		queryFn: () => apiRequest('GET', '/admin/maintenance')
	});
}

export type AdminOverview = components['schemas']['AdminOverviewView'];
export type AdminUsers = components['schemas']['AdminUsersView'];
export type AdminProjects = components['schemas']['AdminProjectsView'];
export type AdminItems = components['schemas']['AdminItemsView'];
export type AdminAudit = components['schemas']['AdminAuditView'];
export type AdminWorkflows = components['schemas']['AdminWorkflowsView'];
export type AdminSettings = components['schemas']['AdminSettingsView'];
export type AdminMaintenance = components['schemas']['AdminMaintenanceView'];
