import { expect, it } from 'vitest';
import { importListParameters, importReturnHref, readImportListState } from './list-state.js';

it('restores submitted directory state while preserving the batch and unrelated parameters', () => {
	const current = new URLSearchParams({
		view: 'pending',
		page: '7',
		page_size: '25',
		batch: 'receipt / 一',
		context: 'return & review'
	});
	const expected = { view: 'completed' as const, page: 2, pageSize: 10 };
	const parameters = importListParameters(expected, current);
	expect(readImportListState(new URLSearchParams(parameters.toString()))).toEqual(expected);
	expect(parameters.get('batch')).toBe('receipt / 一');
	expect(parameters.get('context')).toBe('return & review');
	expect(current.get('page')).toBe('7');
	const defaults = importListParameters({ view: 'pending', page: 1, pageSize: 20 }, parameters);
	expect([...defaults]).toEqual([
		['batch', 'receipt / 一'],
		['context', 'return & review']
	]);
});

it.each([
	['', { view: 'pending', page: 1, pageSize: 20 }],
	['view=unknown&page=Infinity&page_size=999', { view: 'pending', page: 1, pageSize: 20 }],
	['view=completed&page=-4&page_size=10', { view: 'completed', page: 1, pageSize: 10 }],
	['view=completed&page=2.9&page_size=50', { view: 'completed', page: 2, pageSize: 50 }]
])('validates directory URL values: %s', (query, expected) => {
	expect(readImportListState(new URLSearchParams(query))).toEqual(expected);
});

it('returns to the captured history page after opening a batch without accepting arbitrary return URLs', () => {
	const parameters = new URLSearchParams({
		from: 'history',
		batch: 'receipt-1',
		view: 'completed',
		page: '3',
		page_size: '10',
		context: 'saved-position'
	});
	expect(importReturnHref('workspace-1', parameters)).toBe(
		'workspace/workspace-1/import/history?context=saved-position&view=completed&page=3&page_size=10'
	);
	expect(
		importReturnHref('workspace-1', new URLSearchParams('from=https://example.com&batch=receipt-1'))
	).toBe('workspace/workspace-1/import');
});
