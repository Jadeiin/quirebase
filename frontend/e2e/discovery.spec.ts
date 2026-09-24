import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

test('discovery renders the flat results response contract', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({ json: [{ id: 'crossref', name: 'Crossref' }] })
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
		route.fulfill({ json: [{ id: 'openalex', name: 'OpenAlex' }] })
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
				records: [{ title: 'Candidate' }],
				errors: []
			}
		})
	);

	await page.goto('/workspace/workspace-1/discovery');
	await page.getByRole('button', { name: 'Add condition' }).click();
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('systems');
	await page.getByPlaceholder('Another condition').fill('review');
	await page.getByLabel('From year').fill('2020');
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	await expect.poll(() => searchBody).toMatchObject({ year_from: 2020 });
	await expect.poll(() => (searchBody?.clauses as unknown[])?.length).toBe(2);
	await page.getByRole('button', { name: 'Review and import' }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/import\?batch=batch-discovery$/);
	await expect(page.getByText('Candidate')).toBeVisible();
});
