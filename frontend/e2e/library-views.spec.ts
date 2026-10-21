import { expect, test, type Locator, type Page } from '@playwright/test';
import { directoryPage, mockSession, tagPage } from './helpers';

const libraryPath = '/workspace/workspace-1/library';
const facets = {
	authors: [
		{
			last_name: 'Research & Council',
			first_name: null,
			full_name: 'Research & Council',
			item_count: 6
		},
		{ last_name: 'Smith', first_name: 'Ada', full_name: 'Ada Smith', item_count: 5 },
		{ last_name: 'Chen', first_name: 'Li', full_name: '陈丽', item_count: 4 },
		{ last_name: 'García', first_name: 'Ana', full_name: 'Ana García', item_count: 3 },
		{ last_name: 'Jones', first_name: 'Sam', full_name: 'Sam Jones', item_count: 2 },
		{
			last_name: 'Visible after expansion',
			first_name: null,
			full_name: 'Visible after expansion',
			item_count: 1
		}
	],
	keywords: [
		{ value: ' graph; theory & ML ', item_count: 6 },
		{ value: 'Search', item_count: 4 }
	],
	reference_types: [
		{ value: 'JournalArticle', item_count: 5 },
		{ value: 'Book', item_count: 5 }
	]
};

async function mockLibraryViews(page: Page) {
	await mockSession(page);
	const items = Array.from({ length: 30 }, (_, index) => ({
		id: `item-${index + 1}`,
		title_html: `Reading Item ${String(index + 1).padStart(2, '0')}`,
		authors: [],
		publication_date: '2025',
		publication_title: null,
		doi: null,
		version: 1
	}));
	const itemReads: URL[] = [];
	await page.route('**/api/v1/workspaces/*/items?*', (route) => {
		itemReads.push(new URL(route.request().url()));
		return route.fulfill({ json: directoryPage(items, route) });
	});
	await page.route('**/api/v1/workspaces/*/tags?*', (route) =>
		route.fulfill({
			json: tagPage(
				[
					{
						id: 'tag-1',
						name: 'Methods',
						accessible_item_count: 30,
						authorization: { allowed: ['tag.use'] }
					}
				],
				route
			)
		})
	);
	const project = {
		id: 'project-1',
		name: 'Reading Project',
		description: '',
		item_count: 30,
		state: 'active',
		participation: 'workspace',
		is_participating: true,
		allowed_participation_changes: [],
		authorization: { allowed: ['project_item.manage'] },
		active_participants: []
	};
	await page.route('**/api/v1/workspaces/*/projects?*', (route) =>
		route.fulfill({ json: directoryPage([project], route) })
	);
	await page.route('**/api/v1/workspaces/*/projects/project-1', (route) =>
		route.fulfill({ json: project })
	);
	await page.route('**/api/v1/workspaces/*/items/*/overview', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		return route.fulfill({
			json: {
				id,
				version: 1,
				citation_key: null,
				metadata: { id: `urn:${id}`, type: 'JournalArticle', title: `Preview ${id}` },
				authorization: { allowed: [] },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				latest_revision_id: null,
				thumbnail: null,
				copy_targets: []
			}
		});
	});
	const facetReads: URL[] = [];
	await page.route(/\/api\/v1\/workspaces\/[^/]+\/items\/facets(?:\?.*)?$/, (route) => {
		facetReads.push(new URL(route.request().url()));
		return route.fulfill({ json: facets });
	});
	return { itemReads, facetReads };
}

async function openViews(page: Page) {
	const dialog = page.getByRole('dialog', { name: 'Saved views', exact: true });
	if (!(await dialog.isVisible()))
		await page.getByRole('button', { name: 'Saved views', exact: true }).click();
	await expect(dialog).toBeVisible();
	return dialog;
}

async function saveView(page: Page, name: string) {
	const dialog = await openViews(page);
	await dialog.getByRole('textbox', { name: 'View name', exact: true }).fill(name);
	await dialog.getByRole('button', { name: 'Save current view', exact: true }).click();
	return openViews(page);
}

async function linkParameters(link: Locator, page: Page) {
	return new URL((await link.getAttribute('href'))!, page.url()).searchParams;
}

