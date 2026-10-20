import { expect, test, type Page } from '@playwright/test';
import type { components } from '../src/lib/api/schema.js';
import { directoryPage, mockSession, tagPage } from './helpers';

const items: components['schemas']['ItemSearchView'][] = Array.from({ length: 12 }, (_, index) => ({
	id: `item-${index + 1}`,
	title_html: `Reference ${index + 1}`,
	authors: [],
	publication_date: '2025',
	publication_title: 'Journal of Research',
	doi: null,
	version: 1
}));

function deferred() {
	let resolve!: () => void;
	const promise = new Promise<void>((complete) => {
		resolve = complete;
	});
	return { promise, resolve };
}

async function mockPreviewNavigation(
	page: Page,
	options: {
		beforeListRead?: (url: URL) => Promise<void>;
		failListRead?: (url: URL) => boolean;
	} = {}
) {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/*/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/*/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	const reads: URL[] = [];
	await page.route('**/api/v1/workspaces/*/items?*', async (route) => {
		const url = new URL(route.request().url());
		reads.push(url);
		await options.beforeListRead?.(url);
		if (options.failListRead?.(url))
			return route.fulfill({
				status: 500,
				json: { code: 'internal_error', message: 'Adjacent page temporarily unavailable' }
			});
		const limit = Number(url.searchParams.get('limit'));
		const offset = Number(url.searchParams.get('offset'));
		return route.fulfill({
			json: { items: items.slice(offset, offset + limit), total: items.length, limit, offset }
		});
	});
	const previews: string[] = [];
	await page.route('**/api/v1/workspaces/*/items/*/overview', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		previews.push(id);
		return route.fulfill({
			json: {
				id,
				version: 1,
				citation_key: null,
				metadata: {
					id: `urn:${id}`,
					type: 'JournalArticle',
					title: `Preview ${id}`,
					description: `Abstract for ${id}`,
					date_published: '2025'
				},
				authorization: { allowed: ['item.update'] },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				latest_revision_id: null,
				thumbnail: null,
				copy_targets: []
			}
		});
	});
	return { reads, previews };
}

function previewPanel(page: Page) {
	return page.getByRole('complementary', { name: 'Item preview', exact: true });
}

function pageTwo(url: URL) {
	return url.searchParams.get('offset') === '10';
}

async function settleResponse(page: Page, release: () => void) {
	const response = page.waitForResponse(
		(response) =>
			new URL(response.url()).pathname.endsWith('/items') && pageTwo(new URL(response.url()))
	);
	release();
	await (await response).finished();
	// Let the fetch continuation and Svelte's resulting DOM updates run before
	// asserting that an obsolete response has left navigation untouched.
	await page.evaluate(
		() =>
			new Promise<void>((resolve) =>
				requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
			)
	);
}

