import { expect, it } from 'vitest';
import {
	affiliationLinks,
	licenseLink,
	metadataFilterLinks,
	workIdentifierLinks
} from './metadata-links.js';
import type { Metadata } from './metadata-draft.js';
import { libraryHref, refineLibraryFilters } from '../library/filters.js';

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
	expect(
		new URL(author.orcidFilterHref!, 'https://app.example/').searchParams.get('author_orcid')
	).toBe(expected.split('/').at(-1));
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
	expect(author.orcidFilterHref).toBeUndefined();
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

it('preserves ordered same-name credits with their own roles and affiliations', () => {
	const metadata = {
		id: 'urn:test:credits',
		type: 'JournalArticle',
		title: 'Local author details',
		contributors: [
			{ type: 'Person', person: {}, roles: ['Author'] },
			{
				type: 'Person',
				person: {
					name: 'Alex Morgan',
					id: 'https://orcid.org/0000-0002-1825-0097',
					affiliations: [
						{ name: ' First  Institute ', identifier: '03yrm5c26', identifier_type: 'ROR' }
					]
				},
				roles: ['Author', 'Editor']
			},
			{
				type: 'Person',
				person: { name: 'Alex Morgan', affiliations: [{ name: 'Second Institute' }] },
				roles: ['Author']
			},
			{
				type: 'Organization',
				organization: { name: 'Research Council' },
				person: { affiliations: [{ name: 'Inactive institute' }] },
				roles: ['Author']
			},
			{
				type: 'Person',
				person: { name: 'An editor', affiliations: [{ name: 'Editorial office' }] },
				roles: ['Editor']
			}
		]
	} as Metadata;
	const initial = structuredClone(metadata);
	const authors = metadataFilterLinks('workspace-1', metadata).authors;
	expect(
		authors.map((author) => ({
			label: author.label,
			names: author.affiliations.map((a) => a.name),
			roles: author.roles,
			organization: author.organization
		}))
	).toEqual([
		{
			label: 'Alex Morgan',
			names: ['First Institute'],
			roles: ['Author', 'Editor'],
			organization: false
		},
		{ label: 'Alex Morgan', names: ['Second Institute'], roles: ['Author'], organization: false },
		{ label: 'Research Council', names: [], roles: ['Author'], organization: true }
	]);
	expect(authors[0].affiliations[0].identifier.href).toBe('https://ror.org/03yrm5c26');
	expect(authors[0].orcidHref).toBe('https://orcid.org/0000-0002-1825-0097');
	expect(authors[1].orcidHref).toBeUndefined();
	expect(metadata).toEqual(initial);
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

it.each([
	['03yrm5c26', 'ROR', true],
	[' HTTP://ROR.ORG/03YRM5C26/ ', 'URL', true],
	['https://ror.org/03yrm5c26', undefined, true],
	['https://ror.org/03yrm5c26', 'FundRef', false],
	['03yrm5c26', undefined, false],
	['https://ror.org/03yrm5c27', 'ROR', false]
])(
	'offers a ROR filter only for a valid institution identifier %s (%s)',
	(identifier, identifier_type, valid) => {
		const metadata = {
			contributors: [
				{
					type: 'Person',
					roles: ['Author'],
					person: {
						name: 'Ada',
						affiliations: [{ name: 'Institute', identifier, identifier_type }]
					}
				}
			]
		} as Metadata;
		const [author] = metadataFilterLinks('workspace-1', metadata).authors;
		expect(Boolean(author.affiliations[0].rorFilterHref)).toBe(valid);
		expect(Boolean(author.affiliations[0].nameRorFilterHref)).toBe(valid);
		if (valid)
			expect(
				new URL(author.affiliations[0].rorFilterHref!, 'https://app.example').searchParams.get(
					'author_ror'
				)
			).toBe('03yrm5c26');
		if (valid) {
			expect(
				new URL(author.affiliations[0].rorFilterHref!, 'https://app.example').searchParams.has(
					'authors'
				)
			).toBe(false);
			expect(
				JSON.parse(
					new URL(
						author.affiliations[0].nameRorFilterHref!,
						'https://app.example'
					).searchParams.get('authors')!
				)
			).toEqual([{ last_name: 'Ada', first_name: '' }]);
		}
	}
);

it('uses only the active organizational Author ROR and retains Library preview scope in every action', () => {
	const metadata = {
		contributors: [
			{
				type: 'Organization',
				roles: ['Author'],
				organization: { name: 'Council', id: 'https://ror.org/03yrm5c26' },
				person: { name: 'Inactive', affiliations: [{ identifier: 'https://ror.org/02mhbdp94' }] }
			},
			{
				type: 'Person',
				roles: ['Author'],
				person: {
					name: 'Ada',
					id: 'https://orcid.org/0000-0002-1825-0097',
					affiliations: [{ identifier: '03yrm5c26', identifier_type: 'ROR' }]
				}
			}
		]
	} as Metadata;
	const links = metadataFilterLinks('workspace-1', metadata, (filter) =>
		libraryHref(
			'workspace-1',
			refineLibraryFilters({ query: 'committed', project: 'project-1', sort: 'title' }, filter),
			1,
			50,
			'item-1'
		)
	);
	const [organization, person] = links.authors;
	expect(organization.rorHref).toBe('https://ror.org/03yrm5c26');
	expect(organization.affiliations).toEqual([]);
	expect(person.rorHref).toBeUndefined();
	for (const href of [
		organization.href,
		organization.rorFilterHref,
		organization.nameRorFilterHref,
		person.href,
		person.orcidFilterHref,
		person.affiliations[0].rorFilterHref,
		person.affiliations[0].nameRorFilterHref
	]) {
		const params = new URL(href!, 'https://app.example').searchParams;
		expect(params.get('q')).toBe('committed');
		expect(params.get('project')).toBe('project-1');
		expect(params.get('sort')).toBe('title');
		expect(params.get('page_size')).toBe('50');
		expect(params.get('preview')).toBe('item-1');
	}
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
				roles: ['Author'],
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
	const links = affiliationLinks('workspace-1', metadata);
	expect(links.map((link) => link.name)).toEqual(['Research University', 'Laboratory']);
	expect(links[0].identifier).toMatchObject({ href: affiliation.identifier, icon: 'ror' });
	expect(
		new URL(links[0].rorFilterHref!, 'https://app.example').searchParams.get('author_ror')
	).toBe('03yrm5c26');
	expect(links[1].rorFilterHref).toBeUndefined();
	expect(links[1].identifier.href).toBeUndefined();
	expect(metadata).toEqual(initial);
});

it.each([false, true])(
	'Overview institution filters use Author credits even when an Editor shares the affiliation (%s)',
	(editorFirst) => {
		const shared = { name: 'Shared Institute', identifier: '03yrm5c26', identifier_type: 'ROR' };
		const author = {
			type: 'Person',
			roles: ['Author'],
			person: { name: 'Ada', affiliations: [shared] }
		};
		const editor = {
			type: 'Person',
			roles: ['Editor'],
			person: {
				name: 'Editor',
				affiliations: [
					shared,
					{ name: 'Editorial Institute', identifier: '02mhbdp94', identifier_type: 'ROR' }
				]
			}
		};
		const links = affiliationLinks('workspace-1', {
			contributors: editorFirst ? [editor, author] : [author, editor]
		} as Metadata);
		expect(links).toHaveLength(2);
		expect(links.find((row) => row.name === 'Shared Institute')?.rorFilterHref).toContain(
			'author_ror=03yrm5c26'
		);
		expect(links.find((row) => row.name === 'Editorial Institute')?.rorFilterHref).toBeUndefined();
		expect(links.every((row) => row.nameRorFilterHref === undefined)).toBe(true);
	}
);

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
