import { expect, test } from '@playwright/test';
import { directoryPage, tagPage, chooseSearchOption, mockSession } from './helpers';

test('Tag filter keeps word separators while synchronizing the trimmed URL', async ({ page }) => {
	await mockSession(page);
	const tags = ['machine learning', 'machinery'].map((name, index) => ({
		id: `tag-${index}`,
		name,
		accessible_item_count: 1,
		authorization: { allowed: ['tag.manage'] }
	}));
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage(tags, route) })
	);
	await page.goto('/workspace/workspace-1/tools?tool=tags');
	const filter = page.getByPlaceholder('Filter Tags');
	await expect(page.locator('strong').filter({ hasText: /^machine learning$/ })).toBeVisible();
	await page.clock.install();
	await filter.fill('machine ');
	await page.clock.runFor(250);
	await expect(page).toHaveURL(/tag_search=machine$/);
	await expect(filter).toHaveValue('machine ');
	await filter.pressSequentially('learning');
	await page.clock.runFor(250);
	await expect
		.poll(() => new URL(page.url()).searchParams.get('tag_search'))
		.toBe('machine learning');
	await expect(filter).toHaveValue('machine learning');
	await expect(page.locator('strong').filter({ hasText: /^machine learning$/ })).toBeVisible();
	await expect(page.locator('strong').filter({ hasText: /^machinery$/ })).toHaveCount(0);

	await page.getByRole('tab', { name: 'Duplicate review', exact: true }).click();
	await page.getByRole('tab', { name: 'Manage Tags', exact: true }).click();
	await filter.fill('machinery');
	await page.clock.runFor(250);
	await expect(page).toHaveURL(/tag_search=machinery$/);
	await page.goBack();
	await expect(page.getByRole('tab', { name: 'Duplicate review', exact: true })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await page.goBack();
	await expect(filter).toHaveValue('machine learning');
});

