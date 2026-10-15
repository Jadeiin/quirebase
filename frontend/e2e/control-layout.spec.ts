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
						authors: null,
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
				item: { id: 'item-1', title_html: metadata.title, doi: '10.1000/test', version: 3 },
				authorization: { allowed: ['item.update', 'workspace.export'] },
				copy_targets: [],
				tags: [],
				latest_revision: latest,
				counts: { revisions: 1, attachments: 0, annotations: 0, discussion: 0 }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/documents', (route) =>
		route.fulfill({ json: { item_id: 'item-1', files: [{ ...latest, kind: 'revision' }] } })
	);
	await page.goto('/workspace/workspace-1/item/item-1');
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
	await page.getByLabel('Bulk action').selectOption('add_tag');
	await chooseSearchOption(page, 'Select Tag', 'Reading');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	await expect
		.poll(() => submitted)
		.toMatchObject({ action: 'add_tag', tag_name: 'Reading', item_ids: ['item-1'] });
});

test('bulk Project chooser aligns with the action selector', async ({ page }) => {
	await page.setViewportSize({ width: 1440, height: 1000 });
	await library(page);
	await page.getByLabel('Bulk action').selectOption('add_project');
	const action = (await page.getByLabel('Bulk action').boundingBox())!;
	const project = (await page
		.getByRole('combobox', { name: 'Select Project', exact: true })
		.boundingBox())!;
	expect(Math.abs(action.y - project.y), JSON.stringify({ action, project })).toBeLessThan(2);
	expect(Math.abs(action.height - project.height)).toBeLessThan(2);
	await page.getByLabel('Bulk action').selectOption('add_tag');
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
	await page.getByLabel('Bulk action').selectOption('add_tag');
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
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: {
				search: [],
				lookup: [
					{ id: 'crossref', name: 'Crossref', identifier_namespaces: ['doi'] },
					{ id: 'openalex', name: 'OpenAlex', identifier_namespaces: ['openalex', 'doi'] }
				],
				max_search_clauses: 5
			}
		})
	);
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
