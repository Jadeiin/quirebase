// @vitest-environment jsdom
import { CancelledError, QueryClient } from '@tanstack/svelte-query';
import { expect, it, vi } from 'vitest';
import {
	projectDetailQuery,
	projectListQuery,
	projectOptionsQuery,
	type ProjectSummary
} from './queries.js';
import { ApiError } from '#lib/api/client.js';

function project(id: string, name = id): ProjectSummary {
	return {
		id,
		name,
		created_at: '2026-01-01T00:00:00Z',
		updated_at: '2026-01-02T00:00:00Z',
		item_count: 0,
		state: 'active',
		participation: 'workspace',
		is_participating: true,
		description: '',
		allowed_participation_changes: [],
		authorization: { allowed: ['project_item.manage'] }
	};
}

it('keeps server searches and Workspaces in independent Project option caches', async () => {
	const received: URL[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		const url = new URL(request.url);
		received.push(url);
		return new Response(
			JSON.stringify({
				items: [project(`${url.pathname}:${url.searchParams.get('search')}`)],
				total: 1,
				offset: 0,
				limit: 25
			})
		);
	});
	const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
	try {
		await client.fetchInfiniteQuery(projectOptionsQuery('workspace-1', 'Journal & 特刊'));
		await client.fetchInfiniteQuery(projectOptionsQuery('workspace-1', 'Graph'));
		await client.fetchInfiniteQuery(projectOptionsQuery('workspace-2', 'Graph'));
		await client.fetchInfiniteQuery(projectOptionsQuery('workspace-1', 'Graph'));
		expect(received.map((url) => url.pathname)).toEqual([
			'/api/v1/workspaces/workspace-1/projects',
			'/api/v1/workspaces/workspace-1/projects',
			'/api/v1/workspaces/workspace-2/projects'
		]);
		expect(received.map((url) => Object.fromEntries(url.searchParams))).toEqual([
			{ view: 'all', limit: '25', offset: '0', search: 'Journal & 特刊' },
			{ view: 'all', limit: '25', offset: '0', search: 'Graph' },
			{ view: 'all', limit: '25', offset: '0', search: 'Graph' }
		]);
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});

it('continues a server search at the returned offset and deduplicates changing pages', async () => {
	const offsets: string[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		const url = new URL(request.url);
		const offset = url.searchParams.get('offset')!;
		offsets.push(offset);
		expect(url.searchParams.get('search')).toBe('Methods');
		return new Response(
			JSON.stringify({
				items:
					offset === '0'
						? [project('project-1'), project('project-2', 'Old name')]
						: [project('project-2', 'Updated name'), project('project-26')],
				total: 26,
				offset: Number(offset),
				limit: 25
			})
		);
	});
	const client = new QueryClient();
	try {
		const options = projectOptionsQuery('workspace-1', 'Methods');
		const data = await client.fetchInfiniteQuery({ ...options, pages: 2 });
		expect(offsets).toEqual(['0', '25']);
		expect(options.select?.(data).map(({ id, name }) => ({ id, name }))).toEqual([
			{ id: 'project-1', name: 'project-1' },
			{ id: 'project-2', name: 'Updated name' },
			{ id: 'project-26', name: 'project-26' }
		]);
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});

it('sends every directory filter to the server and separates their cached results', async () => {
	const received: URL[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		const url = new URL(request.url);
		received.push(url);
		return new Response(
			JSON.stringify({ items: [project(url.search)], total: 30, offset: 25, limit: 25 })
		);
	});
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	try {
		await client.fetchQuery(
			projectListQuery('workspace-1', 'mine', 25, 'Methods & 方法', 50, {
				state: 'archived',
				sort: 'updated',
				direction: 'desc'
			})
		);
		await client.fetchQuery(
			projectListQuery('workspace-1', 'mine', 25, 'Methods & 方法', 50, {
				state: 'active',
				sort: 'created',
				direction: 'asc'
			})
		);
		expect(received.map((url) => Object.fromEntries(url.searchParams))).toEqual([
			{
				view: 'mine',
				limit: '50',
				offset: '25',
				search: 'Methods & 方法',
				state: 'archived',
				sort: 'updated',
				direction: 'desc'
			},
			{
				view: 'mine',
				limit: '50',
				offset: '25',
				search: 'Methods & 方法',
				state: 'active',
				sort: 'created',
				direction: 'asc'
			}
		]);
		expect(client.getQueryCache().getAll()).toHaveLength(2);
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});

