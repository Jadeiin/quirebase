export function readProjectListState(parameters: Pick<URLSearchParams, 'get'>) {
	const page = Number(parameters.get('page') ?? 1);
	const size = Number(parameters.get('page_size'));
	const view = parameters.get('view');
	const sort = parameters.get('sort');
	return {
		search: parameters.get('q') ?? '',
		page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
		pageSize: [10, 20, 25, 50, 100].includes(size) ? size : 25,
		view: view === 'mine' || view === 'joinable' ? view : 'all',
		sort: sort === 'created' || sort === 'title' ? sort : 'updated'
	} as const;
}

export type ProjectListState = ReturnType<typeof readProjectListState>;

export function projectListParameters(state: ProjectListState, items = false) {
	const parameters = new URLSearchParams();
	if (state.search) parameters.set('q', state.search);
	if (state.page > 1) parameters.set('page', String(state.page));
	if (state.pageSize !== 25) parameters.set('page_size', String(state.pageSize));
	if (!items && state.view !== 'all') parameters.set('view', state.view);
	if (items && state.sort !== 'updated') parameters.set('sort', state.sort);
	return parameters.toString();
}
