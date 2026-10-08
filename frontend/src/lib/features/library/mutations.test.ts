// @vitest-environment jsdom

import { QueryClient } from '@tanstack/svelte-query';
import { describe, expect, it, vi } from 'vitest';
import { defaultExportPreferences } from '#lib/export-preferences.js';
import { runLibraryBulkMutation, type LibraryBulkAction } from './mutations';

describe('Library bulk request contract', () => {
	it.each(['add_tag', 'delete', 'add_project'] as LibraryBulkAction[])(
		'serializes valid optional UUIDs for %s',
		async (action) => {
			const projectId = action === 'add_project' ? '01930abc-0000-7000-8000-000000000001' : '';
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
					exportFormat: 'bibtex',
					preferences: defaultExportPreferences
				},
				new QueryClient()
			);
			expect(body?.action).toBe(action);
			if (projectId) expect(body?.project_id).toBe(projectId);
			else expect(body).not.toHaveProperty('project_id');
		}
	);
});
