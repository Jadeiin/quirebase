import { mockMetadataSources } from './helpers';
import { expect, test, type Page } from '@playwright/test';
import type { AnnotationPlugin, PluginRegistry, UIPlugin } from '@embedpdf/svelte-pdf-viewer';
import { minimalPdf, mockSession, annotationList, setAnnotationSource } from './helpers';

test('PDF reader uses the built-in EmbedPDF viewer with Quirebase annotations', async ({
	page
}) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await mockSession(page);
	const annotationRequests: string[] = [];
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/viewer',
		(route) =>
			route.fulfill({
				json: {
					item: { id: 'item-1', title_html: 'Reader item', version: 1 },
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
					projects: [{ id: 'project-1', name: 'Shared', editable: true }]
				}
			})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/annotations**', (route) => {
		annotationRequests.push(new URL(route.request().url()).search);
		if (route.request().method() === 'GET') {
			return route.fulfill({
				json: annotationList([
					{
						id: 'annotation-1',
						revision_id: 'revision-1',
						page_index: 0,
						kind: 'highlight',
						scope: 'private',
						project_id: null,
						body: 'Important',
						selected_text: 'evidence',
						payload: {
							type: 'highlight',
							rect: { x: 20, y: 30, width: 80, height: 12 },
							segment_rects: [{ x: 20, y: 30, width: 80, height: 12 }],
							style: {
								stroke_color: '#f59e0b',
								fill_color: '#fde68a',
								text_color: null,
								opacity: 0.7,
								stroke_width: 1,
								dash_pattern: []
							}
						},
						version: 1,
						author_display_name: 'reader',
						editable: true,
						created_at: '2026-09-16T00:00:00Z',
						updated_at: '2026-09-16T00:00:00Z',
						replies: []
					}
				])
			});
		}
		return route.fulfill({ json: { ok: true } });
	});
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content',
		(route) => route.fulfill({ contentType: 'application/pdf', body: minimalPdf() })
	);

	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByRole('button', { name: 'Document Menu' })).toBeVisible();
	await expect(page.locator('[data-epdf-i="comment-button"]')).toBeAttached();
	await expect(page.getByText('1 annotation loaded')).toBeVisible();
	expect(annotationRequests.at(-1)).toContain('revision_id=revision-1');

	await setAnnotationSource(page, 'Shared');
	await expect.poll(() => annotationRequests.at(-1)).toContain('project_id=project-1');
});

async function expectAnnotationMode(page: Page, editable: boolean) {
	// Annotation data can settle before EmbedPDF mounts its responsive toolbar.
	await expect(page.getByRole('button', { name: 'Document Menu' })).toBeVisible();
	const modeSelector = page.locator('[data-epdf-i="mode-select-button"] button');
	if (!(await modeSelector.isVisible())) {
		const annotate = page.getByRole('button', { name: 'Annotate', exact: true });
		if (editable) {
			await expect(annotate).toBeVisible();
			await expect(annotate).toBeEnabled();
			await annotate.click();
		} else await expect(annotate).toBeHidden();
		return;
	}
	await modeSelector.click();
	const annotate = page.getByRole('menuitem', { name: 'Annotate', exact: true });
	if (editable) {
		await expect(annotate).toBeVisible();
		await expect(annotate).toBeEnabled();
		await annotate.click();
	} else {
		await expect(annotate).toBeDisabled();
		await page.getByRole('menuitem', { name: 'View', exact: true }).click();
	}
}

