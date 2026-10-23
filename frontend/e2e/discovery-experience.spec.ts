import { expect, test, type Page } from '@playwright/test';
import type { components } from '../src/lib/api/schema.js';
import { directoryPage, mockSession } from './helpers';

type SearchRequest = components['schemas']['DiscoverySearchRequest'];
type Candidate = components['schemas']['CandidateView'];
type SearchPage = components['schemas']['CandidatePageView'];
type ImportBatch = components['schemas']['ImportBatchPreview'];

const discoveryPath = '/workspace/workspace-1/discovery';
const projectsPath = '/workspace/workspace-1/projects';
const batchId = '10000000-0000-4000-8000-000000000045';

async function mockDiscovery(page: Page) {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: {
				search: [
					{ id: 'openalex', name: 'OpenAlex', sorts: ['relevance', 'published', 'cited'] },
					{ id: 'arxiv', name: 'arXiv', sorts: ['relevance', 'published'] }
				],
				lookup: [
					{ id: 'crossref', name: 'Crossref', identifier_namespaces: ['doi'] },
					{ id: 'arxiv', name: 'arXiv', identifier_namespaces: ['arxiv'] }
				],
				max_search_clauses: 5,
				max_search_page_size: 100
			}
		})
	);
}

function candidates(body: SearchRequest): Candidate[] {
	return ['A', 'B', 'C'].map((letter) => ({
		provider: body.provider,
		identifier_provider: body.provider === 'arxiv' ? 'arxiv' : 'doi',
		identifier: `${body.clauses[0].term}-${body.page}-${letter}`,
		title: `${body.clauses[0].term} page ${body.page} ${letter}`,
		authors: 'A. Researcher',
		publication_title: 'Research Journal',
		publication_date: '2024',
		abstract: '<p>An abstract with <em>useful context</em> for reviewing this candidate.</p>'
	}));
}

function searchPage(body: SearchRequest, results = candidates(body)): SearchPage {
	return {
		provider: body.provider,
		results,
		total: 120,
		page: body.page,
		per_page: body.per_page
	};
}

