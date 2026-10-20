// @vitest-environment jsdom

import { QueryClient } from '@tanstack/svelte-query';
import { describe, expect, it, vi } from 'vitest';
import { defaultExportPreferences } from '#lib/export-preferences.js';
import {
	libraryBulkMutationOptions,
	runLibraryBulkMutation,
	type LibraryBulkAction
} from './mutations';
import { itemKeys } from '#lib/features/item/queries.js';
import { projectKeys } from '#lib/features/projects/queries.js';
import { pdfReaderKeys } from '#lib/features/pdf-reader/queries.js';
import { tagKeys } from '#lib/features/tags/queries.js';
import { libraryKeys } from './queries.js';

describe('Library bulk request contract', () => {
	it.each([
		'add_tag',
		'remove_tag',
		'delete',
		'add_project',
		'remove_project'
	] as LibraryBulkAction[])('serializes valid optional UUIDs for %s', async (action) => {
		const projectId =
			action === 'add_project' || action === 'remove_project'
				? '01930abc-0000-7000-8000-000000000001'
				: '';
		const tagId = '01930abc-0000-7000-8000-000000000004';
		let body: Record<string, unknown> | undefined;
		vi.stubGlobal(
			'fetch',
			vi.fn(async (input: RequestInfo | URL) => {
				body = await (input as Request).json();
				return new Response(JSON.stringify({ affected: 1 }), {
					headers: { 'Content-Type': 'application/json' }
				});
			})
		);
		await runLibraryBulkMutation(
			'01930abc-0000-7000-8000-000000000002',
			{
				action,
				itemIds: ['01930abc-0000-7000-8000-000000000003'],
				projectId,
				tagName: 'Research',
				tagId,
				exportFormat: 'bibtex',
				preferences: defaultExportPreferences
			},
			new QueryClient()
		);
		expect(body?.action).toBe(action);
		if (projectId) expect(body?.project_id).toBe(projectId);
		else expect(body).not.toHaveProperty('project_id');
		if (action === 'remove_tag') expect(body?.tag_id).toBe(tagId);
		else expect(body).not.toHaveProperty('tag_id');
		if (action === 'add_tag') expect(body?.tag_name).toBe('Research');
		else expect(body?.tag_name).toBe('');
		if (action === 'delete') expect(body?.confirmation).toBe('delete');
		else if (action === 'remove_project') expect(body?.confirmation).toBe('remove_project');
		else expect(body?.confirmation).toBe('');
	});

	it.each(['remove_project', 'remove_tag'] as const)(
		'invalidates associated read models after %s without affecting another Workspace',
		async (action) => {
			vi.stubGlobal(
				'fetch',
				vi.fn(async () => new Response('{}', { headers: { 'Content-Type': 'application/json' } }))
			);
			const client = new QueryClient();
			const keys = [
				libraryKeys.list('workspace-1', { project: 'project-1' }, 2),
				itemKeys.overview('workspace-1', 'item-1'),
				itemKeys.organize('workspace-1', 'item-1'),
				...(action === 'remove_project'
					? [
							projectKeys.detail('workspace-1', 'project-1'),
							pdfReaderKeys.viewer('workspace-1', 'item-1', 'revision-1')
						]
					: [tagKeys.all('workspace-1')])
			];
			for (const key of keys) client.setQueryData(key, { stale: true });
			const otherWorkspace = itemKeys.overview('workspace-2', 'item-1');
			client.setQueryData(otherWorkspace, { stale: false });
			await runLibraryBulkMutation(
				'workspace-1',
				{
					action,
					itemIds: ['item-1'],
					projectId: 'project-1',
					tagName: 'Research',
					tagId: 'tag-1',
					exportFormat: 'bibtex',
					preferences: defaultExportPreferences
				},
				client
			);
			for (const key of keys) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
			expect(client.getQueryState(otherWorkspace)?.isInvalidated).toBe(false);
		}
	);

	it.each([
		{ action: 'add_project', status: 403 },
		{ action: 'add_project', status: 404 },
		{ action: 'remove_project', status: 403 },
		{ action: 'remove_project', status: 404 }
	] as const)(
		'reconciles cached Project associations after $action receives $status',
		async ({ action, status }) => {
			vi.stubGlobal(
				'fetch',
				async () =>
					new Response(JSON.stringify({ code: 'not_found', message: 'Project unavailable' }), {
						status
					})
			);
			const client = new QueryClient();
			const listing = libraryKeys.list('workspace-1', { project: 'project-1' }, 1);
			const anotherListing = libraryKeys.list('workspace-1', { project: 'project-2' }, 1);
			const organize = itemKeys.organize('workspace-1', 'item-2');
			const otherWorkspace = itemKeys.organize('workspace-2', 'item-2');
			const snapshot = {
				projects: [{ id: 'project-1' }, { id: 'project-2' }],
				tag_matrix: { assigned_ids: ['tag-1'] }
			};
			try {
				client.setQueryData(listing, { cached: true });
				client.setQueryData(anotherListing, { cached: true });
				client.setQueryData(organize, snapshot);
				client.setQueryData(otherWorkspace, snapshot);
				const mutation = client
					.getMutationCache()
					.build(client, libraryBulkMutationOptions('workspace-1', client));
				await expect(
					mutation.execute({
						input: {
							action,
							itemIds: ['item-1'],
							projectId: 'project-1',
							tagName: '',
							exportFormat: 'bibtex',
							preferences: defaultExportPreferences
						}
					})
				).rejects.toMatchObject({ status });
				expect(client.getQueryData(listing)).toBeNull();
				expect(client.getQueryData(anotherListing)).toEqual({ cached: true });
				expect(client.getQueryData(organize)).toEqual({
					...snapshot,
					projects: [{ id: 'project-2' }]
				});
				expect(client.getQueryData(otherWorkspace)).toEqual(snapshot);
			} finally {
				client.clear();
			}
		}
	);
});