async function holdSavedViewsLock(page: Page) {
	await page.evaluate(async () => {
		let acquired!: () => void;
		const ready = new Promise<void>((resolve) => (acquired = resolve));
		void navigator.locks.request(
			'quirebase:library-views:user-1:workspace-1',
			() =>
				new Promise<void>((resolve) => {
					(window as Window & { releaseSavedViewsLock?: () => void }).releaseSavedViewsLock =
						resolve;
					acquired();
				})
		);
		await ready;
	});
}

async function releaseSavedViewsLock(page: Page) {
	await page.evaluate(() => {
		(window as Window & { releaseSavedViewsLock?: () => void }).releaseSavedViewsLock?.();
	});
}

async function expectQueuedViewUpdates(page: Page, count: number) {
	await expect
		.poll(() =>
			page.evaluate(async () => {
				const { pending } = await navigator.locks.query();
				return pending?.filter(({ name }) => name === 'quirebase:library-views:user-1:workspace-1')
					.length;
			})
		)
		.toBe(count);
}

test('refinement values load on demand from submitted filters and expand without another request', async ({
	page
}) => {
	const { facetReads } = await mockLibraryViews(page);
	await page.goto(`${libraryPath}?q=committed&project=project-1&sort=title&page=2&page_size=10`);
	await expect(page.locator('[data-library-item-select="item-11"]')).toBeVisible();
	expect(facetReads).toEqual([]);
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const refinements = page.getByRole('region', { name: 'Refine current results', exact: true });
	const authors = refinements.getByRole('group', { name: 'Author', exact: true });
	await expect(authors.getByRole('link')).toHaveCount(5);
	await expect(
		authors.getByRole('link', { name: 'Research & Council 6', exact: true })
	).toBeVisible();
	expect(facetReads).toHaveLength(1);
	expect(Object.fromEntries(facetReads[0].searchParams)).toEqual({
		query: 'committed',
		project: 'project-1',
		limit: '10',
		offset: '10',
		sort: 'title',
		direction: 'asc'
	});
	await authors.getByRole('button', { name: 'Show more Author', exact: true }).click();
	await expect(
		authors.getByRole('link', { name: 'Visible after expansion 1', exact: true })
	).toBeVisible();
	await authors.getByRole('button', { name: 'Show less Author', exact: true }).click();
	await expect(authors.getByRole('link')).toHaveCount(5);
	await page.getByRole('textbox', { name: 'Library Search', exact: true }).fill('draft search');
	await page.getByRole('textbox', { name: 'Contributor', exact: true }).fill('draft contributor');
	await page.getByRole('textbox', { name: 'Keyword', exact: true }).fill('draft keyword');
	await page.evaluate(
		() =>
			new Promise<void>((resolve) =>
				requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
			)
	);
	expect(facetReads).toHaveLength(1);
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect.poll(() => facetReads.at(-1)?.searchParams.get('query')).toBe('draft search');
	expect(facetReads.at(-1)?.searchParams.get('author')).toBe('draft contributor');
	expect(facetReads.at(-1)?.searchParams.get('keyword')).toBe('draft keyword');
});

test('refinements follow the displayed Item page, page size and sorting', async ({ page }) => {
	const { itemReads, facetReads } = await mockLibraryViews(page);
	await page.route(/\/api\/v1\/workspaces\/[^/]+\/items\/facets(?:\?.*)?$/, (route) => {
		const url = new URL(route.request().url());
		facetReads.push(url);
		const label = `Author for ${url.searchParams.get('offset') ?? '0'} ${url.searchParams.get('limit')} ${url.searchParams.get('sort') ?? 'updated'} ${url.searchParams.get('direction') ?? 'default'}`;
		return route.fulfill({
			json: {
				authors: [{ last_name: label, first_name: null, full_name: label, item_count: 1 }],
				keywords: [],
				reference_types: []
			}
		});
	});
	await page.goto(`${libraryPath}?project=project-1&page_size=10`);
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const refinements = page.getByRole('region', { name: 'Refine current results', exact: true });
	await expect(
		refinements.getByRole('link', { name: 'Author for 0 10 updated desc 1', exact: true })
	).toBeVisible();
	await expect(page.locator('[data-library-item-select]')).toHaveCount(10);
	expect(facetReads).toHaveLength(1);
	expect(Object.fromEntries(facetReads[0].searchParams)).toEqual({
		project: 'project-1',
		limit: '10',
		offset: '0',
		sort: 'updated',
		direction: 'desc'
	});

	await page.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.locator('[data-library-item-select="item-11"]')).toBeVisible();
	await expect(
		refinements.getByRole('link', { name: 'Author for 10 10 updated desc 1', exact: true })
	).toBeVisible();
	await page.getByRole('combobox', { name: 'Page Size', exact: true }).selectOption('20');
	await expect(page.locator('[data-library-item-select]')).toHaveCount(20);
	await expect(
		refinements.getByRole('link', { name: 'Author for 0 20 updated desc 1', exact: true })
	).toBeVisible();
	await page.getByRole('combobox', { name: 'Sort By', exact: true }).selectOption('author');
	await expect.poll(() => itemReads.at(-1)?.searchParams.get('sort')).toBe('author');
	await expect(
		refinements.getByRole('link', { name: 'Author for 0 20 author asc 1', exact: true })
	).toBeVisible();
	await page.locator('#library-sort-direction').click();
	await expect.poll(() => itemReads.at(-1)?.searchParams.get('direction')).toBe('desc');
	await expect(
		refinements.getByRole('link', { name: 'Author for 0 20 author desc 1', exact: true })
	).toBeVisible();
	expect(facetReads).toHaveLength(5);
});

