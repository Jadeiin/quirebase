import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

test('library renders canonical rich titles and exposes later pages', async ({ page }) => {
	await mockSession(page);
	const requestedPages: number[] = [];
	const requestedQueries: Array<{ query: string | null; q: string | null }> = [];
	await page.route('**/api/v1/items*', (route) => {
		const searchParameters = new URL(route.request().url()).searchParams;
		const requestedPage = Number(searchParameters.get('page') ?? '1');
		requestedPages.push(requestedPage);
		requestedQueries.push({ query: searchParameters.get('query'), q: searchParameters.get('q') });
		return route.fulfill({
			json: {
				items: [
					{
						id: `item-${requestedPage}`,
						title_html: requestedPage === 1 ? '<i>Visible</i> $x^2$ Item' : 'Second page Item',
						authors: null,
						publication_date: null,
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 26,
				page: requestedPage,
				per_page: 25
			}
		});
	});

	await page.goto('/library');
	await expect(page.locator('strong i', { hasText: 'Visible' })).toBeVisible();
	await expect(page.locator('strong math msup')).toBeVisible();
	await expect(page.getByText('$x^2$', { exact: false })).toHaveCount(0);
	await page.getByPlaceholder('Search title, author, Tag, or full text').fill('quantum fields');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page).toHaveURL(/\/library\?q=quantum\+fields$/);
	await expect.poll(() => requestedQueries).toContainEqual({ query: 'quantum fields', q: null });
	await page.getByRole('button', { name: 'Next page' }).click();
	await expect.poll(() => requestedPages).toContain(2);
	await expect.poll(() => requestedQueries.at(-1)).toEqual({ query: 'quantum fields', q: null });
	await expect(page.getByText('Second page Item')).toBeVisible();
});

test('Library page selection toggles and icon pagination reaches every boundary', async ({
	page
}) => {
	await mockSession(page);
	const requestedPages: number[] = [];
	await page.route('**/api/v1/account', (route) =>
		route.fulfill({
			json: {
				user: { id: 'user-1', username: 'reader', role: 'member' },
				sessions: [],
				api_tokens: []
			}
		})
	);
	await page.route('**/api/v1/tags', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/projects', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/items?*', (route) => {
		const currentPage = Number(new URL(route.request().url()).searchParams.get('page') ?? '1');
		requestedPages.push(currentPage);
		return route.fulfill({
			json: {
				items: [1, 2].map((number) => ({
					id: `item-${currentPage}-${number}`,
					title_html: `Page ${currentPage} Item ${number}`,
					authors: 'A. Reader',
					publication_date: '2026',
					publication_title: null,
					doi: null,
					version: 1
				})),
				total: 75,
				page: currentPage,
				per_page: 25
			}
		});
	});

	await page.goto('/library');
	const pageSelection = page.getByLabel('Select this page');
	const itemSelections = page.locator('article input[type="checkbox"]');
	await pageSelection.check();
	await expect(page.locator('article input[type="checkbox"]:checked')).toHaveCount(2);
	await pageSelection.uncheck();
	await expect(page.locator('article input[type="checkbox"]:checked')).toHaveCount(0);
	await expect(itemSelections).toHaveCount(2);

	await page.getByRole('button', { name: 'Last page' }).click();
	await expect.poll(() => requestedPages.at(-1)).toBe(3);
	await page.getByRole('button', { name: 'Previous page' }).click();
	await expect.poll(() => requestedPages.at(-1)).toBe(2);
	await page.getByRole('button', { name: 'First page' }).click();
	await expect(page).toHaveURL(/\/library$/);
	await expect(page.getByText('Page 1 Item 1')).toBeVisible();
	await page.getByRole('button', { name: 'Next page' }).click();
	await expect(page).toHaveURL(/page=2/);
	await expect(page.getByText('Page 2 Item 1')).toBeVisible();
});

test('Library history navigation restores filter drafts and clears selection', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/tags', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/projects', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/items?*', (route) => {
		const query = new URL(route.request().url()).searchParams.get('query') ?? 'all';
		return route.fulfill({
			json: {
				items: [
					{
						id: `item-${query}`,
						title_html: `Result for ${query}`,
						authors: 'A. Reader',
						publication_date: '2026',
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 1,
				page: 1,
				per_page: 25
			}
		});
	});

	await page.goto('/library');
	const search = page.getByPlaceholder('Search title, author, Tag, or full text');
	await search.fill('foo');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page).toHaveURL(/q=foo/);
	await expect(page.getByText('Result for foo')).toBeVisible();

	await search.fill('bar');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page).toHaveURL(/q=bar/);
	await expect(page.getByText('Result for bar')).toBeVisible();
	await page.locator('article input[type="checkbox"]').check();
	await expect(page.getByText('1 selected')).toBeVisible();

	await page.goBack();
	await expect(page).toHaveURL(/q=foo/);
	await expect(page.getByText('Result for foo')).toBeVisible();
	await expect(search).toHaveValue('foo');
	await expect(page.getByText('1 selected')).toHaveCount(0);
});

