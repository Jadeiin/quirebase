import { expect, it } from 'vitest';
import {
	contributorName,
	contributorAffiliations,
	identifierRows,
	doiComparisonKey,
	pdfFileUrls,
	workKeywords,
	type Metadata
} from './metadata-draft.js';

it.each([
	['10.1000/PRIMARY', '10.1000/primary'],
	[' DOI: 10.1000/Primary ', '10.1000/primary'],
	['HTTPS://DX.DOI.ORG/10.1000/PRIMARY', '10.1000/primary'],
	['https://doi.org/10.1000/pr%69mary', '10.1000/primary'],
	['https://doi.org/10.1000/%C3%9Cber', '10.1000/Über'],
	['10.1000/Über', '10.1000/Über'],
	['10.1000/über', '10.1000/über'],
	['10.1000/A%3c', '10.1000/a%3c'],
	['https://doi.org/10.1000/A%253c', '10.1000/a%3c'],
	['https://doi.org/10.1000/A%3c', '10.1000/a<'],
	['https://doi.org/10.1000/%FF', '10.1000/%ff'],
	['https://doi.org/10.1000/A%3c%invalid', '10.1000/a<%invalid']
])('compares DOI spelling %s as %s without conflating distinct identifiers', (value, expected) => {
	expect(doiComparisonKey(value)).toBe(expected);
});

it('projects the selected contributor entity while preserving both entity snapshots', () => {
	const credit = {
		type: 'Organization',
		person: { name: 'Ada Researcher', affiliations: [{ name: 'University' }] },
		organization: { name: 'Research Council' },
		roles: ['Author']
	};
	const work = {
		id: 'https://doi.org/10.1000/entity',
		type: 'Dataset',
		title: 'Research',
		contributors: [credit]
	} as Metadata;
	expect(contributorName(credit)).toBe('Research Council');
	expect(contributorAffiliations(work)).toEqual([]);
	credit.type = 'Person';
	expect(contributorName(credit)).toBe('Ada Researcher');
	expect(contributorAffiliations(work)).toEqual(['University']);
	expect(credit.organization.name).toBe('Research Council');
});

it('deduplicates affiliation and keyword display without changing the contributor records', () => {
	const metadata = {
		id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
		type: 'Dataset',
		title: 'Research',
		contributors: [
			{
				type: 'Person',
				person: {
					name: 'Ada',
					affiliations: [{ name: ' University  of Research ' }, { name: 'Laboratory' }]
				},
				roles: ['Author']
			},
			{
				type: 'Person',
				person: { name: 'Grace', affiliations: [{ name: 'University of Research' }] },
				roles: ['Author']
			}
		],
		subjects: [{ subject: 'Research' }, { subject: 'Research' }]
	} as Metadata;
	const initial = structuredClone(metadata);
	expect(contributorAffiliations(metadata)).toEqual(['University of Research', 'Laboratory']);
	expect(workKeywords(metadata)).toEqual(['Research']);
	expect(metadata).toEqual(initial);
});

it('offers unique remote PDF URLs and keeps unknown download endpoints selectable', () => {
	const metadata = {
		id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
		type: 'Dataset',
		title: 'Research',
		files: [
			{ url: 'https://papers.example/download?id=1', mime_type: 'application/pdf; charset=binary' },
			{ url: 'https://papers.example/download?id=1', mime_type: 'application/pdf' },
			{ url: 'https://papers.example/ARTICLE.PDF?token=test' },
			{ url: 'https://papers.example/unknown' },
			{ url: 'https://papers.example/supplement.zip', mime_type: 'application/zip' },
			{ url: 'javascript:alert(1)', mime_type: 'application/pdf' },
			{ url: 'file:///private/article.pdf' },
			{ url: 'invalid' }
		]
	} as Metadata;
	expect(pdfFileUrls(metadata)).toEqual([
		'https://papers.example/download?id=1',
		'https://papers.example/ARTICLE.PDF?token=test',
		'https://papers.example/unknown'
	]);
});

it('deduplicates identifier display rows and preserves the complete Work', () => {
	const metadata = {
		id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
		type: 'Dataset',
		identifiers: [
			{ identifier_type: 'PMID', identifier: '42' },
			{ identifier_type: 'PMID', identifier: '42' },
			{ identifier_type: 'Other', scheme: 'pmid', identifier: '42' },
			{ identifier_type: 'PMID', identifier: '43' },
			{ identifier_type: 'Other', scheme: 'Local registry', identifier: '42' }
		]
	} as Metadata;
	const original = structuredClone(metadata);
	expect(identifierRows(metadata)).toEqual([
		{ provider: 'pmid', value: '42' },
		{ provider: 'pmid', value: '43' },
		{ provider: 'local registry', value: '42' }
	]);
	expect(metadata).toEqual(original);
});

it('combines backend primary lookup context with identifier display without changing the Work', () => {
	const metadata = {
		id: 'https://pubmed.ncbi.nlm.nih.gov/42/',
		type: 'Preprint',
		identifiers: [{ identifier_type: 'PMID', identifier: '42' }]
	} as Metadata;
	const original = structuredClone(metadata);
	expect(identifierRows(metadata, { provider: 'pmid', value: '42' })).toEqual([
		{ provider: 'pmid', value: '42' }
	]);
	expect(
		identifierRows({ id: metadata.id, type: metadata.type }, { provider: 'pmid', value: '42' })
	).toEqual([{ provider: 'pmid', value: '42' }]);
	expect(metadata).toEqual(original);
});
