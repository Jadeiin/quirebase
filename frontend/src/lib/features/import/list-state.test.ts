import { expect, it } from 'vitest';
import { importListParameters, importReturnHref, readImportListState } from './list-state.js';
import {
	discoverySearchParameters,
	defaultDiscoverySearch,
	type SearchRequest
} from '../discovery/search-state.js';

it('restores submitted directory state while preserving the batch and unrelated parameters', () => {
	const current = new URLSearchParams({
		view: 'uncommitted',
		page: '7',
		page_size: '25',
		batch: 'receipt / 一',
		context: 'return & review'
	});
	const expected = { view: 'committed' as const, page: 2, pageSize: 10 };
	const parameters = importListParameters(expected, current);
	expect(readImportListState(new URLSearchParams(parameters.toString()))).toEqual(expected);
	expect(parameters.get('batch')).toBe('receipt / 一');
	expect(parameters.get('context')).toBe('return & review');
	expect(current.get('page')).toBe('7');
	const defaults = importListParameters({ view: 'uncommitted', page: 1, pageSize: 20 }, parameters);
	expect([...defaults]).toEqual([
		['batch', 'receipt / 一'],
		['context', 'return & review']
	]);
});

it.each([
	['', { view: 'uncommitted', page: 1, pageSize: 20 }],
	['view=unknown&page=Infinity&page_size=999', { view: 'uncommitted', page: 1, pageSize: 20 }],
	['view=committed&page=-4&page_size=10', { view: 'committed', page: 1, pageSize: 10 }],
	['view=committed&page=2.9&page_size=50', { view: 'committed', page: 2, pageSize: 50 }]
])('validates directory URL values: %s', (query, expected) => {
	expect(readImportListState(new URLSearchParams(query))).toEqual(expected);
});

it('returns to the captured history page after opening a batch without accepting arbitrary return URLs', () => {
	const parameters = new URLSearchParams({
		from: 'history',
		batch: 'receipt-1',
		view: 'committed',
		page: '3',
		page_size: '10',
		context: 'saved-position'
	});
	expect(importReturnHref('workspace-1', parameters)).toBe(
		'workspace/workspace-1/import/history?context=saved-position&view=committed&page=3&page_size=10'
	);
	expect(
		importReturnHref('workspace-1', new URLSearchParams('from=https://example.com&batch=receipt-1'))
	).toBe('workspace/workspace-1/import');
});

it('returns to the captured Discovery search using only its validated criteria', () => {
	const search: SearchRequest = {
		...defaultDiscoverySearch(),
		provider: 'crossref',
		clauses: [{ field: 'title', operator: 'and', term: '研究 & science' }],
		page: 3,
		per_page: 25
	};
	const parameters = new URLSearchParams(discoverySearchParameters(search));
	parameters.set('from', 'discovery');
	parameters.set('batch', 'batch-1');
	parameters.set('return_to', 'https://example.com');
	expect(importReturnHref('workspace-1', parameters)).toBe(
		`workspace/workspace-1/discovery?${discoverySearchParameters(search)}`
	);
	expect(importReturnHref('workspace-1', new URLSearchParams('from=discovery&clause=broken'))).toBe(
		'workspace/workspace-1/discovery'
	);
});
