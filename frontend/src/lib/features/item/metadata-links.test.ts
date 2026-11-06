import { expect, it } from 'vitest';
import {
	affiliationLinks,
	licenseLink,
	metadataFilterLinks,
	workIdentifierLinks
} from './metadata-links.js';
import type { Metadata } from './metadata-draft.js';

function authorLinks(contributors: unknown[]) {
	return metadataFilterLinks('workspace-1', {
		id: 'urn:test:orcid',
		type: 'JournalArticle',
		title: 'ORCID links',
		contributors
	} as Metadata).authors;
}

it.each([
	['https://orcid.org/0000-0002-1825-0097', 'https://orcid.org/0000-0002-1825-0097'],
	[' http://orcid.org/0000-0002-1825-0097/ ', 'https://orcid.org/0000-0002-1825-0097'],
	['https://orcid.org/0000-0002-1694-233x', 'https://orcid.org/0000-0002-1694-233X']
])('links a personal author with ORCID %s to its HTTPS record', (id, expected) => {
	const [author] = authorLinks([
		{ type: 'Person', person: { name: 'Jane Smith', id }, roles: ['Author'] }
	]);
	expect(author.orcidHref).toBe(expected);
	expect(author.href).toContain('authors=');
});

it.each([
	undefined,
	'',
	'https://openalex.org/A123',
	'0000-0002-1825-0097',
	'https://orcid.org/0000-0002-1825-0098',
	'https://orcid.org/0000-0002-1825-0097?redirect=elsewhere',
	'https://orcid.org.example.com/0000-0002-1825-0097',
	'https://orcid.org@elsewhere.example/0000-0002-1825-0097',
	'javascript:alert(1)'
])('keeps the author filter without an ORCID link for %s', (id) => {
	const [author] = authorLinks([
		{ type: 'Person', person: { name: 'Jane Smith', id }, roles: ['Author'] }
	]);
	expect(author.label).toBe('Jane Smith');
	expect(author.orcidHref).toBeUndefined();
	expect(author.href).toContain('authors=');
});

it('uses only active personal Author credits for ORCID links', () => {
	const person = { name: 'Jane Smith', id: 'https://orcid.org/0000-0002-1825-0097' };
	const authors = authorLinks([
		{ type: 'Person', person, roles: ['Author', 'Editor'] },
		{ type: 'Person', person, roles: ['Editor'] },
		{ type: 'Organization', person, organization: { name: 'Research Council' }, roles: ['Author'] }
	]);
	expect(authors.map(({ label, orcidHref }) => ({ label, orcidHref }))).toEqual([
		{ label: 'Jane Smith', orcidHref: person.id },
		{ label: 'Research Council', orcidHref: undefined }
	]);
});

it('deduplicates resolved Work identifiers and keeps typed labels', () => {
	const metadata = {
		id: 'https://doi.org/10.1000/research',
		type: 'JournalArticle',
		identifiers: [
			{ identifier_type: 'DOI', identifier: '10.1000/research' },
			{ identifier_type: 'Other', scheme: 'OpenAlex', identifier: 'W12345' }
		],
		contributors: [
			{
				type: 'Person',
				person: {
					name: 'Jane',
					affiliations: [{ identifier: '03yrm5c26', identifier_type: 'ROR' }]
				}
			}
		]
	} as Metadata;
	expect(workIdentifierLinks(metadata)).toEqual([
		{
			label: 'DOI: 10.1000/research',
			href: 'https://doi.org/10.1000/research',
			icon: 'doi'
		},
		{
			label: 'OpenAlex: W12345',
			href: 'https://openalex.org/W12345',
			icon: 'external-link'
		}
	]);
});

it('keeps institution names and their record-local identifiers paired', () => {
	const affiliation = {
		name: ' Research  University ',
		identifier: 'https://ror.org/03yrm5c26',
		identifier_type: 'ROR'
	};
	const metadata = {
		id: 'urn:test',
		type: 'Dataset',
		contributors: [
			{
				type: 'Person',
				person: { name: 'Jane', affiliations: [affiliation, affiliation, { name: 'Laboratory' }] }
			},
			{
				type: 'Organization',
				organization: { name: 'Council' },
				person: { affiliations: [{ name: 'Inactive institution' }] }
			}
		]
	} as Metadata;
	const initial = structuredClone(metadata);
	const links = affiliationLinks(metadata);
	expect(links.map((link) => link.name)).toEqual(['Research University', 'Laboratory']);
	expect(links[0].identifier).toMatchObject({ href: affiliation.identifier, icon: 'ror' });
	expect(links[1].identifier.href).toBeUndefined();
	expect(metadata).toEqual(initial);
});

it('links explicit CC license deeds and retains their rights restrictions', () => {
	expect(licenseLink({ id: 'CC-BY-NC-4.0', title: 'CC BY-NC 4.0' })).toEqual({
		label: 'CC BY-NC 4.0',
		href: 'https://creativecommons.org/licenses/by-nc/4.0/',
		icon: 'creative-commons'
	});
	expect(licenseLink({ id: 'CC0-1.0' }).href).toBe(
		'https://creativecommons.org/publicdomain/zero/1.0/'
	);
	expect(licenseLink({ title: 'Publisher terms' })).toEqual({ label: 'Publisher terms' });
});