test('author refinements and applied chips retain the credited display name and raw exact values', async ({
	page
}) => {
	const { facetReads } = await mockLibraryViews(page);
	await page.route(/\/api\/v1\/workspaces\/[^/]+\/items\/facets(?:\?.*)?$/, (route) => {
		facetReads.push(new URL(route.request().url()));
		return route.fulfill({
			json: {
				authors: [{ last_name: 'Chen', first_name: 'Li', full_name: '陈丽', item_count: 1 }],
				keywords: [],
				reference_types: []
			}
		});
	});
	await page.route('**/api/v1/workspaces/*/items?*', (route) =>
		route.fulfill({
			json: directoryPage(
				[
					{
						id: 'item-1',
						title_html: 'Names in original order',
						authors: [{ last_name: 'Chen', first_name: 'Li', full_name: '陈丽' }],
						publication_date: null,
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				route
			)
		})
	);
	await page.goto(`${libraryPath}?author_last_name=Chen&author_first_name=Li&preview=item-1`);
	const applied = page.getByRole('group', { name: 'Applied filters', exact: true });
	await expect(
		applied.getByRole('button', { name: 'Remove filter Author: 陈丽', exact: true })
	).toBeVisible();
	expect(facetReads).toHaveLength(0);
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const authors = page
		.getByRole('region', { name: 'Refine current results', exact: true })
		.getByRole('group', { name: 'Author', exact: true });
	const credited = authors.getByRole('link', { name: '陈丽 1', exact: true });
	await expect(credited).toBeVisible();
	const parameters = await linkParameters(credited, page);
	expect(parameters.get('author_last_name')).toBe('Chen');
	expect(parameters.get('author_first_name')).toBe('Li');
	expect(parameters.get('preview')).toBe('item-1');
});

test('native refinement links replace broad criteria with exact values while preserving the Library scope', async ({
	page
}) => {
	const { itemReads } = await mockLibraryViews(page);
	const initial = {
		q: 'reading',
		tag: 'tag-1',
		project: 'project-1',
		author: 'broad author',
		keyword: 'graph',
		sort: 'author',
		direction: 'desc',
		has_files: 'false',
		page: '3',
		page_size: '10',
		preview: 'item-21'
	};
	await page.goto(`${libraryPath}?${new URLSearchParams(initial)}`);
	await expect(page.locator('#library-preview')).toContainText('Preview item-21');
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const refinements = page.getByRole('region', { name: 'Refine current results', exact: true });
	const author = refinements
		.getByRole('group', { name: 'Author', exact: true })
		.getByRole('link', { name: 'Research & Council 6', exact: true });
	const authorParameters = await linkParameters(author, page);
	expect(authorParameters.get('author_last_name')).toBe('Research & Council');
	expect(authorParameters.has('author_first_name')).toBe(true);
	expect(authorParameters.get('author_first_name')).toBe('');
	expect(authorParameters.has('author')).toBe(false);
	expect(authorParameters.has('page')).toBe(false);
	expect(authorParameters.get('preview')).toBe('item-21');
	await author.click();
	await expect(page).toHaveURL(`${libraryPath}?${authorParameters}`);
	const keyword = refinements
		.getByRole('group', { name: 'Keyword', exact: true })
		.getByRole('link', { name: 'graph; theory & ML 6', exact: true });
	const keywordParameters = await linkParameters(keyword, page);
	expect(keywordParameters.get('keyword_exact')).toBe(' graph; theory & ML ');
	expect(keywordParameters.has('keyword')).toBe(false);
	expect(keywordParameters.get('preview')).toBe('item-21');
	await keyword.click();
	await expect(page).toHaveURL(`${libraryPath}?${keywordParameters}`);
	const type = refinements
		.getByRole('group', { name: 'Type', exact: true })
		.locator('a[href*="reference_type=JournalArticle"]');
	await type.click();
	await expect
		.poll(() => Object.fromEntries(new URL(page.url()).searchParams))
		.toEqual({
			q: 'reading',
			tag: 'tag-1',
			project: 'project-1',
			sort: 'author',
			direction: 'desc',
			has_files: 'false',
			page_size: '10',
			preview: 'item-21',
			author_last_name: 'Research & Council',
			author_first_name: '',
			keyword_exact: ' graph; theory & ML ',
			reference_type: 'JournalArticle'
		});
	await expect(page.locator('#library-preview')).toContainText('Preview item-21');
	await expect
		.poll(() => itemReads.at(-1)?.searchParams.get('reference_type'))
		.toBe('JournalArticle');
	expect(itemReads.at(-1)?.searchParams.get('author_first_name')).toBe('');
	expect(itemReads.at(-1)?.searchParams.has('author')).toBe(false);
	expect(itemReads.at(-1)?.searchParams.has('keyword')).toBe(false);
	expect(itemReads.at(-1)?.searchParams.get('offset')).toBe('0');
});

test('Search and Files chips remove applied criteria and clear selection without dropping other filters', async ({
	page
}) => {
	const { itemReads } = await mockLibraryViews(page);
	await page.goto(
		`${libraryPath}?q=committed+search&project=project-1&sort=title&has_files=false&page=2&page_size=10`
	);
	await page.locator('[data-library-item-select="item-11"]').check();
	await page
		.getByRole('textbox', { name: 'Library Search', exact: true })
		.fill('unsubmitted search');
	const applied = page.getByRole('group', { name: 'Applied filters', exact: true });
	await applied
		.getByRole('button', { name: 'Remove filter Search: committed search', exact: true })
		.click();
	await expect(page).toHaveURL(
		`${libraryPath}?project=project-1&sort=title&has_files=false&page_size=10`
	);
	await expect(page.getByRole('textbox', { name: 'Library Search', exact: true })).toHaveValue('');
	await expect(page.getByRole('region', { name: 'Bulk actions', exact: true })).toHaveCount(0);
	await applied
		.getByRole('button', { name: 'Remove filter Files: Without files', exact: true })
		.click();
	await expect(page).toHaveURL(`${libraryPath}?project=project-1&sort=title&page_size=10`);
	await expect(
		applied.getByRole('link', { name: 'Project: Reading Project', exact: true })
	).toBeVisible();
	await expect.poll(() => itemReads.at(-1)?.searchParams.has('has_files')).toBe(false);
	expect(itemReads.at(-1)?.searchParams.get('project')).toBe('project-1');
});

test('saved views persist submitted filters, open native links, rename and delete after reload', async ({
	page
}) => {
	await mockLibraryViews(page);
	const filters = {
		q: 'committed search',
		project: 'project-1',
		sort: 'author',
		direction: 'desc',
		author_last_name: 'Research & Council',
		author_first_name: '',
		keyword_exact: ' graph; theory & ML ',
		has_files: 'false',
		page_size: '10'
	};
	await page.goto(
		`${libraryPath}?${new URLSearchParams({ ...filters, page: '2', preview: 'item-11' })}#library-item-item-11`
	);
	await page.getByRole('textbox', { name: 'Library Search', exact: true }).fill('unsaved draft');
	let dialog = await saveView(page, 'Reading queue');
	let view = dialog.getByRole('link', { name: 'Reading queue', exact: true });
	const destination = new URL((await view.getAttribute('href'))!, page.url());
	expect(destination.pathname).toBe(libraryPath);
	expect(Object.fromEntries(destination.searchParams)).toEqual(filters);
	expect(destination.hash).toBe('');
	await page.keyboard.press('Escape');
	await page.reload();
	dialog = await openViews(page);
	view = dialog.getByRole('link', { name: 'Reading queue', exact: true });
	await view.click();
	await expect(dialog).toHaveCount(0);
	await expect(page).toHaveURL(destination.href);
	await expect(page.getByRole('textbox', { name: 'Library Search', exact: true })).toHaveValue(
		'committed search'
	);
	dialog = await openViews(page);
	const row = dialog.getByRole('group', { name: 'Reading queue', exact: true });
	await row.getByRole('button', { name: 'Rename Reading queue', exact: true }).click();
	await row.getByRole('textbox', { name: 'New name', exact: true }).fill('Reviewed queue');
	await row.getByRole('button', { name: 'Save name', exact: true }).click();
	await expect(dialog.getByRole('link', { name: 'Reading queue', exact: true })).toHaveCount(0);
	await expect(dialog.getByRole('link', { name: 'Reviewed queue', exact: true })).toHaveAttribute(
		'href',
		`${destination.pathname}${destination.search}`
	);
	await page.keyboard.press('Escape');
	await page.reload();
	dialog = await openViews(page);
	await dialog.getByRole('button', { name: 'Delete Reviewed queue', exact: true }).click();
	await expect(dialog.getByRole('link', { name: 'Reviewed queue', exact: true })).toHaveCount(0);
	await page.keyboard.press('Escape');
	await page.reload();
	dialog = await openViews(page);
	await expect(dialog.getByRole('link', { name: 'Reviewed queue', exact: true })).toHaveCount(0);
});

test('saved views stay separate for each Workspace and signed-in user', async ({ page }) => {
	await mockLibraryViews(page);
	await page.goto(`${libraryPath}?q=Workspace+one`);
	let dialog = await saveView(page, 'Reading queue');
	await expect(dialog.getByRole('link', { name: 'Reading queue', exact: true })).toBeVisible();
	await page.keyboard.press('Escape');
	await page.goto('/workspace/workspace-2/library?q=Workspace+two');
	dialog = await openViews(page);
	await expect(dialog.getByRole('link', { name: 'Reading queue', exact: true })).toHaveCount(0);
	dialog = await saveView(page, 'Reading queue');
	await expect(dialog.getByRole('link', { name: 'Reading queue', exact: true })).toHaveAttribute(
		'href',
		'/workspace/workspace-2/library?q=Workspace+two'
	);
	await page.keyboard.press('Escape');
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: { authenticated: true, user: { id: 'user-2', username: 'another', role: 'member' } }
		})
	);
	await page.reload();
	dialog = await openViews(page);
	await expect(dialog.getByRole('link', { name: 'Reading queue', exact: true })).toHaveCount(0);
	await page.keyboard.press('Escape');
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: { authenticated: true, user: { id: 'user-1', username: 'reader', role: 'member' } }
		})
	);
	await page.reload();
	dialog = await openViews(page);
	await expect(dialog.getByRole('link', { name: 'Reading queue', exact: true })).toHaveAttribute(
		'href',
		'/workspace/workspace-2/library?q=Workspace+two'
	);
	await page.keyboard.press('Escape');
	await page.goto(libraryPath);
	dialog = await openViews(page);
	await expect(dialog.getByRole('link', { name: 'Reading queue', exact: true })).toHaveAttribute(
		'href',
		`${libraryPath}?q=Workspace+one`
	);
});

