// @vitest-environment jsdom
import { CancelledError, QueryClient } from '@tanstack/svelte-query';
import { expect, it, vi } from 'vitest';
import {
	invalidateItemOrganize,
	invalidateUnavailableImportBatch,
	invalidateUnavailableProject
} from '#lib/query/invalidation.js';
import {
	libraryFacetsQuery,
	libraryListQuery,
	type LibraryFacets,
	type LibrarySearch
} from './queries.js';

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

const facetSnapshot: LibraryFacets = {
	authors: [{ last_name: 'Smith', first_name: null, full_name: 'Smith', item_count: 1 }],
	keywords: [{ value: 'Graph theory', item_count: 1 }],
	reference_types: [{ value: 'Dataset', item_count: 1 }]
};

it.each(['list', 'facets'] as const)(
	'forwards combined organization filters to the %s endpoint without losing false values',
	async (source) => {
		const received: URL[] = [];
		vi.stubGlobal('fetch', async (request: Request) => {
			received.push(new URL(request.url));
			return new Response(JSON.stringify(source === 'list' ? snapshot : facetSnapshot));
		});
		const client = new QueryClient();
		try {
			const filters = {
				import_batch: 'batch-1',
				has_files: false,
				has_tags: false,
				has_projects: false,
				sort: 'created' as const,
				direction: 'asc' as const
			};
			if (source === 'list') {
				await client.fetchQuery(libraryListQuery('workspace-1', filters, 3, 50));
			} else {
				await client.fetchQuery(libraryFacetsQuery('workspace-1', filters, 3, 50));
			}
			expect(received).toHaveLength(1);
			expect(Object.fromEntries(received[0].searchParams)).toEqual({
				import_batch: 'batch-1',
				has_files: 'false',
				has_tags: 'false',
				has_projects: 'false',
				limit: '50',
				offset: '100',
				sort: 'created',
				direction: 'asc'
			});
		} finally {
			client.clear();
			vi.unstubAllGlobals();
		}
	}
);

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
					authors: [{ last_name: '研究 Council & Co.', first_name: '' }],
					publication_title: ' Journal & 特刊 ',
					keyword_exact: 'Graph; theory',
					query: '',
					import_batch: 'batch-1',
					tag: '',
					has_files: false
				},
				2
			)
		);
		const parameters = new URL(received!.url).searchParams;
		expect(JSON.parse(parameters.get('authors')!)).toEqual([
			{ last_name: '研究 Council & Co.', first_name: '' }
		]);
		expect(parameters.get('publication_title')).toBe(' Journal & 特刊 ');
		expect(parameters.get('keyword_exact')).toBe('Graph; theory');
		expect(parameters.get('has_files')).toBe('false');
		expect(parameters.get('offset')).toBe('25');
		expect(parameters.get('import_batch')).toBe('batch-1');
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

