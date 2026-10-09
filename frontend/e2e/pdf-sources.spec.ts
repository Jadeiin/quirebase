import { expect, test, type Page } from '@playwright/test';
import type { AnnotationPlugin, CommandsPlugin, PluginRegistry } from '@embedpdf/svelte-pdf-viewer';
import { annotationList, minimalPdf, mockSession, setAnnotationSource } from './helpers';

async function sourceReader(page: Page, privateCount = 1) {
	await mockSession(page);
	const makeAnnotation = (id: string, projectId: string | null) => ({
		id,
		revision_id: 'revision-1',
		revision_name: 'paper.pdf',
		page_index: 0,
		kind: 'note',
		scope: projectId ? 'project' : 'private',
		project_id: projectId,
		project_name: projectId,
		body: id,
		selected_text: null,
		payload: { type: 'note', rect: { x: 20, y: 30, width: 24, height: 24 } },
		version: 1,
		author_display_name: 'reader',
		mine: true,
		editable: true,
		authorization: { allowed: [] },
		created_at: '2026-09-16T00:00:00Z',
		updated_at: '2026-09-16T00:00:00Z',
		replies: []
	});
	const rows = [
		...Array.from({ length: privateCount }, (_, i) => makeAnnotation(`private-${i}`, null)),
		makeAnnotation('shared-1', 'project-1'),
		makeAnnotation('shared-2', 'project-2')
	];
	const state = {
		writes: [] as Record<string, unknown>[],
		cursors: [] as (string | null)[],
		readQueries: [] as string[],
		deletedIds: [] as string[],
		contentLoads: 0,
		editBetweenPages: false,
		viewerReads: 0,
		projects: [
			{ id: 'project-1', name: 'First Project', editable: true },
			{ id: 'project-2', name: 'Second Project', editable: true }
		]
	};
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/viewer',
		(route) => {
			state.viewerReads++;
			return route.fulfill({
				json: {
					item: { id: 'item-1', title_html: 'Multiple sources', version: 1 },
					editable: true,
					annotation_author: 'reader',
					revision: {
						id: 'revision-1',
						original_name: 'paper.pdf',
						page_count: 1,
						processing_state: 'ready',
						page_geometry: [[0, 0, 300, 400]],
						content_url: '/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content'
					},
					projects: state.projects
				}
			});
		}
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content',
		(route) => {
			state.contentLoads++;
			return route.fulfill({ contentType: 'application/pdf', body: minimalPdf() });
		}
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/annotations**', (route) => {
		const request = route.request();
		const url = new URL(request.url());
		if (request.method() === 'GET') {
			const query = url.searchParams;
			const cursor = query.get('cursor');
			const perPage = Number(query.get('per_page') ?? 100);
			state.cursors.push(cursor);
			state.readQueries.push(url.search);
			if (
				query
					.getAll('project_id')
					.some((id) => !state.projects.some((project) => project.id === id))
			) {
				return route.fulfill({ status: 404, json: { message: 'Project no longer available' } });
			}
			if (state.editBetweenPages && (cursor || Number(query.get('page')) > 1)) {
				const last = [...rows]
					.filter((row) => row.scope === 'private')
					.sort((a, b) => (a.id < b.id ? -1 : 1))
					.at(-1)!;
				last.body = 'Updated between annotation pages';
				last.updated_at = '2026-10-01T00:00:00Z';
			}
			const visible = rows
				.filter((row) => !state.deletedIds.includes(row.id))
				.filter((row) =>
					row.scope === 'private'
						? query.get('scope') !== 'project'
						: query.get('scope') !== 'private' &&
							query.getAll('project_id').includes(row.project_id!)
				);
			if (query.get('pagination') === 'cursor') {
				const remaining = visible
					.filter((row) => !cursor || row.id > cursor)
					.sort((a, b) => (a.id < b.id ? -1 : 1));
				const pageRows = remaining.slice(0, perPage);
				return route.fulfill({
					json: annotationList(
						pageRows,
						1,
						perPage,
						visible.length,
						remaining.length > perPage ? pageRows.at(-1)!.id : null
					)
				});
			}
			const pageNumber = Number(query.get('page') ?? 1);
			visible.sort((a, b) =>
				a.updated_at > b.updated_at ? -1 : a.updated_at < b.updated_at ? 1 : a.id < b.id ? -1 : 1
			);
			return route.fulfill({
				json: annotationList(
					visible.slice((pageNumber - 1) * perPage, pageNumber * perPage),
					pageNumber,
					perPage,
					visible.length
				)
			});
		}
		if (request.method() === 'DELETE') {
			const id = url.pathname.split('/').at(-1)!;
			if (state.deletedIds.includes(id))
				return route.fulfill({ status: 404, json: { message: 'Annotation already deleted' } });
			state.deletedIds.push(id);
			return route.fulfill({ json: { ok: true } });
		}
		const body = request.postDataJSON();
		state.writes.push(body);
		if (request.method() === 'POST') {
			if (rows.some((row) => row.id === body.id))
				return route.fulfill({ status: 409, json: { message: 'Annotation UUID reserved' } });
			const row = { ...makeAnnotation(body.id, body.project_id), ...body };
			rows.push(row);
			return route.fulfill({ json: row });
		}
		const row = rows.find((row) => row.id === url.pathname.split('/').at(-1))!;
		Object.assign(row, body, { version: row.version + 1 });
		return route.fulfill({ json: row });
	});
	return state;
}