test('saved-view updates from two tabs wait for one lock and preserve concurrent saves, renames and deletions', async ({
	page,
	context
}) => {
	const other = await context.newPage();
	try {
		await mockLibraryViews(page);
		await mockLibraryViews(other);
		await page.goto(`${libraryPath}?q=first`);
		await other.goto(`${libraryPath}?q=second`);
		const firstDialog = await openViews(page);
		const secondDialog = await openViews(other);
		await firstDialog.getByRole('textbox', { name: 'View name', exact: true }).fill('First view');
		await secondDialog.getByRole('textbox', { name: 'View name', exact: true }).fill('Second view');
		await holdSavedViewsLock(page);
		await Promise.all([
			firstDialog.getByRole('button', { name: 'Save current view', exact: true }).click(),
			secondDialog.getByRole('button', { name: 'Save current view', exact: true }).click()
		]);
		await expectQueuedViewUpdates(page, 2);
		await expect(firstDialog.getByText('View saved', { exact: true })).toHaveCount(0);
		await expect(secondDialog.getByText('View saved', { exact: true })).toHaveCount(0);
		await releaseSavedViewsLock(page);
		for (const dialog of [firstDialog, secondDialog]) {
			await expect(dialog.getByRole('link', { name: 'First view', exact: true })).toHaveAttribute(
				'href',
				`${libraryPath}?q=first`
			);
			await expect(dialog.getByRole('link', { name: 'Second view', exact: true })).toHaveAttribute(
				'href',
				`${libraryPath}?q=second`
			);
		}
		await firstDialog.getByRole('button', { name: 'Rename First view', exact: true }).click();
		await firstDialog.getByRole('textbox', { name: 'New name', exact: true }).fill('Renamed first');
		await holdSavedViewsLock(page);
		await Promise.all([
			firstDialog.getByRole('button', { name: 'Save name', exact: true }).click(),
			secondDialog.getByRole('button', { name: 'Delete Second view', exact: true }).click()
		]);
		await expectQueuedViewUpdates(page, 2);
		await releaseSavedViewsLock(page);
		for (const dialog of [firstDialog, secondDialog]) {
			await expect(
				dialog.getByRole('link', { name: 'Renamed first', exact: true })
			).toHaveAttribute('href', `${libraryPath}?q=first`);
			await expect(dialog.getByRole('link', { name: 'First view', exact: true })).toHaveCount(0);
			await expect(dialog.getByRole('link', { name: 'Second view', exact: true })).toHaveCount(0);
		}
	} finally {
		await releaseSavedViewsLock(page);
		await other.close();
	}
});