for (const projectEditable of [false, true]) {
	test(`PDF annotation tools follow scope permissions with Project editable=${projectEditable}`, async ({
		page
	}) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await mockSession(page);
		let writable = true;
		await page.route(
			'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/viewer',
			(route) =>
				route.fulfill({
					json: {
						item: { id: 'item-1', title_html: 'Reader item', version: 1 },
						editable: writable,
						annotation_author: 'reader',
						revision: {
							id: 'revision-1',
							original_name: 'paper.pdf',
							page_count: 1,
							processing_state: 'ready',
							page_geometry: [[0, 0, 300, 400]],
							content_url:
								'/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content'
						},
						projects: [
							{ id: 'project-1', name: 'Shared', editable: writable && projectEditable },
							{ id: 'project-archived', name: 'Archived', editable: false }
						]
					}
				})
		);
		const annotationRequests: string[] = [];
		await page.route('**/api/v1/workspaces/workspace-1/items/item-1/annotations**', (route) => {
			annotationRequests.push(route.request().url());
			return route.fulfill({ json: annotationList([]) });
		});
		let contentRequests = 0;
		await page.route(
			'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content',
			(route) => {
				contentRequests++;
				return route.fulfill({ contentType: 'application/pdf', body: minimalPdf() });
			}
		);
		await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
		await expect(page.getByText('0 annotations loaded')).toBeAttached();
		await expectAnnotationMode(page, true);
		const loadedContentRequests = contentRequests;
		await setAnnotationSource(page, 'Shared');
		await expect.poll(() => annotationRequests.at(-1)).toContain('project_id=project-1');
		await expectAnnotationMode(page, true);
		const sources = page.getByRole('button', { name: 'Displayed annotation sources', exact: true });
		await sources.click();
		const destination = page.getByRole('radio', { name: 'Shared', exact: true });
		if (projectEditable) await expect(destination).toBeEnabled();
		else await expect(destination).toBeDisabled();
		await expect(page.getByRole('radio', { name: 'Archived', exact: true })).toBeDisabled();
		if (projectEditable) {
			await destination.check();
			await page.getByRole('radio', { name: 'Private annotations', exact: true }).check();
		}
		await sources.click();
		await expectAnnotationMode(page, true);
		await setAnnotationSource(page, 'Archived');
		await expect.poll(() => annotationRequests.at(-1)).toContain('project_id=project-archived');
		await expectAnnotationMode(page, true);
		expect(contentRequests).toBe(loadedContentRequests);

		// Read-only Workspace projections also disable the annotation mode.
		writable = false;
		await page.reload();
		await expect(page.getByText('0 annotations loaded')).toBeAttached();
		await expectAnnotationMode(page, false);
		writable = true;
		await page.reload();
		await expect(page.getByText('0 annotations loaded')).toBeAttached();
		await expectAnnotationMode(page, true);
	});
}

async function mockScopeReader(page: Page, withAnnotations = false) {
	await mockSession(page);
	const state = {
		viewerFailed: false,
		writable: true,
		nativeComments: false,
		contentRequests: 0,
		annotationReadGate: null as Promise<void> | null,
		deletedIds: [] as string[],
		mutationRequests: [] as string[],
		mutationBodies: [] as Record<string, unknown>[]
	};
	const annotations = ['private', 'project'].map((scope) => ({
		id: `annotation-${scope}`,
		revision_id: 'revision-1',
		page_index: 0,
		kind: 'rectangle',
		scope,
		project_id: scope === 'project' ? 'project-1' : null,
		body: `${scope} annotation`,
		selected_text: null,
		payload: {
			type: 'rectangle',
			rect: { x: scope === 'private' ? 20 : 150, y: 100, width: 80, height: 50 },
			style: { stroke_color: '#ef4444', fill_color: '#fee2e2', opacity: 1, stroke_width: 1 }
		},
		version: 1,
		author_display_name: 'reader',
		editable: scope === 'private',
		created_at: '2026-09-16T00:00:00Z',
		updated_at: '2026-09-16T00:00:00Z',
		replies: []
	}));
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/viewer',
		(route) =>
			state.viewerFailed
				? route.fulfill({ status: 500, json: { message: 'Reader unavailable' } })
				: route.fulfill({
						json: {
							item: { id: 'item-1', title_html: 'Reader item', version: 1 },
							editable: state.writable,
							annotation_author: 'reader',
							revision: {
								id: 'revision-1',
								original_name: 'paper.pdf',
								page_count: 1,
								processing_state: 'ready',
								page_geometry: [[0, 0, 300, 400]],
								content_url:
									'/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content'
							},
							projects: [
								{ id: 'project-1', name: 'Shared', editable: false },
								{ id: 'project-archived', name: 'Archived', editable: false }
							]
						}
					})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/annotations**', async (route) => {
		if (route.request().method() !== 'GET') state.mutationRequests.push(route.request().method());
		if (route.request().method() === 'DELETE') {
			state.deletedIds.push(new URL(route.request().url()).pathname.split('/').at(-1)!);
			return route.fulfill({ json: { ok: true } });
		}
		if (route.request().method() === 'PATCH') {
			const id = new URL(route.request().url()).pathname.split('/').at(-1);
			const annotation = annotations.find((annotation) => annotation.id === id)!;
			const patch = route.request().postDataJSON();
			state.mutationBodies.push(patch);
			Object.assign(annotation, patch, {
				version: annotation.version + 1
			});
			return route.fulfill({ json: annotation });
		}
		const query = new URL(route.request().url()).searchParams;
		const rows = withAnnotations
			? annotations
					.filter((annotation) => !state.deletedIds.includes(annotation.id))
					.filter((annotation) =>
						annotation.scope === 'private'
							? query.get('scope') !== 'project'
							: query.get('scope') !== 'private' &&
								query.getAll('project_id').includes(annotation.project_id!)
					)
					.map((annotation) => ({ ...annotation, editable: state.writable && annotation.editable }))
			: [];
		await state.annotationReadGate;
		return route.fulfill({ json: annotationList(rows) });
	});
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content',
		(route) => {
			state.contentRequests++;
			return route.fulfill({
				contentType: 'application/pdf',
				body: minimalPdf(state.nativeComments)
			});
		}
	);
	return state;
}

