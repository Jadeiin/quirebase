import type { AdminSection } from './queries';

export function defaultAdminSortDirection(
	sort: 'username' | 'created' | 'expires' | 'name' | 'owner'
) {
	return sort === 'created' ? 'desc' : 'asc';
}

function defaultSortField(section: AdminSection) {
	return section === 'users' ? 'username' : section === 'workspaces' ? 'name' : 'created';
}

export function readAdminFilters(parameters: Pick<URLSearchParams, 'get'>, section: AdminSection) {
	const page = Number(parameters.get('page') ?? 1);
	const size = Number(parameters.get('page_size'));
	const role = parameters.get('role');
	const active = parameters.get('active');
	const state = parameters.get('state') ?? '';
	const requestedSort = parameters.get('sort');
	const defaultSort = defaultSortField(section);
	const sort =
		requestedSort === 'created' ||
		(['users', 'invitations'].includes(section) && requestedSort === 'username') ||
		(section === 'invitations' && requestedSort === 'expires') ||
		(section === 'workspaces' && (requestedSort === 'name' || requestedSort === 'owner'))
			? requestedSort
			: defaultSort;
	const direction = parameters.get('direction');
	const frozen = parameters.get('frozen');
	const ownerActive = parameters.get('owner_active');
	return {
		page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
		pageSize: [10, 20, 25, 50, 100].includes(size)
			? size
			: section === 'overview'
				? 10
				: section === 'audit'
					? 50
					: 20,
		search: ['users', 'invitations', 'workspaces', 'audit'].includes(section)
			? (parameters.get('q') ?? '')
			: '',
		role:
			['users', 'invitations'].includes(section) && (role === 'member' || role === 'administrator')
				? role
				: '',
		active: section === 'users' && (active === 'true' || active === 'false') ? active : '',
		workspaceState:
			section === 'workspaces' && (state === 'active' || state === 'archived') ? state : '',
		frozen: section === 'workspaces' && (frozen === 'true' || frozen === 'false') ? frozen : '',
		ownerActive:
			section === 'workspaces' && (ownerActive === 'true' || ownerActive === 'false')
				? ownerActive
				: '',
		sort,
		direction:
			direction === 'asc' || direction === 'desc' ? direction : defaultAdminSortDirection(sort),
		invitationState:
			section === 'invitations' && ['pending', 'accepted', 'revoked', 'expired'].includes(state)
				? state
				: '',
		workflowName: section === 'workflows' ? (parameters.get('name') ?? '') : '',
		action: section === 'audit' ? (parameters.get('action') ?? '') : '',
		targetType: section === 'audit' ? (parameters.get('target_type') ?? '') : '',
		workflowState:
			section === 'workflows' &&
			['pending', 'running', 'succeeded', 'failed', 'cancelled'].includes(state)
				? state
				: ''
	} as const;
}

export type AdminFilters = ReturnType<typeof readAdminFilters>;

export function adminListParameters(filters: AdminFilters, section: AdminSection) {
	const parameters = new URLSearchParams();
	const defaultSize = section === 'overview' ? 10 : section === 'audit' ? 50 : 20;
	if (filters.page > 1) parameters.set('page', String(filters.page));
	if (filters.pageSize !== defaultSize) parameters.set('page_size', String(filters.pageSize));
	if (filters.search) parameters.set('q', filters.search);
	if (section === 'users' || section === 'invitations') {
		if (filters.role) parameters.set('role', filters.role);
		if (section === 'users' && filters.active) parameters.set('active', filters.active);
	}
	if (section === 'invitations' && filters.invitationState)
		parameters.set('state', filters.invitationState);
	if (section === 'workspaces') {
		if (filters.workspaceState) parameters.set('state', filters.workspaceState);
		if (filters.frozen) parameters.set('frozen', filters.frozen);
		if (filters.ownerActive) parameters.set('owner_active', filters.ownerActive);
	}
	if (section === 'audit') {
		if (filters.action) parameters.set('action', filters.action);
		if (filters.targetType) parameters.set('target_type', filters.targetType);
	}
	if (section === 'workflows' && filters.workflowState)
		parameters.set('state', filters.workflowState);
	if (section === 'workflows' && filters.workflowName) parameters.set('name', filters.workflowName);
	if (['users', 'invitations', 'workspaces', 'audit', 'workflows'].includes(section)) {
		if (filters.sort !== defaultSortField(section)) parameters.set('sort', filters.sort);
		if (filters.direction !== defaultAdminSortDirection(filters.sort))
			parameters.set('direction', filters.direction);
	}
	return parameters.toString();
}