test('a queued save settles after reopening without clearing the new name or taking focus', async ({
	page
}) => {
	await mockLibraryViews(page);
	await page.goto(`${libraryPath}?q=reading`);
	let dialog = await openViews(page);
	await dialog.getByRole('textbox', { name: 'View name', exact: true }).fill('Queued view');
	await holdSavedViewsLock(page);
	try {
		await dialog.getByRole('button', { name: 'Save current view', exact: true }).click();
		await expectQueuedViewUpdates(page, 1);
		await page.keyboard.press('Escape');
		await expect(dialog).toHaveCount(0);
		dialog = await openViews(page);
		const name = dialog.getByRole('textbox', { name: 'View name', exact: true });
		await name.fill('New draft');
		await releaseSavedViewsLock(page);
		await expect(dialog.getByRole('link', { name: 'Queued view', exact: true })).toHaveAttribute(
			'href',
			`${libraryPath}?q=reading`
		);
		await expect(name).toHaveValue('New draft');
		await expect(name).toBeFocused();
		await expect(dialog.getByText('View saved', { exact: true })).toHaveCount(0);
	} finally {
		await releaseSavedViewsLock(page);
	}
});

test('failed refinement reads expose a local retry and preserve unsubmitted search text', async ({
	page
}) => {
	await mockLibraryViews(page);
	let failing = true;
	await page.route(/\/api\/v1\/workspaces\/[^/]+\/items\/facets(?:\?.*)?$/, (route) =>
		route.fulfill(failing ? { status: 503, json: { code: 'internal_error' } } : { json: facets })
	);
	await page.goto(libraryPath);
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const refinements = page.getByRole('region', { name: 'Refine current results', exact: true });
	await expect(refinements.getByRole('alert')).toContainText('Unable to load filter values.');
	await expect(refinements.getByRole('link')).toHaveCount(0);
	await expect(refinements.getByText('No values on this page.', { exact: true })).toHaveCount(0);
	await page.getByRole('textbox', { name: 'Library Search', exact: true }).fill('keep this draft');
	failing = false;
	await refinements.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(
		refinements.getByRole('link', { name: 'Research & Council 6', exact: true })
	).toBeVisible();
	await expect(refinements.getByRole('alert')).toHaveCount(0);
	await expect(page.getByRole('textbox', { name: 'Library Search', exact: true })).toHaveValue(
		'keep this draft'
	);
	await expect(page).toHaveURL(libraryPath);
});

