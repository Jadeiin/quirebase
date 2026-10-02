import { expect, test, type Page } from '@playwright/test';
import type { AnnotationPlugin, PluginRegistry } from '@embedpdf/svelte-pdf-viewer';
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
		const destination = page.getByLabel('New annotation source');
		await expectAnnotationMode(page, true);
		const loadedContentRequests = contentRequests;
		await setAnnotationSource(page, 'Shared');
		await expect.poll(() => annotationRequests.at(-1)).toContain('project_id=project-1');
		await expectAnnotationMode(page, true);
		if (projectEditable)
			await expect(destination.locator('option[value="project-1"]')).toHaveJSProperty(
				'disabled',
				false
			);
		else
			await expect(destination.locator('option[value="project-1"]')).toHaveJSProperty(
				'disabled',
				true
			);
		await expect(destination.locator('option[value="project-archived"]')).toHaveJSProperty(
			'disabled',
			true
		);
		if (projectEditable) {
			await destination.selectOption('project-1');
			await expectAnnotationMode(page, true);
			await destination.selectOption('');
		}
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
		deletedIds: [] as string[],
		mutationRequests: [] as string[]
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
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/annotations**', (route) => {
		if (route.request().method() !== 'GET') state.mutationRequests.push(route.request().method());
		if (route.request().method() === 'DELETE') {
			state.deletedIds.push(new URL(route.request().url()).pathname.split('/').at(-1)!);
			return route.fulfill({ json: { ok: true } });
		}
		if (route.request().method() === 'PATCH') {
			const id = new URL(route.request().url()).pathname.split('/').at(-1);
			const annotation = annotations.find((annotation) => annotation.id === id)!;
			Object.assign(annotation, route.request().postDataJSON(), {
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
	await setAnnotationSource(page, 'Archived');
	await page.getByRole('button', { name: 'Comment', exact: true }).click();
	const card = commentCard(page, 'private annotation');
	await card.getByRole('button').first().click();
	await page.getByRole('button', { name: 'Edit', exact: true }).click();
	await page.locator('textarea').fill('Edited private annotation');
	await page.getByRole('button', { name: 'Save', exact: true }).click();
	await expect(page.getByText('Edited private annotation', { exact: true })).toBeVisible();
	await expect.poll(() => state.mutationRequests).toEqual(['PATCH']);
	await expect(page.getByText('Saved', { exact: true })).toBeVisible();
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
		annotations.selectAnnotation(0, annotationId);
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
			.toBe('annotation-private');
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
	await page.getByText('Displayed annotation sources', { exact: true }).click();
	await expect(page.locator('details').getByLabel('Archived', { exact: true })).toBeChecked();
	await page.getByText('Displayed annotation sources', { exact: true }).click();
	await expect(page.getByLabel('New annotation source')).toHaveValue('');
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
