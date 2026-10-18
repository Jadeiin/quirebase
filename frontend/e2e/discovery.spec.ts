import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

test('Discovery follows provider sorts and the server clause limit', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: {
				search: [
					{ id: 'openalex', name: 'OpenAlex', sorts: ['relevance', 'published', 'cited'] },
					{ id: 'arxiv', name: 'arXiv', sorts: ['relevance', 'published'] }
				],
				lookup: [],
				max_search_clauses: 2
			}
		})
	);
	let searchBody: Record<string, unknown> | null = null;
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		searchBody = route.request().postDataJSON();
		return route.fulfill({
			json: { provider: 'arxiv', results: [], total: 0, page: 1, per_page: 20 }
		});
	});
	await page.goto('/workspace/workspace-1/discovery');
	const sort = page.getByRole('combobox', { name: 'Sort', exact: true });
	await sort.selectOption('cited');
	await page.getByRole('combobox', { name: 'Provider', exact: true }).selectOption('arxiv');
	await expect(sort).toHaveValue('relevance');
	await expect(sort.locator('option[value="cited"]')).toHaveCount(0);
	await page.getByRole('button', { name: 'Add condition' }).click();
	await expect(page.getByRole('button', { name: 'Add condition' })).toBeDisabled();
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('systems');
	await page.getByPlaceholder('Another condition').fill('review');
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	await expect.poll(() => searchBody).toMatchObject({ provider: 'arxiv', sort: 'relevance' });
});

test('Discovery paging retains the successful query while a new query is edited or rejected', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: {
				search: [
					{ id: 'crossref', name: 'Crossref', sorts: ['relevance', 'published', 'cited'] },
					{ id: 'arxiv', name: 'arXiv', sorts: ['relevance', 'published'] }
				],
				lookup: [],
				max_search_clauses: 5
			}
		})
	);
	const requests: Array<{
		provider: string;
		sort: string;
		page: number;
		per_page: number;
		clauses: { term: string }[];
		year_from: number;
	}> = [];
	let rejectNewQuery = true;
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		const body = route.request().postDataJSON();
		requests.push(body);
		if (body.clauses[0].term === 'beta' && rejectNewQuery)
			return route.fulfill({ status: 503, json: { code: 'upstream_service_error' } });
		return route.fulfill({
			json: {
				provider: body.provider,
				page: body.page,
				per_page: body.per_page,
				total: 120,
				results: [
					{
						provider: body.provider,
						identifier_provider: 'doi',
						identifier: '10.1000/result',
						title: `${body.clauses[0].term} page ${body.page}`
					}
				]
			}
		});
	});
	await page.goto('/workspace/workspace-1/discovery');
	const term = page.getByPlaceholder('Title, author, DOI, or topic');
	await term.fill('alpha');
	await page.getByRole('combobox', { name: 'Sort', exact: true }).selectOption('cited');
	await page.getByRole('textbox', { name: 'From year', exact: true }).fill('2020');
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	await expect(page.getByText('alpha page 1', { exact: true })).toBeVisible();
	await term.fill('beta');
	await page.getByRole('combobox', { name: 'Provider', exact: true }).selectOption('arxiv');
	await page.getByRole('textbox', { name: 'From year', exact: true }).fill('2024');
	const pagination = page.getByRole('navigation', { name: 'Discovery result pages' });
	await pagination.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.getByText('alpha page 2', { exact: true })).toBeVisible();
	await pagination.getByRole('combobox', { name: 'Page Size', exact: true }).selectOption('50');
	await expect(pagination.getByText('Showing 1–50 of 120')).toBeVisible();
	await expect(term).toHaveValue('beta');
	// Calendar widgets can leave an assertive announcement outside the application content.
	await page.evaluate(() => {
		const announcement = document.createElement('span');
		announcement.setAttribute('role', 'alert');
		announcement.setAttribute('aria-live', 'assertive');
		announcement.style.cssText = 'position:absolute;clip:rect(0,0,0,0);width:1px;height:1px';
		announcement.textContent = 'Calendar selection updated';
		document.body.append(announcement);
	});
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	await expect(page.getByRole('main').getByRole('alert')).toBeVisible();
	await expect(page.getByText('alpha page 1', { exact: true })).toBeVisible();
	await pagination.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.getByText('alpha page 2', { exact: true })).toBeVisible();
	rejectNewQuery = false;
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	await expect(page.getByText('beta page 1', { exact: true })).toBeVisible();
	expect(
		requests.map((body) => ({
			provider: body.provider,
			sort: body.sort,
			term: body.clauses[0].term,
			year: body.year_from,
			page: body.page,
			size: body.per_page
		}))
	).toEqual([
		{ provider: 'crossref', sort: 'cited', term: 'alpha', year: 2020, page: 1, size: 20 },
		{ provider: 'crossref', sort: 'cited', term: 'alpha', year: 2020, page: 2, size: 20 },
		{ provider: 'crossref', sort: 'cited', term: 'alpha', year: 2020, page: 1, size: 50 },
		{ provider: 'arxiv', sort: 'relevance', term: 'beta', year: 2024, page: 1, size: 50 },
		{ provider: 'crossref', sort: 'cited', term: 'alpha', year: 2020, page: 2, size: 50 },
		{ provider: 'arxiv', sort: 'relevance', term: 'beta', year: 2024, page: 1, size: 50 }
	]);
});

