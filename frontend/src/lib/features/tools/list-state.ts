export function readToolsState(parameters: Pick<URLSearchParams, 'get'>) {
	const tool = parameters.get('tool');
	const mode = parameters.get('mode');
	const page = Number(parameters.get('tag_page') ?? 1);
	const size = Number(parameters.get('tag_size'));
	return {
		tool: tool === 'tags' || tool === 'citation-styles' ? tool : 'duplicates',
		mode: mode === 'title' || mode === 'similar' ? mode : 'identifier',
		tagSearch: parameters.get('tag_search') ?? '',
		tagPage: Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1,
		pageSize: [10, 20, 25, 50, 100].includes(size) ? size : 20,
		styleQuery: parameters.get('style_query') ?? ''
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
	return parameters.toString();
}