test('adding a Library Item invalidates a previously opened Project', async ({ page }) => {
	await mockSession(page);
	let added = false;
	let projectReads = 0;
	await page.route('**/api/v1/tags', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/projects/joinable', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/projects/project-1', (route) => {
		projectReads += 1;
		return route.fulfill({
			json: {
				id: 'project-1',
				name: 'Research',
				description: 'Reading list',
				role: 'owner',
				item_count: added ? 1 : 0,
				state: 'active',
				visibility: 'private',
				items: added
					? [
							{
								id: 'item-1',
								title_html: 'Newly added Item',
								authors: 'A. Reader',
								publication_date: '2026',
								publication_title: null,
								doi: null,
								version: 1
							}
						]
					: [],
				members: [{ user_id: 'user-1', username: 'reader', role: 'owner' }]
			}
		});
	});
	await page.route('**/api/v1/projects', (route) =>
		route.fulfill({
			json: [
				{
					id: 'project-1',
					name: 'Research',
					role: 'owner',
					item_count: added ? 1 : 0,
					state: 'active',
					visibility: 'private',
					description: 'Reading list'
				}
			]
		})
	);
	await page.route('**/api/v1/items?*', (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'item-1',
						title_html: 'Newly added Item',
						authors: 'A. Reader',
						publication_date: '2026',
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 1,
				page: 1,
				per_page: 25
			}
		})
	);
	await page.route('**/api/v1/items/bulk', (route) => {
		added = true;
		return route.fulfill({ json: { ok: true } });
	});

	await page.goto('/projects/project-1');
	await expect.poll(() => projectReads).toBe(1);
	await page.getByRole('link', { name: 'Library', exact: true }).first().click();
	await page.getByLabel('Select this page').check();
	await page.getByLabel('Bulk action').selectOption('add_project');
	await page.getByLabel('Select Project').selectOption('project-1');
	await page.getByRole('button', { name: 'Apply' }).click();
	await expect(page.getByText('Bulk action completed')).toBeVisible();
	await page.getByRole('link', { name: 'Projects', exact: true }).first().click();
	await page.getByRole('link').filter({ hasText: 'Research' }).click();
	await expect.poll(() => projectReads).toBeGreaterThan(1);
	await expect(page.getByText('Newly added Item')).toBeVisible();
});

test('saved export preferences flow into Library bibliography requests', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/account', (route) =>
		route.fulfill({
			json: {
				user: { id: 'user-1', username: 'reader', role: 'member' },
				sessions: [],
				api_tokens: []
			}
		})
	);
	await page.route('**/api/v1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [{ key: 'apa', name: 'APA' }] } })
	);
	await page.route('**/api/v1/citation-key-preview*', (route) =>
		route.fulfill({ json: { key: 'Reader2026' } })
	);

	await page.goto('/account');
	await page.getByLabel('Default citation format').selectOption('bibtex');
	await page.getByLabel('Include additional identifiers').check();
	await expect
		.poll(() =>
			page.evaluate(
				() =>
					JSON.parse(localStorage.getItem('quirebase:export-preferences:v1:account:user-1')!)
						.citation
			)
		)
		.toMatchObject({ format: 'bibtex', includeIdentifiers: true });

	let exportBody: Record<string, unknown> | null = null;
	await page.route('**/api/v1/items*', (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'item-1',
						title_html: 'Exportable',
						authors: 'A. Author',
						publication_date: '2026',
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 1,
				page: 1,
				per_page: 25
			}
		})
	);
	await page.route('**/api/v1/tags', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/projects', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/items/bibliography', (route) => {
		exportBody = route.request().postDataJSON();
		return route.fulfill({
			body: '@article{Reader2026}',
			headers: { 'Content-Disposition': 'attachment; filename="items.bib"' }
		});
	});

	await page.goto('/library');
	await page.getByLabel('Select A. Author').check();
	await page.getByLabel('Bulk action').selectOption('bibliography');
	await page.getByRole('button', { name: 'Apply' }).click();
	await expect
		.poll(() => exportBody)
		.toMatchObject({
			file_format: 'bibtex',
			include_identifiers: true
		});
});

test('library filters do not overflow narrow viewports', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 720 });
	await mockSession(page);
	await page.route('**/api/v1/tags', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/projects', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/items*', (route) =>
		route.fulfill({ json: { items: [], total: 0, page: 1, per_page: 25 } })
	);

	await page.goto('/library');
	await expect(page.getByPlaceholder('Search title, author, Tag, or full text')).toBeVisible();
	const { scrollWidth, innerWidth } = await page.evaluate(() => ({
		scrollWidth: document.documentElement.scrollWidth,
		innerWidth: window.innerWidth
	}));
	expect(scrollWidth).toBeLessThanOrEqual(innerWidth);
});