test('authoritative Project denial purges earlier refinement snapshots before a failed history return', async ({
	page
}) => {
	await mockLibraryViews(page);
	await page.goto(`${libraryPath}?project=project-1`);
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const refinements = page.getByRole('region', { name: 'Refine current results', exact: true });
	const author = refinements.getByRole('link', { name: 'Research & Council 6', exact: true });
	await expect(author).toBeVisible();
	const denied = (url: string) => new URL(url).searchParams.has('author_last_name');
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({
			status: denied(route.request().url()) ? 404 : 503,
			json: { code: denied(route.request().url()) ? 'not_found' : 'internal_error' }
		})
	);
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/items\/facets(?:\?.*)?$/, (route) =>
		route.fulfill({
			status: denied(route.request().url()) ? 404 : 503,
			json: { code: denied(route.request().url()) ? 'not_found' : 'internal_error' }
		})
	);
	await author.click();
	await expect(refinements.getByRole('alert')).toContainText('Unable to load filter values.');
	await expect(refinements.getByRole('link')).toHaveCount(0);
	await expect(page.locator('[data-library-item-select]')).toHaveCount(0);
	await page.goBack();
	await expect(page).toHaveURL(`${libraryPath}?project=project-1`);
	await expect(refinements.getByRole('alert')).toContainText('Unable to load filter values.');
	await expect(refinements.getByRole('link')).toHaveCount(0);
	await expect(page.locator('[data-library-item-select]')).toHaveCount(0);
	await expect(page.getByText('No Items found.', { exact: true })).toHaveCount(0);
});

