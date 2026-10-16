import { expect, it } from 'vitest';
import { libraryHref, libraryPage, libraryParameters, readLibraryFilters } from './filters.js';
import { metadataFilterLinks } from '../item/metadata-links.js';
import type { Metadata } from '../item/metadata-draft.js';

it('round-trips precise filters, empty given names, Unicode and URL punctuation', () => {
	const filters = {
		author_last_name: '研究 & Council; 50%_+',
		author_first_name: '',
		publication_title: ' Journal & 特刊? #1 ',
		keyword_exact: ' graph; theory & ML ',
		reference_type: 'JournalArticle',
		year: '2024',
		tag: 'tag-1',
		has_files: false
	};
	const parameters = libraryParameters(filters, 3);
	expect(parameters.has('author_first_name')).toBe(true);
	expect(readLibraryFilters(parameters)).toMatchObject(filters);
	expect(libraryPage(parameters)).toBe(3);
	expect(libraryHref('workspace /一', filters)).toContain(
		'workspace/workspace%20%2F%E4%B8%80/library?'
	);
	expect(libraryParameters({ author_last_name: 'Smith' }).has('author_first_name')).toBe(false);
});

it.each(['NaN', 'Infinity', '-2', '0', ''])('keeps invalid page %s on page one', (page) => {
	expect(libraryPage(new URLSearchParams({ page }))).toBe(1);
});

it('builds author links from active entities and Author roles in record order', () => {
	const metadata = {
		id: 'urn:test',
		type: 'JournalArticle',
		title: 'Research',
		date_published: '2024-06-15T12:00:00Z',
		container: { title: 'Journal & 特刊' },
		contributors: [
			{
				type: 'Person',
				person: { name: 'Credited name', family_name: 'Smith', given_name: 'Jane' },
				roles: ['Author']
			},
			{ type: 'Person', person: { given_name: 'Ada' }, roles: ['Author'] },
			{
				type: 'Organization',
				person: { name: 'Inactive person' },
				organization: { name: 'Research Council' },
				roles: ['Author']
			},
			{ type: 'Person', person: { name: 'Editor' }, roles: ['Editor'] }
		]
	} as Metadata;
	const links = metadataFilterLinks('workspace-1', metadata);
	expect(links.authors.map((author) => author.label)).toEqual([
		'Credited name',
		'Ada',
		'Research Council'
	]);
	const filters = links.authors.map((author) =>
		readLibraryFilters(new URL(`https://test/${author.href}`).searchParams)
	);
	expect(filters).toMatchObject([
		{ author_last_name: 'Smith', author_first_name: 'Jane' },
		{ author_last_name: 'Ada', author_first_name: '' },
		{ author_last_name: 'Research Council', author_first_name: '' }
	]);
	expect(links.date.href).toBe('workspace/workspace-1/library?year=2024');
	expect(links.publication.href).toContain('publication_title=Journal+%26+');
	expect(links.type.href).toBe('workspace/workspace-1/library?reference_type=JournalArticle');
});
