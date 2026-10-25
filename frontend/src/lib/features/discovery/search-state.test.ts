import { describe, expect, it } from 'vitest';
import {
	candidateKey,
	defaultDiscoverySearch,
	discoverySearchParameters,
	identifiersForCandidates,
	readDiscoverySearch,
	type Candidate,
	type SearchRequest
} from './search-state.js';

function parameters(clauses: unknown, extra: Record<string, string> = {}) {
	return new URLSearchParams({ clause: JSON.stringify(clauses), ...extra });
}

const clause: SearchRequest['clauses'][number] = {
	field: 'any',
	operator: 'and',
	term: 'neural networks'
};
const candidate: Candidate = {
	provider: 'crossref',
	identifier_provider: 'doi',
	identifier: '10.1000/example',
	title: 'Example'
};

it('creates independent empty search drafts without initiating a submitted search', () => {
	const first = defaultDiscoverySearch();
	first.clauses[0].term = 'draft';
	expect(defaultDiscoverySearch().clauses[0].term).toBe('');
	expect(readDiscoverySearch(new URLSearchParams())).toBeNull();
	expect(
		readDiscoverySearch(new URLSearchParams(discoverySearchParameters(defaultDiscoverySearch())))
	).toBeNull();
});

describe('Discovery search URLs', () => {
	it('round trips conditions, Provider, sorting, publication years and list position', () => {
		const request: SearchRequest = {
			...defaultDiscoverySearch(),
			provider: 'crossref',
			clauses: [
				{ field: 'title', operator: 'and', term: 'AI & 科研 + C++' },
				{ field: 'author', operator: 'or', term: '王小明' },
				{ field: 'abstract', operator: 'not', term: 'discarded topic' }
			],
			page: 7,
			per_page: 50,
			sort: 'published',
			year_from: 1999,
			year_to: 2026
		};
		expect(readDiscoverySearch(new URLSearchParams(discoverySearchParameters(request)))).toEqual(
			request
		);
	});

	it('omits defaults while retaining the submitted conditions', () => {
		const request = { ...defaultDiscoverySearch(), clauses: [clause] };
		const encoded = new URLSearchParams(discoverySearchParameters(request));
		expect([...encoded.keys()]).toEqual(['clause']);
		expect(readDiscoverySearch(encoded)).toEqual(request);
	});

	it('normalizes pagination and unknown sorts without changing valid conditions', () => {
		expect(
			readDiscoverySearch(parameters([clause], { page: '3.9', page_size: '1000', sort: 'bad' }))
		).toMatchObject({ page: 3, per_page: 100, sort: 'relevance' });
		expect(
			readDiscoverySearch(parameters([clause], { page: '-10', page_size: '0' }))
		).toMatchObject({ page: 1, per_page: 1 });
		expect(
			readDiscoverySearch(parameters([clause], { page: 'Infinity', page_size: 'NaN' }))
		).toMatchObject({ page: 1, per_page: 20 });
		expect(readDiscoverySearch(parameters([clause], { page: '101' }))?.page).toBe(101);
	});

	it('trims submitted terms and allows one-sided year ranges', () => {
		expect(
			readDiscoverySearch(parameters([{ ...clause, term: '  C++  ' }], { year_from: '2020' }))
		).toMatchObject({ clauses: [{ ...clause, term: 'C++' }], year_from: 2020, year_to: null });
	});

	it.each([
		null,
		{},
		[],
		[null],
		['term'],
		[{ ...clause, field: 'private' }],
		[{ ...clause, operator: 'xor' }],
		[{ ...clause, term: '   ' }],
		[{ ...clause, term: 'x'.repeat(301) }],
		Array.from({ length: 6 }, () => clause)
	])('rejects malformed or unsupported conditions: %j', (clauses) => {
		expect(readDiscoverySearch(parameters(clauses))).toBeNull();
	});

	it.each<Record<string, string>>([
		{ year_from: '999' },
		{ year_to: '10000' },
		{ year_from: '2020.5' },
		{ year_to: 'invalid' },
		{ year_from: '2026', year_to: '2020' },
		{ provider: '../../private' }
	])('rejects invalid submitted constraints: %j', (extra) => {
		expect(readDiscoverySearch(parameters([clause], extra))).toBeNull();
	});

	it('does not throw for broken JSON', () => {
		expect(readDiscoverySearch(new URLSearchParams('clause=%7Bbroken'))).toBeNull();
	});
});

describe('Discovery candidate selection', () => {
	it('separates Provider and namespace identities without delimiter collisions', () => {
		expect(candidateKey(candidate)).not.toBe(candidateKey({ ...candidate, provider: 'datacite' }));
		expect(candidateKey(candidate)).not.toBe(
			candidateKey({ ...candidate, identifier_provider: 'pmid' })
		);
		expect(candidateKey({ ...candidate, identifier_provider: 'a:b', identifier: 'c' })).not.toBe(
			candidateKey({ ...candidate, identifier_provider: 'a', identifier: 'b:c' })
		);
	});

	it('builds an Identifier Namespace import request, deduplicating repeated identifiers', () => {
		expect(
			identifiersForCandidates([
				candidate,
				{ ...candidate, provider: 'datacite' },
				{ ...candidate, identifier: '10.1000/second' }
			])
		).toEqual({ provider: 'doi', identifiers: ['10.1000/example', '10.1000/second'] });
	});

	it('accepts the import limit after deduplication and rejects incompatible selections', () => {
		const fifty = Array.from({ length: 50 }, (_, index) => ({
			...candidate,
			identifier: String(index)
		}));
		expect(identifiersForCandidates([...fifty, fifty[0]])?.identifiers).toHaveLength(50);
		expect(identifiersForCandidates([...fifty, candidate])).toBeNull();
		expect(identifiersForCandidates([])).toBeNull();
		expect(
			identifiersForCandidates([candidate, { ...candidate, identifier_provider: 'pmid' }])
		).toBeNull();
		expect(identifiersForCandidates([{ ...candidate, identifier: ' ' }])).toBeNull();
		expect(identifiersForCandidates([{ ...candidate, identifier: 'x'.repeat(501) }])).toBeNull();
	});
});
