import { expect, test } from '@playwright/test';
import { tagPage, chooseSearchOption, mockSession } from './helpers';

test('Tools exposes Tag maintenance and Citation Style installation', async ({ page }) => {
	await mockSession(page);
	let styleCreation: Record<string, unknown> | null = null;
	let duplicateReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/duplicates*', (route) => {
		duplicateReads += 1;
		return route.fulfill({ json: { groups: [] } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({
			json: tagPage(
				[
					{
						id: 'tag-1',
						name: 'Methods',
						accessible_item_count: 3,
						authorization: { allowed: ['tag.manage'] }
					}
				],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) => {
		if (route.request().method() === 'POST') {
			styleCreation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'style-1' } });
		}
		return route.fulfill({ json: { styles: [] } });
	});

	await page.goto('/workspace/workspace-1/tools');
	await expect.poll(() => duplicateReads).toBe(0);
	await page.getByRole('button', { name: 'Check for duplicates' }).click();
	await expect.poll(() => duplicateReads).toBe(1);
	await page.getByRole('radio', { name: 'Same DOI' }).focus();
	await page.getByRole('radio', { name: 'Same DOI' }).press('ArrowRight');
	await expect(page.getByRole('radio', { name: 'Same title' })).toBeChecked();
	await expect.poll(() => duplicateReads).toBe(1);
	await expect(page.getByText('The match criteria changed.')).toBeVisible();
	await page.getByRole('button', { name: 'Check for duplicates' }).click();
	await expect.poll(() => duplicateReads).toBe(2);
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await expect(page.locator('strong').filter({ hasText: 'Methods' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Rename' })).toBeVisible();
	await page.getByRole('tab', { name: 'Citation Styles' }).click();
	await page.getByLabel('Style name').fill('House style');
	await page.getByLabel('CSL XML').fill('<style version="1.0"></style>');
	await page.getByRole('button', { name: 'Install Citation Style' }).click();
	await expect
		.poll(() => styleCreation)
		.toEqual({
			name: 'House style',
			csl: '<style version="1.0"></style>'
		});
});

test('Tag page clamps after deleting the last page of Tags', async ({ page }) => {
	await mockSession(page);
	let tags = Array.from({ length: 21 }, (_, index) => ({
		id: `tag-${index + 1}`,
		name: `Tag ${String(index + 1).padStart(2, '0')}`,
		accessible_item_count: 1,
		authorization: { allowed: ['tag.manage'] }
	}));
	await page.route('**/api/v1/workspaces/workspace-1/tags**', (route) => {
		const request = route.request();
		if (request.method() === 'DELETE') {
			tags = tags.filter((tag) => !request.url().endsWith(tag.id));
			return route.fulfill({ json: { ok: true } });
		}
		return route.fulfill({ json: tagPage(tags, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [] } })
	);

	await page.goto('/workspace/workspace-1/tools');
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await expect(page.getByText('21 Tags')).toBeVisible();
	await page.getByRole('button', { name: 'Next page' }).click();
	await expect(page.getByText('Page 2 of 2')).toBeVisible();
	const tagRow = (name: string) =>
		page.locator('strong').filter({ hasText: new RegExp(`^${name}$`) });
	await expect(tagRow('Tag 21')).toBeVisible();

	await page.getByRole('button', { name: 'Delete' }).click();
	await page.getByRole('button', { name: 'Delete Tag' }).click();
	await expect(page.getByText('20 Tags')).toBeVisible();
	await expect(tagRow('Tag 21')).toHaveCount(0);
	await expect(tagRow('Tag 20')).toBeVisible();
	await expect(page.getByText('Page 2 of 2')).toHaveCount(0);
});

for (const concurrentChange of ['created', 'renamed']) {
	test(`Tag conflict refreshes Tools and merge targets after another member ${concurrentChange} a Tag`, async ({
		page
	}) => {
		await mockSession(page);
		const workspaceReads: string[] = [];
		page.on('request', (request) => {
			const path = new URL(request.url()).pathname;
			if (
				request.method() === 'GET' &&
				(path === '/api/v1/workspaces' || path === '/api/v1/workspaces/workspace-1')
			) {
				workspaceReads.push(path);
			}
		});
		let tagReads = 0;
		let duplicateReads = 0;
		let styleReads = 0;
		const source = {
			id: 'tag-1',
			name: 'Methods',
			accessible_item_count: 3,
			authorization: { allowed: ['tag.manage'] }
		};
		const target = { ...source, id: 'tag-2', name: 'Previous name' };
		let tags = concurrentChange === 'created' ? [source] : [source, target];
		await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) => {
			tagReads++;
			return route.fulfill({ json: tagPage(tags, route) });
		});
		await page.route('**/api/v1/workspaces/workspace-1/tags/tag-1', (route) => {
			expect(route.request().method()).toBe('PATCH');
			expect(route.request().postDataJSON()).toEqual({ name: 'Results' });
			tags = [source, { ...target, name: 'Results' }];
			return route.fulfill({
				status: 409,
				json: { code: 'tag_conflict', message: 'name already exists' }
			});
		});
		await page.route('**/api/v1/workspaces/workspace-1/duplicates*', (route) => {
			duplicateReads++;
			return route.fulfill({ json: { groups: [] } });
		});
		await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) => {
			styleReads++;
			return route.fulfill({ json: { styles: [] } });
		});

		await page.goto('/workspace/workspace-1/tools');
		await page.getByRole('button', { name: 'Check for duplicates' }).click();
		await expect(page.getByText('No duplicate groups found.')).toBeVisible();
		await page.getByRole('tab', { name: 'Manage Tags' }).click();
		const sourceSelect = page.getByRole('combobox', { name: 'Source Tag', exact: true });
		const targetSelect = page.getByRole('combobox', { name: 'Target Tag', exact: true });
		await chooseSearchOption(page, 'Source Tag', 'Methods');
		if (concurrentChange === 'renamed')
			await chooseSearchOption(page, 'Target Tag', 'Previous name');
		const initialWorkspaceReads = [...workspaceReads];
		const initialTagReads = tagReads;
		const initialStyleReads = styleReads;
		const initialDuplicateReads = duplicateReads;
		await page.getByRole('button', { name: 'Rename', exact: true }).first().click();
		const dialog = page.getByRole('dialog', { name: 'Rename Tag', exact: true });
		await dialog.getByRole('textbox', { name: 'New Tag name' }).fill('Results');
		await dialog.getByRole('button', { name: 'Rename', exact: true }).click();

		await expect(page.getByText('This Tag conflicts with an existing Tag.')).toBeVisible();
		await expect(page.locator('strong').filter({ hasText: /^Results$/ })).toBeVisible();
		await expect(page.locator('strong').filter({ hasText: /^Methods$/ })).toBeVisible();
		await expect(page.locator('strong').filter({ hasText: /^Previous name$/ })).toHaveCount(0);
		if (concurrentChange === 'renamed') await expect(targetSelect).toHaveValue('Results');
		await expect(sourceSelect).toHaveValue('Methods');
		await chooseSearchOption(page, 'Target Tag', 'Results');
		await expect(page.getByRole('button', { name: 'Merge Tags', exact: true })).toBeEnabled();
		expect(tagReads).toBeGreaterThan(initialTagReads);
		expect(workspaceReads).toEqual(initialWorkspaceReads);
		expect(styleReads).toBe(initialStyleReads);
		expect(duplicateReads).toBe(initialDuplicateReads);
	});
}

