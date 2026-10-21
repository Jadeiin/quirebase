function readPagination(parameters: Pick<URLSearchParams, 'get'>) {
	const page = Number(parameters.get('page') ?? 1);
	const size = Number(parameters.get('page_size'));
	return {
		search: parameters.get('q') ?? '',
		page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
		pageSize: [10, 20, 25, 50, 100].includes(size) ? size : 25
	};
}

export function defaultProjectSortDirection(sort: 'name' | 'created' | 'updated') {
	return sort === 'name' ? 'asc' : 'desc';
}

export function readProjectListState(parameters: Pick<URLSearchParams, 'get'>) {
	const view = parameters.get('view');
	const state = parameters.get('state');
	const requestedSort = parameters.get('sort');
	const sort = requestedSort === 'created' || requestedSort === 'updated' ? requestedSort : 'name';
	const direction = parameters.get('direction');
	return {
		...readPagination(parameters),
		view: view === 'mine' || view === 'joinable' ? view : 'all',
		state: state === 'active' || state === 'archived' ? state : '',
		sort,
		direction:
			direction === 'asc' || direction === 'desc' ? direction : defaultProjectSortDirection(sort)
	} as const;
}

export type ProjectListState = ReturnType<typeof readProjectListState>;

function paginationParameters(state: ReturnType<typeof readPagination>) {
	const parameters = new URLSearchParams();
	if (state.search) parameters.set('q', state.search);
	if (state.page > 1) parameters.set('page', String(state.page));
	if (state.pageSize !== 25) parameters.set('page_size', String(state.pageSize));
	return parameters;
}

export function projectListParameters(state: ProjectListState) {
	const parameters = paginationParameters(state);
	if (state.view !== 'all') parameters.set('view', state.view);
	if (state.state) parameters.set('state', state.state);
	if (state.sort !== 'name') parameters.set('sort', state.sort);
	if (state.direction !== defaultProjectSortDirection(state.sort))
		parameters.set('direction', state.direction);
	return parameters.toString();
}

// Project detail retains the existing Library-link parameters; directory sorting is independent.
export function readProjectItemListState(parameters: Pick<URLSearchParams, 'get'>) {
	const sort = parameters.get('sort');
	return {
		...readPagination(parameters),
		sort: sort === 'created' || sort === 'title' ? sort : 'updated'
	} as const;
}

export type ProjectItemListState = ReturnType<typeof readProjectItemListState>;

export function projectItemListParameters(state: ProjectItemListState) {
	const parameters = paginationParameters(state);
	if (state.sort !== 'updated') parameters.set('sort', state.sort);
	return parameters.toString();
}
