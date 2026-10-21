export function readToolsState(parameters: Pick<URLSearchParams, 'get'>) {
	const tool = parameters.get('tool');
	const mode = parameters.get('mode');
	const page = Number(parameters.get('tag_page') ?? 1);
	const size = Number(parameters.get('tag_size'));
	const stylePage = Number(parameters.get('style_page') ?? 1);
	const styleSize = Number(parameters.get('style_size'));
	const styleScope = parameters.get('style_scope');
	return {
		tool: tool === 'tags' || tool === 'citation-styles' ? tool : 'duplicates',
		mode: mode === 'title' || mode === 'file' ? mode : 'identifier',
		tagSearch: parameters.get('tag_search') ?? '',
		tagPage: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
		pageSize: [10, 20, 25, 50, 100].includes(size) ? size : 20,
		styleQuery: parameters.get('style_query') ?? '',
		stylePage: Number.isFinite(stylePage) ? Math.max(1, Math.floor(stylePage)) : 1,
		styleSize: [10, 20, 25, 50, 100].includes(styleSize) ? styleSize : 25,
		styleScope: styleScope === 'builtin' || styleScope === 'custom' ? styleScope : '',
		styleDirection: parameters.get('style_direction') === 'desc' ? 'desc' : 'asc'
	} as const;
}

export type ToolsState = ReturnType<typeof readToolsState>;

export function toolsParameters(state: ToolsState) {
	const parameters = new URLSearchParams();
	if (state.tool !== 'duplicates') parameters.set('tool', state.tool);
	if (state.mode !== 'identifier') parameters.set('mode', state.mode);
	if (state.tagSearch) parameters.set('tag_search', state.tagSearch);
	if (state.tagPage > 1) parameters.set('tag_page', String(state.tagPage));
	if (state.pageSize !== 20) parameters.set('tag_size', String(state.pageSize));
	if (state.styleQuery) parameters.set('style_query', state.styleQuery);
	if (state.stylePage > 1) parameters.set('style_page', String(state.stylePage));
	if (state.styleSize !== 25) parameters.set('style_size', String(state.styleSize));
	if (state.styleScope) parameters.set('style_scope', state.styleScope);
	if (state.styleDirection !== 'asc') parameters.set('style_direction', state.styleDirection);
	return parameters.toString();
}
