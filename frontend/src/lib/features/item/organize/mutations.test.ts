// @vitest-environment jsdom

import { CancelledError, QueryClient } from '@tanstack/svelte-query';
import { expect, it, vi } from 'vitest';
import { itemKeys, itemOrganizeQuery } from '../queries.js';
import type { OrganizeView } from '../types';
import { projectAssignmentMutationOptions } from './mutations.js';
import {
	libraryKeys,
	libraryListQuery,
	type LibrarySearch
} from '#lib/features/library/queries.js';

const snapshot: OrganizeView = {
	authorization: { allowed: ['project_item.manage', 'tag.use'] },
	projects: [
		{
			id: 'project-denied',
			name: 'Private Project',
			assigned: true,
			participation: 'managed',
			is_participating: true
		},
		{
			id: 'project-readable',
			name: 'Readable Project',
			assigned: false,
			participation: 'workspace',
			is_participating: true
		}
	],
	tag_matrix: {
		groups: [{ letter: 'M', tags: [{ id: 'tag-methods', name: 'Methods' }] }],
		assigned_ids: ['tag-methods'],
		recommended_ids: [],
		suggested_names: [],
		recommendation_state: 'ready',
		recommendation_error: null
	}
};

it.each([
	{ status: 403, assigned: false },
	{ status: 403, assigned: true },
	{ status: 404, assigned: false },
	{ status: 404, assigned: true }
])(
	'purges an unavailable Project across cached Items after $status (assigned=$assigned)',
	async ({ status, assigned }) => {
		vi.stubGlobal(
			'fetch',
			async () =>
				new Response(JSON.stringify({ code: 'not_found', message: 'Project unavailable' }), {
					status
				})
		);
		const client = new QueryClient();
		const current = itemKeys.organize('workspace-1', 'item-1');
		const anotherItem = itemKeys.organize('workspace-1', 'item-2');
		const anotherWorkspace = itemKeys.organize('workspace-2', 'item-1');
		const unaffectedProjection = itemKeys.overview('workspace-1', 'item-1');
		const deniedLists = [
			libraryKeys.list('workspace-1', { project: 'project-denied' }, 1),
			libraryKeys.list('workspace-1', { project: 'project-denied', sort: 'title' }, 2, 10)
		];
		const unaffectedLists = [
			libraryKeys.list('workspace-1', {}, 1),
			libraryKeys.list('workspace-1', { project: 'project-readable' }, 1),
			libraryKeys.list('workspace-2', { project: 'project-denied' }, 1)
		];
		try {
			for (const key of [current, anotherItem, anotherWorkspace, unaffectedProjection])
				client.setQueryData(key, snapshot);
			for (const key of [...deniedLists, ...unaffectedLists])
				client.setQueryData(key, { cached: true });
			const mutation = client
				.getMutationCache()
				.build(client, projectAssignmentMutationOptions('workspace-1', 'item-1', client));
			await expect(
				mutation.execute({ project: { ...snapshot.projects[0], assigned } })
			).rejects.toMatchObject({ status });
			for (const key of [current, anotherItem]) {
				expect(client.getQueryData(key)).toEqual({
					...snapshot,
					projects: [snapshot.projects[1]]
				});
				expect(client.getQueryState(key)?.isInvalidated).toBe(true);
			}
			expect(client.getQueryData(anotherWorkspace)).toEqual(snapshot);
			expect(client.getQueryData(unaffectedProjection)).toEqual(snapshot);
			for (const key of deniedLists) expect(client.getQueryData(key)).toBeNull();
			for (const key of unaffectedLists) expect(client.getQueryData(key)).toEqual({ cached: true });
		} finally {
			client.clear();
		}
	}
);

it('cancels older organize and Library reads before they can restore denied Project data', async () => {
	const started = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	const olderRequests: Request[] = [];
	const librarySnapshot: LibrarySearch = { items: [], total: 0, offset: 25, limit: 25 };
	vi.stubGlobal('fetch', async (request: Request) => {
		if (request.method === 'GET') {
			olderRequests.push(request);
			if (olderRequests.length === 2) started.resolve();
			await release.promise;
			return new Response(
				JSON.stringify(
					new URL(request.url).pathname.endsWith('/organize') ? snapshot : librarySnapshot
				)
			);
		}
		return new Response(JSON.stringify({ code: 'not_found', message: 'Project unavailable' }), {
			status: 404
		});
	});
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	const older = itemOrganizeQuery('workspace-1', 'item-2');
	const olderLibrary = libraryListQuery('workspace-1', { project: 'project-denied' }, 2);
	try {
		client.setQueryData(older.queryKey, snapshot);
		client.setQueryData(olderLibrary.queryKey, librarySnapshot);
		const obsolete = client.fetchQuery(older).catch((reason: unknown) => reason);
		const obsoleteLibrary = client.fetchQuery(olderLibrary).catch((reason: unknown) => reason);
		await started.promise;
		const mutation = client
			.getMutationCache()
			.build(client, projectAssignmentMutationOptions('workspace-1', 'item-1', client));
		await expect(mutation.execute({ project: snapshot.projects[0] })).rejects.toMatchObject({
			status: 404
		});
		for (const request of olderRequests) expect(request.signal.aborted).toBe(true);
		release.resolve();
		expect(await obsolete).toBeInstanceOf(CancelledError);
		expect(await obsoleteLibrary).toBeInstanceOf(CancelledError);
		expect(client.getQueryData(older.queryKey)).toEqual({
			...snapshot,
			projects: [snapshot.projects[1]]
		});
		expect(client.getQueryData(olderLibrary.queryKey)).toBeNull();
	} finally {
		release.resolve();
		client.clear();
	}
});

it.each([409, 500])(
	'retains visible Project associations for a non-access failure %i',
	async (status) => {
		vi.stubGlobal(
			'fetch',
			async () =>
				new Response(
					JSON.stringify({ code: 'project_lifecycle_error', message: 'Project changed' }),
					{ status }
				)
		);
		const client = new QueryClient();
		const current = itemKeys.organize('workspace-1', 'item-1');
		const anotherItem = itemKeys.organize('workspace-1', 'item-2');
		try {
			client.setQueryData(current, snapshot);
			client.setQueryData(anotherItem, snapshot);
			const mutation = client
				.getMutationCache()
				.build(client, projectAssignmentMutationOptions('workspace-1', 'item-1', client));
			await expect(mutation.execute({ project: snapshot.projects[0] })).rejects.toMatchObject({
				status
			});
			expect(client.getQueryData(current)).toEqual(snapshot);
			expect(client.getQueryData(anotherItem)).toEqual(snapshot);
		} finally {
			client.clear();
		}
	}
);
