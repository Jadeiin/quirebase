import { workspaceHref } from '#lib/workspaces/href.js';

export type LibraryFilters = {
	query?: string;
	tag?: string;
	project?: string;
	year?: string;
	keyword?: string;
	author?: string;
	sort?: 'updated' | 'created' | 'title';
	has_files?: boolean;
	reference_type?: string;
	publication_title?: string;
	keyword_exact?: string;
	author_last_name?: string;
	author_first_name?: string;
};

const exactKeys = [
	'reference_type',
	'publication_title',
	'keyword_exact',
	'author_last_name',
	'author_first_name'
] as const;

export function librarySort(value: string | null): 'updated' | 'created' | 'title' {
	return value === 'created' || value === 'title' ? value : 'updated';
}

export function readLibraryFilters(
	parameters: Pick<URLSearchParams, 'get' | 'has'>
): LibraryFilters {
	return {
		query: parameters.get('q')?.trim() ?? '',
		tag: parameters.get('tag') ?? '',
		project: parameters.get('project') ?? '',
		year: parameters.get('year')?.trim() ?? '',
		keyword: parameters.get('keyword')?.trim() ?? '',
		author: parameters.get('author')?.trim() ?? '',
		sort: librarySort(parameters.get('sort')),
		has_files: parameters.has('has_files') ? parameters.get('has_files') === 'true' : undefined,
		...Object.fromEntries(exactKeys.map((key) => [key, parameters.get(key) ?? undefined]))
	};
}

export function libraryPage(parameters: Pick<URLSearchParams, 'get'>): number {
	const page = Number(parameters.get('page') ?? '1');
	return Number.isFinite(page) ? Math.max(1, Math.floor(page)) : 1;
}

export function libraryParameters(filters: LibraryFilters, page = 1): URLSearchParams {
	const result = new URLSearchParams();
	for (const key of ['query', 'tag', 'project', 'year', 'keyword', 'author', 'sort'] as const) {
		const value = filters[key];
		if (value && !(key === 'sort' && value === 'updated')) {
			result.set(key === 'query' ? 'q' : key, value);
		}
	}
	if (filters.has_files !== undefined) result.set('has_files', String(filters.has_files));
	for (const key of exactKeys) {
		// Empty given names select single-field and organization names exactly.
		if (filters[key] !== undefined) result.set(key, filters[key]);
	}
	if (page > 1) result.set('page', String(page));
	return result;
}

export function libraryHref(workspaceId: string, filters: LibraryFilters = {}, page = 1) {
	const query = libraryParameters(filters, page).toString();
	return workspaceHref(workspaceId, query ? `library?${query}` : 'library');
}