test('returning to stale duplicate results waits for an explicit check', async ({ page }) => {
	await mockSession(page);
	let scans = 0;
	await page.route('**/api/v1/workspaces/workspace-1/duplicates*', (route) => {
		scans++;
		return route.fulfill({ json: { groups: [] } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.goto('/workspace/workspace-1/tools');
	const check = page.getByRole('button', { name: 'Check for duplicates', exact: true });
	await check.click();
	await expect(page.getByText('No duplicate groups found.', { exact: true })).toBeVisible();
	expect(scans).toBe(1);
	await page.clock.install();
	await page.getByRole('tab', { name: 'Manage Tags', exact: true }).click();
	await expect(page.getByPlaceholder('Filter Tags')).toBeVisible();
	await page.clock.fastForward(31_000);
	await page.getByRole('tab', { name: 'Duplicate review', exact: true }).click();
	await expect(check).toBeVisible();
	await page.clock.runFor(500);
	expect(scans).toBe(1);
	await expect(page.getByText('No duplicate groups found.', { exact: true })).toBeVisible();
	await check.click();
	await expect.poll(() => scans).toBe(2);
});

test('an in-flight duplicate scan stays with its submitted criteria', async ({ page }) => {
	await mockSession(page);
	const modes: string[] = [];
	const started = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	await page.route('**/api/v1/workspaces/workspace-1/duplicates*', async (route) => {
		modes.push(new URL(route.request().url()).searchParams.get('mode')!);
		if (modes.length === 1) {
			started.resolve();
			await release.promise;
		}
		return route.fulfill({ json: { groups: [] } });
	});
	await page.goto('/workspace/workspace-1/tools');
	const check = page.getByRole('button', { name: 'Check for duplicates', exact: true });
	await check.click();
	await started.promise;
	const identifier = page.getByRole('radio', { name: 'Shared identifier', exact: true });
	const title = page.getByRole('radio', { name: 'Same title', exact: true });
	await identifier.focus();
	await identifier.press('ArrowRight');
	await expect(title).toBeChecked();
	await expect(page.getByText('The match criteria changed.')).toBeVisible();
	await title.press('ArrowLeft');
	await expect(identifier).toBeChecked();
	release.resolve();
	await expect(page.getByText('No duplicate groups found.', { exact: true })).toBeVisible();
	await expect(check).toBeEnabled();
	expect(modes).toEqual(['identifier']);

	await identifier.focus();
	await identifier.press('ArrowRight');
	await expect(title).toBeChecked();
	await check.click();
	await expect(page.getByText('No duplicate groups found.', { exact: true })).toBeVisible();
	expect(modes).toEqual(['identifier', 'title']);
});

test('leaving an unfinished duplicate scan restores an idle explicit check', async ({ page }) => {
	await mockSession(page);
	let scans = 0;
	const started = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	await page.route('**/api/v1/workspaces/workspace-1/duplicates*', async (route) => {
		scans++;
		if (scans === 1) {
			started.resolve();
			await release.promise;
		}
		await route.fulfill({ json: { groups: [] } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.goto('/workspace/workspace-1/tools');
	await page.getByRole('button', { name: 'Check for duplicates', exact: true }).click();
	await started.promise;
	await page.getByRole('link', { name: 'Projects', exact: true }).click();
	await expect(page).toHaveURL(/\/projects$/);
	await page.goBack();
	const check = page.getByRole('button', { name: 'Check for duplicates', exact: true });
	await expect(check).toBeEnabled();
	await expect(page.getByText('Run a check when you are ready', { exact: true })).toBeVisible();
	expect(scans).toBe(1);
	release.resolve();
	await check.click();
	await expect(page.getByText('No duplicate groups found.', { exact: true })).toBeVisible();
	expect(scans).toBe(2);
});

for (const outcome of ['success', 'failure'] as const) {
	test(`style search edits survive a pending installation ending in ${outcome}`, async ({
		page
	}) => {
		await mockSession(page);
		const styles = [
			{ key: 'apa', name: 'APA', scope: 'builtin' },
			{ key: 'chicago', name: 'Chicago', scope: 'builtin' }
		];
		const started = Promise.withResolvers<void>();
		const release = Promise.withResolvers<void>();
		await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', async (route) => {
			if (route.request().method() === 'POST') {
				started.resolve();
				await release.promise;
				return route.fulfill(
					outcome === 'success'
						? { status: 201, json: { id: 'custom' } }
						: { status: 500, json: { code: 'internal_error' } }
				);
			}
			const query = new URL(route.request().url()).searchParams.get('query') ?? '';
			return route.fulfill({
				json: { styles: styles.filter((style) => style.name.includes(query)) }
			});
		});
		await page.goto('/workspace/workspace-1/tools?tool=citation-styles');
		await expect(page.locator('strong').filter({ hasText: /^APA$/ })).toBeVisible();
		await page.getByLabel('Style name', { exact: true }).fill('House style');
		await page.getByLabel('CSL XML', { exact: true }).fill('<style version="1.0"></style>');
		await page.getByRole('button', { name: 'Install Citation Style', exact: true }).click();
		await started.promise;
		const search = page.getByPlaceholder('Search styles', { exact: true });
		await search.fill('Chicago');
		await expect(page).toHaveURL(/style_query=Chicago/);
		await expect(search).toHaveValue('Chicago');
		await expect(page.locator('strong').filter({ hasText: /^Chicago$/ })).toBeVisible();
		await expect(page.locator('strong').filter({ hasText: /^APA$/ })).toHaveCount(0);
		release.resolve();
		await expect(
			page.getByRole('button', { name: 'Install Citation Style', exact: true })
		).toBeEnabled();
		await expect(search).toHaveValue('Chicago');
	});
}

for (const outcome of ['success', 'failure'] as const) {
	test(`Tag filter edits survive a pending merge ending in ${outcome}`, async ({ page }) => {
		await mockSession(page);
		const source = {
			id: 'source',
			name: 'Methods',
			accessible_item_count: 1,
			authorization: { allowed: ['tag.manage'] }
		};
		const target = { ...source, id: 'target', name: 'Results' };
		let tags = [source, target];
		await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
			route.fulfill({ json: tagPage(tags, route) })
		);
		const started = Promise.withResolvers<void>();
		const release = Promise.withResolvers<void>();
		await page.route('**/api/v1/workspaces/workspace-1/tags/merge', async (route) => {
			started.resolve();
			await release.promise;
			if (outcome === 'success') tags = [target];
			return route.fulfill(
				outcome === 'success'
					? { json: { ok: true } }
					: { status: 500, json: { code: 'internal_error' } }
			);
		});
		await page.goto('/workspace/workspace-1/tools?tool=tags');
		await chooseSearchOption(page, 'Source Tag', 'Methods');
		await chooseSearchOption(page, 'Target Tag', 'Results');
		await page.getByRole('button', { name: 'Merge Tags', exact: true }).click();
		await started.promise;
		await page.clock.install();
		const filter = page.getByPlaceholder('Filter Tags');
		await filter.fill('Results');
		await page.clock.runFor(250);
		await expect(page).toHaveURL(/tag_search=Results/);
		await expect(filter).toHaveValue('Results');
		await expect(page.locator('strong').filter({ hasText: /^Results$/ })).toBeVisible();
		await expect(page.locator('strong').filter({ hasText: /^Methods$/ })).toHaveCount(0);
		release.resolve();
		await expect(page.getByRole('combobox', { name: 'Source Tag', exact: true })).toBeEnabled();
		await expect(filter).toHaveValue('Results');
	});
}

for (const tool of [
	{ key: 'tags', tab: 'Manage Tags', input: 'Filter Tags', parameter: 'tag_search' },
	{
		key: 'citation-styles',
		tab: 'Citation Styles',
		input: 'Search styles',
		parameter: 'style_query'
	}
]) {
	test(`${tool.input} cancels an unpublished draft on Back and restores on Forward`, async ({
		page
	}) => {
		await mockSession(page);
		await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
			route.fulfill({ json: tagPage([], route) })
		);
		await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) =>
			route.fulfill({ json: { styles: [] } })
		);
		await page.goto('/workspace/workspace-1/tools');
		await page.getByRole('tab', { name: tool.tab, exact: true }).click();
		await expect.poll(() => new URL(page.url()).searchParams.get('tool')).toBe(tool.key);
		const input = page.getByPlaceholder(tool.input, { exact: true });
		await expect(input).toBeVisible();
		await page.clock.install();
		await input.fill('unpublished');
		await page.goBack();
		await expect(page).toHaveURL('/workspace/workspace-1/tools');
		await page.clock.runFor(500);
		expect(new URL(page.url()).searchParams.has(tool.parameter)).toBe(false);
		await expect(page.getByRole('tab', { name: 'Duplicate review', exact: true })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await page.goForward();
		await expect(input).toHaveValue('');
		expect(new URL(page.url()).searchParams.get('tool')).toBe(tool.key);
	});
}

test('style search preserves raw word separators while publishing a trimmed draft', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [] } })
	);
	await page.goto('/workspace/workspace-1/tools?tool=citation-styles');
	const input = page.getByPlaceholder('Search styles', { exact: true });
	await expect(input).toBeVisible();
	await page.clock.install();
	await input.fill('house ');
	await page.clock.runFor(250);
	await expect.poll(() => new URL(page.url()).searchParams.get('style_query')).toBe('house');
	await expect(input).toHaveValue('house ');
	await input.pressSequentially('style');
	await page.clock.runFor(250);
	await expect.poll(() => new URL(page.url()).searchParams.get('style_query')).toBe('house style');
	await expect(input).toHaveValue('house style');
});