async function refocusReader(page: Page) {
	await page.evaluate(() => {
		for (const visibilityState of ['hidden', 'visible']) {
			Object.defineProperty(document, 'visibilityState', {
				configurable: true,
				value: visibilityState
			});
			window.dispatchEvent(new Event('visibilitychange'));
		}
	});
}

function commentCard(page: Page, body: string) {
	return page
		.getByText(body, { exact: true })
		.locator('xpath=ancestor::div[contains(@class, "rounded-lg")][1]');
}

async function openPdfSidebar(page: Page, id: string, side: 'left' | 'right', tab?: string) {
	await page.locator('embedpdf-container').evaluate(
		async (element, { id, side, tab }) => {
			const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
				.registry;
			registry
				.getPlugin<UIPlugin>('ui')!
				.provides()
				.forDocument('revision-1')
				.setActiveSidebar(side, 'main', id, tab);
		},
		{ id, side, tab }
	);
	return page.locator(`[data-sidebar-id="${id}"]`);
}

async function dragPdfSidebar(page: Page, id: string, distance: number) {
	const handle = page
		.locator(`[data-sidebar-id="${id}"]`)
		.getByRole('separator', { name: 'Resize PDF sidebar' });
	await expect(handle).toBeVisible();
	const box = (await handle.boundingBox())!;
	const x = box.x + box.width / 2;
	const y = box.y + box.height / 2;
	await page.mouse.move(x, y);
	await page.mouse.down();
	await page.mouse.move(x + distance, y, { steps: 10 });
	await page.mouse.up();
}

test('PDF comment sidebar resizes, remembers its width and supports keyboard controls', async ({
	page
}) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	const state = await mockScopeReader(page, true);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('1 annotation loaded')).toBeVisible();
	await page.getByRole('button', { name: 'Comment', exact: true }).click();
	const sidebar = page.locator('[data-sidebar-id="comment-panel"]');
	const handle = sidebar.getByRole('separator', { name: 'Resize PDF sidebar' });
	await expect(handle).toHaveAttribute('aria-valuenow', '250');
	await dragPdfSidebar(page, 'comment-panel', -150);
	await expect.poll(async () => (await sidebar.boundingBox())?.width).toBe(400);
	await expect(sidebar.getByText('private annotation', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Comment', exact: true }).click();
	await expect(sidebar).toBeHidden();
	await page.getByRole('button', { name: 'Comment', exact: true }).click();
	await expect(handle).toHaveAttribute('aria-valuenow', '400');
	await page.reload();
	await expect(page.getByText('1 annotation loaded')).toBeVisible();
	await page.getByRole('button', { name: 'Comment', exact: true }).click();
	await expect(handle).toHaveAttribute('aria-valuenow', '400');
	await handle.focus();
	await page.keyboard.press('ArrowLeft');
	await expect(handle).toHaveAttribute('aria-valuenow', '410');
	await page.keyboard.press('Shift+ArrowRight');
	await expect(handle).toHaveAttribute('aria-valuenow', '360');
	await page.keyboard.press('Home');
	await expect(handle).toHaveAttribute('aria-valuenow', '250');
	await dragPdfSidebar(page, 'comment-panel', 500);
	await expect(handle).toHaveAttribute('aria-valuenow', '200');
	await handle.dblclick();
	await expect(handle).toHaveAttribute('aria-valuenow', '250');
	expect(state.mutationRequests).toEqual([]);
});

