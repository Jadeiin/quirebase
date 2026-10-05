import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

test('Tools exposes Tag maintenance and Citation Style installation', async ({ page }) => {
	await mockSession(page);
	let styleCreation: Record<string, unknown> | null = null;
	let duplicateReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/duplicates*', (route) => {
		duplicateReads += 1;
		return route.fulfill({ json: { groups: [] } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/tags', (route) =>
		route.fulfill({
			json: [
				{
					id: 'tag-1',
					name: 'Methods',
					accessible_item_count: 3,
					authorization: { allowed: ['tag.manage'] }
				}
			]
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
	await page.getByRole('button', { name: 'Same title' }).click();
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
		return route.fulfill({ json: tags });
	});
	await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [] } })
	);

	await page.goto('/workspace/workspace-1/tools');
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await expect(page.getByText('21 Tags')).toBeVisible();
	await page.getByRole('button', { name: 'Next' }).click();
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
		await page.route('**/api/v1/workspaces/workspace-1/tags', (route) => {
			tagReads++;
			return route.fulfill({ json: tags });
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
		await sourceSelect.selectOption('tag-1');
		if (concurrentChange === 'renamed') await targetSelect.selectOption('tag-2');
		const initialWorkspaceReads = [...workspaceReads];
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
		await expect(targetSelect.locator('option[value="tag-2"]')).toHaveText('Results');
		await expect(sourceSelect).toHaveValue('tag-1');
		await targetSelect.selectOption('tag-2');
		await expect(page.getByRole('button', { name: 'Merge Tags', exact: true })).toBeEnabled();
		expect(tagReads).toBe(2);
		expect(workspaceReads).toEqual(initialWorkspaceReads);
		expect(styleReads).toBe(initialStyleReads);
		expect(duplicateReads).toBe(initialDuplicateReads);
	});
}