test('a completed style installation preserves a newer form draft', async ({ page }) => {
	await mockSession(page);
	const started = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	let submitted: unknown;
	await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', async (route) => {
		if (route.request().method() === 'POST') {
			submitted = route.request().postDataJSON();
			started.resolve();
			await release.promise;
			return route.fulfill({ status: 201, json: { id: 'custom' } });
		}
		return route.fulfill({ json: { styles: [] } });
	});
	await page.goto('/workspace/workspace-1/tools?tool=citation-styles');
	const name = page.getByLabel('Style name', { exact: true });
	const csl = page.getByLabel('CSL XML', { exact: true });
	const install = page.getByRole('button', { name: 'Install Citation Style', exact: true });
	await name.fill('First style');
	await csl.fill('<style version="1.0"></style>');
	await install.click();
	await started.promise;
	await expect(install).toBeDisabled();
	await name.fill('Next style');
	await csl.fill('<style version="1.0"><info/></style>');
	release.resolve();
	await expect(install).toBeEnabled();
	expect(submitted).toEqual({ name: 'First style', csl: '<style version="1.0"></style>' });
	await expect(name).toHaveValue('Next style');
	await expect(csl).toHaveValue('<style version="1.0"><info/></style>');
});

test('Tools exposes Tag maintenance and Citation Style installation', async ({ page }) => {
	await mockSession(page);
	let styleCreation: Record<string, unknown> | null = null;
	let duplicateReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/duplicates*', (route) => {
		duplicateReads += 1;
		return route.fulfill({ json: { groups: [] } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({
			json: tagPage(
				[
					{
						id: 'tag-1',
						name: 'Methods',
						accessible_item_count: 3,
						authorization: { allowed: ['tag.manage'] }
					}
				],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) => {
		if (route.request().method() === 'POST') {
			styleCreation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'style-1' } });
		}
		return route.fulfill({ json: { styles: [] } });
	});

	await page.goto('/workspace/workspace-1/tools');
	await expect.poll(() => duplicateReads).toBe(0);
	await page.getByRole('button', { name: 'Check for duplicates' }).click();
	await expect.poll(() => duplicateReads).toBe(1);
	await page.getByRole('radio', { name: 'Shared identifier' }).focus();
	await page.getByRole('radio', { name: 'Shared identifier' }).press('ArrowRight');
	await expect(page.getByRole('radio', { name: 'Same title' })).toBeChecked();
	await expect.poll(() => duplicateReads).toBe(1);
	await expect(page.getByText('The match criteria changed.')).toBeVisible();
	await page.getByRole('button', { name: 'Check for duplicates' }).click();
	await expect.poll(() => duplicateReads).toBe(2);
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await expect(page.locator('strong').filter({ hasText: 'Methods' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Rename' })).toBeVisible();
	await page.getByRole('tab', { name: 'Citation Styles' }).click();
	await page.getByLabel('Style name').fill('House style');
	await page.getByLabel('CSL XML').fill('<style version="1.0"></style>');
	await page.getByRole('button', { name: 'Install Citation Style' }).click();
	await expect
		.poll(() => styleCreation)
		.toEqual({
			name: 'House style',
			csl: '<style version="1.0"></style>'
		});
});

test('Tag page clamps after deleting the last page of Tags', async ({ page }) => {
	await mockSession(page);
	let tags = Array.from({ length: 21 }, (_, index) => ({
		id: `tag-${index + 1}`,
		name: `Tag ${String(index + 1).padStart(2, '0')}`,
		accessible_item_count: 1,
		authorization: { allowed: ['tag.manage'] }
	}));
	await page.route('**/api/v1/workspaces/workspace-1/tags**', (route) => {
		const request = route.request();
		if (request.method() === 'DELETE') {
			tags = tags.filter((tag) => !request.url().endsWith(tag.id));
			return route.fulfill({ json: { ok: true } });
		}
		return route.fulfill({ json: tagPage(tags, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [] } })
	);

	await page.goto('/workspace/workspace-1/tools');
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await expect(page.getByText('21 Tags')).toBeVisible();
	await page.getByRole('button', { name: 'Next page' }).click();
	await expect(page.getByText('Page 2 of 2')).toBeVisible();
	const tagRow = (name: string) =>
		page.locator('strong').filter({ hasText: new RegExp(`^${name}$`) });
	await expect(tagRow('Tag 21')).toBeVisible();

	await page.getByRole('button', { name: 'Delete' }).click();
	await page.getByRole('button', { name: 'Delete Tag' }).click();
	await expect(page.getByText('20 Tags')).toBeVisible();
	await expect(tagRow('Tag 21')).toHaveCount(0);
	await expect(tagRow('Tag 20')).toBeVisible();
	await expect(page.getByText('Page 2 of 2')).toHaveCount(0);
});

for (const concurrentChange of ['created', 'renamed']) {
	test(`Tag conflict refreshes Tools and merge targets after another member ${concurrentChange} a Tag`, async ({
		page
	}) => {
		await mockSession(page);
		const workspaceReads: string[] = [];
		page.on('request', (request) => {
			const path = new URL(request.url()).pathname;
			if (
				request.method() === 'GET' &&
				(path === '/api/v1/workspaces' || path === '/api/v1/workspaces/workspace-1')
			) {
				workspaceReads.push(path);
			}
		});
		let tagReads = 0;
		let duplicateReads = 0;
		let styleReads = 0;
		const source = {
			id: 'tag-1',
			name: 'Methods',
			accessible_item_count: 3,
			authorization: { allowed: ['tag.manage'] }
		};
		const target = { ...source, id: 'tag-2', name: 'Previous name' };
		let tags = concurrentChange === 'created' ? [source] : [source, target];
		await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) => {
			tagReads++;
			return route.fulfill({ json: tagPage(tags, route) });
		});
		await page.route('**/api/v1/workspaces/workspace-1/tags/tag-1', (route) => {
			expect(route.request().method()).toBe('PATCH');
			expect(route.request().postDataJSON()).toEqual({ name: 'Results' });
			tags = [source, { ...target, name: 'Results' }];
			return route.fulfill({
				status: 409,
				json: { code: 'tag_conflict', message: 'name already exists' }
			});
		});
		await page.route('**/api/v1/workspaces/workspace-1/duplicates*', (route) => {
			duplicateReads++;
			return route.fulfill({ json: { groups: [] } });
		});
		await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) => {
			styleReads++;
			return route.fulfill({ json: { styles: [] } });
		});

		await page.goto('/workspace/workspace-1/tools');
		await page.getByRole('button', { name: 'Check for duplicates' }).click();
		await expect(page.getByText('No duplicate groups found.')).toBeVisible();
		await page.getByRole('tab', { name: 'Manage Tags' }).click();
		const sourceSelect = page.getByRole('combobox', { name: 'Source Tag', exact: true });
		const targetSelect = page.getByRole('combobox', { name: 'Target Tag', exact: true });
		await chooseSearchOption(page, 'Source Tag', 'Methods');
		if (concurrentChange === 'renamed')
			await chooseSearchOption(page, 'Target Tag', 'Previous name');
		const initialWorkspaceReads = [...workspaceReads];
		const initialTagReads = tagReads;
		const initialStyleReads = styleReads;
		const initialDuplicateReads = duplicateReads;
		await page.getByRole('button', { name: 'Rename', exact: true }).first().click();
		const dialog = page.getByRole('dialog', { name: 'Rename Tag', exact: true });
		await dialog.getByRole('textbox', { name: 'New Tag name' }).fill('Results');
		await dialog.getByRole('button', { name: 'Rename', exact: true }).click();

		await expect(page.getByText('This Tag conflicts with an existing Tag.')).toBeVisible();
		await expect(dialog.getByRole('textbox', { name: 'New Tag name' })).toHaveValue('Results');
		await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
		await expect(page.locator('strong').filter({ hasText: /^Results$/ })).toBeVisible();
		await expect(page.locator('strong').filter({ hasText: /^Methods$/ })).toBeVisible();
		await expect(page.locator('strong').filter({ hasText: /^Previous name$/ })).toHaveCount(0);
		if (concurrentChange === 'renamed') await expect(targetSelect).toHaveValue('Results');
		await expect(sourceSelect).toHaveValue('Methods');
		await chooseSearchOption(page, 'Target Tag', 'Results');
		await expect(page.getByRole('button', { name: 'Merge Tags', exact: true })).toBeEnabled();
		expect(tagReads).toBeGreaterThan(initialTagReads);
		expect(workspaceReads).toEqual(initialWorkspaceReads);
		expect(styleReads).toBe(initialStyleReads);
		expect(duplicateReads).toBe(initialDuplicateReads);
	});
}