test('PDF navigation, annotation style and search sidebars resize independently', async ({
	page
}) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	await mockScopeReader(page);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('0 annotations loaded')).toBeVisible();
	for (const { id, side } of [
		{ id: 'sidebar-panel', side: 'left' },
		{ id: 'annotation-panel', side: 'left' },
		{ id: 'search-panel', side: 'right' }
	] as const) {
		const sidebar = await openPdfSidebar(page, id, side);
		const handle = sidebar.getByRole('separator', { name: 'Resize PDF sidebar' });
		await expect(handle).toHaveAttribute('aria-valuenow', '250');
		await dragPdfSidebar(page, id, side === 'left' ? 80 : -80);
		await expect.poll(async () => (await sidebar.boundingBox())?.width).toBe(330);
		await handle.focus();
		await page.keyboard.press(side === 'left' ? 'ArrowRight' : 'ArrowLeft');
		await expect(handle).toHaveAttribute('aria-valuenow', '340');
	}
	const navigation = await openPdfSidebar(page, 'sidebar-panel', 'left', 'outline');
	await expect(navigation.getByRole('separator', { name: 'Resize PDF sidebar' })).toHaveAttribute(
		'aria-valuenow',
		'340'
	);
	await expect(navigation.getByRole('separator', { name: 'Resize PDF sidebar' })).toHaveCount(1);
});

test('PDF sidebars preserve document space and retain mobile bottom drawers', async ({ page }) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	await mockScopeReader(page);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('0 annotations loaded')).toBeVisible();
	const comment = await openPdfSidebar(page, 'comment-panel', 'right');
	await dragPdfSidebar(page, 'comment-panel', -1000);
	await expect(comment.getByRole('separator', { name: 'Resize PDF sidebar' })).toHaveAttribute(
		'aria-valuenow',
		'600'
	);
	const navigation = await openPdfSidebar(page, 'sidebar-panel', 'left');
	await expect(navigation.getByRole('separator', { name: 'Resize PDF sidebar' })).toBeVisible();
	await dragPdfSidebar(page, 'sidebar-panel', 1000);
	const documentWidth = () =>
		page.locator('#document-content').evaluate((element) => {
			const panels = [...element.querySelectorAll(':scope > [data-sidebar-id]')];
			return (
				element.clientWidth -
				panels.reduce((sum, panel) => sum + panel.getBoundingClientRect().width, 0)
			);
		});
	await expect.poll(documentWidth).toBeGreaterThanOrEqual(320);
	await page.setViewportSize({ width: 1024, height: 800 });
	await expect.poll(documentWidth).toBeGreaterThanOrEqual(320);
	for (const sidebar of [comment, navigation]) {
		await expect
			.poll(async () => (await sidebar.boundingBox())?.width ?? 0)
			.toBeGreaterThanOrEqual(200);
	}
	await page.setViewportSize({ width: 390, height: 844 });
	await expect(page.getByRole('separator', { name: 'Resize PDF sidebar' })).toHaveCount(0);
	await expect(comment.locator('.cursor-grab')).toBeVisible();
	await expect.poll(async () => (await comment.boundingBox())?.height ?? 0).toBeGreaterThan(100);
	await expect.poll(async () => (await comment.boundingBox())?.width).toBe(390);
	// Drag the existing mobile grip upwards; its full-height drawer remains functional.
	const grip = (await comment.locator('.cursor-grab').boundingBox())!;
	const before = (await comment.boundingBox())!.height;
	await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
	await page.mouse.down();
	await page.mouse.move(grip.x + grip.width / 2, grip.y - 300, { steps: 10 });
	await page.mouse.up();
	await expect
		.poll(async () => (await comment.boundingBox())?.height ?? 0)
		.toBeGreaterThan(before + 100);
	await page.setViewportSize({ width: 1440, height: 900 });
	await expect(comment.getByRole('separator', { name: 'Resize PDF sidebar' })).toHaveCount(1);
	await expect(navigation.getByRole('separator', { name: 'Resize PDF sidebar' })).toHaveCount(1);
	await expect.poll(documentWidth).toBeGreaterThanOrEqual(320);
});

