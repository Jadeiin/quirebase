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
						publication_date: '2026',
						imported: false
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
						title: 'Candidate',
						imported: false
					}
				],
				total: 1,
				page: 1,
				per_page: 20
			}
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/imports/identifier', (route) =>
		route.fulfill({ json: { id: 'batch-discovery', status: 'ready', records: [], errors: [] } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/imports/batch-discovery', (route) =>
		route.fulfill({
			json: {
				id: 'batch-discovery',
				status: 'ready',
				workflow_id: null,
				records: [{ metadata: { title: 'Candidate', authors: [] } }],
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