test('discovery renders the flat results response contract', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: {
				search: [{ id: 'crossref', name: 'Crossref', sorts: ['relevance', 'published', 'cited'] }],
				lookup: [{ id: 'crossref', name: 'Crossref' }],
				max_search_clauses: 5
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) =>
		route.fulfill({
			json: {
				provider: 'crossref',
				results: [
					{
						provider: 'crossref',
						identifier_provider: 'doi',
						identifier: '10.1000/result',
						title: 'Discovered paper',
						authors: 'A. Researcher',
						publication_date: '2026'
					}
				],
				total: 1,
				page: 1,
				per_page: 20
			}
		})
	);

	await page.goto('/workspace/workspace-1/discovery');
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('paper');
	await page.getByRole('button', { name: 'Search Discovery' }).click();

	await expect(page.getByText('Discovered paper')).toBeVisible();
	await expect(page.getByText('doi:10.1000/result')).toBeVisible();
});

test('discovery query builder stages a selected Candidate Record for Import', async ({ page }) => {
	await mockSession(page);
	let searchBody: Record<string, unknown> | null = null;
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: {
				search: [{ id: 'openalex', name: 'OpenAlex', sorts: ['relevance', 'published', 'cited'] }],
				lookup: [{ id: 'openalex', name: 'OpenAlex' }],
				max_search_clauses: 5
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', async (route) => {
		searchBody = route.request().postDataJSON();
		return route.fulfill({
			json: {
				provider: 'openalex',
				results: [
					{
						provider: 'openalex',
						identifier_provider: 'openalex',
						identifier: 'W123',
						title: 'Candidate'
					}
				],
				total: 1,
				page: 1,
				per_page: 20
			}
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/imports/identifiers', (route) =>
		route.fulfill({ json: { id: 'batch-discovery', status: 'ready', records: [], errors: [] } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/imports/batch-discovery', (route) =>
		route.fulfill({
			json: {
				id: 'batch-discovery',
				status: 'ready',
				workflow_id: null,
				records: [
					{
						metadata: {
							id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
							type: 'Other',
							title: 'Candidate'
						}
					}
				],
				errors: []
			}
		})
	);

	await page.goto('/workspace/workspace-1/discovery');
	await page.getByRole('button', { name: 'Add condition' }).click();
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('systems');
	await page.getByPlaceholder('Another condition').fill('review');
	await page.getByRole('textbox', { name: 'From year', exact: true }).fill('2020');
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	await expect.poll(() => searchBody).toMatchObject({ year_from: 2020 });
	await expect.poll(() => (searchBody?.clauses as unknown[])?.length).toBe(2);
	await page.getByRole('button', { name: 'Review and import' }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/import\?batch=batch-discovery$/);
	await expect(page.getByText('Candidate')).toBeVisible();
});

test('discovery year calendars submit years and allow clearing an open-ended range', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: {
				search: [{ id: 'openalex', name: 'OpenAlex', sorts: ['relevance', 'published', 'cited'] }],
				lookup: [{ id: 'openalex', name: 'OpenAlex' }],
				max_search_clauses: 5
			}
		})
	);
	const requests: Array<Record<string, unknown>> = [];
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		requests.push(route.request().postDataJSON());
		return route.fulfill({
			json: { provider: 'openalex', results: [], total: 0, page: 1, per_page: 20 }
		});
	});
	await page.goto('/workspace/workspace-1/discovery');
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('systems');
	const from = page.getByRole('textbox', { name: 'From year', exact: true });
	const to = page.getByRole('textbox', { name: 'To year', exact: true });
	await from.fill('2020');
	await page.getByRole('button', { name: 'Choose date for From year', exact: true }).click();
	await page
		.getByRole('application', { name: 'Calendar for From year', exact: true })
		.getByRole('button', { name: '2021', exact: true })
		.click();
	await to.fill('2025');
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	await expect.poll(() => requests.at(-1)).toMatchObject({ year_from: 2021, year_to: 2025 });
	await from.fill('');
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	await expect.poll(() => requests.at(-1)).toMatchObject({ year_from: null, year_to: 2025 });
});