test('PDF comment sidebar is read-only for canonical and native comments in a read-only Workspace', async ({
	page
}) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	const state = await mockScopeReader(page, true);
	state.writable = false;
	state.nativeComments = true;
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1?project_id=project-1');
	await expect(page.getByText('2 annotations loaded')).toBeVisible();
	await page.getByRole('button', { name: 'Comment', exact: true }).click();
	for (const body of ['private annotation', 'project annotation', 'Native PDF comment']) {
		const card = commentCard(page, body);
		await expect(card).toBeVisible();
		await expect(card.getByRole('button')).toHaveCount(0);
		await expect(card.getByRole('textbox')).toHaveCount(0);
	}
	await expect(page.getByText('Native PDF reply', { exact: true })).toBeVisible();
	expect(state.mutationRequests).toEqual([]);
});

test('PDF comment sidebar preserves private edits in a read-only Project', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	const state = await mockScopeReader(page, true);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('1 annotation loaded')).toBeVisible();
	const sourceRead = page.waitForResponse((response) => {
		const url = new URL(response.url());
		return (
			response.request().method() === 'GET' &&
			url.pathname.endsWith('/annotations') &&
			url.searchParams.getAll('project_id').includes('project-archived')
		);
	});
	await setAnnotationSource(page, 'Archived');
	await (await sourceRead).finished();
	await expect(page.getByText('1 annotation loaded')).toBeVisible();
	await page.getByRole('button', { name: 'Comment', exact: true }).click();
	const card = commentCard(page, 'private annotation');
	await card.getByRole('button').first().click();
	await page.getByRole('button', { name: 'Edit', exact: true }).click();
	await expect(page.locator('textarea')).toHaveValue('private annotation');
	await page.locator('textarea').fill('Edited private annotation');
	await page.getByRole('button', { name: 'Save', exact: true }).click();
	await expect
		.poll(() => state.mutationBodies.map((patch) => patch.body))
		.toEqual(['Edited private annotation']);
	await expect(page.getByText('Edited private annotation', { exact: true })).toBeVisible();
	await expect.poll(() => state.mutationRequests).toEqual(['PATCH']);
	await expect(page.getByText('Saved', { exact: true })).toBeVisible();
});

test('PDF source refresh preserves a private draft and its Save click', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	const state = await mockScopeReader(page, true);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('1 annotation loaded')).toBeVisible();
	let releaseRead!: () => void;
	state.annotationReadGate = new Promise<void>((resolve) => {
		releaseRead = resolve;
	});
	try {
		await setAnnotationSource(page, 'Archived');
		await expect(page.getByText('Loading annotations…', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Comment', exact: true }).click();
		await commentCard(page, 'private annotation').getByRole('button').first().click();
		await page.getByRole('button', { name: 'Edit', exact: true }).click();
		await expect(page.locator('textarea')).toHaveValue('private annotation');
		await page.locator('textarea').fill('Draft survives source refresh');
		const save = page.getByRole('button', { name: 'Save', exact: true });
		const box = (await save.boundingBox())!;
		await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
		await page.mouse.down();
		releaseRead();
		await expect(page.getByText('1 annotation loaded')).toBeVisible();
		await expect(page.locator('textarea')).toHaveValue('Draft survives source refresh');
		await page.mouse.up();
		await expect(page.getByText('Draft survives source refresh', { exact: true })).toBeVisible();
		await expect
			.poll(() => state.mutationBodies.map((patch) => patch.body))
			.toEqual(['Draft survives source refresh']);
		await expect.poll(() => state.mutationRequests).toEqual(['PATCH']);
		await expect(page.getByText('Saved', { exact: true })).toBeVisible();
	} finally {
		releaseRead();
	}
});