test('a saved-view storage failure preserves its draft and can be retried after storage recovers', async ({
	page
}) => {
	await mockLibraryViews(page);
	await page.goto(`${libraryPath}?q=reading`);
	await page.evaluate(() => {
		const original = Storage.prototype.setItem;
		Storage.prototype.setItem = function (key, value) {
			if (key.startsWith('quirebase:library-views:'))
				throw new DOMException('Test storage is full', 'QuotaExceededError');
			return original.call(this, key, value);
		};
		(window as Window & { restoreLibraryViewStorage?: () => void }).restoreLibraryViewStorage =
			() => {
				Storage.prototype.setItem = original;
			};
	});
	const dialog = await openViews(page);
	const name = dialog.getByRole('textbox', { name: 'View name', exact: true });
	await name.fill('Keep this view name');
	await dialog.getByRole('button', { name: 'Save current view', exact: true }).click();
	await expect(dialog.getByRole('alert')).toHaveText('Unable to update saved views.');
	await expect(name).toHaveValue('Keep this view name');
	await expect(dialog.getByText('View saved', { exact: true })).toHaveCount(0);
	await expect(dialog.getByRole('link', { name: 'Keep this view name', exact: true })).toHaveCount(
		0
	);
	await page.evaluate(() => {
		(window as Window & { restoreLibraryViewStorage?: () => void }).restoreLibraryViewStorage?.();
	});
	await dialog.getByRole('button', { name: 'Save current view', exact: true }).click();
	await expect(
		dialog.getByRole('link', { name: 'Keep this view name', exact: true })
	).toHaveAttribute('href', `${libraryPath}?q=reading`);
	await expect(dialog.getByText('View saved', { exact: true })).toBeVisible();
	await expect(dialog.getByRole('alert')).toHaveCount(0);
	await expect(name).toHaveValue('');
});

