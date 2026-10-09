import { expect, test, type Page } from '@playwright/test';
import type { AnnotationPlugin, CommandsPlugin, PluginRegistry } from '@embedpdf/svelte-pdf-viewer';
import { minimalPdf, mockSession, annotationList, setAnnotationSource } from './helpers';

async function mockReplyReader(
	page: Page,
	options: { deferRootDelete?: boolean; withReply?: boolean } = {}
) {
	await mockSession(page);
	const reply = {
		id: 'reply-1',
		annotation_id: 'annotation-1',
		body: 'Owned reply',
		version: 1,
		author_display_name: 'reader',
		editable: true,
		created_at: '2026-09-16T00:00:00Z',
		updated_at: '2026-09-16T00:00:00Z'
	};
	const annotation = {
		id: 'annotation-1',
		revision_id: 'revision-1',
		page_index: 0,
		kind: 'note',
		scope: 'private',
		project_id: null,
		body: 'Owned annotation',
		selected_text: null,
		payload: {
			type: 'note',
			rect: { x: 20, y: 30, width: 24, height: 24 },
			style: {
				stroke_color: null,
				fill_color: null,
				text_color: null,
				opacity: 1,
				stroke_width: 1,
				dash_pattern: []
			}
		},
		version: 1,
		author_display_name: 'reader',
		editable: true,
		created_at: '2026-09-16T00:00:00Z',
		updated_at: '2026-09-16T00:00:00Z'
	};
	let releaseRootDelete!: () => void;
	const rootDeleteGate = new Promise<void>((resolve) => {
		releaseRootDelete = resolve;
	});
	const state = {
		deleted: options.withReply === false,
		rootDeleted: false,
		rootDeletePending: false,
		releaseRootDelete,
		replyRequests: [] as string[],
		annotationLoads: 0
	};
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/viewer',
		(route) =>
			route.fulfill({
				json: {
					item: { id: 'item-1', title_html: 'Reply history', version: 1 },
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
					projects: [{ id: 'project-1', name: 'Read-only Project', editable: false }]
				}
			})
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content',
		(route) => route.fulfill({ contentType: 'application/pdf', body: minimalPdf() })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/annotations**', async (route) => {
		const request = route.request();
		const url = new URL(request.url());
		if (request.method() === 'GET') {
			state.annotationLoads++;
			return route.fulfill({
				json: annotationList(
					url.searchParams.get('scope') === 'project' || state.rootDeleted
						? []
						: [{ ...annotation, replies: state.deleted ? [] : [reply] }]
				)
			});
		}
		state.replyRequests.push(`${request.method()} ${url.pathname}${url.search}`);
		const isReply = url.pathname.includes('/replies/');
		if (request.method() === 'DELETE') {
			if (!isReply) {
				state.rootDeletePending = true;
				if (options.deferRootDelete) await rootDeleteGate;
				state.rootDeleted = true;
				annotation.version++;
				return route.fulfill({ json: { ok: true } });
			}
			state.deleted = true;
			reply.version++;
			return route.fulfill({ json: { ok: true } });
		}
		if (request.method() === 'POST' && url.pathname.endsWith('/restore')) {
			if (!isReply) {
				if (Number(url.searchParams.get('version')) !== annotation.version) {
					return route.fulfill({ status: 409, json: { message: 'Annotation version conflict' } });
				}
				state.rootDeleted = false;
				annotation.version++;
				return route.fulfill({
					json: { ...annotation, replies: state.deleted ? [] : [reply] }
				});
			}
			if (Number(url.searchParams.get('version')) !== reply.version) {
				return route.fulfill({ status: 409, json: { message: 'Reply version conflict' } });
			}
			state.deleted = false;
			reply.version++;
			return route.fulfill({ json: reply });
		}
		return route.fulfill({
			status: 409,
			json: { message: 'annotation object ID already exists' }
		});
	});
	return state;
}

async function readerHistoryAction(page: Page, action: 'undo' | 'redo' = 'undo') {
	await page.locator('embedpdf-container').evaluate(async (element, action) => {
		const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
			.registry;
		registry
			.getPlugin<CommandsPlugin>('commands')!
			.provides()
			.execute(`history:${action}`, 'revision-1');
	}, action);
}