test('PDF comment sidebar refreshes the Workspace write gate after permissions change', async ({
	page
}) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	const state = await mockScopeReader(page, true);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('1 annotation loaded')).toBeVisible();
	await page.clock.install();
	for (const writable of [false, true]) {
		state.writable = writable;
		const loadedContentRequests = state.contentRequests;
		await page.clock.fastForward(31_000);
		await refocusReader(page);
		await expect.poll(() => state.contentRequests).toBeGreaterThan(loadedContentRequests);
		await expect(page.getByRole('button', { name: 'Comment', exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Comment', exact: true }).click();
		const card = commentCard(page, 'private annotation');
		await expect(card).toBeVisible();
		await expect(card.getByRole('button')).toHaveCount(writable ? 2 : 0);
		await expect(card.getByRole('textbox')).toHaveCount(writable ? 1 : 0);
	}
	expect(state.mutationRequests).toEqual([]);
});

async function selectReaderAnnotation(page: Page, id: string) {
	return page.locator('embedpdf-container').evaluate(async (element, annotationId) => {
		const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
			.registry;
		const annotations = registry
			.getPlugin<AnnotationPlugin>('annotation')!
			.provides()
			.forDocument('revision-1');
		annotations.deselectAnnotation();
		annotations.selectAnnotation(0, `annotation:${annotationId}`);
		return annotations.getSelectedAnnotation()?.object.id ?? null;
	}, id);
}

for (const projectId of ['project-1', 'project-archived']) {
	test(`PDF preserves individual annotation permissions in read-only scope ${projectId}`, async ({
		page
	}) => {
		await page.setViewportSize({ width: 1280, height: 800 });
		const state = await mockScopeReader(page, true);
		await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
		await expect(page.getByText('1 annotation loaded')).toBeVisible();
		await setAnnotationSource(page, projectId === 'project-1' ? 'Shared' : 'Archived');
		await expect
			.poll(() => selectReaderAnnotation(page, 'annotation-private'))
			.toBe('annotation:annotation-private');
		const deleteButton = page.locator('[data-epdf-i="delete-annotation"] button');
		await expect(deleteButton).toBeVisible();
		await expect(deleteButton).toBeEnabled();
		await deleteButton.click();
		await expect.poll(() => state.deletedIds).toEqual(['annotation-private']);
		await expect.poll(() => selectReaderAnnotation(page, 'annotation-project')).toBeNull();
		await expectAnnotationMode(page, true);
	});
}

test('PDF restores creation tools after remounting in a read-only Project', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	const state = await mockScopeReader(page);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('0 annotations loaded')).toBeAttached();
	await setAnnotationSource(page, 'Archived');
	const loadedContentRequests = state.contentRequests;
	await page.clock.install();
	await page.clock.fastForward(31_000);
	state.viewerFailed = true;
	await refocusReader(page);
	await expect
		.poll(async () => {
			await page.clock.runFor(1000);
			return page.getByText('Unable to open this PDF.').isVisible();
		})
		.toBe(true);
	state.viewerFailed = false;
	await refocusReader(page);
	await expect.poll(() => state.contentRequests).toBeGreaterThan(loadedContentRequests);
	await expect(page.getByRole('button', { name: 'Document Menu' })).toBeVisible();
	const sources = page.getByRole('button', { name: 'Displayed annotation sources', exact: true });
	await sources.click();
	await expect(page.getByRole('checkbox', { name: 'Archived', exact: true })).toBeChecked();
	await expect(page.getByRole('radio', { name: 'Private annotations', exact: true })).toBeChecked();
	await sources.click();
	await expectAnnotationMode(page, true);
});