test('saved-view keyboard editing and deletion keep useful focus and restore the opening trigger', async ({
	page
}) => {
	await mockLibraryViews(page);
	await page.goto(libraryPath);
	const trigger = page.getByRole('button', { name: 'Saved views', exact: true });
	await trigger.focus();
	await trigger.press('Enter');
	const dialog = page.getByRole('dialog', { name: 'Saved views', exact: true });
	const name = dialog.getByRole('textbox', { name: 'View name', exact: true });
	await expect(name).toBeFocused();
	await name.fill('Reading queue');
	await name.press('Enter');
	await expect(dialog.getByRole('link', { name: 'Reading queue', exact: true })).toBeVisible();
	await name.fill('Second queue');
	await name.press('Enter');
	await expect(dialog.getByRole('link', { name: 'Second queue', exact: true })).toBeVisible();
	const rename = dialog.getByRole('button', { name: 'Rename Reading queue', exact: true });
	await rename.focus();
	await rename.press('Enter');
	const newName = dialog.getByRole('textbox', { name: 'New name', exact: true });
	await expect(newName).toBeFocused();
	await expect
		.poll(() =>
			newName.evaluate((input: HTMLInputElement) => [input.selectionStart, input.selectionEnd])
		)
		.toEqual([0, 'Reading queue'.length]);
	await newName.fill('Reviewed queue');
	await newName.press('Enter');
	const renamed = dialog.getByRole('button', { name: 'Rename Reviewed queue', exact: true });
	await expect(renamed).toBeFocused();
	await renamed.press('Tab');
	const removeFirst = dialog.getByRole('button', { name: 'Delete Reviewed queue', exact: true });
	await expect(removeFirst).toBeFocused();
	await removeFirst.press('Enter');
	const second = dialog.getByRole('link', { name: 'Second queue', exact: true });
	await expect(second).toBeFocused();
	await second.press('Tab');
	await expect(
		dialog.getByRole('button', { name: 'Rename Second queue', exact: true })
	).toBeFocused();
	await page.keyboard.press('Tab');
	const removeSecond = dialog.getByRole('button', { name: 'Delete Second queue', exact: true });
	await expect(removeSecond).toBeFocused();
	await removeSecond.press('Space');
	await expect(dialog.getByRole('link')).toHaveCount(0);
	await expect(name).toBeFocused();
	await name.press('Escape');
	await expect(dialog).toHaveCount(0);
	await expect(trigger).toBeFocused();
});

test('narrow Library refinements and long saved-view names stay within the viewport', async ({
	page
}, testInfo) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await mockLibraryViews(page);
	const longAuthorName = 'International Research Council for Scientific Communication '.repeat(3);
	await page.route(/\/api\/v1\/workspaces\/[^/]+\/items\/facets(?:\?.*)?$/, (route) =>
		route.fulfill({
			json: {
				...facets,
				authors: [
					facets.authors[0],
					...Array.from({ length: 60 }, (_, index) => ({
						last_name: `Council ${index + 1}`,
						first_name: null,
						full_name: `${longAuthorName}${index + 1}`,
						item_count: 1
					}))
				]
			}
		})
	);
	await page.goto(libraryPath);
	await expect(page.getByRole('button', { name: 'Saved views', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const refinements = page.getByRole('region', { name: 'Refine current results', exact: true });
	const authors = refinements.getByRole('group', { name: 'Author', exact: true });
	const keywords = refinements.getByRole('group', { name: 'Keyword', exact: true });
	const types = refinements.getByRole('group', { name: 'Type', exact: true });
	await expect(
		authors.getByRole('link', { name: 'Research & Council 6', exact: true })
	).toBeVisible();
	const [authorBox, keywordBox, typeBox] = await Promise.all([
		authors.boundingBox(),
		keywords.boundingBox(),
		types.boundingBox()
	]);
	expect(keywordBox!.y).toBeGreaterThanOrEqual(authorBox!.y + authorBox!.height);
	expect(typeBox!.y).toBeGreaterThanOrEqual(keywordBox!.y + keywordBox!.height);
	const moreAuthors = authors.getByRole('button', { name: 'Show more Author', exact: true });
	await moreAuthors.focus();
	await moreAuthors.press('Enter');
	await expect(authors.getByRole('link')).toHaveCount(61);
	const authorList = authors.getByRole('list');
	await expect
		.poll(() =>
			authorList.evaluate(
				(list) => list.scrollHeight > list.clientHeight && list.clientHeight <= 400
			)
		)
		.toBe(true);
	const lastAuthor = authors.getByRole('link').last();
	await lastAuthor.focus();
	await expect(lastAuthor).toBeInViewport();
	await expect.poll(() => authorList.evaluate((list) => list.scrollTop)).toBeGreaterThan(0);
	await authors.getByRole('button', { name: 'Show less Author', exact: true }).click();
	await expect(authors.getByRole('link')).toHaveCount(5);
	await expect
		.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
		.toBe(true);
	await page.screenshot({ path: testInfo.outputPath('refinements-mobile.png'), fullPage: true });
	const longName = '文献阅读集'.repeat(16);
	const dialog = await saveView(page, longName);
	await expect(dialog.getByRole('link', { name: longName, exact: true })).toBeVisible();
	await expect
		.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
		.toBe(true);
	await expect
		.poll(() => dialog.evaluate((element) => element.scrollWidth <= element.clientWidth))
		.toBe(true);
	await page.screenshot({ path: testInfo.outputPath('saved-views-mobile.png'), fullPage: true });
});
