import { expect, it } from 'vitest';
import {
	defaultSortDirection,
	libraryHref,
	libraryPage,
	libraryPageSize,
	libraryParameters,
	refineLibraryFilters,
	submitLibraryFilters,
	readLibraryFilters
} from './filters.js';
import { metadataFilterLinks } from '../item/metadata-links.js';
import type { Metadata } from '../item/metadata-draft.js';

it.each(['updated', 'created', 'published', 'title', 'publication', 'author'] as const)(
	'round-trips both directions for %s and omits its default direction',
	(sort) => {
		for (const direction of ['asc', 'desc'] as const) {
			const parameters = libraryParameters({ query: 'research', sort, direction }, 2, 50);
			expect(readLibraryFilters(parameters)).toMatchObject({ query: 'research', sort, direction });
			expect(parameters.has('direction')).toBe(direction !== defaultSortDirection(sort));
		}
		expect(readLibraryFilters(new URLSearchParams({ sort, direction: 'invalid' })).direction).toBe(
			defaultSortDirection(sort)
		);
	}
);

it('refines submitted results and replaces conflicting author criteria', () => {
	const applied = {
		query: 'committed',
		tag: 'tag-1',
		project: 'project-1',
		import_batch: 'batch-1',
		has_files: false,
		year: '2025',
		publication_title: 'Old journal',
		author: 'old query',
		author_last_name: 'Old',
		author_first_name: 'Name',
		sort: 'title' as const
	};
	const author = refineLibraryFilters(applied, {
		author_last_name: ' Council; & 一 ',
		author_first_name: ''
	});
	expect(author).toEqual({
		...applied,
		author: undefined,
		author_last_name: ' Council; & 一 ',
		author_first_name: ''
	});
	expect(readLibraryFilters(libraryParameters(author))).toMatchObject({
		author: '',
		author_last_name: ' Council; & 一 ',
		author_first_name: '',
		has_files: false
	});
	expect(refineLibraryFilters(author, { year: '2026' })).toEqual({ ...author, year: '2026' });
	expect(refineLibraryFilters(author, { publication_title: 'New & Journal' })).toEqual({
		...author,
		publication_title: 'New & Journal'
	});
});

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

it('preserves an import scope through refinements, search submissions and pagination', () => {
	const scoped = readLibraryFilters(new URLSearchParams({ import_batch: 'batch-1' }));
	const refined = refineLibraryFilters(scoped, { year: '2026' });
	const submitted = submitLibraryFilters(refined, { query: 'graph', tag: 'tag-1' });
	const href = new URL(
		libraryHref('workspace-1', { ...submitted, sort: 'title', direction: 'asc' }, 2, 50, 'item-1'),
		'https://app.example/'
	);
	expect(Object.fromEntries(href.searchParams)).toEqual({
		q: 'graph',
		tag: 'tag-1',
		import_batch: 'batch-1',
		year: '2026',
		sort: 'title',
		page: '2',
		page_size: '50',
		preview: 'item-1'
	});
});

it('replaces a broad keyword with an exact refinement while preserving the result scope', () => {
	expect(
		refineLibraryFilters(
			{ keyword: 'graph', project: 'project-1', has_files: false, sort: 'author' },
			{ keyword_exact: 'Graph; theory & ML' }
		)
	).toEqual({
		keyword: undefined,
		keyword_exact: 'Graph; theory & ML',
		project: 'project-1',
		has_files: false,
		sort: 'author'
	});
});

it('broad author and keyword searches replace exact criteria without clearing unrelated refinements', () => {
	const applied = {
		author_last_name: 'Smith',
		author_first_name: '',
		keyword_exact: 'Graph theory',
		reference_type: 'JournalArticle',
		project: 'project-1',
		sort: 'title' as const
	};
	expect(submitLibraryFilters(applied, { author: '', keyword: '', year: '2024' })).toEqual({
		...applied,
		author: '',
		keyword: '',
		year: '2024'
	});
	expect(submitLibraryFilters(applied, { author: 'Jones', keyword: 'models' })).toEqual({
		author: 'Jones',
		keyword: 'models',
		reference_type: 'JournalArticle',
		project: 'project-1',
		sort: 'title'
	});
});

it.each(['NaN', 'Infinity', '-2', '0', ''])('keeps invalid page %s on page one', (page) => {
	expect(libraryPage(new URLSearchParams({ page }))).toBe(1);
});

it.each([10, 20, 25, 50, 100])('round-trips page size %i with filters and the page', (pageSize) => {
	const filters = { query: '研究 & ML', sort: 'title' as const, author_first_name: '' };
	const url = new URL(`https://test/${libraryHref('workspace-1', filters, 3, pageSize)}`);
	expect(libraryPageSize(url.searchParams)).toBe(pageSize);
	expect(libraryPage(url.searchParams)).toBe(3);
	expect(readLibraryFilters(url.searchParams)).toMatchObject(filters);
	expect(url.searchParams.has('page_size')).toBe(pageSize !== 25);
});

it('keeps a shareable preview independent of the submitted Library query', () => {
	const filters = { query: '研究 & ML', sort: 'title' as const, author_first_name: '' };
	const withoutPreview = new URL(`https://test/${libraryHref('workspace-1', filters, 3, 50)}`);
	const withPreview = new URL(
		`https://test/${libraryHref('workspace-1', filters, 3, 50, 'item /一')}`
	);
	expect(withPreview.searchParams.get('preview')).toBe('item /一');
	expect(readLibraryFilters(withPreview.searchParams)).toEqual(
		readLibraryFilters(withoutPreview.searchParams)
	);
	expect(
		libraryParameters(
			readLibraryFilters(withPreview.searchParams),
			libraryPage(withPreview.searchParams),
			libraryPageSize(withPreview.searchParams)
		).toString()
	).toBe(withoutPreview.searchParams.toString());
});

it.each([null, '', 'NaN', 'Infinity', '-1', '0', '1.5', '15', '101', '1000'])(
	'falls back to the default for unsupported page size %s',
	(value) => {
		expect(libraryPageSize(new URLSearchParams(value === null ? {} : { page_size: value }))).toBe(
			25
		);
	}
);

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