async function editOrCreate(page: Page, createId?: string) {
	await page.locator('embedpdf-container').evaluate(async (element, id) => {
		const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
			.registry;
		const scope = registry
			.getPlugin<AnnotationPlugin>('annotation')!
			.provides()
			.forDocument('revision-1');
		const original = scope.getAnnotations().find((entry) => entry.object.id === 'shared-2')!.object;
		if (id) scope.createAnnotation(0, { ...original, id, contents: 'New note' });
		else scope.updateAnnotation(0, original.id, { contents: 'Edited original source' });
	}, createId);
}

test('PDF overlays private and two Projects, while writes keep independent destinations', async ({
	page
}) => {
	const state = await sourceReader(page);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('1 annotation loaded')).toBeAttached();
	const contentLoads = state.contentLoads;
	await page
		.getByRole('combobox', { name: 'New annotation source', exact: true })
		.selectOption('project-1');
	await expect(page.getByText('2 annotations loaded')).toBeAttached();
	await setAnnotationSource(page, 'Second Project');
	await expect(page.getByText('3 annotations loaded')).toBeAttached();
	await page
		.getByRole('combobox', { name: 'New annotation source', exact: true })
		.selectOption('project-1');
	await editOrCreate(page);
	await expect.poll(() => state.writes.length).toBe(1);
	expect(state.writes[0]).toMatchObject({ scope: 'project', project_id: 'project-2' });
	await expect(page.getByText('Saved', { exact: true })).toBeAttached();
	await editOrCreate(page, 'new-project-1');
	await expect.poll(() => state.writes.length).toBe(2);
	expect(state.writes[1]).toMatchObject({ scope: 'project', project_id: 'project-1' });
	await expect(page.getByText('Saved', { exact: true })).toBeAttached();
	await page.getByRole('combobox', { name: 'New annotation source', exact: true }).selectOption('');
	await editOrCreate(page, 'new-private');
	await expect.poll(() => state.writes.length).toBe(3);
	expect(state.writes[2]).toMatchObject({ scope: 'private', project_id: null });
	expect(state.contentLoads).toBe(contentLoads);
});

test('PDF loads every annotation page and clears overlays when no sources are selected', async ({
	page
}) => {
	const state = await sourceReader(page, 101);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('101 annotations loaded')).toBeAttached();
	expect(state.cursors.some((cursor) => cursor !== null)).toBe(true);
	await setAnnotationSource(page, 'Private annotations', false);
	await expect(page.getByText('0 annotations loaded')).toBeAttached();
	await setAnnotationSource(page, 'Second Project');
	await expect(page.getByText('1 annotation loaded')).toBeAttached();
	await page.getByRole('button', { name: 'Comment', exact: true }).click();
	await expect(page.getByText('shared-2', { exact: true })).toBeVisible();
	await expect(page.getByText('private-0', { exact: true })).toHaveCount(0);
});

