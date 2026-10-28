import { expect, test, type Page } from '@playwright/test';
import { mockSession, tagPage, directoryPage } from './helpers';

const metadata = {
	id: 'urn:test:filters',
	type: 'JournalArticle',
	title: 'Filter navigation',
	date_published: '2024-06-15',
	container: { title: 'Journal & 特刊; 50%_' },
	contributors: [
		{ type: 'Person', person: { family_name: 'Smith', given_name: 'Jane' }, roles: ['Author'] },
		{ type: 'Organization', organization: { name: '研究 Council & Co.' }, roles: ['Author'] }
	],
	subjects: [{ subject: 'Graph; theory & ML' }]
};

async function setup(page: Page) {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/filter-item/overview', (route) =>
		route.fulfill({
			json: {
				id: 'filter-item',
				version: 1,
				metadata,
				citation_key: null,
				authorization: { allowed: [] },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [{ id: 'tag-1', name: 'Methods & 方法' }],
				latest_revision_id: null,
				copy_targets: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({
			json: tagPage(
				[
					{
						id: 'tag-1',
						name: 'Methods & 方法',
						accessible_item_count: 26,
						authorization: { allowed: [] }
					}
				],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	const requests: URLSearchParams[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		requests.push(new URL(route.request().url()).searchParams);
		return route.fulfill({
			json: {
				items: [
					{
						id: 'filter-item',
						title_html: metadata.title,
						authors: [{ full_name: 'Jane Smith', last_name: 'Smith', first_name: 'Jane' }],
						publication_date: '2024',
						publication_title: metadata.container.title,
						doi: null,
						version: 1
					}
				],
				total: 26,
				limit: 25,
				offset: Number(requests.at(-1)?.get('offset') ?? 0)
			}
		});
	});
	return requests;
}

const targets = [
	{
		label: 'Jane Smith',
		expected: { authors: JSON.stringify([{ last_name: 'Smith', first_name: 'Jane' }]) }
	},
	{
		label: '研究 Council & Co.',
		expected: { authors: JSON.stringify([{ last_name: '研究 Council & Co.', first_name: '' }]) }
	},
	{ label: metadata.container.title, expected: { publication_title: metadata.container.title } },
	{ label: metadata.date_published, expected: { year: '2024' } },
	{ label: 'Journal article', expected: { reference_type: 'JournalArticle' } },
	{ label: 'Methods & 方法', expected: { tag: 'tag-1' } },
	{ label: 'Graph; theory & ML', expected: { keyword_exact: 'Graph; theory & ML' } }
];

for (const target of targets) {
	test(`Item field ${target.label} opens its exact Workspace filter`, async ({ page }) => {
		const requests = await setup(page);
		await page.goto('/workspace/workspace-1/item/filter-item?q=old&project=old&page=4');
		const links = page.getByRole('link', { name: target.label, exact: true });
		await expect(links.first()).toBeVisible();
		const hrefs = await links.evaluateAll((elements) =>
			elements.map((element) => element.getAttribute('href'))
		);
		expect(hrefs.length).toBeGreaterThan(0);
		expect(new Set(hrefs).size).toBe(1);
		await links.first().click();
		await expect(page).toHaveURL(/\/workspace\/workspace-1\/library\?/);
		expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual(target.expected);
		await expect
			.poll(() => Object.fromEntries(requests.at(-1) ?? []))
			.toMatchObject(target.expected);
		await expect(page.getByRole('button', { name: /^Remove filter / })).toHaveCount(1);
		await page.reload();
		await expect(page.getByRole('button', { name: /^Remove filter / })).toHaveCount(1);
		await page.getByRole('button', { name: /^Remove filter / }).click();
		await expect(page).toHaveURL('/workspace/workspace-1/library');
	});
}

test('exact filters survive search, pagination and browser history without applying unsaved input', async ({
	page
}) => {
	const requests = await setup(page);
	await page.goto(
		'/workspace/workspace-1/library?authors=%5B%7B%22last_name%22%3A%22Ada%22%2C%22first_name%22%3A%22%22%7D%5D&keyword_exact=Graph%3B+theory&publication_title=Journal&has_files=false'
	);
	const input = page.getByPlaceholder('Search title, author, Tag, or full text');
	await input.fill('applied search');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect.poll(() => requests.at(-1)?.get('query')).toBe('applied search');
	await input.fill('unsaved search');
	await page.getByRole('button', { name: 'Next page' }).click();
	await expect(page).toHaveURL(/page=2/);
	await expect.poll(() => requests.at(-1)?.get('query')).toBe('applied search');
	expect(JSON.parse(requests.at(-1)?.get('authors') ?? '[]')[0]?.first_name).toBe('');
	expect(requests.at(-1)?.get('keyword_exact')).toBe('Graph; theory');
	expect(requests.at(-1)?.get('has_files')).toBe('false');
	await page.getByRole('button', { name: 'Remove filter Author: Ada', exact: true }).click();
	await expect.poll(() => new URL(page.url()).searchParams.has('authors')).toBe(false);
	expect(new URL(page.url()).searchParams.has('authors')).toBe(false);
	expect(new URL(page.url()).searchParams.has('page')).toBe(false);
	await page.goBack();
	await expect(
		page.getByRole('button', { name: 'Remove filter Author: Ada', exact: true })
	).toBeVisible();
	await page.goForward();
	await expect(
		page.getByRole('button', { name: 'Remove filter Author: Ada', exact: true })
	).toHaveCount(0);
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
	await expect(page).toHaveURL('/workspace/workspace-1/library');
});
