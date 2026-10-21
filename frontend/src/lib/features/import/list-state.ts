import { workspaceHref } from '#lib/workspaces/href.js';

export type ImportListState = {
	view: 'pending' | 'completed';
	page: number;
	pageSize: number;
};

export function readImportListState(parameters: Pick<URLSearchParams, 'get'>): ImportListState {
	const page = Number(parameters.get('page') ?? 1);
	const size = Number(parameters.get('page_size'));
	return {
		view: parameters.get('view') === 'completed' ? 'completed' : 'pending',
		page: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
		pageSize: [10, 20, 25, 50, 100].includes(size) ? size : 20
	};
}

export function importListParameters(state: ImportListState, current?: URLSearchParams) {
	const parameters = new URLSearchParams(current);
	for (const key of ['view', 'page', 'page_size']) parameters.delete(key);
	if (state.view === 'completed') parameters.set('view', state.view);
	if (state.page > 1) parameters.set('page', String(state.page));
	if (state.pageSize !== 20) parameters.set('page_size', String(state.pageSize));
	return parameters;
}

/** Only this feature's list state can select the return destination. */
export function importReturnHref(
	workspaceId: string,
	parameters: Pick<URLSearchParams, 'get' | 'toString'>
) {
	if (parameters.get('from') !== 'history') return workspaceHref(workspaceId, 'import');
	const listing = importListParameters(
		readImportListState(parameters),
		new URLSearchParams(parameters.toString())
	);
	listing.delete('batch');
	listing.delete('from');
	const query = listing.toString();
	return workspaceHref(workspaceId, `import/history${query ? `?${query}` : ''}`);
}
