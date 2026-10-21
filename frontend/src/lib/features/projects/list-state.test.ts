import { describe, expect, it } from 'vitest';
import {
	defaultProjectSortDirection,
	projectItemListParameters,
	projectListParameters,
	readProjectItemListState,
	readProjectListState
} from './list-state.js';

it('normalizes malformed directory filters without accepting Library-only sorts', () => {
	expect(readProjectListState(new URLSearchParams())).toEqual({
		search: '',
		page: 1,
		pageSize: 25,
		view: 'all',
		state: '',
		sort: 'name',
		direction: 'asc'
	});
	const state = readProjectListState(
		new URLSearchParams({
			q: '  Methods & 方法  ',
			page: 'Infinity',
			page_size: '99',
			view: 'unknown',
			state: 'deleted',
			sort: 'title',
			direction: 'up'
		})
	);
	expect(state).toEqual({
		search: '  Methods & 方法  ',
		page: 1,
		pageSize: 25,
		view: 'all',
		state: '',
		sort: 'name',
		direction: 'asc'
	});
	expect(readProjectListState(new URLSearchParams('page=3.9')).page).toBe(3);
	expect(readProjectListState(new URLSearchParams('page=-2')).page).toBe(1);
});

describe('Project directory URLs', () => {
	it.each(['name', 'created', 'updated'] as const)('round trips %s in both directions', (sort) => {
		for (const direction of ['asc', 'desc'] as const) {
			const state = readProjectListState(
				new URLSearchParams({
					q: 'Methods & 方法',
					page: '3',
					page_size: '50',
					view: 'mine',
					state: 'archived',
					sort,
					direction
				})
			);
			expect(readProjectListState(new URLSearchParams(projectListParameters(state)))).toEqual(
				state
			);
		}
	});

	it('omits defaults while preserving explicit nondefault order', () => {
		expect(projectListParameters(readProjectListState(new URLSearchParams()))).toBe('');
		for (const sort of ['name', 'created', 'updated'] as const) {
			const state = readProjectListState(new URLSearchParams({ sort }));
			expect(state.direction).toBe(defaultProjectSortDirection(sort));
			expect(new URLSearchParams(projectListParameters(state)).has('direction')).toBe(false);
		}
		const created = readProjectListState(new URLSearchParams('sort=created&direction=asc'));
		expect(new URLSearchParams(projectListParameters(created)).get('direction')).toBe('asc');
	});

	it('preserves search and filters for pagination and ordering', () => {
		const state = readProjectListState(
			new URLSearchParams('q=flow&view=joinable&state=active&page=4')
		);
		const sorted = { ...state, sort: 'updated' as const, direction: 'desc' as const, page: 1 };
		expect(readProjectListState(new URLSearchParams(projectListParameters(sorted)))).toEqual(
			sorted
		);
		expect(
			readProjectListState(new URLSearchParams(projectListParameters({ ...sorted, page: 2 })))
		).toEqual({ ...sorted, page: 2 });
	});
});

it('keeps Project Item Library-link parameters independent of directory sorting', () => {
	const items = readProjectItemListState(
		new URLSearchParams(
			'q=Methods&page=2&page_size=50&sort=title&state=archived&view=mine&direction=asc'
		)
	);
	expect(items).toEqual({ search: 'Methods', page: 2, pageSize: 50, sort: 'title' });
	expect(projectItemListParameters(items)).toBe('q=Methods&page=2&page_size=50&sort=title');
	expect(readProjectItemListState(new URLSearchParams('sort=name')).sort).toBe('updated');
	expect(projectItemListParameters(readProjectItemListState(new URLSearchParams()))).toBe('');
});