it.each([401, 403, 404])(
	'purges related directory variants after HTTP %s without corrupting option caches',
	async (status) => {
		const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
		const snapshot = { items: [project('project-1')], total: 1, limit: 25, offset: 0 };
		const current = projectListQuery('workspace-1');
		const related = [
			current,
			projectListQuery('workspace-1', 'mine', 25),
			projectListQuery('workspace-1', 'joinable', 0, 'search', 50, {
				state: 'active',
				sort: 'created',
				direction: 'desc'
			})
		];
		const other = projectListQuery('workspace-2');
		const detail = projectDetailQuery('workspace-1', 'project-1');
		const options = projectOptionsQuery('workspace-1');
		for (const query of [...related, other, detail]) client.setQueryData(query.queryKey, snapshot);
		const optionSnapshot = { pages: [snapshot], pageParams: [0] };
		client.setQueryData(options.queryKey, optionSnapshot);
		vi.stubGlobal(
			'fetch',
			async () =>
				new Response(JSON.stringify({ code: 'not_found', message: 'Unavailable' }), { status })
		);
		try {
			await expect(client.fetchQuery(current)).rejects.toBeInstanceOf(ApiError);
			for (const query of related) {
				expect(client.getQueryData(query.queryKey)).toBeNull();
				expect(client.getQueryState(query.queryKey)?.dataUpdatedAt).toBe(0);
			}
			expect(client.getQueryData(other.queryKey)).toEqual(snapshot);
			expect(client.getQueryData(detail.queryKey)).toEqual(snapshot);
			expect(client.getQueryData(options.queryKey)).toEqual(optionSnapshot);
		} finally {
			client.clear();
			vi.unstubAllGlobals();
		}
	}
);

it('retains directory rows after a transient refresh failure', async () => {
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	const options = projectListQuery('workspace-1');
	const snapshot = { items: [project('project-1')], total: 1, limit: 25, offset: 0 };
	client.setQueryData(options.queryKey, snapshot);
	vi.stubGlobal('fetch', async () => new Response('Unavailable', { status: 503 }));
	try {
		await expect(client.fetchQuery(options)).rejects.toBeInstanceOf(ApiError);
		expect(client.getQueryData(options.queryKey)).toEqual(snapshot);
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});

it('cancels other in-flight directory variants before purging their denied rows', async () => {
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	const pending = projectListQuery('workspace-1', 'mine');
	const denied = projectListQuery('workspace-1', 'all');
	const snapshot = { items: [project('project-1')], total: 1, limit: 25, offset: 0 };
	client.setQueryData(pending.queryKey, snapshot);
	let resolvePending: ((response: Response) => void) | undefined;
	vi.stubGlobal('fetch', async (request: Request) => {
		if (new URL(request.url).searchParams.get('view') === 'mine') {
			return await new Promise<Response>((resolve) => {
				resolvePending = resolve;
			});
		}
		return new Response(JSON.stringify({ code: 'forbidden', message: 'Unavailable' }), {
			status: 403
		});
	});
	try {
		const result = client.fetchQuery(pending).catch((error: unknown) => error);
		await vi.waitFor(() => expect(resolvePending).toBeDefined());
		await expect(client.fetchQuery(denied)).rejects.toBeInstanceOf(ApiError);
		expect(await result).toBeInstanceOf(CancelledError);
		resolvePending!(new Response(JSON.stringify(snapshot)));
		await Promise.resolve();
		expect(client.getQueryData(pending.queryKey)).toBeNull();
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});
