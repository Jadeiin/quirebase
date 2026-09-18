import { expect, test } from '@playwright/test';
import { minimalPdf, mockSession } from './helpers';

test('PDF reader uses the built-in EmbedPDF viewer with Quirebase annotations', async ({
	page
}) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await mockSession(page);
	const annotationRequests: string[] = [];
	await page.route('**/api/v1/items/item-1/revisions/revision-1/viewer', (route) =>
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
					content_url: '/api/v1/items/item-1/revisions/revision-1/content'
				},
				projects: [{ id: 'project-1', name: 'Shared' }]
			}
		})
	);
	await page.route('**/api/v1/items/item-1/annotations**', (route) => {
		annotationRequests.push(new URL(route.request().url()).search);
		if (route.request().method() === 'GET') {
			return route.fulfill({
				json: [
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
				]
			});
		}
		return route.fulfill({ json: { ok: true } });
	});
	await page.route('**/api/v1/items/item-1/revisions/revision-1/content', (route) =>
		route.fulfill({ contentType: 'application/pdf', body: minimalPdf() })
	);

	await page.goto('/item/item-1/pdf/revision-1');
	await expect(page.getByRole('button', { name: 'Document Menu' })).toBeVisible();
	await expect(page.locator('[data-epdf-i="comment-button"]')).toBeAttached();
	await expect(page.getByText('1 annotations loaded')).toBeVisible();
	expect(annotationRequests.at(-1)).toContain('revision_id=revision-1');

	await page.getByLabel('Annotation visibility').selectOption('project-1');
	await expect.poll(() => annotationRequests.at(-1)).toContain('project_id=project-1');
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
		await page.route('**/api/v1/items/item-1/revisions/revision-1/viewer', (route) =>
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
						content_url: '/api/v1/items/item-1/revisions/revision-1/content'
					},
					projects: []
				}
			})
		);
		await page.route('**/api/v1/items/item-1/annotations**', (route) =>
			route.request().method() === 'GET'
				? route.fulfill({ json: [] })
				: route.fulfill({ json: { ok: true } })
		);
		await page.route('**/api/v1/items/item-1/revisions/revision-1/content', (route) =>
			route.fulfill({ contentType: 'application/pdf', body: minimalPdf() })
		);

		await page.goto('/item/item-1/pdf/revision-1');
		await expect(page.getByRole('button', { name: 'Document Menu' })).toBeVisible();
		await page.locator('[data-epdf-i="mode-select-button"] button').click();
		await expect(page.locator('[data-epdf-i="mode:annotate"]')).toBeVisible();
	});
});
