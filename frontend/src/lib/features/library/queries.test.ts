// @vitest-environment jsdom
import { CancelledError, QueryClient } from '@tanstack/svelte-query';
import { expect, it, vi } from 'vitest';
import { libraryListQuery, type LibrarySearch } from './queries.js';

const snapshot: LibrarySearch = {
	items: [
		{
			id: 'item-1',
			title_html: 'Project working set',
			authors: [],
			publication_date: null,
			publication_title: null,
			doi: null,
			version: 1
		}
	],
	total: 1,
	limit: 25,
	offset: 0
};

it('sends explicit empty exact name parts while omitting blank broad filters', async () => {
	let received: Request | undefined;
	vi.stubGlobal('fetch', async (request: Request) => {
		received = request;
		return new Response(JSON.stringify({ items: [], total: 0, limit: 25, offset: 25 }));
	});
	const client = new QueryClient();
	try {
		await client.fetchQuery(
			libraryListQuery(
				'workspace-1',
				{
					author_last_name: '研究 Council & Co.',
					author_first_name: '',
					publication_title: ' Journal & 特刊 ',
					keyword_exact: 'Graph; theory',
					query: '',
					tag: '',
					has_files: false
				},
				2
			)
		);
		const parameters = new URL(received!.url).searchParams;
		expect(parameters.get('author_first_name')).toBe('');
		expect(parameters.get('author_last_name')).toBe('研究 Council & Co.');
		expect(parameters.get('publication_title')).toBe(' Journal & 特刊 ');
		expect(parameters.get('keyword_exact')).toBe('Graph; theory');
		expect(parameters.get('has_files')).toBe('false');
		expect(parameters.get('offset')).toBe('25');
		expect(parameters.has('query')).toBe(false);
		expect(parameters.has('tag')).toBe(false);
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});

it('fetches different page sizes independently and uses the size to compute the offset', async () => {
	const received: URL[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		const url = new URL(request.url);
		received.push(url);
		return new Response(
			JSON.stringify({
				items: [],
				total: 101,
				limit: Number(url.searchParams.get('limit')),
				offset: Number(url.searchParams.get('offset'))
			})
		);
	});
	const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
	try {
		for (const size of [10, 50, 10]) {
			await client.fetchQuery(libraryListQuery('workspace-1', { sort: 'title' }, 3, size));
		}
		expect(
			received.map(({ searchParams }) => ({
				limit: searchParams.get('limit'),
				offset: searchParams.get('offset'),
				sort: searchParams.get('sort')
			}))
		).toEqual([
			{ limit: '10', offset: '20', sort: 'title' },
			{ limit: '50', offset: '100', sort: 'title' }
		]);
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});

it.each([401, 403, 404])(
	'discards denied Project lists after HTTP %i until a successful read',
	async (status) => {
		let responseStatus = status;
		vi.stubGlobal(
			'fetch',
			async () =>
				new Response(
					JSON.stringify(
						responseStatus === 200 ? snapshot : { code: 'request_failed', message: 'Read failed' }
					),
					{ status: responseStatus }
				)
		);
		const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
		const current = libraryListQuery('workspace-1', { project: 'project-1' }, 1);
		const related = [
			current,
			libraryListQuery('workspace-1', { project: 'project-1' }, 2),
			libraryListQuery('workspace-1', { project: 'project-1', sort: 'title' }, 1, 10)
		];
		const unrelated = [
			libraryListQuery('workspace-1', {}, 1),
			libraryListQuery('workspace-1', { project: 'project-2' }, 1),
			libraryListQuery('workspace-2', { project: 'project-1' }, 1)
		];
		try {
			for (const options of [...related, ...unrelated])
				client.setQueryData(options.queryKey, snapshot);
			await expect(client.fetchQuery(current)).rejects.toMatchObject({ status });
			for (const options of related) expect(client.getQueryData(options.queryKey)).toBeNull();
			for (const options of unrelated)
				expect(client.getQueryData(options.queryKey)).toEqual(snapshot);
			responseStatus = 500;
			await expect(client.fetchQuery(current)).rejects.toMatchObject({ status: 500 });
			expect(client.getQueryData(current.queryKey)).toBeNull();
			responseStatus = 200;
			await expect(client.fetchQuery(current)).resolves.toEqual(snapshot);
			expect(client.getQueryData(current.queryKey)).toEqual(snapshot);
		} finally {
			client.clear();
			vi.unstubAllGlobals();
		}
	}
);

it.each([0, 429, 500])('keeps the last snapshot after transient failure %i', async (status) => {
	vi.stubGlobal('fetch', async () => {
		if (!status) throw new TypeError('Network unavailable');
		return new Response(JSON.stringify({ code: 'request_failed', message: 'Temporary failure' }), {
			status
		});
	});
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	const options = libraryListQuery('workspace-1', { project: 'project-1' }, 1);
	try {
		client.setQueryData(options.queryKey, snapshot);
		await expect(client.fetchQuery(options)).rejects.toBeInstanceOf(Error);
		expect(client.getQueryData(options.queryKey)).toEqual(snapshot);
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});

it('cancels an older Project page before its late response can restore denied associations', async () => {
	let olderRequest: Request | undefined;
	let arrived = () => {};
	let release = () => {};
	const requested = new Promise<void>((resolve) => {
		arrived = resolve;
	});
	vi.stubGlobal('fetch', async (request: Request) => {
		if (new URL(request.url).searchParams.get('offset') === '25') {
			olderRequest = request;
			arrived();
			return new Promise<Response>((resolve) => {
				release = () => resolve(new Response(JSON.stringify(snapshot)));
			});
		}
		return new Response(JSON.stringify({ code: 'not_found', message: 'Not found' }), {
			status: 404
		});
	});
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	const current = libraryListQuery('workspace-1', { project: 'project-1' }, 1);
	const older = libraryListQuery('workspace-1', { project: 'project-1' }, 2);
	try {
		client.setQueryData(current.queryKey, snapshot);
		client.setQueryData(older.queryKey, snapshot);
		const obsolete = client.fetchQuery(older).catch((reason: unknown) => reason);
		await requested;
		await expect(client.fetchQuery(current)).rejects.toMatchObject({ status: 404 });
		expect(olderRequest?.signal.aborted).toBe(true);
		release();
		expect(await obsolete).toBeInstanceOf(CancelledError);
		expect(client.getQueryData(older.queryKey)).toBeNull();
	} finally {
		release();
		client.clear();
		vi.unstubAllGlobals();
	}
});
