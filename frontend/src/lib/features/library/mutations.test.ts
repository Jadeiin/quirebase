// @vitest-environment jsdom

import { QueryClient } from '@tanstack/svelte-query';
import { describe, expect, it, vi } from 'vitest';
import { defaultExportPreferences } from '#lib/export-preferences.js';
import {
	libraryBulkMutationOptions,
	readLibraryBibliography,
	runLibraryBulkMutation,
	type LibraryMutationInput
} from './mutations';
import { itemKeys } from '#lib/features/item/queries.js';
import { projectKeys } from '#lib/features/projects/queries.js';
import { pdfReaderKeys } from '#lib/features/pdf-reader/queries.js';
import { tagKeys } from '#lib/features/tags/queries.js';
import { libraryKeys } from './queries.js';

describe('Library bulk request contract', () => {
	it.each([{ itemIds: ['item-3'] }, { itemIds: ['item-3', 'item-1', 'item-2'] }])(
		'reads one bibliography request for the ordered selection $itemIds',
		async ({ itemIds }) => {
			const content = '@article{Müller2026,\n  title = {Research}\n}\n';
			let received: Request | undefined;
			let body: Record<string, unknown> | undefined;
			const fetcher = vi.fn(async (request: RequestInfo | URL) => {
				received = request as Request;
				body = await received.json();
				return new Response(content, { headers: { 'Content-Type': 'application/x-bibtex' } });
			});
			vi.stubGlobal('fetch', fetcher);
			const preferences = structuredClone(defaultExportPreferences);
			preferences.citation = {
				format: 'bibtex',
				style: 'workspace-style',
				includeAbstract: false,
				preserveCase: true,
				encoding: 'latex',
				doiPolicy: 'omit',
				urlPolicy: 'omit_when_doi',
				excludedFields: 'note, keywords',
				sortBy: 'title',
				citationKeyFormula: 'auth + year',
				citationKeyForceAscii: false
			};

			await expect(
				readLibraryBibliography('workspace-1', {
					itemIds,
					preferences: preferences.citation,
					exportFormat: 'bibtex'
				})
			).resolves.toBe(content);

			expect(fetcher).toHaveBeenCalledOnce();
			expect(received?.method).toBe('POST');
			expect(new URL(received!.url).pathname).toBe(
				'/api/v1/workspaces/workspace-1/items/bibliography'
			);
			expect(body).toEqual({
				item_ids: itemIds,
				file_format: 'bibtex',
				style: 'workspace-style',
				include_abstract: false,
				preserve_case: true,
				encoding: 'latex',
				doi_policy: 'omit',
				url_policy: 'omit_when_doi',
				excluded_fields: ['note', 'keywords'],
				sort_by: 'title',
				citation_key_formula: 'auth + year',
				citation_key_force_ascii: false
			});
		}
	);

	it.each(['copy_bibliography', 'bibliography', 'documents'] as const)(
		'%s preserves cached read models and does not clear the selection',
		async (action) => {
			const content = 'A formatted citation\n';
			const fetcher = vi.fn(async () => new Response(content));
			vi.stubGlobal('fetch', fetcher);
			vi.stubGlobal('showSaveFilePicker', async () => ({
				createWritable: async () => ({
					write: async () => undefined,
					close: async () => undefined
				})
			}));
			const client = new QueryClient();
			const keys = [
				libraryKeys.list('workspace-1', {}, 1),
				itemKeys.overview('workspace-1', 'item-1'),
				projectKeys.detail('workspace-1', 'project-1'),
				tagKeys.all('workspace-1')
			];
			const selected = new Set(['item-2', 'item-1']);
			const afterMutation = vi.fn(() => selected.clear());
			try {
				for (const key of keys) client.setQueryData(key, { cached: true });
				const mutation = client
					.getMutationCache()
					.build(client, libraryBulkMutationOptions('workspace-1', client));
				const result = await mutation.execute({
					input:
						action === 'documents'
							? {
									action,
									itemIds: [...selected],
									preferences: defaultExportPreferences.document
								}
							: {
									action,
									itemIds: [...selected],
									exportFormat: 'csl',
									preferences: defaultExportPreferences.citation
								},
					afterMutation
				});
				expect(result).toBe(action === 'copy_bibliography' ? content : undefined);
				expect(fetcher).toHaveBeenCalledOnce();
				expect(afterMutation).not.toHaveBeenCalled();
				expect([...selected]).toEqual(['item-2', 'item-1']);
				for (const key of keys) {
					expect(client.getQueryState(key)?.isInvalidated).toBe(false);
					expect(client.getQueryData(key)).toEqual({ cached: true });
				}
			} finally {
				client.clear();
			}
		}
	);

	it('preserves structured bibliography text instead of parsing its JSON representation', async () => {
		const content = '[\n  { "id": "item-1", "title": "Research" }\n]\n';
		vi.stubGlobal(
			'fetch',
			async () =>
				new Response(content, {
					headers: { 'Content-Type': 'application/vnd.citationstyles.csl+json' }
				})
		);
		await expect(
			readLibraryBibliography('workspace-1', {
				itemIds: ['item-1'],
				exportFormat: 'csl-json',
				preferences: defaultExportPreferences.citation
			})
		).resolves.toBe(content);
	});

	it('keeps bibliography authorization failures recoverable through the normal API error contract', async () => {
		vi.stubGlobal(
			'fetch',
			async () =>
				new Response(JSON.stringify({ code: 'permission_denied', message: 'Export unavailable' }), {
					status: 403,
					headers: { 'Content-Type': 'application/json' }
				})
		);
		await expect(
			readLibraryBibliography('workspace-1', {
				itemIds: ['item-1'],
				exportFormat: 'csl',
				preferences: defaultExportPreferences.citation
			})
		).rejects.toMatchObject({ status: 403, code: 'permission_denied' });
	});

	it.each([
		{ action: 'add_tag', item_ids: ['item-1'], tag_name: 'Research' },
		{ action: 'remove_tag', item_ids: ['item-1'], tag_id: 'tag-1' },
		{ action: 'delete_items', item_ids: ['item-1'] },
		{ action: 'add_project', item_ids: ['item-1'], project_id: 'project-1' },
		{ action: 'remove_project', item_ids: ['item-1'], project_id: 'project-1' }
	] satisfies LibraryMutationInput[])(
		'serializes only the parameters for $action',
		async (input) => {
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
				input,
				new QueryClient()
			);
			expect(body?.action).toBe(input.action);
			if ('project_id' in input) expect(body?.project_id).toBe(input.project_id);
			else expect(body).not.toHaveProperty('project_id');
			if (input.action === 'remove_tag') expect(body?.tag_id).toBe(input.tag_id);
			else expect(body).not.toHaveProperty('tag_id');
			if (input.action === 'add_tag') expect(body?.tag_name).toBe('Research');
			else expect(body).not.toHaveProperty('tag_name');
			expect(body).not.toHaveProperty('confirmation');
		}
	);

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
				action === 'remove_project'
					? { action, item_ids: ['item-1'], project_id: 'project-1' }
					: { action, item_ids: ['item-1'], tag_id: 'tag-1' },
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
							item_ids: ['item-1'],
							project_id: 'project-1'
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