for (const sources of ['unchanged', 'add-project', 'hide-private']) {
	test(`PDF restores deleted replies through Undo after changing sources: ${sources}`, async ({
		page
	}) => {
		const state = await mockReplyReader(page);
		await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
		await expect(page.getByText('1 annotation loaded')).toBeAttached();
		await page.getByRole('button', { name: 'Comment', exact: true }).click();
		await expect(page.getByText('Owned reply', { exact: true })).toBeVisible();
		await page.locator('embedpdf-container').evaluate(async (element) => {
			const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
				.registry;
			registry
				.getPlugin<AnnotationPlugin>('annotation')!
				.provides()
				.forDocument('revision-1')
				.deleteAnnotation(0, 'reply-1');
		});
		await expect(page.getByText('Saved', { exact: true })).toBeAttached();
		await expect(page.getByText('Owned reply', { exact: true })).toHaveCount(0);
		if (sources === 'add-project') {
			const previousLoads = state.annotationLoads;
			await setAnnotationSource(page, 'Read-only Project');
			await expect.poll(() => state.annotationLoads).toBeGreaterThan(previousLoads);
			await expect(page.getByText('1 annotation loaded')).toBeAttached();
		}
		if (sources === 'hide-private') {
			await setAnnotationSource(page, 'Private annotations', false);
			await expect(page.getByText('0 annotations loaded')).toBeAttached();
		}
		await readerHistoryAction(page);
		await expect.poll(() => state.deleted).toBe(false);
		if (sources === 'hide-private') {
			await expect(page.getByText('Owned reply', { exact: true })).toHaveCount(0);
			await setAnnotationSource(page, 'Private annotations');
		}
		await expect(page.getByText('Owned reply', { exact: true })).toBeVisible();
		expect(state.replyRequests).toEqual([
			'DELETE /api/v1/workspaces/workspace-1/items/item-1/annotations/annotation-1/replies/reply-1?version=1',
			'POST /api/v1/workspaces/workspace-1/items/item-1/annotations/annotation-1/replies/reply-1/restore?version=2'
		]);
	});
}

for (const withReply of [false, true]) {
	test(`PDF preserves early Undo of a pending DELETE, with replies: ${withReply}`, async ({
		page
	}) => {
		const state = await mockReplyReader(page, { deferRootDelete: true, withReply });
		await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
		await expect(page.getByText('1 annotation loaded')).toBeAttached();
		await page.getByRole('button', { name: 'Comment', exact: true }).click();
		await page.locator('embedpdf-container').evaluate(async (element) => {
			const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
				.registry;
			registry
				.getPlugin<AnnotationPlugin>('annotation')!
				.provides()
				.forDocument('revision-1')
				.deleteAnnotation(0, 'annotation-1');
		});
		await expect.poll(() => state.rootDeletePending).toBe(true);
		await readerHistoryAction(page); // Undo while the DELETE response is still held.
		await expect(page.getByText('Owned annotation', { exact: true })).toBeVisible();
		state.releaseRootDelete();
		await expect.poll(() => state.replyRequests.some((url) => url.includes('/restore'))).toBe(true);
		await expect(page.getByText('Saved', { exact: true })).toBeAttached();
		await expect(page.getByText('Owned annotation', { exact: true })).toBeVisible();
		if (withReply) await expect(page.getByText('Owned reply', { exact: true })).toBeVisible();
		expect(state.rootDeleted).toBe(false);
		expect(state.annotationLoads).toBe(1);
		// Reconciliation imports must preserve the original Undo/Redo command.
		await readerHistoryAction(page, 'redo');
		await expect.poll(() => state.rootDeleted).toBe(true);
		await expect(page.getByText('Owned annotation', { exact: true })).toHaveCount(0);
		await readerHistoryAction(page);
		await expect(page.getByText('Saved', { exact: true })).toBeAttached();
		await expect(page.getByText('Owned annotation', { exact: true })).toBeVisible();
		if (withReply) await expect(page.getByText('Owned reply', { exact: true })).toBeVisible();
		expect(state.annotationLoads).toBe(1);
		const pageIds = await page.locator('embedpdf-container').evaluate(async (element) => {
			const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
				.registry;
			return registry
				.getPlugin<AnnotationPlugin>('annotation')!
				.provides()
				.forDocument('revision-1')
				.getState().pages[0];
		});
		expect(pageIds).toHaveLength(withReply ? 2 : 1);
		expect(new Set(pageIds).size).toBe(pageIds.length);
	});
}