test.describe('touch-first PDF reader', () => {
	test.use({
		viewport: { width: 390, height: 844 },
		hasTouch: true,
		isMobile: true,
		deviceScaleFactor: 3
	});

	test('matches the built-in viewer annotation modes', async ({ page }) => {
		await mockSession(page);
		await page.route(
			'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/viewer',
			(route) =>
				route.fulfill({
					json: {
						item: { id: 'item-1', title_html: 'Reader item', version: 1 },
						editable: true,
						annotation_author: 'reader',
						revision: {
							id: 'revision-1',
							original_name: 'paper.pdf',
							page_count: 1,
							processing_state: 'ready',
							page_geometry: [[0, 0, 300, 400]],
							content_url:
								'/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content'
						},
						projects: []
					}
				})
		);
		await page.route('**/api/v1/workspaces/workspace-1/items/item-1/annotations**', (route) =>
			route.request().method() === 'GET'
				? route.fulfill({ json: annotationList([]) })
				: route.fulfill({ json: { ok: true } })
		);
		await page.route(
			'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content',
			(route) => route.fulfill({ contentType: 'application/pdf', body: minimalPdf() })
		);

		await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
		await expect(page.getByRole('button', { name: 'Document Menu' })).toBeVisible();
		await page.locator('[data-epdf-i="mode-select-button"] button').click();
		await expect(page.locator('[data-epdf-i="mode:annotate"]')).toBeVisible();
	});
});

test('deleting a reader annotation refreshes the Item overview count', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	const state = await mockScopeReader(page, true);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Reader item'
				},
				citation_key: null,
				id: 'item-1',
				version: 1,
				latest_revision_id: 'revision-1',
				authorization: { allowed: ['workspace.export'] },
				copy_targets: [],
				counts: {
					revisions: 1,
					attachments: 0,
					annotations: state.deletedIds.length ? 0 : 1,
					discussion: 0
				},
				tags: []
			}
		})
	);

	await page.goto('/workspace/workspace-1/item/item-1');
	const annotationsCount = page
		.locator('span:text-is("Annotations")')
		.locator('xpath=preceding-sibling::strong');
	await expect(annotationsCount).toHaveText('1');
	await page.getByRole('link', { name: 'Read PDF' }).click();
	await expect(page).toHaveURL(/\/item\/item-1\/pdf\/revision-1$/);
	await expect(page.getByText('1 annotation loaded')).toBeVisible();
	await expect
		.poll(() => selectReaderAnnotation(page, 'annotation-private'))
		.toBe('annotation:annotation-private');
	await page.locator('[data-epdf-i="delete-annotation"] button').click();
	await expect.poll(() => state.deletedIds).toEqual(['annotation-private']);
	await page.goBack();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/item\/item-1$/);
	await expect(annotationsCount).toHaveText('0');
});

test('annotated download follows the displayed annotation sources', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await mockScopeReader(page, true);
	const exports: string[] = [];
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/export**',
		(route) => {
			exports.push(new URL(route.request().url()).search);
			return route.fulfill({ contentType: 'application/pdf', body: minimalPdf() });
		}
	);

	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('1 annotation loaded')).toBeVisible();

	// The download menu has no annotation-scope selector; it follows the displayed sources.
	const downloadTrigger = page.getByRole('button', { name: 'Download', exact: true });
	await downloadTrigger.click();
	await expect(page.getByText('Annotations to include')).toHaveCount(0);
	await expect(page.getByText('Current PDF')).toHaveCount(0);

	// Both reader panels share one frame design, and the two-item menu stays compact.
	const menuContent = page.locator(`[id="${await downloadTrigger.getAttribute('aria-controls')}"]`);
	const menuBox = (await menuContent.boundingBox())!;
	const annotationsTrigger = page.getByRole('button', {
		name: 'Displayed annotation sources',
		exact: true
	});
	await annotationsTrigger.click();
	const annotationsContent = page.locator(
		`[id="${await annotationsTrigger.getAttribute('aria-controls')}"]`
	);
	expect(await menuContent.evaluate((element) => getComputedStyle(element).borderRadius)).toBe(
		await annotationsContent.evaluate((element) => getComputedStyle(element).borderRadius)
	);
	expect(menuBox.width).toBeLessThanOrEqual((await annotationsContent.boundingBox())!.width);
	await annotationsTrigger.click();

	await downloadTrigger.click();
	await page.getByRole('button', { name: 'Download with annotations' }).click();
	await expect.poll(() => exports.at(-1)).toContain('scope=private');
	await page.keyboard.press('Escape');

	// Displaying a Project adds it to the export alongside private annotations.
	await setAnnotationSource(page, 'Shared');
	await page.getByRole('button', { name: 'Download', exact: true }).click();
	await page.getByRole('button', { name: 'Download with annotations' }).click();
	await expect.poll(() => exports.at(-1)).toContain('project_id=project-1');
	expect(exports.at(-1)).not.toContain('scope=');
	await page.keyboard.press('Escape');

	// Hiding private annotations exports only the displayed Projects.
	await setAnnotationSource(page, 'Private annotations', false);
	await page.getByRole('button', { name: 'Download', exact: true }).click();
	await page.getByRole('button', { name: 'Download with annotations' }).click();
	await expect.poll(() => exports.at(-1)).toContain('scope=project');
	expect(exports.at(-1)).toContain('project_id=project-1');
	await page.keyboard.press('Escape');

	// With nothing displayed there is nothing to export.
	await setAnnotationSource(page, 'Shared', false);
	await page.getByRole('button', { name: 'Download', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Download with annotations' })).toBeDisabled();
});