it('reads facets for the current page, size and sorting while preserving exact filters', async () => {
	const received: URL[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		received.push(new URL(request.url));
		return new Response(JSON.stringify(facetSnapshot));
	});
	const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
	const filters = {
		query: '',
		tag: '',
		project: 'project-1',
		import_batch: 'batch-1',
		year: '2025',
		keyword: 'graph',
		author: '',
		reference_type: 'Dataset',
		publication_title: ' Journal & 特刊 ',
		keyword_exact: 'Graph; theory',
		authors: [{ last_name: '研究 Council & Co.', first_name: '' }],
		has_files: false
	};
	try {
		await client.fetchQuery(
			libraryFacetsQuery('workspace-1', { ...filters, sort: 'title', direction: 'asc' }, 2, 10)
		);
		await client.fetchQuery(
			libraryFacetsQuery('workspace-1', { ...filters, sort: 'published', direction: 'desc' }, 2, 10)
		);
		await client.fetchQuery(
			libraryFacetsQuery('workspace-1', { ...filters, sort: 'published', direction: 'desc' }, 3, 10)
		);
		await client.fetchQuery(
			libraryFacetsQuery('workspace-1', { ...filters, sort: 'published', direction: 'desc' }, 3, 50)
		);
		await client.fetchQuery(
			libraryFacetsQuery('workspace-1', { ...filters, sort: 'published', direction: 'asc' }, 3, 50)
		);
		await client.fetchQuery(
			libraryFacetsQuery('workspace-1', { ...filters, sort: 'title', direction: 'asc' }, 2, 10)
		);
		expect(received).toHaveLength(5);
		expect(received[0].pathname).toBe('/api/v1/workspaces/workspace-1/items/facets');
		expect(Object.fromEntries(received[0].searchParams)).toEqual({
			project: 'project-1',
			import_batch: 'batch-1',
			year: '2025',
			keyword: 'graph',
			reference_type: 'Dataset',
			publication_title: ' Journal & 特刊 ',
			keyword_exact: 'Graph; theory',
			authors: JSON.stringify([{ last_name: '研究 Council & Co.', first_name: '' }]),
			has_files: 'false',
			limit: '10',
			offset: '10',
			sort: 'title',
			direction: 'asc'
		});
		expect(
			received.map(({ searchParams }) => ({
				limit: searchParams.get('limit'),
				offset: searchParams.get('offset'),
				sort: searchParams.get('sort'),
				direction: searchParams.get('direction')
			}))
		).toEqual([
			{ limit: '10', offset: '10', sort: 'title', direction: 'asc' },
			{ limit: '10', offset: '10', sort: 'published', direction: 'desc' },
			{ limit: '10', offset: '20', sort: 'published', direction: 'desc' },
			{ limit: '50', offset: '100', sort: 'published', direction: 'desc' },
			{ limit: '50', offset: '100', sort: 'published', direction: 'asc' }
		]);
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});

it.each(
	[401, 403, 404].flatMap((status) =>
		(['list', 'facets'] as const).map((source) => ({ status, source }))
	)
)(
	'discards related Project lists and facets after $source rejects with HTTP $status until a successful read',
	async ({ status, source }) => {
		let responseStatus = status;
		vi.stubGlobal(
			'fetch',
			async (request: Request) =>
				new Response(
					JSON.stringify(
						responseStatus === 200
							? new URL(request.url).pathname.endsWith('/facets')
								? facetSnapshot
								: snapshot
							: { code: 'request_failed', message: 'Read failed' }
					),
					{ status: responseStatus }
				)
		);
		const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
		const current = libraryListQuery('workspace-1', { project: 'project-1' }, 1);
		const currentFacets = libraryFacetsQuery('workspace-1', { project: 'project-1' });
		const fetchCurrent = () =>
			source === 'list' ? client.fetchQuery(current) : client.fetchQuery(currentFacets);
		const currentKey = source === 'list' ? current.queryKey : currentFacets.queryKey;
		const currentData = source === 'list' ? snapshot : facetSnapshot;
		const related = [
			{ key: current.queryKey, data: snapshot },
			{
				key: libraryListQuery('workspace-1', { project: 'project-1' }, 2).queryKey,
				data: snapshot
			},
			{
				key: libraryListQuery('workspace-1', { project: 'project-1', sort: 'title' }, 1, 10)
					.queryKey,
				data: snapshot
			},
			{ key: currentFacets.queryKey, data: facetSnapshot },
			{
				key: libraryFacetsQuery(
					'workspace-1',
					{ project: 'project-1', year: '2025', sort: 'title', direction: 'asc' },
					3,
					10
				).queryKey,
				data: facetSnapshot
			}
		];
		const unrelated = [
			{ key: libraryListQuery('workspace-1', {}, 1).queryKey, data: snapshot },
			{
				key: libraryListQuery('workspace-1', { project: 'project-2' }, 1).queryKey,
				data: snapshot
			},
			{
				key: libraryListQuery('workspace-2', { project: 'project-1' }, 1).queryKey,
				data: snapshot
			},
			{ key: libraryFacetsQuery('workspace-1', {}).queryKey, data: facetSnapshot },
			{
				key: libraryFacetsQuery('workspace-1', { project: 'project-2' }).queryKey,
				data: facetSnapshot
			},
			{
				key: libraryFacetsQuery('workspace-2', { project: 'project-1' }).queryKey,
				data: facetSnapshot
			}
		];
		try {
			for (const { key, data } of [...related, ...unrelated])
				client.setQueryData<LibrarySearch | LibraryFacets>(key, data);
			await expect(fetchCurrent()).rejects.toMatchObject({ status });
			for (const { key } of related) expect(client.getQueryData(key)).toBeNull();
			for (const { key, data } of unrelated) expect(client.getQueryData(key)).toEqual(data);
			responseStatus = 500;
			await expect(fetchCurrent()).rejects.toMatchObject({ status: 500 });
			expect(client.getQueryData(currentKey)).toBeNull();
			responseStatus = 200;
			await expect(fetchCurrent()).resolves.toEqual(currentData);
			expect(client.getQueryData(currentKey)).toEqual(currentData);
		} finally {
			client.clear();
			vi.unstubAllGlobals();
		}
	}
);