test('Tools requests only the visible Tag page and filters on the server', async ({ page }) => {
	await mockSession(page);
	const tags = Array.from({ length: 65 }, (_, index) => ({
		id: `tag-${index + 1}`,
		name: `Tag ${String(index + 1).padStart(2, '0')}`,
		accessible_item_count: 1,
		authorization: { allowed: ['tag.manage'] }
	}));
	const reads: Array<{ offset: number; limit: number; search: string | null }> = [];
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) => {
		const query = new URL(route.request().url()).searchParams;
		reads.push({
			offset: Number(query.get('offset') ?? 0),
			limit: Number(query.get('limit')),
			search: query.get('search')
		});
		return route.fulfill({ json: tagPage(tags, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [] } })
	);
	await page.goto('/workspace/workspace-1/tools');
	expect(reads).toEqual([]);
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await expect(page.getByText('65 Tags')).toBeVisible();
	expect(reads).toEqual([{ offset: 0, limit: 20, search: null }]);
	await page.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.locator('strong').filter({ hasText: /^Tag 21$/ })).toBeVisible();
	await expect(page.locator('strong').filter({ hasText: /^Tag 20$/ })).toHaveCount(0);
	expect(reads.at(-1)).toEqual({ offset: 20, limit: 20, search: null });
	await page.getByPlaceholder('Filter Tags').fill('Tag 65');
	await expect(page.getByText('1 Tag', { exact: true })).toBeVisible();
	await expect(page.locator('strong').filter({ hasText: /^Tag 65$/ })).toBeVisible();
	expect(reads.at(-1)).toEqual({ offset: 0, limit: 20, search: 'Tag 65' });
});