async function mockBatch(page: Page, titles: string[]) {
	const batch: ImportBatch = {
		id: batchId,
		file_format: 'metadata',
		status: 'ready',
		workflow_id: null,
		created_at: '2026-10-22T00:00:00Z',
		committed_item_ids: [],
		records: titles.map((title, index) => ({
			is_basic: false,
			metadata: {
				id: `urn:uuid:20000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
				type: 'JournalArticle',
				title
			}
		})),
		errors: []
	};
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) =>
		route.fulfill({ json: batch })
	);
	return batch;
}

async function search(page: Page, term = 'alpha') {
	await page.getByPlaceholder('Title, author, DOI, or topic').fill(term);
	await page.getByRole('button', { name: 'Search Discovery', exact: true }).click();
	await expect(page.getByRole('heading', { name: `${term} page 1 A`, exact: true })).toBeVisible();
}

async function expectPreviewNavigation(page: Page, resultUrl: string) {
	const expected = new URL(resultUrl).searchParams;
	expected.set('batch', batchId);
	expected.set('from', 'discovery');
	await expect(page).toHaveURL(
		(url) =>
			url.pathname === '/workspace/workspace-1/import' &&
			[...expected].every(([key, value]) => url.searchParams.get(key) === value)
	);
}

test('Discovery retains selected candidates after preview failure and retries one batch in their identifier namespace', async ({
	page
}) => {
	await mockDiscovery(page);
	let searches = 0;
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		searches++;
		return route.fulfill({ json: searchPage(route.request().postDataJSON()) });
	});
	const batch = await mockBatch(page, ['alpha page 1 A', 'alpha page 1 C']);
	const previews: unknown[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/imports/identifiers', (route) => {
		previews.push(route.request().postDataJSON());
		return previews.length === 1
			? route.fulfill({ status: 503, json: { code: 'upstream_service_error' } })
			: route.fulfill({ json: batch });
	});
	await page.goto(discoveryPath);
	await search(page);
	const resultUrl = page.url();
	await page.getByRole('checkbox', { name: 'Select alpha page 1 A', exact: true }).check();
	await page.getByRole('checkbox', { name: 'Select alpha page 1 C', exact: true }).check();
	await page.getByRole('button', { name: 'Review selected', exact: true }).click();
	const failure = page.getByRole('main').getByRole('alert');
	await expect(failure).toBeVisible();
	await expect(
		page.getByRole('checkbox', { name: 'Select alpha page 1 A', exact: true })
	).toBeChecked();
	await expect(
		page.getByRole('checkbox', { name: 'Select alpha page 1 C', exact: true })
	).toBeChecked();
	await expect(page.getByRole('heading', { name: 'alpha page 1 B', exact: true })).toBeVisible();
	await expect(page).toHaveURL(resultUrl);
	await failure.getByRole('button', { name: 'Retry', exact: true }).click();
	await expectPreviewNavigation(page, resultUrl);
	await expect(page.getByRole('heading', { name: 'Import preview' })).toBeVisible();
	await expect(page.getByText('2 ready to import', { exact: true })).toBeVisible();
	expect(previews).toEqual([
		{ identifiers: ['alpha-1-A', 'alpha-1-C'], provider: 'doi' },
		{ identifiers: ['alpha-1-A', 'alpha-1-C'], provider: 'doi' }
	]);
	expect(searches).toBe(1);
});

test('Discovery restores the submitted query and page after Import navigation and a document reload', async ({
	page
}) => {
	await mockDiscovery(page);
	const requests: SearchRequest[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		const body: SearchRequest = route.request().postDataJSON();
		requests.push(body);
		return route.fulfill({ json: searchPage(body) });
	});
	const batch = await mockBatch(page, ['alpha page 2 A']);
	await page.route('**/api/v1/workspaces/workspace-1/imports/identifiers', (route) =>
		route.fulfill({ json: batch })
	);
	await page.goto(discoveryPath);
	await page.getByRole('button', { name: 'Add condition', exact: true }).click();
	await page
		.getByRole('combobox', { name: 'Search field', exact: true })
		.nth(0)
		.selectOption('title');
	await page
		.getByRole('combobox', { name: 'Boolean operator', exact: true })
		.nth(1)
		.selectOption('not');
	await page
		.getByRole('combobox', { name: 'Search field', exact: true })
		.nth(1)
		.selectOption('author');
	await page.getByPlaceholder('Another condition').fill('excluded');
	await page.getByRole('combobox', { name: 'Sort', exact: true }).selectOption('cited');
	await page.getByRole('textbox', { name: 'From year', exact: true }).fill('2020');
	await page.getByRole('textbox', { name: 'To year', exact: true }).fill('2025');
	await search(page);
	const pagination = page.getByRole('navigation', { name: 'Discovery result pages', exact: true });
	await pagination.getByRole('combobox', { name: 'Page Size', exact: true }).selectOption('50');
	await expect(pagination.getByText('Showing 1–50 of 120')).toBeVisible();
	await pagination.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'alpha page 2 A', exact: true })).toBeVisible();
	const resultUrl = page.url();
	const resultRequest = requests.at(-1);
	await page.getByRole('button', { name: 'Review and import', exact: true }).first().click();
	await expectPreviewNavigation(page, resultUrl);
	await expect(page.getByText('alpha page 2 A', { exact: true })).toBeVisible();
	await page.goBack();
	await expect(page).toHaveURL(resultUrl);
	await expect(page.getByRole('heading', { name: 'alpha page 2 A', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Review and import', exact: true }).first().click();
	await expectPreviewNavigation(page, resultUrl);
	await page.getByRole('button', { name: 'Back to Discovery', exact: true }).click();
	await expect(page).toHaveURL(resultUrl);
	await page.reload();
	await expect(page.getByRole('heading', { name: 'alpha page 2 A', exact: true })).toBeVisible();
	await expect(page).toHaveURL(resultUrl);
	await expect(page.getByPlaceholder('Title, author, DOI, or topic')).toHaveValue('alpha');
	await expect(page.getByPlaceholder('Another condition')).toHaveValue('excluded');
	await expect(page.getByRole('combobox', { name: 'Provider', exact: true })).toHaveValue(
		'openalex'
	);
	await expect(page.getByRole('combobox', { name: 'Sort', exact: true })).toHaveValue('cited');
	await expect(
		page.getByRole('combobox', { name: 'Search field', exact: true }).nth(0)
	).toHaveValue('title');
	await expect(
		page.getByRole('combobox', { name: 'Boolean operator', exact: true }).nth(1)
	).toHaveValue('not');
	await expect(
		page.getByRole('combobox', { name: 'Search field', exact: true }).nth(1)
	).toHaveValue('author');
	await expect(page.getByRole('textbox', { name: 'From year', exact: true })).toHaveValue('2020');
	await expect(page.getByRole('textbox', { name: 'To year', exact: true })).toHaveValue('2025');
	await expect(pagination.getByRole('combobox', { name: 'Page Size', exact: true })).toHaveValue(
		'50'
	);
	await expect(pagination.getByText('Showing 51–100 of 120')).toBeVisible();
	expect(requests.at(-1)).toEqual(resultRequest);
});

test('Discovery history restores successful searches while pagination preserves an edited draft and clears selection', async ({
	page
}) => {
	await mockDiscovery(page);
	const requests: SearchRequest[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		const body: SearchRequest = route.request().postDataJSON();
		requests.push(body);
		return route.fulfill({ json: searchPage(body) });
	});
	await page.goto(discoveryPath);
	await search(page);
	const alphaUrl = page.url();
	await page.getByRole('button', { name: 'Select this page', exact: true }).click();
	await expect(
		page.getByRole('checkbox', { name: 'Select alpha page 1 A', exact: true })
	).toBeChecked();
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('draft');
	await page.getByRole('combobox', { name: 'Provider', exact: true }).selectOption('arxiv');
	const pagination = page.getByRole('navigation', { name: 'Discovery result pages', exact: true });
	await pagination.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'alpha page 2 A', exact: true })).toBeVisible();
	await expect(page.getByPlaceholder('Title, author, DOI, or topic')).toHaveValue('draft');
	await expect(page.getByRole('combobox', { name: 'Provider', exact: true })).toHaveValue('arxiv');
	await expect(
		page.getByRole('checkbox', { name: 'Select alpha page 2 A', exact: true })
	).not.toBeChecked();
	await expect(page.getByRole('button', { name: 'Review selected', exact: true })).toBeDisabled();
	expect(requests.at(-1)).toMatchObject({
		provider: 'openalex',
		clauses: [{ term: 'alpha' }],
		page: 2
	});
	const alphaPageTwoUrl = page.url();
	await search(page, 'beta');
	const betaUrl = page.url();
	await page.goBack();
	await expect(page).toHaveURL(alphaPageTwoUrl);
	await expect(page.getByRole('heading', { name: 'alpha page 2 A', exact: true })).toBeVisible();
	await expect(page.getByPlaceholder('Title, author, DOI, or topic')).toHaveValue('alpha');
	await page.goBack();
	await expect(page).toHaveURL(alphaUrl);
	await expect(page.getByRole('heading', { name: 'alpha page 1 A', exact: true })).toBeVisible();
	await page.goForward();
	await expect(page).toHaveURL(alphaPageTwoUrl);
	await expect(page.getByRole('heading', { name: 'alpha page 2 A', exact: true })).toBeVisible();
	await page.goForward();
	await expect(page).toHaveURL(betaUrl);
	await expect(page.getByRole('heading', { name: 'beta page 1 A', exact: true })).toBeVisible();
	await expect(page.getByRole('combobox', { name: 'Provider', exact: true })).toHaveValue('arxiv');
});

test('Discovery search failure keeps its successful URL, results and selection, and Retry uses the failed request', async ({
	page
}) => {
	await mockDiscovery(page);
	const requests: SearchRequest[] = [];
	let rejectBeta = true;
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		const body: SearchRequest = route.request().postDataJSON();
		requests.push(body);
		return body.clauses[0].term === 'beta' && rejectBeta
			? route.fulfill({ status: 503, json: { code: 'upstream_service_error' } })
			: route.fulfill({ json: searchPage(body) });
	});
	await page.goto(discoveryPath);
	await search(page);
	const resultUrl = page.url();
	await page.getByRole('checkbox', { name: 'Select alpha page 1 A', exact: true }).check();
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('beta');
	await page.getByRole('button', { name: 'Search Discovery', exact: true }).click();
	const failure = page.getByRole('main').getByRole('alert');
	await expect(failure).toBeVisible();
	await expect(page).toHaveURL(resultUrl);
	await expect(page.getByRole('heading', { name: 'alpha page 1 A', exact: true })).toBeVisible();
	await expect(
		page.getByRole('checkbox', { name: 'Select alpha page 1 A', exact: true })
	).toBeChecked();
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('gamma');
	rejectBeta = false;
	await failure.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'beta page 1 A', exact: true })).toBeVisible();
	await expect(page.getByPlaceholder('Title, author, DOI, or topic')).toHaveValue('gamma');
	await expect(
		page.getByRole('checkbox', { name: 'Select beta page 1 A', exact: true })
	).not.toBeChecked();
	await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
	expect(requests.map((body) => body.clauses[0].term)).toEqual(['alpha', 'beta', 'beta']);
});

test('Discovery resumes only the latest search submitted while offline', async ({ page }) => {
	await mockDiscovery(page);
	const requests: SearchRequest[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		const body: SearchRequest = route.request().postDataJSON();
		requests.push(body);
		return route.fulfill({ json: searchPage(body) });
	});
	await page.goto(discoveryPath);
	await search(page);
	const successfulUrl = page.url();
	const term = page.getByPlaceholder('Title, author, DOI, or topic');
	const submit = page.getByRole('button', { name: 'Search Discovery', exact: true });
	const failure = page.getByRole('main').getByRole('alert');
	try {
		await page.context().setOffline(true);
		await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
		// Drive TanStack's online manager explicitly as well as the browser transport.
		await page.evaluate(() => window.dispatchEvent(new Event('offline')));
		await term.fill('beta');
		await submit.click();
		await expect(failure.getByRole('button', { name: 'Retry', exact: true })).toBeEnabled();
		await expect(submit).toBeEnabled();
		await expect(page).toHaveURL(successfulUrl);
		await expect(page.getByRole('heading', { name: 'alpha page 1 A', exact: true })).toBeVisible();
		expect(requests.map((body) => body.clauses[0].term)).toEqual(['alpha']);
		await term.fill('gamma');
		await submit.click();
		await expect(failure.getByRole('button', { name: 'Retry', exact: true })).toBeEnabled();
		await expect(submit).toBeEnabled();
		await expect(page).toHaveURL(successfulUrl);
		expect(requests.map((body) => body.clauses[0].term)).toEqual(['alpha']);
		await page.context().setOffline(false);
		await page.evaluate(() => window.dispatchEvent(new Event('online')));
		await expect(page.getByRole('heading', { name: 'gamma page 1 A', exact: true })).toBeVisible();
		await expect(page).toHaveURL((url) => {
			const clauses = JSON.parse(url.searchParams.get('clause') ?? '[]');
			return url.pathname === discoveryPath && clauses[0]?.term === 'gamma';
		});
		await expect(term).toHaveValue('gamma');
		await expect(page.getByRole('heading', { name: 'beta page 1 A', exact: true })).toHaveCount(0);
		await expect(failure).toHaveCount(0);
		expect(requests.map((body) => body.clauses[0].term)).toEqual(['alpha', 'gamma']);
	} finally {
		await page.context().setOffline(false);
		await page.evaluate(() => window.dispatchEvent(new Event('online')));
	}
});

test('Discovery distinguishes an empty search from the initial state and exposes expandable abstracts and plain-text selection labels', async ({
	page
}) => {
	await mockDiscovery(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		const body: SearchRequest = route.request().postDataJSON();
		const found = candidates(body);
		found[0].title = '<em>alpha</em> page 1 A';
		return route.fulfill({
			json:
				body.clauses[0].term === 'empty'
					? { ...searchPage(body, []), total: 0 }
					: searchPage(body, found)
		});
	});
	await page.goto(discoveryPath);
	await expect(page.getByText('Search results will appear here.', { exact: true })).toBeVisible();
	await expect(page.getByText('No candidates found', { exact: true })).toHaveCount(0);
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('empty');
	await page.getByRole('button', { name: 'Search Discovery', exact: true }).click();
	await expect(page.getByText('No candidates found', { exact: true })).toBeVisible();
	await expect(page.getByText('Search results will appear here.', { exact: true })).toHaveCount(0);
	await search(page);
	const first = page
		.getByRole('article')
		.filter({ has: page.getByRole('heading', { name: 'alpha page 1 A', exact: true }) });
	await first.getByRole('checkbox', { name: 'Select alpha page 1 A', exact: true }).check();
	const expand = first.getByRole('button', { name: 'Show abstract', exact: true });
	const abstract = first.locator(`[id="${await expand.getAttribute('aria-controls')}"]`);
	await expect(expand).toHaveAttribute('aria-expanded', 'false');
	await expect(abstract).toHaveClass(/line-clamp-3/);
	await expand.click();
	const collapse = first.getByRole('button', { name: 'Hide abstract', exact: true });
	await expect(collapse).toHaveAttribute('aria-expanded', 'true');
	await expect(abstract).toContainText(
		'An abstract with useful context for reviewing this candidate.'
	);
	await expect(abstract).not.toHaveClass(/line-clamp-3/);
	await collapse.click();
	await expect(first.getByRole('button', { name: 'Show abstract', exact: true })).toHaveAttribute(
		'aria-expanded',
		'false'
	);
	await expect(abstract).toHaveClass(/line-clamp-3/);
	await page.getByRole('button', { name: 'Clear selection', exact: true }).click();
	await expect(
		first.getByRole('checkbox', { name: 'Select alpha page 1 A', exact: true })
	).not.toBeChecked();
	await expect(page.getByRole('button', { name: 'Review selected', exact: true })).toBeDisabled();
});

test('Discovery can show 100 candidates but keeps a bulk preview within one explicit 50-candidate selection', async ({
	page
}) => {
	test.setTimeout(60_000);
	await mockDiscovery(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		const body: SearchRequest = route.request().postDataJSON();
		return route.fulfill({
			json: {
				...searchPage(
					body,
					Array.from({ length: body.per_page }, (_, index) => ({
						provider: body.provider,
						identifier_provider: 'doi',
						identifier: `10.1000/candidate-${index + 1}`,
						title: index === 0 ? 'alpha page 1 A' : `Candidate ${index + 1}`
					}))
				),
				total: 100
			}
		});
	});
	const batch = await mockBatch(
		page,
		Array.from({ length: 50 }, (_, index) => `Candidate ${index + 2}`)
	);
	const previews: unknown[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/imports/identifiers', (route) => {
		previews.push(route.request().postDataJSON());
		return route.fulfill({ json: batch });
	});
	await page.goto(discoveryPath);
	await search(page);
	const pagination = page.getByRole('navigation', { name: 'Discovery result pages', exact: true });
	await pagination.getByRole('combobox', { name: 'Page Size', exact: true }).selectOption('100');
	await expect(page.getByRole('article')).toHaveCount(100);
	await expect(page.getByRole('button', { name: 'Select this page', exact: true })).toBeDisabled();
	await expect(
		page.getByText('Select up to 50 candidates for one import preview.', { exact: true })
	).toBeVisible();
	const selection = page.getByRole('article').getByRole('checkbox');
	for (let index = 0; index < 50; index++) await selection.nth(index).check();
	await expect(page.locator('article input[type="checkbox"]:checked')).toHaveCount(50);
	await expect(selection.nth(50)).toBeDisabled();
	await expect(selection.nth(0)).toBeEnabled();
	await selection.nth(0).uncheck();
	await expect(selection.nth(50)).toBeEnabled();
	await selection.nth(50).check();
	await expect(page.locator('article input[type="checkbox"]:checked')).toHaveCount(50);
	const resultUrl = page.url();
	await page.getByRole('button', { name: 'Review selected', exact: true }).click();
	await expectPreviewNavigation(page, resultUrl);
	await expect(page.getByText('50 ready to import', { exact: true })).toBeVisible();
	expect(previews).toEqual([
		{
			provider: 'doi',
			identifiers: Array.from({ length: 50 }, (_, index) => `10.1000/candidate-${index + 2}`)
		}
	]);
});

for (const operation of ['search', 'preview'] as const) {
	test(`a late Discovery ${operation} response cannot navigate away from another page`, async ({
		page
	}) => {
		await mockDiscovery(page);
		await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
			route.fulfill({ json: directoryPage([], route) })
		);
		const started = Promise.withResolvers<void>();
		const release = Promise.withResolvers<void>();
		const responded = Promise.withResolvers<void>();
		await page.route('**/api/v1/workspaces/workspace-1/discovery/search', async (route) => {
			const body: SearchRequest = route.request().postDataJSON();
			if (operation === 'search' && body.clauses[0].term === 'slow') {
				started.resolve();
				await release.promise;
				await route.fulfill({ json: searchPage(body) });
				responded.resolve();
				return;
			}
			return route.fulfill({ json: searchPage(body) });
		});
		const batch = await mockBatch(page, ['alpha page 1 A']);
		await page.route('**/api/v1/workspaces/workspace-1/imports/identifiers', async (route) => {
			started.resolve();
			await release.promise;
			await route.fulfill({ json: batch });
			responded.resolve();
		});
		try {
			await page.goto(discoveryPath);
			await search(page);
			if (operation === 'search') {
				await page.getByPlaceholder('Title, author, DOI, or topic').fill('slow');
				await page.getByRole('button', { name: 'Search Discovery', exact: true }).click();
			} else {
				await page.getByRole('button', { name: 'Review and import', exact: true }).first().click();
			}
			await started.promise;
			await page.getByRole('link', { name: 'Projects', exact: true }).first().click();
			await expect(page).toHaveURL(projectsPath);
			await expect(
				page.getByRole('heading', { name: 'Projects', exact: true, level: 1 })
			).toBeVisible();
			release.resolve();
			await responded.promise;
			await page.evaluate(
				() =>
					new Promise<void>((resolve) =>
						requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
					)
			);
			await expect(page).toHaveURL(projectsPath);
			await expect(
				page.getByRole('heading', { name: 'Projects', exact: true, level: 1 })
			).toBeVisible();
		} finally {
			release.resolve();
		}
	});
}
