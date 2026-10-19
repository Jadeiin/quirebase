export function readWorkspaceListState(parameters: Pick<URLSearchParams, 'get'>) {
	const page = Number(parameters.get('page') ?? 1);
	const size = Number(parameters.get('page_size'));
	return {
		search: parameters.get('q') ?? '',
		page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
		pageSize: [10, 20, 25, 50, 100].includes(size) ? size : 25
	};
}

export function workspaceListParameters(search: string, page = 1, pageSize = 25) {
	const parameters = new URLSearchParams();
	if (search) parameters.set('q', search);
	if (page > 1) parameters.set('page', String(page));
	if (pageSize !== 25) parameters.set('page_size', String(pageSize));
	return parameters.toString();
}
