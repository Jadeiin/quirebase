import { expect, test, type Page } from '@playwright/test';
import { mockSession, tagPage, directoryPage } from './helpers';

const metadata = {
	id: 'https://doi.org/10.1000/filters',
	type: 'JournalArticle',
	title: 'Filter navigation',
	date_published: '2024-06-15',
	container: { title: 'Journal & 特刊; 50%_', license: { id: 'CC-BY-4.0' } },
	license: { id: 'CC-BY-NC-4.0', title: 'CC BY-NC 4.0' },
	identifiers: [
		{ identifier_type: 'DOI', identifier: '10.1000/filters' },
		{ identifier_type: 'arXiv', identifier: '2601.12345v2' },
		{ identifier_type: 'Other', scheme: 'OpenAlex', identifier: 'W12345' },
		{ identifier_type: 'PMID', identifier: '42' }
	],
	contributors: [
		{
			type: 'Person',
			person: {
				family_name: 'Smith',
				given_name: 'Jane',
				id: 'https://orcid.org/0000-0002-1825-0097',
				affiliations: [
					{
						name: 'Research University',
						identifier: 'https://ror.org/03yrm5c26',
						identifier_type: 'ROR'
					}
				]
			},
			roles: ['Author']
		},
		{ type: 'Person', person: { name: 'Ada' }, roles: ['Author'] },
		{
			type: 'Organization',
			person: { name: 'Inactive person', id: 'https://orcid.org/0000-0002-1694-233X' },
			organization: { name: '研究 Council & Co.' },
			roles: ['Author']
		}
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

test('an author ORCID opens separately while the name keeps its Library filter', async ({
	page
}) => {
	await setup(page);
	await page.goto('/workspace/workspace-1/item/filter-item');
	const header = page
		.locator('header')
		.filter({ has: page.getByRole('heading', { name: metadata.title }) });
	const orcid = header.getByRole('link', {
		name: "View Jane Smith's ORCID (opens in a new tab)",
		exact: true
	});
	await expect(orcid).toBeVisible();
	await expect(header.getByRole('link', { name: /ORCID/ })).toHaveCount(1);
	await expect(orcid).toHaveAttribute('href', 'https://orcid.org/0000-0002-1825-0097');
	await expect(orcid).toHaveAttribute('rel', 'external noopener noreferrer');
	await expect(orcid.locator('img')).toBeVisible();
	await expect(header.getByRole('link', { name: 'Ada', exact: true })).toBeVisible();

	// Fulfill the external page locally; the icon and its link need no external service.
	await page
		.context()
		.route('https://orcid.org/**', (route) =>
			route.fulfill({ contentType: 'text/html', body: '<title>ORCID record</title>' })
		);
	await orcid.focus();
	const popupOpened = page.waitForEvent('popup');
	await page.keyboard.press('Enter');
	const popup = await popupOpened;
	await expect(popup).toHaveURL('https://orcid.org/0000-0002-1825-0097');
	await expect(page).toHaveURL('/workspace/workspace-1/item/filter-item');
	await popup.close();
	await header.getByRole('link', { name: 'Jane Smith', exact: true }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/library\?authors=/);
});

test('scholarly identifiers and affiliations expose local icons and correctly scoped external links', async ({
	page
}) => {
	await setup(page);
	const externalRequests: string[] = [];
	page.on('request', (request) => {
		const url = new URL(request.url());
		if (['http:', 'https:'].includes(url.protocol) && url.hostname !== '127.0.0.1')
			externalRequests.push(url.href);
	});
	await page.goto('/workspace/workspace-1/item/filter-item');
	for (const [label, href] of [
		['DOI: 10.1000/filters', 'https://doi.org/10.1000/filters'],
		['arXiv: 2601.12345v2', 'https://arxiv.org/abs/2601.12345v2'],
		['OpenAlex: W12345', 'https://openalex.org/W12345'],
		['PMID: 42', 'https://pubmed.ncbi.nlm.nih.gov/42'],
		['ROR: https://ror.org/03yrm5c26', 'https://ror.org/03yrm5c26'],
		['CC BY-NC 4.0', 'https://creativecommons.org/licenses/by-nc/4.0/'],
		['CC-BY-4.0', 'https://creativecommons.org/licenses/by/4.0/']
	]) {
		const link = page.getByRole('link', { name: label, exact: true });
		await expect(link).toHaveCount(1);
		await expect(link).toHaveAttribute('href', href);
		await expect(link).toHaveAttribute('target', '_blank');
		await expect(link.locator('img, svg')).toBeVisible();
	}
	await expect(page.getByText('Research University', { exact: true })).toBeVisible();
	await expect(page.getByText('Publication license', { exact: true })).toBeVisible();
	await expect(page.getByText('Open access', { exact: true })).toHaveCount(0);
	for (const width of [390, 1280]) {
		await page.setViewportSize({ width, height: 900 });
		expect(
			await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
		).toBe(true);
	}
	const images = page.locator('a img[aria-hidden="true"]');
	await expect(images).toHaveCount(5);
	await expect
		.poll(() =>
			images.evaluateAll((nodes) =>
				nodes.every((node) => (node as HTMLImageElement).naturalWidth > 0)
			)
		)
		.toBe(true);
	await page.evaluate(() => localStorage.setItem('quirebase:theme', 'dark'));
	await page.reload();
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect(images.first()).toHaveCSS('filter', 'invert(1)');
	expect(externalRequests).toEqual([]);
});

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
