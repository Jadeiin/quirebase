import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

test('Tools exposes Tag maintenance and Citation Style installation', async ({ page }) => {
	await mockSession(page);
	let styleCreation: Record<string, unknown> | null = null;
	let duplicateReads = 0;
	await page.route('**/api/v1/duplicates*', (route) => {
		duplicateReads += 1;
		return route.fulfill({ json: { groups: [] } });
	});
	await page.route('**/api/v1/tags', (route) =>
		route.fulfill({ json: [{ id: 'tag-1', name: 'Methods', accessible_item_count: 3 }] })
	);
	await page.route('**/api/v1/citation-styles*', (route) => {
		if (route.request().method() === 'POST') {
			styleCreation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'style-1' } });
		}
		return route.fulfill({ json: { styles: [] } });
	});

	await page.goto('/tools');
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
		accessible_item_count: 1
	}));
	await page.route('**/api/v1/tags**', (route) => {
		const request = route.request();
		if (request.method() === 'DELETE') {
			tags = tags.filter((tag) => !request.url().endsWith(tag.id));
			return route.fulfill({ json: { ok: true } });
		}
		return route.fulfill({ json: tags });
	});
	await page.route('**/api/v1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [] } })
	);

	await page.goto('/tools');
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
