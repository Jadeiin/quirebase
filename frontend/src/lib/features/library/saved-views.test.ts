import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
	deleteLibraryView,
	InvalidSavedViews,
	librarySavedViewsKey,
	readLibrarySavedViews,
	renameLibraryView,
	resetInvalidLibrarySavedViews,
	savedLibraryViewHref,
	savedViewNameLimit,
	saveLibraryView
} from './saved-views.js';
import type { LibraryFilters } from './filters.js';

function memoryStorage() {
	const values = new Map<string, string>();
	return {
		getItem: (key: string) => values.get(key) ?? null,
		setItem: (key: string, value: string) => void values.set(key, value)
	};
}

const key = librarySavedViewsKey('user-1', 'workspace-1');

function deferred() {
	let resolve!: () => void;
	const promise = new Promise<void>((done) => (resolve = done));
	return { promise, resolve };
}

function memoryLocks() {
	const queues = new Map<string, Promise<void>>();
	return {
		request: vi.fn(async <T>(name: string, options: { mode: string }, callback: () => T) => {
			const previous = queues.get(name) ?? Promise.resolve();
			const released = deferred();
			const next = previous.then(() => released.promise);
			queues.set(name, next);
			await previous;
			try {
				return await callback();
			} finally {
				released.resolve();
				if (queues.get(name) === next) queues.delete(name);
			}
		})
	};
}

let locks: ReturnType<typeof memoryLocks>;
beforeEach(() => {
	locks = memoryLocks();
	vi.stubGlobal('navigator', { locks });
});

