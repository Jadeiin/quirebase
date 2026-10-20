import { expect, test, type Page } from '@playwright/test';
import { chooseSearchOption, directoryPage, mockSession, tagPage } from './helpers';

async function mockLibrary(page: Page, editableProject = true, itemCount = 26) {
	await mockSession(page);
	const items = Array.from({ length: itemCount }, (_, index) => ({
		id: `item-${index}`,
		title_html: `Library Item ${index}`,
		authors: [],
		publication_date: null,
		publication_title: null,
		doi: null,
		version: 1
	}));
	const projects = ['project-1', 'project-2'].map((id, index) => ({
		id,
		name: `Reading Project ${index + 1}`,
		item_count: items.length,
		state: 'active',
		participation: 'workspace',
		is_participating: true,
		allowed_participation_changes: [],
		authorization: { allowed: editableProject ? ['project_item.manage'] : [] }
	}));
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: directoryPage(projects, route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-*', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-1);
		return route.fulfill({
			json: { ...projects.find((project) => project.id === id), active_participants: [] }
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({
			json: tagPage(
				[
					{
						id: 'tag-methods',
						name: 'Methods',
						accessible_item_count: items.length,
						authorization: { allowed: ['tag.use'] }
					}
				],
				route
			)
		})
	);
	const removed = new Set<string>();
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const query = new URL(route.request().url()).searchParams;
		const filtered = query.has('project') || query.has('tag');
		return route.fulfill({
			json: directoryPage(
				items.filter((item) => !filtered || !removed.has(item.id)),
				route
			)
		});
	});
	return { removed, items };
}