for (const view of ['table', 'list'] as const) {
	test(`${view} preview browses the current page with buttons and keyboard and respects the first boundary`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		await mockPreviewNavigation(page);
		await page.goto('/workspace/workspace-1/library?page_size=10&preview=item-1');
		const preview = previewPanel(page);
		const heading = preview.getByRole('heading', { name: 'Item preview', exact: true });
		const previous = preview.getByRole('button', { name: 'Previous Item', exact: true });
		const next = preview.getByRole('button', { name: 'Next Item', exact: true });
		await expect(preview).toContainText('Item 1 of 12');
		await expect(previous).toBeDisabled();
		await expect(next).toBeEnabled();
		await next.click();
		await expect(
			preview.getByRole('heading', { name: 'Preview item-2', exact: true })
		).toBeVisible();
		await expect(preview).toContainText('Item 2 of 12');
		await expect(heading).toBeFocused();
		await heading.press('j');
		await expect(page).toHaveURL(/preview=item-3$/);
		await expect(preview).toContainText('Item 3 of 12');
		await heading.press('ArrowUp');
		await expect(page).toHaveURL(/preview=item-2$/);
		await previous.click();
		await expect(page).toHaveURL(/preview=item-1$/);
		await expect(previous).toBeDisabled();
		await heading.press('k');
		await expect(page).toHaveURL(/preview=item-1$/);
		await preview.getByRole('button', { name: 'Close preview', exact: true }).click();
		await expect(preview).toHaveCount(0);
		await expect(page.locator('[data-library-item-select="item-1"]')).toBeFocused();
		await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(0);
	});

	test(`${view} preview crosses page edges in both directions and preserves submitted filters and sorting`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		const { reads } = await mockPreviewNavigation(page);
		const filters = {
			q: 'committed research',
			year: '2025',
			sort: 'author',
			direction: 'desc',
			has_files: 'true',
			author_last_name: 'Smith',
			author_first_name: '',
			publication_title: 'Journal of Research',
			page_size: '10'
		};
		await page.goto(
			`/workspace/workspace-1/library?${new URLSearchParams({ ...filters, preview: 'item-10' })}`
		);
		const preview = previewPanel(page);
		const previous = preview.getByRole('button', { name: 'Previous Item', exact: true });
		const next = preview.getByRole('button', { name: 'Next Item', exact: true });
		await expect(preview).toContainText('Item 10 of 12');
		await next.click();
		await expect(
			preview.getByRole('heading', { name: 'Preview item-11', exact: true })
		).toBeVisible();
		await expect(preview).toContainText('Item 11 of 12');
		expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({
			...filters,
			page: '2',
			preview: 'item-11'
		});
		await expect(page.locator('[data-library-item-select="item-11"]')).toBeVisible();
		await next.click();
		await expect(preview).toContainText('Item 12 of 12');
		await expect(next).toBeDisabled();
		await preview.getByRole('heading', { name: 'Item preview', exact: true }).press('ArrowDown');
		await expect(page).toHaveURL(/preview=item-12$/);
		await previous.click();
		await expect(preview).toContainText('Item 11 of 12');
		await previous.click();
		await expect(
			preview.getByRole('heading', { name: 'Preview item-10', exact: true })
		).toBeVisible();
		await expect(preview).toContainText('Item 10 of 12');
		expect(Object.fromEntries(new URL(page.url()).searchParams)).toEqual({
			...filters,
			preview: 'item-10'
		});
		expect(reads.some(pageTwo)).toBe(true);
		for (const read of reads) {
			expect(Object.fromEntries(read.searchParams)).toMatchObject({
				query: filters.q,
				year: filters.year,
				sort: filters.sort,
				direction: filters.direction,
				has_files: filters.has_files,
				author_last_name: filters.author_last_name,
				author_first_name: filters.author_first_name,
				publication_title: filters.publication_title,
				limit: '10'
			});
		}
		await preview.getByRole('button', { name: 'Close preview', exact: true }).click();
		await expect(page.locator('[data-library-item-select="item-10"]')).toBeFocused();
	});
}

test('an adjacent-page failure keeps the current preview available and Retry continues browsing', async ({
	page
}) => {
	let failing = true;
	const { reads } = await mockPreviewNavigation(page, {
		failListRead: (url) => pageTwo(url) && failing
	});
	await page.goto('/workspace/workspace-1/library?sort=title&page_size=10&preview=item-10');
	const preview = previewPanel(page);
	await expect(preview).toContainText('Item 10 of 12');
	await preview.getByRole('button', { name: 'Next Item', exact: true }).click();
	await expect(preview.getByRole('alert')).toContainText('Something went wrong. Try again.');
	await expect(
		preview.getByRole('heading', { name: 'Preview item-10', exact: true })
	).toBeVisible();
	await expect(page).toHaveURL(/sort=title&page_size=10&preview=item-10$/);
	await expect(page.locator('[data-library-item-select="item-10"]')).toBeVisible();
	const failedReads = reads.filter(pageTwo).length;
	failing = false;
	await preview.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(
		preview.getByRole('heading', { name: 'Preview item-11', exact: true })
	).toBeVisible();
	await expect(preview).toContainText('Item 11 of 12');
	await expect(preview.getByRole('alert')).toHaveCount(0);
	await expect(page).toHaveURL(/sort=title&page=2&page_size=10&preview=item-11$/);
	expect(reads.filter(pageTwo).length).toBeGreaterThan(failedReads);
});

