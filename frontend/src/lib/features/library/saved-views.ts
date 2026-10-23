/* eslint-disable lingui/no-unlocalized-strings -- Internal storage errors are never rendered; the dialog provides localized feedback. */
import { randomUUID } from '#lib/uuid.js';
import {
	libraryHref,
	libraryPageSize,
	libraryParameters,
	readLibraryFilters,
	type LibraryFilters
} from './filters.js';

export const savedViewNameLimit = 80;

export type LibrarySavedView = {
	id: string;
	name: string;
	filters: LibraryFilters;
	pageSize: number;
};

type ViewStorage = Pick<Storage, 'getItem' | 'setItem'>;
type ViewStorageAccess = () => ViewStorage;

export class InvalidSavedViews extends Error {}

export function librarySavedViewsKey(userId: string, workspaceId: string) {
	return `quirebase:library-views:${encodeURIComponent(userId)}:${encodeURIComponent(workspaceId)}`;
}

function viewName(value: string) {
	const name = value.trim();
	if (!name || name.length > savedViewNameLimit) throw new RangeError('Invalid saved view name');
	return name;
}

function viewParameters(filters: LibraryFilters, pageSize: number) {
	const parameters = libraryParameters(filters, 1, pageSize);
	return libraryParameters(readLibraryFilters(parameters), 1, libraryPageSize(parameters));
}

export function readLibrarySavedViews(storage: ViewStorage, key: string): LibrarySavedView[] {
	const stored = storage.getItem(key);
	if (stored === null) return [];
	let entries: unknown;
	try {
		entries = JSON.parse(stored);
	} catch {
		throw new InvalidSavedViews('Invalid saved views JSON');
	}
	if (!Array.isArray(entries)) throw new InvalidSavedViews('Invalid saved views collection');
	const ids = new Set<string>();
	return entries.map((entry) => {
		if (
			!entry ||
			typeof entry !== 'object' ||
			typeof entry.id !== 'string' ||
			!entry.id ||
			ids.has(entry.id) ||
			typeof entry.name !== 'string' ||
			!entry.name.trim() ||
			entry.name.trim().length > savedViewNameLimit ||
			typeof entry.parameters !== 'string'
		)
			throw new InvalidSavedViews('Invalid saved view');
		ids.add(entry.id);
		const parameters = new URLSearchParams(entry.parameters);
		return {
			id: entry.id,
			name: entry.name.trim(),
			filters: readLibraryFilters(parameters),
			pageSize: libraryPageSize(parameters)
		};
	});
}

function writeLibrarySavedViews(storage: ViewStorage, key: string, views: LibrarySavedView[]) {
	storage.setItem(
		key,
		JSON.stringify(
			views.map(({ id, name, filters, pageSize }) => ({
				id,
				name,
				parameters: viewParameters(filters, pageSize).toString()
			}))
		)
	);
	return views;
}

async function withSavedViewsLock(
	storage: ViewStorageAccess,
	key: string,
	operation: (storage: ViewStorage) => LibrarySavedView[]
) {
	return navigator.locks.request(key, { mode: 'exclusive' }, () => operation(storage()));
}

export async function saveLibraryView(
	storage: ViewStorageAccess,
	key: string,
	name: string,
	filters: LibraryFilters,
	pageSize: number,
	id: string = randomUUID()
) {
	const nextName = viewName(name);
	const parameters = viewParameters(filters, pageSize);
	return withSavedViewsLock(storage, key, (target) => {
		const views = readLibrarySavedViews(target, key);
		if (views.some((view) => view.id === id)) throw new Error('Duplicate saved view ID');
		return writeLibrarySavedViews(target, key, [
			...views,
			{
				id,
				name: nextName,
				filters: readLibraryFilters(parameters),
				pageSize: libraryPageSize(parameters)
			}
		]);
	});
}

export async function renameLibraryView(
	storage: ViewStorageAccess,
	key: string,
	id: string,
	name: string
) {
	const nextName = viewName(name);
	return withSavedViewsLock(storage, key, (target) => {
		const views = readLibrarySavedViews(target, key);
		if (!views.some((view) => view.id === id)) throw new Error('Saved view no longer exists');
		return writeLibrarySavedViews(
			target,
			key,
			views.map((view) => (view.id === id ? { ...view, name: nextName } : view))
		);
	});
}

export async function deleteLibraryView(storage: ViewStorageAccess, key: string, id: string) {
	return withSavedViewsLock(storage, key, (target) =>
		writeLibrarySavedViews(
			target,
			key,
			readLibrarySavedViews(target, key).filter((view) => view.id !== id)
		)
	);
}

/** Reset only damaged data; a different tab may already have repaired the collection. */
export async function resetInvalidLibrarySavedViews(storage: ViewStorageAccess, key: string) {
	return withSavedViewsLock(storage, key, (target) => {
		try {
			return readLibrarySavedViews(target, key);
		} catch (reason) {
			if (!(reason instanceof InvalidSavedViews)) throw reason;
			return writeLibrarySavedViews(target, key, []);
		}
	});
}

export function savedLibraryViewHref(workspaceId: string, view: LibrarySavedView) {
	return libraryHref(workspaceId, view.filters, 1, view.pageSize);
}