it.each(
	[403, 404, 409].flatMap((status) =>
		(['list', 'facets'] as const).map((source) => ({ status, source }))
	)
)(
	'purges only the unavailable import batch across cached pages and facets on $source HTTP $status',
	async ({ status, source }) => {
		vi.stubGlobal(
			'fetch',
			async () =>
				new Response(
					JSON.stringify({
						code: status === 409 ? 'import_batch_conflict' : 'not_found',
						message: 'Batch unavailable'
					}),
					{ status }
				)
		);
		const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
		const current = libraryListQuery('workspace-1', { import_batch: 'batch-1' }, 1);
		const facets = libraryFacetsQuery('workspace-1', { import_batch: 'batch-1' });
		const related = [
			{ key: current.queryKey, data: snapshot },
			{
				key: libraryListQuery('workspace-1', { import_batch: 'batch-1', sort: 'title' }, 2, 50)
					.queryKey,
				data: snapshot
			},
			{ key: facets.queryKey, data: facetSnapshot },
			{
				key: libraryFacetsQuery(
					'workspace-1',
					{ import_batch: 'batch-1', year: '2026', sort: 'published', direction: 'desc' },
					2,
					50
				).queryKey,
				data: facetSnapshot
			}
		];
		const unrelated = [
			{
				key: libraryListQuery('workspace-1', { import_batch: 'batch-2' }, 1).queryKey,
				data: snapshot
			},
			{ key: libraryFacetsQuery('workspace-1', {}).queryKey, data: facetSnapshot },
			{
				key: libraryFacetsQuery('workspace-2', { import_batch: 'batch-1' }).queryKey,
				data: facetSnapshot
			}
		];
		try {
			for (const { key, data } of [...related, ...unrelated])
				client.setQueryData<LibrarySearch | LibraryFacets>(key, data);
			await expect(
				source === 'list' ? client.fetchQuery(current) : client.fetchQuery(facets)
			).rejects.toMatchObject({ status });
			for (const { key } of related) expect(client.getQueryData(key)).toBeNull();
			for (const { key, data } of unrelated) expect(client.getQueryData(key)).toEqual(data);
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
	const options = libraryListQuery(
		'workspace-1',
		{ project: 'project-1', import_batch: 'batch-1' },
		1
	);
	const facets = libraryFacetsQuery('workspace-1', {
		project: 'project-1',
		import_batch: 'batch-1'
	});
	try {
		client.setQueryData(options.queryKey, snapshot);
		client.setQueryData(facets.queryKey, facetSnapshot);
		await expect(client.fetchQuery(options)).rejects.toBeInstanceOf(Error);
		await expect(client.fetchQuery(facets)).rejects.toBeInstanceOf(Error);
		expect(client.getQueryData(options.queryKey)).toEqual(snapshot);
		expect(client.getQueryData(facets.queryKey)).toEqual(facetSnapshot);
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});

it.each(
	[
		{ status: 404, code: 'import_batch_unavailable', unavailable: 'import_batch' },
		{ status: 409, code: 'import_batch_conflict', unavailable: 'import_batch' },
		{ status: 403, code: 'permission_denied', unavailable: 'project' },
		{ status: 404, code: 'not_found', unavailable: 'project' }
	].flatMap((failure) => (['list', 'facets'] as const).map((source) => ({ ...failure, source })))
)(
	'purges only the failed $unavailable from combined filters after $source receives $code',
	async ({ status, code, unavailable, source }) => {
		vi.stubGlobal(
			'fetch',
			async () => new Response(JSON.stringify({ code, message: 'Unavailable' }), { status })
		);
		const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
		const filters = { project: 'project-1', import_batch: 'batch-1' };
		const list = libraryListQuery('workspace-1', filters, 1);
		const facets = libraryFacetsQuery('workspace-1', filters);
		const caches = [
			{ workspaceId: 'workspace-1', filters },
			{ workspaceId: 'workspace-1', filters: { ...filters, sort: 'title' as const } },
			{ workspaceId: 'workspace-1', filters: { project: 'project-1' } },
			{ workspaceId: 'workspace-1', filters: { import_batch: 'batch-1' } },
			{
				workspaceId: 'workspace-1',
				filters: { project: 'project-1', import_batch: 'batch-2' }
			},
			{
				workspaceId: 'workspace-1',
				filters: { project: 'project-2', import_batch: 'batch-1' }
			},
			{ workspaceId: 'workspace-2', filters }
		].flatMap(({ workspaceId, filters }) =>
			[
				{ key: libraryListQuery(workspaceId, filters, 2, 10).queryKey, data: snapshot },
				{ key: libraryFacetsQuery(workspaceId, filters, 3, 50).queryKey, data: facetSnapshot }
			].map((cache) => ({
				...cache,
				denied:
					workspaceId === 'workspace-1' &&
					(unavailable === 'project'
						? filters.project === 'project-1'
						: filters.import_batch === 'batch-1')
			}))
		);
		try {
			client.setQueryData(list.queryKey, snapshot);
			client.setQueryData(facets.queryKey, facetSnapshot);
			for (const { key, data } of caches)
				client.setQueryData<LibrarySearch | LibraryFacets>(key, data);
			await expect(
				source === 'list' ? client.fetchQuery(list) : client.fetchQuery(facets)
			).rejects.toMatchObject({ status, code });
			expect(client.getQueryData(list.queryKey)).toBeNull();
			expect(client.getQueryData(facets.queryKey)).toBeNull();
			for (const { key, data, denied } of caches)
				expect(client.getQueryData(key)).toEqual(denied ? null : data);
		} finally {
			client.clear();
			vi.unstubAllGlobals();
		}
	}
);

it.each([{ project: 'project-1' }, { import_batch: 'batch-1' }])(
	'cancels an older scoped page before its late response can restore unavailable data: %j',
	async (filters) => {
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
		const current = libraryListQuery('workspace-1', filters, 1);
		const older = libraryListQuery('workspace-1', filters, 2);
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
	}
);

it.each([
	{
		code: 'import_batch_unavailable',
		related: { import_batch: 'batch-1' },
		valid: { project: 'project-1' }
	},
	{ code: 'not_found', related: { project: 'project-1' }, valid: { import_batch: 'batch-1' } }
])(
	'cancels only the failed scope from combined filters on $code',
	async ({ code, related, valid }) => {
		const requests: Request[] = [];
		const releases: Array<() => void> = [];
		vi.stubGlobal('fetch', async (request: Request) => {
			const url = new URL(request.url);
			if (url.searchParams.has('project') && url.searchParams.has('import_batch'))
				return new Response(JSON.stringify({ code, message: 'Unavailable' }), { status: 404 });
			requests.push(request);
			return new Promise<Response>((resolve) => {
				releases.push(() =>
					resolve(
						new Response(
							JSON.stringify(url.pathname.endsWith('/facets') ? facetSnapshot : snapshot)
						)
					)
				);
			});
		});
		const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
		const current = libraryListQuery(
			'workspace-1',
			{ project: 'project-1', import_batch: 'batch-1' },
			1
		);
		const relatedList = libraryListQuery('workspace-1', related, 2);
		const relatedFacets = libraryFacetsQuery('workspace-1', related);
		const validList = libraryListQuery('workspace-1', valid, 2);
		const validFacets = libraryFacetsQuery('workspace-1', valid);
		const pending = [
			client.fetchQuery(relatedList).catch((reason: unknown) => reason),
			client.fetchQuery(relatedFacets).catch((reason: unknown) => reason),
			client.fetchQuery(validList),
			client.fetchQuery(validFacets)
		];
		try {
			await vi.waitFor(() => expect(requests).toHaveLength(4));
			await expect(client.fetchQuery(current)).rejects.toMatchObject({ code });
			expect(requests.map((request) => request.signal.aborted)).toEqual([true, true, false, false]);
			for (const release of releases) release();
			const results = await Promise.all(pending);
			expect(results[0]).toBeInstanceOf(CancelledError);
			expect(results[1]).toBeInstanceOf(CancelledError);
			expect(client.getQueryData(relatedList.queryKey)).toBeNull();
			expect(client.getQueryData(relatedFacets.queryKey)).toBeNull();
			expect(client.getQueryData(validList.queryKey)).toEqual(snapshot);
			expect(client.getQueryData(validFacets.queryKey)).toEqual(facetSnapshot);
		} finally {
			for (const release of releases) release();
			client.clear();
			vi.unstubAllGlobals();
		}
	}
);

it.each(['list', 'facets'] as const)(
	'cancels related in-flight reads when a Project %s request is denied',
	async (source) => {
		let olderRequest: Request | undefined;
		let arrived = () => {};
		let release = () => {};
		const requested = new Promise<void>((resolve) => {
			arrived = resolve;
		});
		vi.stubGlobal('fetch', async (request: Request) => {
			const facetRequest = new URL(request.url).pathname.endsWith('/facets');
			if (facetRequest === (source === 'list')) {
				olderRequest = request;
				arrived();
				return new Promise<Response>((resolve) => {
					release = () =>
						resolve(new Response(JSON.stringify(facetRequest ? facetSnapshot : snapshot)));
				});
			}
			return new Response(JSON.stringify({ code: 'not_found', message: 'Not found' }), {
				status: 404
			});
		});
		const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
		const list = libraryListQuery('workspace-1', { project: 'project-1' }, 1);
		const facets = libraryFacetsQuery('workspace-1', { project: 'project-1' });
		try {
			client.setQueryData(list.queryKey, snapshot);
			client.setQueryData(facets.queryKey, facetSnapshot);
			const obsolete = (
				source === 'list' ? client.fetchQuery(facets) : client.fetchQuery(list)
			).catch((reason: unknown) => reason);
			await requested;
			await expect(
				source === 'list' ? client.fetchQuery(list) : client.fetchQuery(facets)
			).rejects.toMatchObject({ status: 404 });
			expect(olderRequest?.signal.aborted).toBe(true);
			release();
			expect(await obsolete).toBeInstanceOf(CancelledError);
			expect(client.getQueryData(list.queryKey)).toBeNull();
			expect(client.getQueryData(facets.queryKey)).toBeNull();
		} finally {
			release();
			client.clear();
			vi.unstubAllGlobals();
		}
	}
);

it('invalidates cached facet counts after Item organization changes without touching other Workspaces', async () => {
	const client = new QueryClient();
	const current = libraryFacetsQuery('workspace-1', { tag: 'tag-1' });
	const unrelated = libraryFacetsQuery('workspace-2', { tag: 'tag-1' });
	try {
		for (const options of [current, unrelated])
			client.setQueryData(options.queryKey, facetSnapshot);
		await invalidateItemOrganize(client, 'workspace-1', 'item-1');
		expect(client.getQueryState(current.queryKey)?.isInvalidated).toBe(true);
		expect(client.getQueryState(unrelated.queryKey)?.isInvalidated).toBe(false);
	} finally {
		client.clear();
	}
});

it('purges unavailable Project facets independently of list pages and other Projects', async () => {
	const client = new QueryClient();
	const related = libraryFacetsQuery('workspace-1', { project: 'project-1' });
	const unrelated = [
		libraryFacetsQuery('workspace-1', { project: 'project-2' }),
		libraryFacetsQuery('workspace-2', { project: 'project-1' })
	];
	try {
		for (const options of [related, ...unrelated])
			client.setQueryData(options.queryKey, facetSnapshot);
		await invalidateUnavailableProject(client, 'workspace-1', 'project-1');
		expect(client.getQueryData(related.queryKey)).toBeNull();
		for (const options of unrelated)
			expect(client.getQueryData(options.queryKey)).toEqual(facetSnapshot);
	} finally {
		client.clear();
	}
});

it('retires deleted receipt projections across pages and facets without allowing late reads to restore them', async () => {
	const requests: Request[] = [];
	const releases: Array<() => void> = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		requests.push(request);
		return new Promise<Response>((resolve) => {
			releases.push(() =>
				resolve(
					new Response(
						JSON.stringify(
							new URL(request.url).pathname.endsWith('/facets') ? facetSnapshot : snapshot
						)
					)
				)
			);
		});
	});
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	const current = libraryListQuery('workspace-1', { import_batch: 'batch-1' }, 1);
	const facets = libraryFacetsQuery('workspace-1', { import_batch: 'batch-1' });
	const related = [
		{ key: current.queryKey, data: snapshot },
		{ key: facets.queryKey, data: facetSnapshot },
		{
			key: libraryListQuery('workspace-1', { import_batch: 'batch-1' }, 2).queryKey,
			data: snapshot
		},
		{
			key: libraryListQuery('workspace-1', { import_batch: 'batch-1', sort: 'title' }, 1, 10)
				.queryKey,
			data: snapshot
		},
		{
			key: libraryFacetsQuery('workspace-1', { import_batch: 'batch-1', year: '2025' }).queryKey,
			data: facetSnapshot
		}
	];
	const unrelated = [
		{
			key: libraryListQuery('workspace-1', { import_batch: 'batch-2' }, 1).queryKey,
			data: snapshot
		},
		{
			key: libraryFacetsQuery('workspace-1', { import_batch: 'batch-2' }).queryKey,
			data: facetSnapshot
		},
		{
			key: libraryListQuery('workspace-2', { import_batch: 'batch-1' }, 1).queryKey,
			data: snapshot
		},
		{
			key: libraryFacetsQuery('workspace-2', { import_batch: 'batch-1' }).queryKey,
			data: facetSnapshot
		},
		{ key: libraryListQuery('workspace-1', {}, 1).queryKey, data: snapshot }
	];
	try {
		for (const { key, data } of [...related, ...unrelated])
			client.setQueryData<LibrarySearch | LibraryFacets>(key, data);
		const pendingList = client.fetchQuery(current).catch((reason: unknown) => reason);
		const pendingFacets = client.fetchQuery(facets).catch((reason: unknown) => reason);
		await vi.waitFor(() => expect(requests).toHaveLength(2));
		await invalidateUnavailableImportBatch(client, 'workspace-1', 'batch-1');
		for (const request of requests) expect(request.signal.aborted).toBe(true);
		for (const release of releases) release();
		expect(await pendingList).toBeInstanceOf(CancelledError);
		expect(await pendingFacets).toBeInstanceOf(CancelledError);
		for (const { key } of related) {
			expect(client.getQueryData(key)).toBeNull();
			expect(client.getQueryState(key)?.dataUpdatedAt).toBe(0);
		}
		for (const { key, data } of unrelated) expect(client.getQueryData(key)).toEqual(data);
	} finally {
		for (const release of releases) release();
		client.clear();
		vi.unstubAllGlobals();
	}
});
