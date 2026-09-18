import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';

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

export function adminSectionQuery(section: AdminSection, filters: AdminFilters) {
	return queryOptions({
		queryKey: adminKeys.section(section, filters),
		queryFn: async (): Promise<unknown> => {
			const common = { page: filters.page, search: filters.search };
			switch (section) {
				case 'users':
					return apiRequest('GET', '/admin/users', {
						params: {
							query: {
								...common,
								role: filters.filterA,
								active: filters.filterB ? filters.filterB === 'true' : undefined
							}
						}
					});
				case 'projects':
					return apiRequest('GET', '/admin/projects', {
						params: {
							query: {
								...common,
								state: filters.filterA,
								visibility: filters.filterB
							}
						}
					});
				case 'items':
					return apiRequest('GET', '/admin/items', {
						params: {
							query: {
								...common,
								has_pdf: filters.filterA ? filters.filterA === 'true' : undefined
							}
						}
					});
				case 'audit':
					return apiRequest('GET', '/admin/audit', {
						params: {
							query: {
								...common,
								action: filters.filterA,
								target_type: filters.filterB
							}
						}
					});
				case 'workflows':
					return apiRequest('GET', '/admin/workflows', {
						params: { query: { state: filters.filterA } }
					});
				case 'settings':
					return apiRequest('GET', '/admin/settings');
				case 'maintenance':
					return apiRequest('GET', '/admin/maintenance');
				default:
					return apiRequest('GET', '/admin/overview');
			}
		}
	});
}