async function mockPreviewBulkRemoval(page: Page, itemCount: number) {
	const { removed, items } = await mockLibrary(page, true, itemCount);
	await page.route('**/api/v1/workspaces/workspace-1/items/*/overview', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		return route.fulfill({
			json: {
				id,
				version: 1,
				citation_key: null,
				metadata: {
					id: `urn:${id}`,
					type: 'JournalArticle',
					title: `Preview ${id}`
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
	const requests: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		const body = route.request().postDataJSON();
		requests.push(body);
		for (const id of body.item_ids) removed.add(id);
		return route.fulfill({ json: { ok: true } });
	});
	return { requests, removed, items };
}

test('Tag removal requires an existing Tag ID and keeps adding and removing targets separate', async ({
	page
}) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await mockLibrary(page);
	const requests: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		requests.push(route.request().postDataJSON());
		return requests.length === 1
			? route.fulfill({
					status: 500,
					json: { code: 'internal_error', message: 'Temporary failure' }
				})
			: route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/library');
	await page.locator('[data-library-item-select="item-0"]').check();
	const toolbar = page.getByRole('region', { name: 'Bulk actions', exact: true });
	const action = toolbar.getByRole('combobox', { name: 'Bulk action', exact: true });
	const apply = toolbar.getByRole('button', { name: 'Apply', exact: true });
	await expect(action.locator('option[value="remove_project"]')).toHaveCount(0);
	await action.selectOption('add_tag');
	await toolbar.getByRole('combobox', { name: 'Select Tag', exact: true }).fill('New taxonomy');
	await page.keyboard.press('Escape');
	await action.selectOption('remove_tag');
	await expect(apply).toBeDisabled();
	await expect(apply).toHaveAccessibleDescription('Choose a Tag to continue.');
	const tag = toolbar.getByRole('combobox', { name: 'Select Tag', exact: true });
	await tag.fill('New taxonomy');
	await expect(page.getByText('No matching options.', { exact: true })).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(apply).toBeDisabled();
	await chooseSearchOption(page, 'Select Tag', 'Methods');
	await action.selectOption('add_tag');
	await expect(toolbar.getByRole('combobox', { name: 'Select Tag', exact: true })).toHaveValue(
		'New taxonomy'
	);
	await action.selectOption('remove_tag');
	await expect(toolbar.getByRole('combobox', { name: 'Select Tag', exact: true })).toHaveValue(
		'Methods'
	);
	await apply.click();
	await expect(page.getByRole('alert')).toBeVisible();
	await expect(page.locator('[data-library-item-select="item-0"]')).toBeChecked();
	await apply.click();
	await expect(toolbar).toHaveCount(0);
	await expect(page.locator('#library-results')).toBeFocused();
	expect(requests).toEqual([
		{
			action: 'remove_tag',
			item_ids: ['item-0'],
			tag_id: 'tag-methods',
			tag_name: '',
			confirmation: ''
		},
		{
			action: 'remove_tag',
			item_ids: ['item-0'],
			tag_id: 'tag-methods',
			tag_name: '',
			confirmation: ''
		}
	]);
});

test('removing from the current Project confirms destructive context while preserving canonical Items', async ({
	page
}) => {
	const { removed } = await mockLibrary(page);
	const requests: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		const body = route.request().postDataJSON();
		requests.push(body);
		for (const id of body.item_ids) removed.add(id);
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/library?project=project-1');
	await page.locator('[data-library-item-select="item-0"]').check();
	const action = page.getByRole('combobox', { name: 'Bulk action', exact: true });
	await action.selectOption('remove_project');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	const dialog = page.getByRole('dialog', {
		name: 'Remove the selected Items from Reading Project 1?'
	});
	await expect(dialog).toContainText(
		'This permanently deletes their Annotations and Replies in this Project.'
	);
	await expect(dialog).toContainText(
		'Items, files, private Annotations, and other Projects are preserved.'
	);
	expect(requests).toEqual([]);
	await dialog.getByRole('button', { name: 'Remove from Project', exact: true }).click();
	await expect(dialog).toHaveCount(0);
	await expect(page.locator('[data-library-item-select="item-0"]')).toHaveCount(0);
	await expect(page.locator('[data-library-item-select="item-1"]')).toBeVisible();
	await expect(page.locator('#library-results')).toBeFocused();
	expect(requests).toEqual([
		{
			action: 'remove_project',
			item_ids: ['item-0'],
			project_id: 'project-1',
			tag_name: '',
			confirmation: 'remove_project'
		}
	]);
	await page.goto('/workspace/workspace-1/library');
	await expect(page.locator('[data-library-item-select="item-0"]')).toBeVisible();
});

test('Project-removal retry retains the original Project and Items after browser navigation', async ({
	page
}) => {
	await mockLibrary(page);
	const release = Promise.withResolvers<void>();
	const requests: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', async (route) => {
		requests.push(route.request().postDataJSON());
		if (requests.length === 1) {
			await release.promise;
			return route.fulfill({
				status: 500,
				json: { code: 'internal_error', message: 'Temporary failure' }
			});
		}
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/library?project=project-2');
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await chooseSearchOption(page, 'Project', 'Reading Project 1');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page).toHaveURL(/project=project-1/);
	await page.getByRole('button', { name: 'Next page', exact: true }).click();
	await page.locator('[data-library-item-select="item-25"]').check();
	await page
		.getByRole('combobox', { name: 'Bulk action', exact: true })
		.selectOption('remove_project');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	const dialog = page.getByRole('dialog');
	await dialog.getByRole('button', { name: 'Remove from Project', exact: true }).click();
	try {
		await expect.poll(() => requests.length).toBe(1);
		await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeDisabled();
		await page.goBack();
		await page.goBack();
		await expect(page).toHaveURL(/project=project-2/);
	} finally {
		release.resolve();
	}
	await expect(dialog.getByRole('alert')).toBeVisible();
	await expect(dialog).toContainText('Reading Project 1');
	await dialog.getByRole('button', { name: 'Remove from Project', exact: true }).click();
	await expect(dialog).toHaveCount(0);
	await expect(page).toHaveURL(/project=project-2/);
	expect(requests).toEqual([
		{
			action: 'remove_project',
			item_ids: ['item-25'],
			project_id: 'project-1',
			tag_name: '',
			confirmation: 'remove_project'
		},
		{
			action: 'remove_project',
			item_ids: ['item-25'],
			project_id: 'project-1',
			tag_name: '',
			confirmation: 'remove_project'
		}
	]);
});

test('Tag-removal completion preserves a newer selection and search focus', async ({ page }) => {
	await mockLibrary(page);
	const release = Promise.withResolvers<void>();
	let requested = false;
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', async (route) => {
		requested = true;
		await release.promise;
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/library');
	await page.locator('[data-library-item-select="item-0"]').check();
	await page.getByRole('combobox', { name: 'Bulk action', exact: true }).selectOption('remove_tag');
	await chooseSearchOption(page, 'Select Tag', 'Methods');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	try {
		await expect.poll(() => requested).toBe(true);
		await page.getByRole('button', { name: 'Clear selection', exact: true }).click();
		await page.locator('[data-library-item-select="item-1"]').check();
		await search.fill('continue typing');
	} finally {
		release.resolve();
	}
	await expect(page.getByText('Bulk action completed', { exact: true })).toBeVisible();
	await expect(page.locator('[data-library-item-select="item-1"]')).toBeChecked();
	await expect(page.locator('[data-library-item-select="item-0"]')).not.toBeChecked();
	await expect(search).toBeFocused();
	await expect(search).toHaveValue('continue typing');
});

test('a read-only current Project does not offer bulk removal', async ({ page }) => {
	await mockLibrary(page, false);
	await page.goto('/workspace/workspace-1/library?project=project-1');
	await page.locator('[data-library-item-select="item-0"]').check();
	const action = page.getByRole('combobox', { name: 'Bulk action', exact: true });
	await expect(action.locator('option[value="remove_project"]')).toHaveCount(0);
	await expect(action.locator('option[value="remove_tag"]')).toHaveCount(1);
});

for (const scenario of [
	{
		name: 'keeps Previous available for the surviving result before a removed final preview',
		itemCount: 3,
		previewId: 'item-2',
		removedIds: ['item-0', 'item-2'],
		direction: 'Previous Item',
		destinationId: 'item-1'
	},
	{
		name: 'uses the real successor when earlier rows and the preview disappear together',
		itemCount: 6,
		previewId: 'item-4',
		removedIds: ['item-0', 'item-2', 'item-4'],
		direction: 'Next Item',
		destinationId: 'item-5'
	}
]) {
	test(`bulk Tag removal ${scenario.name}`, async ({ page }) => {
		const { requests } = await mockPreviewBulkRemoval(page, scenario.itemCount);
		await page.goto(`/workspace/workspace-1/library?tag=tag-methods&preview=${scenario.previewId}`);
		const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
		await expect(preview).toContainText(`Preview ${scenario.previewId}`);
		for (const id of scenario.removedIds) {
			await page.locator(`[data-library-item-select="${id}"]`).check();
		}
		await page
			.getByRole('combobox', { name: 'Bulk action', exact: true })
			.selectOption('remove_tag');
		await chooseSearchOption(page, 'Select Tag', 'Methods');
		await page.getByRole('button', { name: 'Apply', exact: true }).click();
		for (const id of scenario.removedIds) {
			await expect(page.locator(`[data-library-item-select="${id}"]`)).toHaveCount(0);
		}
		await expect(preview).toContainText('Outside current results');
		await expect(preview).toContainText(`Preview ${scenario.previewId}`);
		const browse = preview.getByRole('button', { name: scenario.direction, exact: true });
		await expect(browse).toBeEnabled();
		await browse.click();
		await expect
			.poll(() => new URL(page.url()).searchParams.get('preview'))
			.toBe(scenario.destinationId);
		await expect(preview).toContainText(`Preview ${scenario.destinationId}`);
		expect(requests).toMatchObject([
			{ action: 'remove_tag', item_ids: scenario.removedIds, tag_id: 'tag-methods' }
		]);
	});
}

test('bulk Project removal keeps Previous on the current page after multiple earlier rows disappear', async ({
	page
}) => {
	const { requests } = await mockPreviewBulkRemoval(page, 16);
	await page.goto(
		'/workspace/workspace-1/library?project=project-1&page_size=10&page=2&preview=item-14'
	);
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await expect(preview).toContainText('Preview item-14');
	for (const id of ['item-10', 'item-12', 'item-14']) {
		await page.locator(`[data-library-item-select="${id}"]`).check();
	}
	await page
		.getByRole('combobox', { name: 'Bulk action', exact: true })
		.selectOption('remove_project');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	await page
		.getByRole('dialog', { name: 'Remove the selected Items from Reading Project 1?' })
		.getByRole('button', { name: 'Remove from Project', exact: true })
		.click();
	await expect(page.locator('[data-library-item-select="item-14"]')).toHaveCount(0);
	await expect(page.locator('[data-library-item-select="item-13"]')).toBeVisible();
	await expect(preview).toContainText('Outside current results');
	await preview.getByRole('button', { name: 'Previous Item', exact: true }).click();
	await expect.poll(() => new URL(page.url()).searchParams.get('preview')).toBe('item-13');
	await expect.poll(() => new URL(page.url()).searchParams.get('page')).toBe('2');
	await expect(preview).toContainText('Preview item-13');
	await expect(preview).toContainText('Item 12 of 13');
	expect(requests).toMatchObject([
		{
			action: 'remove_project',
			item_ids: ['item-10', 'item-12', 'item-14'],
			project_id: 'project-1',
			confirmation: 'remove_project'
		}
	]);
});

test('bulk removal preserves the final preview position while the clamped page refreshes an older shorter cache', async ({
	page
}) => {
	const { requests, removed, items } = await mockPreviewBulkRemoval(page, 11);
	let itemCount = 11;
	let clampedPageWaiting = false;
	const releaseClampedPage = Promise.withResolvers<void>();
	await page.route('**/api/v1/workspaces/workspace-1/items?*', async (route) => {
		const params = new URL(route.request().url()).searchParams;
		if (removed.has('item-10') && params.get('offset') === '0') {
			clampedPageWaiting = true;
			await releaseClampedPage.promise;
		}
		return route.fulfill({
			json: directoryPage(
				items.slice(0, itemCount).filter((item) => !removed.has(item.id)),
				route
			)
		});
	});
	await page.goto(
		'/workspace/workspace-1/library?tag=tag-methods&page_size=10&page=2&preview=item-10'
	);
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await expect(preview).toContainText('Preview item-10');
	await expect(page.locator('[data-library-item-select="item-10"]')).toBeVisible();

	// Cache a shorter first page, then restore the original server results before
	// returning to page two through the browser's existing navigation history.
	itemCount = 2;
	await page.getByRole('button', { name: 'Previous page', exact: true }).click();
	await expect.poll(() => new URL(page.url()).searchParams.get('page')).toBe(null);
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	itemCount = 11;
	await page.goBack();
	await expect.poll(() => new URL(page.url()).searchParams.get('page')).toBe('2');
	await page.locator('[data-library-item-select="item-10"]').check();
	await page.getByRole('combobox', { name: 'Bulk action', exact: true }).selectOption('remove_tag');
	await chooseSearchOption(page, 'Select Tag', 'Methods');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	try {
		await expect.poll(() => clampedPageWaiting).toBe(true);
		await expect.poll(() => new URL(page.url()).searchParams.get('page')).toBe(null);
		await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
		await expect(preview).toContainText('Preview item-10');
	} finally {
		releaseClampedPage.resolve();
	}
	await expect(page.locator('[data-library-item-select="item-9"]')).toBeVisible();
	await expect(preview).toContainText('Outside current results');
	const previous = preview.getByRole('button', { name: 'Previous Item', exact: true });
	await expect(previous).toBeEnabled();
	await previous.click();
	await expect.poll(() => new URL(page.url()).searchParams.get('preview')).toBe('item-9');
	await expect(preview).toContainText('Item 10 of 10');
	expect(requests).toMatchObject([
		{ action: 'remove_tag', item_ids: ['item-10'], tag_id: 'tag-methods' }
	]);
});
