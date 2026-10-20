import { workspaceHref, type WorkspacePath } from '#lib/workspaces/href.js';
import { libraryHref, libraryPage, libraryPageSize, readLibraryFilters } from './filters.js';

const anchorPrefix = '#library-item-';
const itemIdentifier = /^[a-zA-Z0-9_-]{1,256}$/;

export function libraryReturnItemId(hash: string): string | null {
	if (!hash.startsWith(anchorPrefix)) return null;
	const id = hash.slice(anchorPrefix.length);
	return itemIdentifier.test(id) ? id : null;
}

/** Canonical, app-relative Library context. Absolute string URLs are never return destinations. */
export function libraryReturnTo(
	workspaceId: string,
	href: string | URL,
	itemId?: string
): WorkspacePath | null {
	const value = href instanceof URL ? `${href.pathname}${href.search}${href.hash}` : href;
	const path = workspaceHref(workspaceId, 'library');
	const match = value.match(/^\/?([^?#]+)(\?[^#]*)?(#.*)?$/);
	if (!match || match[1] !== path) return null;
	try {
		// URLSearchParams tolerates malformed escapes; a navigation context must not.
		decodeURIComponent(match[2] ?? '');
	} catch {
		return null;
	}
	const parameters = new URLSearchParams(match[2] ?? '');
	const preview = parameters.get('preview') ?? '';
	const destination = libraryHref(
		workspaceId,
		readLibraryFilters(parameters),
		libraryPage(parameters),
		libraryPageSize(parameters),
		itemIdentifier.test(preview) ? preview : ''
	);
	const anchor = itemId ?? libraryReturnItemId(match[3] ?? '');
	return anchor && itemIdentifier.test(anchor)
		? `${destination}${anchorPrefix}${anchor}`
		: destination;
}

export function readLibraryReturnTo(
	workspaceId: string,
	parameters: Pick<URLSearchParams, 'get'>
): WorkspacePath | null {
	const value = parameters.get('return_to');
	return value ? libraryReturnTo(workspaceId, value) : null;
}

/** Preserve context on native Item links, including section/PDF query parameters. */
export function libraryItemHref(
	workspaceId: string,
	itemId: string,
	section = '',
	returnTo?: string | null
): WorkspacePath {
	const href = workspaceHref(
		workspaceId,
		`item/${encodeURIComponent(itemId)}${section ? `/${section}` : ''}`
	);
	const destination = returnTo && libraryReturnTo(workspaceId, returnTo);
	if (!destination) return href;
	return `${href}${href.includes('?') ? '&' : '?'}${new URLSearchParams({ return_to: destination })}`;
}

export function libraryReturnHref(
	workspaceId: string,
	parameters: Pick<URLSearchParams, 'get'>,
	{ deletedItemId }: { deletedItemId?: string } = {}
): WorkspacePath {
	const href = readLibraryReturnTo(workspaceId, parameters) ?? libraryHref(workspaceId);
	if (!deletedItemId) return href;
	const destination = new URL(href, 'https://quirebase.invalid/');
	if (destination.searchParams.get('preview') === deletedItemId)
		destination.searchParams.delete('preview');
	if (libraryReturnItemId(destination.hash) === deletedItemId) destination.hash = '';
	return `${destination.pathname.slice(1)}${destination.search}${destination.hash}` as WorkspacePath;
}