test('the annotation source panel stays above the comment sidebar', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await mockScopeReader(page, true);
	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('1 annotation loaded')).toBeVisible();
	await page.getByRole('button', { name: 'Comment', exact: true }).click();
	const pageHeading = page.getByText('Page 1', { exact: true });
	await expect(pageHeading).toBeVisible();

	const trigger = page.getByRole('button', { name: 'Displayed annotation sources', exact: true });
	await trigger.click();
	const panel = page.locator(`[id="${await trigger.getAttribute('aria-controls')}"]`);
	await expect(panel).toBeVisible();
	// Floating UI positions the panel after it opens. Wait for both the overlap and hit test.
	await expect
		.poll(async () => {
			const panelBox = await panel.boundingBox();
			const headingBox = await pageHeading.boundingBox();
			if (!panelBox || !headingBox || headingBox.x >= panelBox.x + panelBox.width) return false;
			const point = {
				x: Math.max(panelBox.x, headingBox.x) + 8,
				y: Math.max(panelBox.y, headingBox.y) + 4
			};
			return page.evaluate(
				({ x, y }) =>
					Boolean(
						document.elementFromPoint(x, y)?.closest('[data-scope="popover"][data-part="content"]')
					),
				point
			);
		})
		.toBe(true);
});

test('PDF reader header follows Item metadata changes', async ({ page }) => {
	await mockSession(page);
	await mockMetadataSources(page, 'item-1', {
		version: 1,
		sources: [
			{
				namespace: 'doi',
				value: '10.1000/reader',
				providers: [{ id: 'datacite', name: 'DataCite' }]
			}
		]
	});
	let synchronized = false;
	const title = () => (synchronized ? 'Synchronized title' : 'Old title');
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'https://doi.org/10.1000/reader',
					type: 'Other',
					title: title(),
					identifiers: [{ identifier_type: 'DOI', identifier: '10.1000/reader' }]
				},
				citation_key: null,
				id: 'item-1',
				version: 1,
				latest_revision_id: null,
				authorization: { allowed: ['item.update', 'workspace.export', 'item.delete'] },
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/metadata/sync', (route) => {
		synchronized = true;
		return route.fulfill({ json: { ok: true } });
	});
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/viewer',
		(route) =>
			route.fulfill({
				json: {
					item: { id: 'item-1', title_html: title(), version: 1 },
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
					projects: []
				}
			})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/annotations**', (route) =>
		route.fulfill({ json: annotationList([]) })
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content',
		(route) => route.fulfill({ contentType: 'application/pdf', body: minimalPdf() })
	);

	await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1');
	await expect(page.getByText('0 annotations loaded')).toBeAttached();
	await expect(page.getByText('Old title')).toBeVisible();

	await page.getByRole('link', { name: 'Item', exact: true }).click();
	await expect(page).toHaveURL(/\/item\/item-1$/);
	await page.getByRole('button', { name: 'Record tools', exact: true }).click();
	await page
		.getByRole('dialog', { name: 'Item actions' })
		.getByLabel('Provider', { exact: true })
		.selectOption('datacite');
	await page.getByRole('button', { name: 'Autoupdate' }).click();
	await expect.poll(() => synchronized).toBe(true);
	await page
		.getByRole('dialog', { name: 'Item actions' })
		.getByRole('button', { name: 'Close' })
		.click();

	await page.goBack();
	await expect(page).toHaveURL(/\/item\/item-1\/pdf\/revision-1$/);
	await expect(page.getByText('Synchronized title')).toBeVisible();
});
