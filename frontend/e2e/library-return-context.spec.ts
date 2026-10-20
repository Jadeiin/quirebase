import { expect, test, type Page } from '@playwright/test';
import { directoryPage, minimalPdf, mockSession, tagPage } from './helpers';

const context =
	'workspace/workspace-1/library?q=reading&sort=title&page=2&page_size=10&preview=item-11#library-item-item-11';
const itemPath = `/workspace/workspace-1/item/item-11?${new URLSearchParams({ return_to: context })}`;

async function mockReadingWorkflow(page: Page) {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/*/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/*/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	const rows = Array.from({ length: 30 }, (_, index) => ({
		id: `item-${index + 1}`,
		title_html: `Reading Item ${index + 1}`,
		authors: [],
		publication_date: null,
		publication_title: null,
		doi: null,
		version: 1
	}));
	let deleted = false;
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const parameters = new URL(route.request().url()).searchParams;
		const limit = Number(parameters.get('limit'));
		const offset = Number(parameters.get('offset'));
		const items = rows.filter((row) => !deleted || row.id !== 'item-11');
		return route.fulfill({
			json: { items: items.slice(offset, offset + limit), total: items.length, limit, offset }
		});
	});
	const metadata = {
		id: 'urn:uuid:00000000-0000-4000-8000-000000000011',
		type: 'JournalArticle',
		title: 'Reading Item 11',
		description: 'A reading workflow abstract'
	};
	await page.route('**/api/v1/workspaces/workspace-1/items/item-11/overview', (route) =>
		route.fulfill({
			json: {
				id: 'item-11',
				version: 1,
				metadata,
				citation_key: null,
				authorization: { allowed: ['item.delete', 'workspace.export'] },
				counts: { revisions: 1, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				latest_revision_id: 'revision-1',
				thumbnail: null,
				copy_targets: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-11', (route) => {
		if (route.request().method() === 'DELETE') {
			deleted = true;
			return route.fulfill({ status: 204 });
		}
		return route.fulfill({ json: { id: 'item-11', version: 1, metadata } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-11/documents', (route) =>
		route.fulfill({
			json: {
				item_id: 'item-11',
				files: [
					{
						id: 'revision-1',
						kind: 'revision',
						original_name: 'reading.pdf',
						mime_type: 'application/pdf',
						size: 100,
						created_at: '2026-10-20T00:00:00Z',
						processing_state: 'ready'
					}
				]
			}
		})
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-11/revisions/revision-1/viewer',
		(route) =>
			route.fulfill({
				json: {
					item: { id: 'item-11', title_html: 'Reading Item 11', version: 1 },
					editable: false,
					annotation_author: 'reader',
					revision: {
						id: 'revision-1',
						original_name: 'reading.pdf',
						page_count: 1,
						processing_state: 'ready',
						page_geometry: [[0, 0, 300, 400]],
						content_url: '/api/v1/workspaces/workspace-1/items/item-11/revisions/revision-1/content'
					},
					projects: []
				}
			})
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-11/revisions/revision-1/content',
		(route) => route.fulfill({ contentType: 'application/pdf', body: minimalPdf() })
	);
	return { isDeleted: () => deleted, items: rows };
}

test('Item sections, files and reader preserve the submitted Library and return to its Item', async ({
	page
}) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	await mockReadingWorkflow(page);
	await page.goto(itemPath);
	await expect(page.getByRole('heading', { level: 1, name: 'Reading Item 11' })).toBeVisible();
	for (const label of ['Overview', 'Metadata', 'Files', 'Organize', 'Annotations', 'Discussion']) {
		const href = await page.getByRole('link', { name: label, exact: true }).getAttribute('href');
		expect(new URL(href!, page.url()).searchParams.get('return_to')).toBe(context);
	}
	await page.getByRole('link', { name: 'Files', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Files', exact: true })).toBeVisible();
	await page.getByRole('link', { name: 'Read', exact: true }).click();
	await expect(page).toHaveURL(/\/pdf\/revision-1\?/);
	const returnLink = page.locator('header').getByRole('link', { name: 'Library', exact: true });
	await expect(returnLink).toHaveAttribute('href', `/${context}`);
	const itemLink = page.locator('header').getByRole('link', { name: 'Item', exact: true });
	expect(
		new URL((await itemLink.getAttribute('href'))!, page.url()).searchParams.get('return_to')
	).toBe(context);
	await itemLink.click();
	await expect(page.getByRole('heading', { level: 1, name: 'Reading Item 11' })).toBeVisible();
	await page.getByRole('link', { name: 'Read PDF', exact: true }).click();
	await returnLink.click();
	await expect(page).toHaveURL(`/${context}`);
	await expect(page.locator('[data-library-item-select="item-11"]')).toBeFocused();
	await expect(page.getByRole('textbox', { name: 'Library Search', exact: true })).toHaveValue(
		'reading'
	);
	await page.goBack();
	await expect(page).toHaveURL(/\/pdf\/revision-1\?/);
	await expect(returnLink).toHaveAttribute('href', `/${context}`);
	await page.goForward();
	await expect(page).toHaveURL(`/${context}`);
});

test('return contexts belong to the Item URL and remain independent across tabs', async ({
	page,
	context: browser
}) => {
	await mockReadingWorkflow(page);
	await page.goto(itemPath);
	const second = await browser.newPage();
	await mockReadingWorkflow(second);
	const otherContext =
		'workspace/workspace-1/library?year=2026&sort=published#library-item-item-11';
	await second.goto(
		`/workspace/workspace-1/item/item-11/files?${new URLSearchParams({ return_to: otherContext })}`
	);
	await expect(
		page.locator('main').getByRole('link', { name: 'Library', exact: true })
	).toHaveAttribute('href', `/${context}`);
	await expect(
		second.locator('main').getByRole('link', { name: 'Library', exact: true })
	).toHaveAttribute('href', `/${otherContext}`);
	await second.close();
});

test('direct and invalid-context Item links keep default Library navigation', async ({ page }) => {
	await mockReadingWorkflow(page);
	for (const returnTo of ['', '/workspace/workspace-2/library', 'https://evil.example/library']) {
		await page.goto(
			`/workspace/workspace-1/item/item-11?${new URLSearchParams({ return_to: returnTo })}`
		);
		await expect(
			page.locator('main').getByRole('link', { name: 'Library', exact: true })
		).toHaveAttribute('href', '/workspace/workspace-1/library');
		await page.getByRole('link', { name: 'Files', exact: true }).click();
		await expect(page).toHaveURL('/workspace/workspace-1/item/item-11/files');
		await page.getByRole('link', { name: 'Read', exact: true }).click();
		await expect(
			page.locator('header').getByRole('link', { name: 'Library', exact: true })
		).toHaveCount(0);
		await expect(
			page.locator('header').getByRole('link', { name: 'Item', exact: true })
		).toHaveAttribute('href', '/workspace/workspace-1/item/item-11');
	}
});

test('deleting an Item returns to the filtered page without reopening the deleted preview', async ({
	page
}) => {
	const { isDeleted } = await mockReadingWorkflow(page);
	await page.goto(itemPath);
	await page.getByRole('button', { name: 'More', exact: true }).click();
	const dialog = page.getByRole('dialog', { name: 'Item actions', exact: true });
	await dialog.getByRole('button', { name: 'Delete Item permanently', exact: true }).click();
	await expect(dialog.getByRole('alert')).toHaveText(
		'This cannot be undone. Delete this Item permanently?'
	);
	await dialog.getByRole('button', { name: 'Delete Item permanently', exact: true }).click();
	await expect.poll(isDeleted).toBe(true);
	await expect(page).toHaveURL(
		'/workspace/workspace-1/library?q=reading&sort=title&page=2&page_size=10'
	);
	await expect(page.locator('[data-library-item-select="item-12"]')).toBeVisible();
	await expect(page.locator('[data-library-item-select="item-11"]')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Close preview', exact: true })).toHaveCount(0);
});

test('returning after Item organization waits for the stale filtered cache before choosing fallback focus', async ({
	page
}) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	const { items } = await mockReadingWorkflow(page);
	const release = Promise.withResolvers<void>();
	let assigned = true;
	let returning = false;
	await page.route('**/api/v1/workspaces/workspace-1/items?*', async (route) => {
		if (!assigned) {
			returning = true;
			await release.promise;
		}
		return route.fulfill({
			json: directoryPage(
				items.filter((item) => assigned || item.id !== 'item-11'),
				route
			)
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-11/organize', (route) =>
		route.fulfill({
			json: {
				authorization: { allowed: ['tag.use'] },
				projects: [],
				tag_matrix: {
					groups: [{ letter: 'M', tags: [{ id: 'tag-1', name: 'Methods' }] }],
					assigned_ids: assigned ? ['tag-1'] : [],
					recommended_ids: [],
					suggested_names: [],
					recommendation_state: 'ready',
					recommendation_error: null
				}
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-11/tags', (route) => {
		assigned = false;
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/library?tag=tag-1&sort=title&page=2&page_size=10');
	await page.getByRole('link', { name: 'Reading Item 11', exact: true }).click();
	await page.getByRole('link', { name: 'Organize', exact: true }).click();
	await page.getByRole('button', { name: 'Remove Methods', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Remove Methods', exact: true })).toHaveCount(0);
	await page.locator('main').getByRole('link', { name: 'Library', exact: true }).click();
	try {
		await expect.poll(() => returning).toBe(true);
		await expect(page.locator('[data-library-item-select="item-11"]')).toBeVisible();
	} finally {
		release.resolve();
	}
	await expect(page.locator('[data-library-item-select="item-11"]')).toHaveCount(0);
	await expect(page.locator('[data-library-item-select="item-12"]')).toBeVisible();
	await expect(page.locator('#library-results')).toBeFocused();
	await expect(page).toHaveURL(/tag=tag-1&sort=title&page=2&page_size=10#library-item-item-11$/);
});

test('a slow Library return preserves intervening search focus and an unsubmitted draft', async ({
	page
}) => {
	const { items } = await mockReadingWorkflow(page);
	const release = Promise.withResolvers<void>();
	let returning = false;
	await page.route('**/api/v1/workspaces/workspace-1/items?*', async (route) => {
		returning = true;
		await release.promise;
		return route.fulfill({ json: directoryPage(items, route) });
	});
	await page.goto(itemPath);
	await page.locator('main').getByRole('link', { name: 'Library', exact: true }).click();
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	try {
		await expect.poll(() => returning).toBe(true);
		await search.fill('notes not yet submitted');
	} finally {
		release.resolve();
	}
	await expect(page.locator('[data-library-item-select="item-11"]')).toBeVisible();
	await expect(search).toBeFocused();
	await expect(search).toHaveValue('notes not yet submitted');
	await expect(page).toHaveURL(`/${context}`);
});

test('a delayed Item deletion refreshes data without replacing later Library navigation', async ({
	page
}) => {
	await mockReadingWorkflow(page);
	const started = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	await page.route('**/api/v1/workspaces/workspace-1/items/item-11', async (route) => {
		if (route.request().method() !== 'DELETE') return route.fallback();
		started.resolve();
		await release.promise;
		return route.fulfill({ status: 204 });
	});
	await page.goto('/workspace/workspace-1/library?q=reading&sort=title&page=2&page_size=10');
	await page.getByRole('link', { name: 'Reading Item 11', exact: true }).click();
	await page.getByRole('button', { name: 'More', exact: true }).click();
	const dialog = page.getByRole('dialog', { name: 'Item actions', exact: true });
	await dialog.getByRole('button', { name: 'Delete Item permanently', exact: true }).click();
	await expect(dialog.getByRole('alert')).toBeVisible();
	await dialog.getByRole('button', { name: 'Delete Item permanently', exact: true }).click();
	try {
		await started.promise;
		await page.goBack();
		await page
			.getByRole('textbox', { name: 'Library Search', exact: true })
			.fill('changed reading');
		await page.getByRole('button', { name: 'Search', exact: true }).click();
		await expect(page).toHaveURL(
			'/workspace/workspace-1/library?q=changed+reading&sort=title&page_size=10'
		);
		await expect(page.locator('[data-library-item-select="item-1"]')).toBeVisible();
		const refreshed = page.waitForResponse((response) => {
			const url = new URL(response.url());
			return url.pathname.endsWith('/items') && url.searchParams.get('query') === 'changed reading';
		});
		release.resolve();
		await (await refreshed).finished();
		await page.evaluate(
			() =>
				new Promise<void>((resolve) =>
					requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
				)
		);
		await expect(page).toHaveURL(
			'/workspace/workspace-1/library?q=changed+reading&sort=title&page_size=10'
		);
	} finally {
		release.resolve();
	}
});
