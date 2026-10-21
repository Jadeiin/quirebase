import type { components } from '#lib/api/schema.js';

export function readWorkspaceListState(parameters: Pick<URLSearchParams, 'get'>) {
	const page = Number(parameters.get('page') ?? 1);
	const size = Number(parameters.get('page_size'));
	return {
		search: parameters.get('q') ?? '',
		page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
		pageSize: [10, 20, 25, 50, 100].includes(size) ? size : 25
	};
}

export function workspaceListParameters(search: string, page = 1, pageSize = 25, current?: string) {
	const parameters = new URLSearchParams(current);
	for (const key of ['q', 'page', 'page_size']) parameters.delete(key);
	if (search) parameters.set('q', search);
	if (page > 1) parameters.set('page', String(page));
	if (pageSize !== 25) parameters.set('page_size', String(pageSize));
	return parameters.toString();
}
export const workspaceRoles: components['schemas']['WorkspaceRole'][] = [
	'owner',
	'admin',
	'editor',
	'reviewer',
	'viewer'
];

export const workspaceInvitationRoles: components['schemas']['WorkspaceInvitationRole'][] = [
	'admin',
	'editor',
	'reviewer',
	'viewer'
];

export type WorkspaceListDirection = 'asc' | 'desc';

export function readWorkspaceMembersState(
	parameters: Pick<URLSearchParams, 'get'>,
	governance: boolean
) {
	const role = parameters.get('role');
	const state = parameters.get('state');
	return {
		...readWorkspaceListState(parameters),
		role: workspaceRoles.find((choice) => choice === role) ?? '',
		state: governance && (state === 'active' || state === 'suspended') ? state : '',
		sort: governance && parameters.get('sort') === 'joined' ? 'joined' : 'username',
		direction: parameters.get('direction') === 'desc' ? 'desc' : 'asc'
	} as const;
}

export type WorkspaceMembersState = ReturnType<typeof readWorkspaceMembersState>;

export function workspaceMemberParameters(state: WorkspaceMembersState) {
	const parameters = new URLSearchParams(
		workspaceListParameters(state.search, state.page, state.pageSize)
	);
	if (state.role) parameters.set('role', state.role);
	if (state.state) parameters.set('state', state.state);
	if (state.sort !== 'username') parameters.set('sort', state.sort);
	if (state.direction !== 'asc') parameters.set('direction', state.direction);
	return parameters.toString();
}

export function defaultInvitationDirection(sort: 'username' | 'created' | 'expires') {
	return sort === 'created' ? 'desc' : 'asc';
}

export function readWorkspaceInvitationsState(parameters: Pick<URLSearchParams, 'get'>) {
	const role = parameters.get('role');
	const requestedSort = parameters.get('sort');
	const sort =
		requestedSort === 'username' || requestedSort === 'expires' ? requestedSort : 'created';
	const direction = parameters.get('direction');
	return {
		...readWorkspaceListState(parameters),
		role: workspaceInvitationRoles.find((choice) => choice === role) ?? '',
		sort,
		direction:
			direction === 'asc' || direction === 'desc' ? direction : defaultInvitationDirection(sort)
	} as const;
}

export type WorkspaceInvitationsState = ReturnType<typeof readWorkspaceInvitationsState>;

export function workspaceInvitationParameters(state: WorkspaceInvitationsState) {
	const parameters = new URLSearchParams(
		workspaceListParameters(state.search, state.page, state.pageSize)
	);
	if (state.role) parameters.set('role', state.role);
	if (state.sort !== 'created') parameters.set('sort', state.sort);
	if (state.direction !== defaultInvitationDirection(state.sort))
		parameters.set('direction', state.direction);
	return parameters.toString();
}
