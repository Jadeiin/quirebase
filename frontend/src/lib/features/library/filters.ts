import type { components } from '#lib/api/schema.js';
import { workspaceHref } from '#lib/workspaces/href.js';

export type LibraryAuthorFilter = components['schemas']['AuthorFilter'];

export type LibraryFilters = {
	query?: string;
	tag?: string;
	project?: string;
	import_batch?: string;
	year?: string;
	keyword?: string;
	author?: string;
	sort?: LibrarySort;
	direction?: LibrarySortDirection;
	has_files?: boolean;
	has_tags?: boolean;
	has_projects?: boolean;
	reference_type?: string;
	publication_title?: string;
	keyword_exact?: string;
	authors?: LibraryAuthorFilter[];
};

export type LibraryMetadataFilter =
	| { authors: [LibraryAuthorFilter] }
	| { publication_title: string }
	| { year: string }
	| { keyword_exact: string }
	| { reference_type: string };

export function refineLibraryFilters(
	applied: LibraryFilters,
	filter: LibraryMetadataFilter | { tag: string }
): LibraryFilters {
	if ('authors' in filter) {
		const [author] = filter.authors;
		const selected = applied.authors ?? [];
		const authors = selected.some((name) => sameAuthor(name, author))
			? selected.filter((name) => !sameAuthor(name, author))
			: [...selected, author];
		return { ...applied, author: undefined, authors: authors.length ? authors : undefined };
	}
	if ('keyword_exact' in filter) return { ...applied, keyword: undefined, ...filter };
	if ('tag' in filter && filter.tag) {
		return { ...applied, has_tags: undefined, ...filter };
	}
	return { ...applied, ...filter };
}

export const libraryAssociationChoices = { any: ':any', none: ':none' } as const;

export function libraryAssociationValue(id: string | undefined, presence: boolean | undefined) {
	return (
		id ||
		(presence === undefined
			? ''
			: presence
				? libraryAssociationChoices.any
				: libraryAssociationChoices.none)
	);
}

export function submitLibraryFilters(
	applied: LibraryFilters,
	draft: Pick<
		LibraryFilters,
		'query' | 'tag' | 'project' | 'year' | 'keyword' | 'author' | 'has_files'
	>
): LibraryFilters {
	const next = { ...applied, ...draft };
	// Typing a broad search replaces its exact refinement; unrelated fields preserve it.
	if (draft.author) {
		delete next.authors;
	}
	if (draft.keyword) delete next.keyword_exact;
	for (const [key, presence] of [
		['tag', 'has_tags'],
		['project', 'has_projects']
	] as const) {
		if (draft[key] === undefined) continue;
		const value = draft[key];
		if (value === libraryAssociationChoices.any || value === libraryAssociationChoices.none) {
			delete next[key];
			next[presence] = value === libraryAssociationChoices.any;
		} else {
			delete next[presence];
		}
	}
	return next;
}

const organizationFilterKeys = ['has_files', 'has_tags', 'has_projects'] as const;

function optionalBoolean(value: string | null): boolean | undefined {
	return value === 'true' ? true : value === 'false' ? false : undefined;
}

const exactKeys = ['reference_type', 'publication_title', 'keyword_exact'] as const;

export type LibrarySort = 'updated' | 'created' | 'title' | 'published' | 'publication' | 'author';
export type LibrarySortDirection = 'asc' | 'desc';

export function librarySort(value: string | null): LibrarySort {
	return value === 'created' ||
		value === 'title' ||
		value === 'author' ||
		value === 'published' ||
		value === 'publication'
		? value
		: 'updated';
}

export function defaultSortDirection(sort: LibrarySort): LibrarySortDirection {
	return sort === 'title' || sort === 'publication' || sort === 'author' ? 'asc' : 'desc';
}

export function sameAuthor(left: LibraryAuthorFilter, right: LibraryAuthorFilter) {
	return (
		left.last_name === right.last_name &&
		(left.first_name ?? undefined) === (right.first_name ?? undefined)
	);
}

function readAuthors(value: string | null): LibraryAuthorFilter[] | undefined {
	if (value === null) return undefined;
	try {
		const parsed: unknown = JSON.parse(value);
		if (!Array.isArray(parsed)) return undefined;
		const authors: LibraryAuthorFilter[] = [];
		for (const name of parsed) {
			if (
				!name ||
				typeof name !== 'object' ||
				typeof name.last_name !== 'string' ||
				(name.first_name != null && typeof name.first_name !== 'string')
			)
				return undefined;
			const author = { last_name: name.last_name, first_name: name.first_name ?? undefined };
			if (!authors.some((selected) => sameAuthor(selected, author))) authors.push(author);
		}
		return authors.length ? authors : undefined;
	} catch {
		return undefined;
	}
}

export function readLibraryFilters(
	parameters: Pick<URLSearchParams, 'get' | 'has'>
): LibraryFilters {
	const sort = librarySort(parameters.get('sort'));
	const direction = parameters.get('direction');
	return {
		query: parameters.get('q')?.trim() ?? '',
		tag: parameters.get('tag') ?? '',
		project: parameters.get('project') ?? '',
		import_batch: parameters.get('import_batch') || undefined,
		year: parameters.get('year')?.trim() ?? '',
		keyword: parameters.get('keyword')?.trim() ?? '',
		author: parameters.get('author')?.trim() ?? '',
		authors: readAuthors(parameters.get('authors')),
		sort,
		direction: direction === 'asc' || direction === 'desc' ? direction : defaultSortDirection(sort),
		...Object.fromEntries(
			organizationFilterKeys.map((key) => [key, optionalBoolean(parameters.get(key))])
		),
		...Object.fromEntries(exactKeys.map((key) => [key, parameters.get(key) ?? undefined]))
	};
}

export function libraryPage(parameters: Pick<URLSearchParams, 'get'>): number {
	const page = Number(parameters.get('page') ?? '1');
	return Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1;
}

export function libraryPageSize(parameters: Pick<URLSearchParams, 'get'>): number {
	const size = Number(parameters.get('page_size'));
	return [10, 20, 25, 50, 100].includes(size) ? size : 25;
}

export function libraryParameters(
	filters: LibraryFilters,
	page = 1,
	pageSize = 25
): URLSearchParams {
	const result = new URLSearchParams();
	for (const key of [
		'query',
		'tag',
		'project',
		'import_batch',
		'year',
		'keyword',
		'author',
		'sort'
	] as const) {
		const value = filters[key];
		if (value && !(key === 'sort' && value === 'updated')) {
			result.set(key === 'query' ? 'q' : key, value);
		}
	}
	if (filters.direction && filters.direction !== defaultSortDirection(filters.sort ?? 'updated')) {
		result.set('direction', filters.direction);
	}
	for (const key of organizationFilterKeys) {
		if (filters[key] !== undefined) result.set(key, String(filters[key]));
	}
	for (const key of exactKeys) {
		// Exact metadata values preserve explicit empty strings.
		if (filters[key] !== undefined) result.set(key, filters[key]);
	}
	if (filters.authors?.length) result.set('authors', JSON.stringify(filters.authors));
	if (page > 1) result.set('page', String(page));
	if (pageSize !== 25) result.set('page_size', String(pageSize));
	return result;
}

export function libraryHref(
	workspaceId: string,
	filters: LibraryFilters = {},
	page = 1,
	pageSize = 25,
	previewItemId = ''
) {
	const parameters = libraryParameters(filters, page, pageSize);
	if (previewItemId) parameters.set('preview', previewItemId);
	const query = parameters.toString();
	return workspaceHref(workspaceId, query ? `library?${query}` : 'library');
}
