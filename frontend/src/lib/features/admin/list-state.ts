import type { AdminSection } from './queries';

export function readAdminFilters(parameters: Pick<URLSearchParams, 'get'>, section: AdminSection) {
	const page = Number(parameters.get('page') ?? 1);
	const size = Number(parameters.get('page_size'));
	const role = parameters.get('role');
	const active = parameters.get('active');
	const state = parameters.get('state') ?? '';
	return {
		page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
		pageSize: [10, 20, 25, 50, 100].includes(size)
			? size
			: section === 'overview'
				? 10
				: section === 'audit'
					? 50
					: 20,
		search: ['users', 'workspaces', 'audit'].includes(section) ? (parameters.get('q') ?? '') : '',
		role: section === 'users' && (role === 'member' || role === 'administrator') ? role : '',
		active: section === 'users' && (active === 'true' || active === 'false') ? active : '',
		action: section === 'audit' ? (parameters.get('action') ?? '') : '',
		targetType: section === 'audit' ? (parameters.get('target_type') ?? '') : '',
		workflowState:
			section === 'workflows' &&
			['pending', 'running', 'succeeded', 'failed', 'cancelled'].includes(state)
				? state
				: ''
	};
}

export type AdminFilters = ReturnType<typeof readAdminFilters>;

export function adminListParameters(filters: AdminFilters, section: AdminSection) {
	const parameters = new URLSearchParams();
	const defaultSize = section === 'overview' ? 10 : section === 'audit' ? 50 : 20;
	if (filters.page > 1) parameters.set('page', String(filters.page));
	if (filters.pageSize !== defaultSize) parameters.set('page_size', String(filters.pageSize));
	if (filters.search) parameters.set('q', filters.search);
	if (section === 'users') {
		if (filters.role) parameters.set('role', filters.role);
		if (filters.active) parameters.set('active', filters.active);
	}
	if (section === 'audit') {
		if (filters.action) parameters.set('action', filters.action);
		if (filters.targetType) parameters.set('target_type', filters.targetType);
	}
	if (section === 'workflows' && filters.workflowState)
		parameters.set('state', filters.workflowState);
	return parameters.toString();
}