describe('Library saved views', () => {
	it('creates distinct saved views without crypto.randomUUID', async () => {
		vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) });
		const storage = memoryStorage();
		await saveLibraryView(() => storage, key, 'First', {}, 25);
		await saveLibraryView(() => storage, key, 'Second', { tag: 'tag-1' }, 25);
		const views = readLibrarySavedViews(storage, key);
		expect(views.map(({ name }) => name)).toEqual(['First', 'Second']);
		expect(new Set(views.map(({ id }) => id)).size).toBe(2);
		for (const view of views)
			expect(view.id).toMatch(/^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/);
	});

	it('saves and restores a combined cleanup view within an import receipt', async () => {
		const storage = memoryStorage();
		const filters = {
			import_batch: 'batch-1',
			has_files: false,
			has_tags: false,
			has_projects: false,
			author_last_name: 'Research Council',
			author_first_name: '',
			sort: 'created' as const,
			direction: 'asc' as const
		};
		await saveLibraryView(() => storage, key, 'Imported items to organize', filters, 50, 'view-1');
		const [restored] = readLibrarySavedViews(storage, key);
		expect(restored.filters).toMatchObject(filters);
		const destination = new URL(
			savedLibraryViewHref('workspace-1', restored),
			'https://app.example/'
		);
		expect(destination.pathname).toBe('/workspace/workspace-1/library');
		expect(Object.fromEntries(destination.searchParams)).toEqual({
			import_batch: 'batch-1',
			sort: 'created',
			direction: 'asc',
			has_files: 'false',
			has_tags: 'false',
			has_projects: 'false',
			author_last_name: 'Research Council',
			author_first_name: '',
			page_size: '50'
		});
	});

	it('isolates accounts and Workspaces, including separator characters', async () => {
		const storage = memoryStorage();
		await saveLibraryView(() => storage, key, 'Reading', { project: 'project-1' }, 25, 'view-1');
		expect(readLibrarySavedViews(storage, librarySavedViewsKey('user-2', 'workspace-1'))).toEqual(
			[]
		);
		expect(readLibrarySavedViews(storage, librarySavedViewsKey('user-1', 'workspace-2'))).toEqual(
			[]
		);
		expect(librarySavedViewsKey('a:b', 'c')).not.toBe(librarySavedViewsKey('a', 'b:c'));
	});

	it('stores only canonical submitted filters, exact empty names, sorting and page size', async () => {
		const storage = memoryStorage();
		const filters = {
			query: '  研究 & ML  ',
			project: 'project-1',
			import_batch: 'batch-1',
			tag: 'tag-1',
			author_last_name: 'Smith',
			author_first_name: '',
			publication_title: ' Journal & 特刊 ',
			has_files: false,
			sort: 'author',
			direction: 'desc',
			page: 9,
			preview: 'item-1',
			return_to: 'https://evil.example/',
			unknown: 'ignored'
		} as LibraryFilters;
		const [view] = await saveLibraryView(() => storage, key, '  Reading  ', filters, 50, 'view-1');
		expect(view).toMatchObject({
			id: 'view-1',
			name: 'Reading',
			pageSize: 50,
			filters: {
				query: '研究 & ML',
				import_batch: 'batch-1',
				author_first_name: '',
				publication_title: ' Journal & 特刊 ',
				has_files: false,
				sort: 'author',
				direction: 'desc'
			}
		});
		const stored = JSON.parse(storage.getItem(key)!);
		expect(Object.keys(stored[0]).sort()).toEqual(['id', 'name', 'parameters']);
		const parameters = new URLSearchParams(stored[0].parameters);
		for (const transient of ['page', 'preview', 'return_to', 'unknown'])
			expect(parameters.has(transient)).toBe(false);
		expect(parameters.has('author_first_name')).toBe(true);
		expect(readLibrarySavedViews(storage, key)).toEqual([view]);
		expect(
			new URL(savedLibraryViewHref('workspace-1', view), 'https://app.example/').pathname
		).toBe('/workspace/workspace-1/library');
	});

	it('rebuilds links from supported filters even when stored parameters contain navigation state', () => {
		const storage = memoryStorage();
		storage.setItem(
			key,
			JSON.stringify([
				{
					id: 'view-1',
					name: 'Local view',
					parameters:
						'q=hello&page=8&preview=item-1&return_to=https%3A%2F%2Fevil.example%2F&url=%2F%2Fevil.example&author_first_name=&page_size=1000&sort=unsafe'
				}
			])
		);
		const [view] = readLibrarySavedViews(storage, key);
		expect(savedLibraryViewHref('workspace-1', view)).toBe(
			'workspace/workspace-1/library?q=hello&author_first_name='
		);
	});

	it('rereads before every mutation to preserve changes made by another tab', async () => {
		const storage = memoryStorage();
		const first = await saveLibraryView(() => storage, key, 'First', {}, 25, 'view-1');
		await saveLibraryView(() => storage, key, 'Second', {}, 25, 'view-2');
		expect(first).toHaveLength(1);
		const renamed = await renameLibraryView(() => storage, key, 'view-1', '  Renamed  ');
		expect(renamed.map(({ id, name }) => [id, name])).toEqual([
			['view-1', 'Renamed'],
			['view-2', 'Second']
		]);
		await saveLibraryView(() => storage, key, 'Third', {}, 25, 'view-3');
		expect((await deleteLibraryView(() => storage, key, 'view-1')).map((view) => view.id)).toEqual([
			'view-2',
			'view-3'
		]);
	});

	it('allows multiple names for identical filters and keeps IDs through renaming', async () => {
		const storage = memoryStorage();
		await saveLibraryView(() => storage, key, 'Morning', { tag: 'tag-1' }, 20, 'view-1');
		await saveLibraryView(() => storage, key, 'Evening', { tag: 'tag-1' }, 20, 'view-2');
		const [first, second] = await renameLibraryView(() => storage, key, 'view-1', 'Reading');
		expect(first.id).toBe('view-1');
		expect(first.filters).toEqual(second.filters);
		expect(first.pageSize).toBe(second.pageSize);
	});

	it.each(['', '   ', 'x'.repeat(savedViewNameLimit + 1)])(
		'rejects invalid names without changing storage: %s',
		async (name) => {
			const storage = memoryStorage();
			await saveLibraryView(() => storage, key, 'Existing', {}, 25, 'view-1');
			const previous = storage.getItem(key);
			await expect(saveLibraryView(() => storage, key, name, {}, 25, 'view-2')).rejects.toThrow(
				RangeError
			);
			await expect(renameLibraryView(() => storage, key, 'view-1', name)).rejects.toThrow(
				RangeError
			);
			expect(storage.getItem(key)).toBe(previous);
		}
	);

	it.each([
		'{invalid',
		'null',
		'{}',
		'[null]',
		'[{"id":"view-1","name":" ","parameters":""}]',
		'[{"id":"view-1","name":"A","parameters":""},{"id":"view-1","name":"B","parameters":""}]'
	])('reports damaged collections and requires an explicit reset: %s', async (value) => {
		const storage = memoryStorage();
		storage.setItem(key, value);
		expect(() => readLibrarySavedViews(storage, key)).toThrow(InvalidSavedViews);
		await expect(saveLibraryView(() => storage, key, 'New view', {}, 25, 'view-1')).rejects.toThrow(
			InvalidSavedViews
		);
		expect(storage.getItem(key)).toBe(value);
		expect(await resetInvalidLibrarySavedViews(() => storage, key)).toEqual([]);
		expect(readLibrarySavedViews(storage, key)).toEqual([]);
	});

	it('does not reset a collection already repaired by another tab', async () => {
		const storage = memoryStorage();
		await saveLibraryView(() => storage, key, 'Recovered', {}, 25, 'view-1');
		expect(await resetInvalidLibrarySavedViews(() => storage, key)).toHaveLength(1);
	});

	it('propagates unavailable reads and failed writes without claiming persistence', async () => {
		const unavailable = {
			getItem: () => {
				throw new Error('Storage blocked');
			},
			setItem: () => {
				throw new Error('Storage blocked');
			}
		};
		expect(() => readLibrarySavedViews(unavailable, key)).toThrow('Storage blocked');
		await expect(resetInvalidLibrarySavedViews(() => unavailable, key)).rejects.toThrow(
			'Storage blocked'
		);
		const storage = memoryStorage();
		await saveLibraryView(() => storage, key, 'Existing', {}, 25, 'view-1');
		const previous = storage.getItem(key);
		const full = {
			getItem: storage.getItem,
			setItem: () => {
				throw new Error('Quota exceeded');
			}
		};
		await expect(saveLibraryView(() => full, key, 'New view', {}, 25, 'view-2')).rejects.toThrow(
			'Quota exceeded'
		);
		await expect(renameLibraryView(() => full, key, 'view-1', 'Rename')).rejects.toThrow(
			'Quota exceeded'
		);
		await expect(deleteLibraryView(() => full, key, 'view-1')).rejects.toThrow('Quota exceeded');
		expect(storage.getItem(key)).toBe(previous);
	});

	it('waits for the shared exclusive lock before accessing storage and preserves concurrent saves', async () => {
		const storage = memoryStorage();
		const access = vi.fn(() => storage);
		const entered = deferred();
		const release = deferred();
		const blocker = locks.request(key, { mode: 'exclusive' }, async () => {
			entered.resolve();
			await release.promise;
		});
		await entered.promise;
		const first = saveLibraryView(access, key, 'First tab', {}, 25, 'view-1');
		const second = saveLibraryView(access, key, 'Second tab', {}, 25, 'view-2');
		await Promise.resolve();
		expect(access).not.toHaveBeenCalled();
		expect(
			locks.request.mock.calls.every(
				([name, options]) => name === key && options.mode === 'exclusive'
			)
		).toBe(true);
		release.resolve();
		await Promise.all([blocker, first, second]);
		expect(readLibrarySavedViews(storage, key).map((view) => view.name)).toEqual([
			'First tab',
			'Second tab'
		]);
	});

	it('serializes rename, deletion and reset under the same key without restoring removed views', async () => {
		const storage = memoryStorage();
		await saveLibraryView(() => storage, key, 'First', {}, 25, 'view-1');
		await saveLibraryView(() => storage, key, 'Second', {}, 25, 'view-2');
		const entered = deferred();
		const release = deferred();
		const blocker = locks.request(key, { mode: 'exclusive' }, async () => {
			entered.resolve();
			await release.promise;
		});
		await entered.promise;
		const renamed = renameLibraryView(() => storage, key, 'view-1', 'Renamed');
		const deleted = deleteLibraryView(() => storage, key, 'view-2');
		const reset = resetInvalidLibrarySavedViews(() => storage, key);
		release.resolve();
		await Promise.all([blocker, renamed, deleted, reset]);
		expect(readLibrarySavedViews(storage, key).map(({ id, name }) => [id, name])).toEqual([
			['view-1', 'Renamed']
		]);
		expect(
			locks.request.mock.calls.every(
				([name, options]) => name === key && options.mode === 'exclusive'
			)
		).toBe(true);
	});

	it('releases a failed write so the next queued operation can persist successfully', async () => {
		const storage = memoryStorage();
		const full = {
			getItem: storage.getItem,
			setItem: () => {
				throw new Error('Quota exceeded');
			}
		};
		const failed = saveLibraryView(() => full, key, 'Failed', {}, 25, 'view-1');
		const succeeding = saveLibraryView(() => storage, key, 'Saved', {}, 25, 'view-2');
		await Promise.all([expect(failed).rejects.toThrow('Quota exceeded'), succeeding]);
		expect(readLibrarySavedViews(storage, key).map((view) => view.name)).toEqual(['Saved']);
	});

	it('captures filter values before waiting while independent Workspace keys remain writable', async () => {
		const storage = memoryStorage();
		const entered = deferred();
		const release = deferred();
		const blocker = locks.request(key, { mode: 'exclusive' }, async () => {
			entered.resolve();
			await release.promise;
		});
		await entered.promise;
		const filters = { query: 'Submitted' };
		const queued = saveLibraryView(() => storage, key, 'Snapshot', filters, 50, 'view-1');
		filters.query = 'Changed later';
		const otherKey = librarySavedViewsKey('user-1', 'workspace-2');
		await saveLibraryView(() => storage, otherKey, 'Independent', {}, 25, 'view-2');
		expect(readLibrarySavedViews(storage, key)).toEqual([]);
		expect(readLibrarySavedViews(storage, otherKey)).toHaveLength(1);
		release.resolve();
		await Promise.all([blocker, queued]);
		expect(readLibrarySavedViews(storage, key)[0]).toMatchObject({
			filters: { query: 'Submitted' },
			pageSize: 50
		});
	});

	it('does not silently write without browser lock support', async () => {
		vi.stubGlobal('navigator', {});
		const access = vi.fn(memoryStorage);
		await expect(saveLibraryView(access, key, 'Unsafe', {}, 25, 'view-1')).rejects.toThrow();
		expect(access).not.toHaveBeenCalled();
	});
});