async function historyAction(page: Page, action: 'undo' | 'redo') {
	await page.locator('embedpdf-container').evaluate(async (element, operation) => {
		const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
			.registry;
		registry
			.getPlugin<CommandsPlugin>('commands')!
			.provides()
			.execute(`history:${operation}`, 'revision-1');
	}, action);
}

async function readerIds(page: Page) {
	return page.locator('embedpdf-container').evaluate(async (element) => {
		const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
			.registry;
		return registry
			.getPlugin<AnnotationPlugin>('annotation')!
			.provides()
			.forDocument('revision-1')
			.getAnnotations()
			.map((entry) => entry.object.id);
	});
}

test('PDF cursor loading includes a later-page annotation edited during traversal', async ({
	page
}) => {
	const state = await sourceReader(page, 101);
	state.editBetweenPages = true;
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('101 annotations loaded')).toBeAttached();
	const ids = await readerIds(page);
	expect(ids).toHaveLength(101);
	expect(new Set(ids).size).toBe(101);
	await page.getByRole('button', { name: 'Comment', exact: true }).click();
	await expect(page.getByText('Updated between annotation pages', { exact: true })).toBeVisible();
});

test('PDF Redo cannot resurrect a creation deleted by another session after a source refresh', async ({
	page
}) => {
	const state = await sourceReader(page);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1?project_id=project-2');
	await expect(page.getByText('2 annotations loaded')).toBeAttached();
	await editOrCreate(page, 'created-here');
	await expect(page.getByText('Saved', { exact: true })).toBeAttached();
	state.deletedIds.push('created-here');
	await setAnnotationSource(page, 'First Project');
	await expect(page.getByText('3 annotations loaded')).toBeAttached();
	await historyAction(page, 'undo');
	await historyAction(page, 'redo');
	await expect.poll(() => state.writes.filter((body) => body.id === 'created-here').length).toBe(2);
	await expect(page.getByText('3 annotations loaded')).toBeAttached();
	expect(await readerIds(page)).not.toContain('created-here');
});

test('PDF clears unavailable linked sources before its initial annotation request', async ({
	page
}) => {
	const state = await sourceReader(page);
	await page.goto(
		'/workspace/workspace-1/item/item-1/pdf/revision-1?project_id=gone&project_id=project-1'
	);
	await expect(page.getByText('2 annotations loaded')).toBeAttached();
	expect(
		state.readQueries.every(
			(query) => !new URLSearchParams(query).getAll('project_id').includes('gone')
		)
	).toBe(true);
	await setAnnotationSource(page, 'First Project', false);
	await expect(page.getByText('1 annotation loaded')).toBeAttached();
});

test('PDF clears display and write sources after their Project becomes unavailable on refresh', async ({
	page
}) => {
	const state = await sourceReader(page);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('1 annotation loaded')).toBeAttached();
	await page
		.getByRole('combobox', { name: 'New annotation source', exact: true })
		.selectOption('project-2');
	await expect(page.getByText('2 annotations loaded')).toBeAttached();
	const reads = state.viewerReads;
	await page.clock.install();
	state.projects = state.projects.filter((project) => project.id !== 'project-2');
	await page.clock.fastForward(31_000);
	await page.evaluate(() => {
		for (const visibilityState of ['hidden', 'visible']) {
			Object.defineProperty(document, 'visibilityState', {
				configurable: true,
				value: visibilityState
			});
			window.dispatchEvent(new Event('visibilitychange'));
		}
	});
	await expect.poll(() => state.viewerReads).toBeGreaterThan(reads);
	await expect(
		page.getByRole('combobox', { name: 'New annotation source', exact: true })
	).toHaveValue('');
	await expect(page.getByText('1 annotation loaded')).toBeAttached();
	expect(new URLSearchParams(state.readQueries.at(-1)).has('project_id')).toBe(false);
	await setAnnotationSource(page, 'First Project');
	await expect(page.getByText('2 annotations loaded')).toBeAttached();
});
