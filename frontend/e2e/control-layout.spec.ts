import { mockMetadataSources } from './helpers';
import { expect, test, type Page } from '@playwright/test';
import { chooseSearchOption, directoryPage, mockSession, tagPage } from './helpers';

async function library(page: Page) {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({
			json: tagPage(
				[{ id: 'tag-1', name: 'Reading', item_count: 0, authorization: { allowed: ['tag.use'] } }],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({
			json: directoryPage(
				[
					{
						id: 'project-1',
						name: 'Reading Project',
						state: 'active',
						participation: 'workspace',
						is_participating: true,
						item_count: 0,
						authorization: { allowed: ['project_item.manage'] }
					}
				],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'item-1',
						title_html: 'Selected Item',
						authors: [],
						publication_date: null,
						version: 1
					}
				],
				total: 1,
				limit: 25,
				offset: 0
			}
		})
	);
	await page.goto('/workspace/workspace-1/library');
	await page.getByLabel('Select this page').check();
}

async function item(page: Page, filename = 'paper.pdf') {
	await mockSession(page);
	const metadata = {
		id: 'https://doi.org/10.1000/test',
		type: 'JournalArticle',
		title: 'Actionable'
	};
	const latest = {
		id: 'revision-1',
		original_name: filename,
		size: 100,
		page_count: 1,
		processing_state: 'ready'
	};
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata,
				citation_key: null,
				id: 'item-1',
				version: 3,
				authorization: { allowed: ['item.update', 'workspace.export'] },
				copy_targets: [],
				tags: [],
				latest_revision_id: latest,
				counts: { revisions: 1, attachments: 0, annotations: 0, discussion: 0 }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/documents', (route) =>
		route.fulfill({ json: { item_id: 'item-1', files: [{ ...latest, kind: 'revision' }] } })
	);
	await page.goto('/workspace/workspace-1/item/item-1');
}

for (const width of [1440, 390]) {
	for (const mode of ['light', 'dark']) {
		test(`admin filter controls have equal heights in ${mode} mode at ${width}px`, async ({
			page
		}) => {
			await page.setViewportSize({ width, height: 1000 });
			await mockSession(page, 'administrator');
			await page.route('**/api/v1/admin/users*', (route) =>
				route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0, invitations: [] } })
			);
			await page.goto('/admin/users');
			const apply = page.getByRole('button', { name: 'Apply filters', exact: true });
			const form = page.locator('form').filter({ has: apply });
			const controls = form.locator('input, select, button');
			await expect(controls).toHaveCount(5);
			for (const control of await controls.all()) await expect(control).toBeVisible();
			await page.evaluate(async (mode) => {
				document.documentElement.dataset.mode = mode;
				await document.fonts.ready;
			}, mode);

			await expect(async () => {
				const boxes = await controls.evaluateAll((elements) =>
					elements.map((element) => {
						const { x, y, width, height } = element.getBoundingClientRect();
						return { tag: element.tagName, x, y, width, height };
					})
				);
				const heights = boxes.map((box) => box.height);
				const details = JSON.stringify(boxes);
				expect(Math.max(...heights) - Math.min(...heights), details).toBeLessThanOrEqual(1);
				for (const box of boxes) {
					expect(Math.abs(box.height - 32), details).toBeLessThanOrEqual(1);
					expect(box.x, details).toBeGreaterThanOrEqual(0);
					expect(box.x + box.width, details).toBeLessThanOrEqual(width + 1);
				}
				if (width === 1440) {
					const tops = boxes.map((box) => box.y);
					expect(Math.max(...tops) - Math.min(...tops), details).toBeLessThanOrEqual(1);
				}
			}).toPass({ timeout: 5000 });
		});
	}
}

test('bulk Tag action offers searchable existing Tags and submits their names', async ({
	page
}) => {
	await library(page);
	let submitted: unknown;
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		submitted = route.request().postDataJSON();
		return route.fulfill({ json: { ok: true } });
	});
	await page.getByRole('combobox', { name: 'Bulk action', exact: true }).selectOption('add_tag');
	await chooseSearchOption(page, 'Select Tag', 'Reading');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	await expect
		.poll(() => submitted)
		.toMatchObject({ action: 'add_tag', tag_name: 'Reading', item_ids: ['item-1'] });
});

test('bulk Project chooser aligns with the action selector', async ({ page }) => {
	await page.setViewportSize({ width: 1440, height: 1000 });
	await library(page);
	await page
		.getByRole('combobox', { name: 'Bulk action', exact: true })
		.selectOption('add_project');
	const action = (await page
		.getByRole('combobox', { name: 'Bulk action', exact: true })
		.boundingBox())!;
	const project = (await page
		.getByRole('combobox', { name: 'Select Project', exact: true })
		.boundingBox())!;
	expect(Math.abs(action.y - project.y), JSON.stringify({ action, project })).toBeLessThan(2);
	expect(Math.abs(action.height - project.height)).toBeLessThan(2);
	await page.getByRole('combobox', { name: 'Bulk action', exact: true }).selectOption('add_tag');
	const tag = (await page
		.getByRole('combobox', { name: 'Select Tag', exact: true })
		.boundingBox())!;
	expect(Math.abs(action.y - tag.y)).toBeLessThan(2);
	expect(Math.abs(action.height - tag.height)).toBeLessThan(2);
});