for (const interaction of ['close', 'switch'] as const) {
	test(`a delayed adjacent-page response cannot reopen or replace a preview after ${interaction}`, async ({
		page
	}) => {
		const gate = deferred();
		const { reads, previews } = await mockPreviewNavigation(page, {
			beforeListRead: (url) => (pageTwo(url) ? gate.promise : Promise.resolve())
		});
		try {
			await page.goto('/workspace/workspace-1/library?page_size=10&preview=item-10');
			const preview = previewPanel(page);
			await expect(preview).toContainText('Item 10 of 12');
			await preview.getByRole('button', { name: 'Next Item', exact: true }).click();
			await expect.poll(() => reads.filter(pageTwo).length).toBe(1);
			await expect(preview.getByRole('button', { name: 'Next Item', exact: true })).toBeDisabled();
			await expect(
				preview.getByRole('button', { name: 'Previous Item', exact: true })
			).toBeDisabled();
			if (interaction === 'close') {
				await preview.getByRole('button', { name: 'Close preview', exact: true }).click();
				await expect(preview).toHaveCount(0);
			} else {
				await page.getByRole('button', { name: 'Preview Item 1', exact: true }).click();
				await expect(
					preview.getByRole('heading', { name: 'Preview item-1', exact: true })
				).toBeVisible();
			}
			await settleResponse(page, gate.resolve);
			expect(new URL(page.url()).searchParams.has('page')).toBe(false);
			if (interaction === 'close') {
				expect(new URL(page.url()).searchParams.has('preview')).toBe(false);
				await expect(preview).toHaveCount(0);
			} else {
				await expect(page).toHaveURL(/preview=item-1$/);
				await expect(
					preview.getByRole('heading', { name: 'Preview item-1', exact: true })
				).toBeVisible();
			}
			expect(previews).not.toContain('item-11');
		} finally {
			gate.resolve();
		}
	});
}

test('finishing cross-page browsing preserves intervening search focus and an unsubmitted draft', async ({
	page
}) => {
	const gate = deferred();
	const { reads } = await mockPreviewNavigation(page, {
		beforeListRead: (url) => (pageTwo(url) ? gate.promise : Promise.resolve())
	});
	try {
		await page.goto('/workspace/workspace-1/library?q=committed&page_size=10&preview=item-10');
		const preview = previewPanel(page);
		await expect(preview).toContainText('Item 10 of 12');
		await preview.getByRole('button', { name: 'Next Item', exact: true }).click();
		await expect.poll(() => reads.filter(pageTwo).length).toBe(1);
		const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
		await search.fill('an unsubmitted research draft');
		gate.resolve();
		await expect(
			preview.getByRole('heading', { name: 'Preview item-11', exact: true })
		).toBeVisible();
		await expect(search).toBeFocused();
		await expect(search).toHaveValue('an unsubmitted research draft');
		expect(new URL(page.url()).searchParams.get('q')).toBe('committed');
		await expect(
			preview.getByRole('heading', { name: 'Item preview', exact: true })
		).not.toBeFocused();
	} finally {
		gate.resolve();
	}
});

test('a shared preview outside the current results remains readable without a fabricated position', async ({
	page
}) => {
	const { previews } = await mockPreviewNavigation(page);
	await page.goto('/workspace/workspace-1/library?q=narrow+results&page_size=10&preview=item-99');
	const preview = previewPanel(page);
	await expect(
		preview.getByRole('heading', { name: 'Preview item-99', exact: true })
	).toBeVisible();
	await expect(preview).toContainText('Outside current results');
	await expect(preview.getByRole('button', { name: 'Previous Item', exact: true })).toBeDisabled();
	await expect(preview.getByRole('button', { name: 'Next Item', exact: true })).toBeDisabled();
	await expect(preview.getByText(/^Item \d+ of \d+$/)).toHaveCount(0);
	await preview.getByRole('heading', { name: 'Item preview', exact: true }).press('j');
	await expect(page).toHaveURL(/preview=item-99$/);
	expect(previews).toEqual(['item-99']);
	await expect(preview.getByRole('link', { name: 'Open full details', exact: true })).toBeVisible();
	await preview.getByRole('button', { name: 'Close preview', exact: true }).click();
	await expect(preview).toHaveCount(0);
	await expect(page.locator('#library-results')).toBeFocused();
});
