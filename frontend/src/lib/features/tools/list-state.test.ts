import { describe, expect, it } from 'vitest';
import { readToolsState, toolsParameters } from './list-state.js';

describe('Citation Style directory URLs', () => {
	it('uses directory defaults without adding them to the URL', () => {
		const state = readToolsState(new URLSearchParams());
		expect(state).toEqual({
			tool: 'duplicates',
			mode: 'identifier',
			tagSearch: '',
			tagPage: 1,
			pageSize: 20,
			styleQuery: '',
			stylePage: 1,
			styleSize: 25,
			styleScope: '',
			styleDirection: 'asc'
		});
		expect(toolsParameters(state)).toBe('');
		expect(
			toolsParameters(
				readToolsState(
					new URLSearchParams('tool=citation-styles&style_page=1&style_size=25&style_direction=asc')
				)
			)
		).toBe('tool=citation-styles');
	});

	it('normalizes malformed filters while preserving search text', () => {
		const state = readToolsState(
			new URLSearchParams({
				tool: 'citation-styles',
				style_query: '  Nature & 方法  ',
				style_page: 'Infinity',
				style_size: '99',
				style_scope: 'private',
				style_direction: 'up',
				style_sort: 'updated'
			})
		);
		expect(state).toMatchObject({
			styleQuery: '  Nature & 方法  ',
			stylePage: 1,
			styleSize: 25,
			styleScope: '',
			styleDirection: 'asc'
		});
		expect(new URLSearchParams(toolsParameters(state)).has('style_sort')).toBe(false);
	});

	it.each([
		['NaN', 1],
		['-3', 1],
		['0', 1],
		['3.9', 3]
	] as const)('normalizes page %s to %s', (page, expected) => {
		expect(readToolsState(new URLSearchParams({ style_page: page })).stylePage).toBe(expected);
	});

	it.each(['', 'builtin', 'custom'])(
		'round trips source %s with both directions and page sizes',
		(scope) => {
			for (const direction of ['asc', 'desc']) {
				for (const size of [10, 20, 25, 50, 100]) {
					const state = readToolsState(
						new URLSearchParams({
							tool: 'citation-styles',
							style_query: '  Nature & 方法 + citations  ',
							style_page: '4',
							style_size: String(size),
							style_scope: scope,
							style_direction: direction
						})
					);
					expect(readToolsState(new URLSearchParams(toolsParameters(state)))).toEqual(state);
				}
			}
		}
	);

	it('keeps directory pagination and search independent of other Tools state', () => {
		const state = readToolsState(
			new URLSearchParams({
				tool: 'citation-styles',
				mode: 'file',
				tag_search: 'Methods & 方法',
				tag_page: '3',
				tag_size: '50',
				style_query: 'journal',
				style_page: '2',
				style_size: '10',
				style_scope: 'custom',
				style_direction: 'desc'
			})
		);
		const nextPage = { ...state, stylePage: 3 };
		expect(readToolsState(new URLSearchParams(toolsParameters(nextPage)))).toEqual(nextPage);
		const changedSearch = { ...nextPage, styleQuery: 'conference', stylePage: 1 };
		expect(readToolsState(new URLSearchParams(toolsParameters(changedSearch)))).toEqual(
			changedSearch
		);
		const tags = { ...changedSearch, tool: 'tags' as const };
		expect(readToolsState(new URLSearchParams(toolsParameters(tags)))).toEqual(tags);
	});
});