test('Tools requests only the visible Tag page and filters on the server', async ({ page }) => {
	await mockSession(page);
	const tags = Array.from({ length: 65 }, (_, index) => ({
		id: `tag-${index + 1}`,
		name: `Tag ${String(index + 1).padStart(2, '0')}`,
		accessible_item_count: 1,
		authorization: { allowed: ['tag.manage'] }
	}));
	const reads: Array<{ offset: number; limit: number; search: string | null }> = [];
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) => {
		const query = new URL(route.request().url()).searchParams;
		reads.push({
			offset: Number(query.get('offset') ?? 0),
			limit: Number(query.get('limit')),
			search: query.get('search')
		});
		return route.fulfill({ json: tagPage(tags, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [] } })
	);
	await page.goto('/workspace/workspace-1/tools');
	expect(reads).toEqual([]);
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await expect(page.getByText('65 Tags')).toBeVisible();
	expect(reads).toEqual([{ offset: 0, limit: 20, search: null }]);
	await page.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.locator('strong').filter({ hasText: /^Tag 21$/ })).toBeVisible();
	await expect(page.locator('strong').filter({ hasText: /^Tag 20$/ })).toHaveCount(0);
	expect(reads.at(-1)).toEqual({ offset: 20, limit: 20, search: null });
	await page.getByPlaceholder('Filter Tags').fill('Tag 65');
	await expect(page.getByText('1 Tag', { exact: true })).toBeVisible();
	await expect(page.locator('strong').filter({ hasText: /^Tag 65$/ })).toBeVisible();
	expect(reads.at(-1)).toEqual({ offset: 0, limit: 20, search: 'Tag 65' });
});
