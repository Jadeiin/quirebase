import { openLibraryAction } from './helpers';
import { expect, test, type Page } from '@playwright/test';
import { directoryPage, mockSession, tagPage } from './helpers';
import type { components } from '../src/lib/api/schema.js';

const items: components['schemas']['ItemSearchView'][] = [1, 2, 3].map((number) => ({
	id: `item-${number}`,
	title_html: `Recovery Item ${number}`,
	authors: [{ full_name: `Author ${number}`, last_name: `Author ${number}`, first_name: null }],
	publication_date: null,
	publication_title: null,
	doi: null,
	version: 1
}));

async function mockLibrary(page: Page) {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
}

test('background refresh restores results focus when the last selected row disappears', async ({
	page
}) => {
	await mockLibrary(page);
	let rows = items;
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({ json: directoryPage(rows, route) })
	);
	await page.goto('/workspace/workspace-1/library');
	await page.getByRole('checkbox', { name: 'Select Author 1', exact: true }).check();
	const toolbar = page.getByRole('region', { name: 'Bulk actions', exact: true });
	const action = toolbar.getByRole('button', { name: 'Add Tag', exact: true });
	await action.focus();
	await expect(action).toBeFocused();
	await page.clock.install();
	rows = items.slice(1);
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
	await expect(page.getByRole('link', { name: 'Recovery Item 1', exact: true })).toHaveCount(0);
	await expect(toolbar).toHaveCount(0);
	await expect(page.locator('#library-results')).toBeFocused();
	await expect(
		page.getByRole('checkbox', { name: 'Select Author 2', exact: true })
	).not.toBeChecked();
});

test('an old bulk completion preserves a reopened Library selection and toolbar focus', async ({
	page
}) => {
	await mockLibrary(page);
	const started = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	const releaseRefresh = Promise.withResolvers<void>();
	let committed = false;
	let refreshing = false;
	await page.route('**/api/v1/workspaces/workspace-1/items?*', async (route) => {
		if (committed) {
			refreshing = true;
			await releaseRefresh.promise;
		}
		return route.fulfill({ json: directoryPage(items, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', async (route) => {
		started.resolve();
		await release.promise;
		committed = true;
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/library');
	await page.getByRole('checkbox', { name: 'Select Author 1', exact: true }).check();
	const toolbar = page.getByRole('region', { name: 'Bulk actions', exact: true });
	await openLibraryAction(page, 'add_tag');
	await page
		.getByRole('dialog')
		.getByRole('combobox', { name: 'Select Tag', exact: true })
		.fill('Methods');
	await page.getByRole('dialog').getByText('Add Tag', { exact: true }).first().click();
	await page.getByRole('dialog').getByRole('button', { name: 'Add Tag', exact: true }).click();
	try {
		await started.promise;
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Continue in Library', exact: true })
			.click();
		await page.getByRole('link', { name: 'Projects', exact: true }).first().click();
		await expect(page).toHaveURL('/workspace/workspace-1/projects');
		await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
		await page.getByRole('link', { name: 'Library', exact: true }).first().click();
		await expect(page).toHaveURL('/workspace/workspace-1/library');
		const selection = page.getByRole('checkbox', { name: 'Select Author 2', exact: true });
		await selection.check();
		const action = toolbar.getByRole('button', { name: 'Add Tag', exact: true });
		await action.focus();
		await expect(action).toBeFocused();
		release.resolve();
		await expect.poll(() => refreshing).toBe(true);
		const sort = page.getByRole('combobox', { name: 'Sort By', exact: true });
		await expect(sort).toBeDisabled();
		releaseRefresh.resolve();
		await expect(sort).toBeEnabled();
		await expect(selection).toBeChecked();
		await expect(action).toBeFocused();
		await expect(toolbar).toContainText('1 selected');
		await expect(page.getByText('Bulk action completed', { exact: true })).toHaveCount(0);
	} finally {
		release.resolve();
		releaseRefresh.resolve();
	}
});
