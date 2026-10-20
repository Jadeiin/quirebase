// @vitest-environment jsdom
import { QueryClient } from '@tanstack/svelte-query';
import { expect, it, vi } from 'vitest';
import { projectOptionsQuery, type ProjectSummary } from './queries.js';

function project(id: string, name = id): ProjectSummary {
	return {
		id,
		name,
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