test('bulk Tag action still accepts a new Tag name', async ({ page }) => {
	await library(page);
	let submitted: unknown;
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		submitted = route.request().postDataJSON();
		return route.fulfill({ json: { ok: true } });
	});
	await page.getByRole('combobox', { name: 'Bulk action', exact: true }).selectOption('add_tag');
	const tag = page.getByRole('combobox', { name: 'Select Tag', exact: true });
	await tag.fill('New topic');
	await tag.press('Escape');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	await expect.poll(() => submitted).toMatchObject({ action: 'add_tag', tag_name: 'New topic' });
});

test('metadata Reference type and publication date selectors align', async ({ page }) => {
	await page.setViewportSize({ width: 1440, height: 1100 });
	await mockSession(page);
	await page.goto('/workspace/workspace-1/import');
	await page.getByRole('tab', { name: 'Manual creation', exact: true }).click();
	const type = (await page.getByLabel('Reference type').boundingBox())!;
	const precision = (await page.getByLabel('Date precision').boundingBox())!;
	const date = (await page
		.getByRole('textbox', { name: 'Publication date', exact: true })
		.boundingBox())!;

	expect(Math.abs(type.y - precision.y), JSON.stringify({ type, precision, date })).toBeLessThan(2);
	expect(Math.abs(type.y - date.y)).toBeLessThan(2);
	expect(Math.abs(type.height - precision.height)).toBeLessThan(2);
	expect(Math.abs(type.height - date.height)).toBeLessThan(2);
});

test('DOI metadata update uses OpenAlex through its advertised lookup capability', async ({
	page
}) => {
	await item(page);
	await mockMetadataSources(page, 'item-1', {
		version: 3,
		sources: [
			{
				namespace: 'doi',
				value: '10.1000/test',
				providers: [
					{ id: 'crossref', name: 'Crossref' },
					{ id: 'openalex', name: 'OpenAlex' }
				]
			}
		]
	});
	let submitted: unknown;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/metadata/sync', (route) => {
		submitted = route.request().postDataJSON();
		return route.fulfill({ json: { ok: true } });
	});
	await page.getByRole('button', { name: 'Record tools', exact: true }).click();
	await expect(page.getByLabel('Provider').locator('option', { hasText: 'OpenAlex' })).toHaveCount(
		1
	);
	await page.getByLabel('Provider').selectOption('openalex');
	await page.getByRole('dialog').getByRole('button', { name: 'Autoupdate', exact: true }).click();
	await expect
		.poll(() => submitted)
		.toEqual({ expected_version: 3, provider: 'openalex', uid: '10.1000/test' });
});

for (const width of [1440, 390]) {
	test(`annotation filename stays inside its card at ${width}px`, async ({ page }) => {
		await page.setViewportSize({ width, height: 1000 });
		await item(page);
		const filename = 'A'.repeat(220) + '.pdf';
		await page.route('**/api/v1/workspaces/workspace-1/items/item-1/annotations*', (route) =>
			route.fulfill({
				json: {
					revisions: [{ id: 'revision-1', original_name: filename }],
					projects: [],
					annotations: [
						{
							id: 'annotation-1',
							revision_id: 'revision-1',
							revision_name: filename,
							scope: 'private',
							page_index: 0,
							kind: 'note',
							body: 'Layout review note',
							author_display_name: 'reader',
							authorization: { allowed: [] },
							replies: []
						}
					],
					total: 1,
					page: 1,
					per_page: 50
				}
			})
		);
		await page.getByRole('link', { name: 'Annotations', exact: true }).click();
		const row = page.getByText('Layout review note', { exact: true }).locator('..');
		await expect(row.getByText(filename, { exact: false })).toBeVisible();
		await page.evaluate(() => document.fonts.ready);
		const overflow = await row.evaluate((element) => ({
			width: element.clientWidth,
			scroll: element.scrollWidth,
			right: element.getBoundingClientRect().right,
			pageWidth: document.documentElement.scrollWidth,
			viewportWidth: document.documentElement.clientWidth
		}));
		expect(overflow.scroll, JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.width + 1);
		expect(overflow.right).toBeLessThanOrEqual(overflow.viewportWidth);
		expect(overflow.pageWidth).toBeLessThanOrEqual(overflow.viewportWidth);
	});

	test(`document download filename stays inside its row at ${width}px`, async ({ page }) => {
		await page.setViewportSize({ width, height: 1000 });
		const filename = 'A'.repeat(220) + '.pdf';
		await item(page, filename);
		await page.getByRole('button', { name: 'Download', exact: true }).click();
		const label = page.getByRole('dialog').locator('label').filter({ hasText: filename });
		await expect(label).toBeVisible();
		const overflow = await label.evaluate((element) => ({
			width: element.clientWidth,
			scroll: element.scrollWidth,
			dialog: element.closest('[role="dialog"]')!.getBoundingClientRect().width
		}));
		expect(overflow.scroll, JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.width + 1);
		expect(overflow.dialog).toBeLessThanOrEqual(width);
	});
}
