import { expect, it } from 'vitest';
import {
	contributorName,
	contributorAffiliations,
	identifierRows,
	pdfFileUrls,
	workKeywords,
	type Metadata
} from './metadata-draft.js';

it.each([
	[{ given_name: 'Ada', family_name: 'Lovelace' }, 'Ada Lovelace'],
	[{ name: '', given_name: 'Xiang', family_name: 'Yu' }, 'Xiang Yu'],
	[{ name: null, given_name: 'Juan', family_name: 'de la Cruz' }, 'Juan de la Cruz'],
	[{ name: 'Wang Wei', given_name: 'Wei', family_name: 'Wang' }, 'Wang Wei'],
	[{ given_name: 'Ada' }, 'Ada'],
	[{ family_name: 'Lovelace' }, 'Lovelace'],
	[{}, '']
])(
	'displays contributor names in reading order when no full name is supplied: %j',
	(person, name) => {
		expect(contributorName({ type: 'Person', person })).toBe(name);
	}
);

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
		{ namespace: 'pmid', value: '42' },
		{ namespace: 'pmid', value: '43' },
		{ namespace: 'local registry', value: '42' }
	]);
	expect(metadata).toEqual(original);
});
