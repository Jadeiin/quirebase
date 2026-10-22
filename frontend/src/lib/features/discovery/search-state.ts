import type { components } from '#lib/api/schema.js';

export type SearchRequest = components['schemas']['DiscoverySearchRequest'];
export type Candidate = components['schemas']['CandidateView'];

const fields = new Set(['any', 'title', 'author', 'publication', 'abstract']);
const operators = new Set(['and', 'or', 'not']);
const sorts = new Set(['relevance', 'published', 'cited', 'updated']);

export function defaultDiscoverySearch(): SearchRequest {
	return {
		provider: 'openalex',
		clauses: [{ field: 'any', operator: 'and', term: '' }],
		page: 1,
		per_page: 20,
		sort: 'relevance',
		year_from: null,
		year_to: null
	};
}

function boundedInteger(value: string | null, fallback: number, maximum: number) {
	if (!value?.trim()) return fallback;
	const number = Number(value);
	return Number.isFinite(number) ? Math.max(1, Math.min(maximum, Math.floor(number))) : fallback;
}

function year(value: string | null) {
	if (!value) return null;
	const number = Number(value);
	return Number.isInteger(number) && number >= 1000 && number <= 9999 ? number : undefined;
}

export function readDiscoverySearch(
	parameters: Pick<URLSearchParams, 'get'>
): SearchRequest | null {
	const encodedClauses = parameters.get('clause');
	if (!encodedClauses) return null;
	let decoded: unknown;
	try {
		decoded = JSON.parse(encodedClauses);
	} catch {
		return null;
	}
	if (!Array.isArray(decoded) || decoded.length < 1 || decoded.length > 5) return null;
	const clauses: SearchRequest['clauses'] = [];
	for (const value of decoded as unknown[]) {
		if (
			!value ||
			typeof value !== 'object' ||
			!('field' in value) ||
			typeof value.field !== 'string' ||
			!fields.has(value.field) ||
			!('operator' in value) ||
			typeof value.operator !== 'string' ||
			!operators.has(value.operator) ||
			!('term' in value) ||
			typeof value.term !== 'string' ||
			!value.term.trim() ||
			value.term.length > 300
		)
			return null;
		clauses.push({ field: value.field, operator: value.operator, term: value.term.trim() });
	}
	const defaults = defaultDiscoverySearch();
	const provider = parameters.get('provider') ?? defaults.provider;
	// Availability and Provider-specific sorts are owned by the live Provider catalog.
	if (!/^[a-z][a-z0-9_]*$/.test(provider)) return null;
	const yearFrom = year(parameters.get('year_from'));
	const yearTo = year(parameters.get('year_to'));
	if (
		yearFrom === undefined ||
		yearTo === undefined ||
		(yearFrom !== null && yearTo !== null && yearFrom > yearTo)
	)
		return null;
	const requestedSort = parameters.get('sort') ?? defaults.sort;
	return {
		provider,
		clauses,
		page: boundedInteger(parameters.get('page'), defaults.page, Number.MAX_SAFE_INTEGER),
		per_page: boundedInteger(parameters.get('page_size'), defaults.per_page, 100),
		sort: sorts.has(requestedSort) ? requestedSort : defaults.sort,
		year_from: yearFrom,
		year_to: yearTo
	};
}

export function discoverySearchParameters(request: SearchRequest): string {
	const parameters = new URLSearchParams();
	const defaults = defaultDiscoverySearch();
	if (request.provider !== defaults.provider) parameters.set('provider', request.provider);
	parameters.set('clause', JSON.stringify(request.clauses));
	if (request.sort !== defaults.sort) parameters.set('sort', request.sort);
	if (request.page !== defaults.page) parameters.set('page', String(request.page));
	if (request.per_page !== defaults.per_page) parameters.set('page_size', String(request.per_page));
	if (request.year_from != null) parameters.set('year_from', String(request.year_from));
	if (request.year_to != null) parameters.set('year_to', String(request.year_to));
	return parameters.toString();
}

export function candidateKey(candidate: Candidate): string {
	return JSON.stringify([candidate.provider, candidate.identifier_provider, candidate.identifier]);
}

export function identifiersForCandidates(
	candidates: readonly Candidate[]
): components['schemas']['IdentifiersImportRequest'] | null {
	if (!candidates.length) return null;
	const provider = candidates[0].identifier_provider;
	if (!provider) return null;
	const identifiers = new Set<string>();
	for (const candidate of candidates) {
		if (
			candidate.identifier_provider !== provider ||
			!candidate.identifier.trim() ||
			candidate.identifier.length > 500
		)
			return null;
		identifiers.add(candidate.identifier);
	}
	return identifiers.size <= 50 ? { provider, identifiers: [...identifiers] } : null;
}
