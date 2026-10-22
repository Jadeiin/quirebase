import { openLibraryAction } from './helpers';
import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { directoryPage, mockSession, workspaceView } from './helpers';

const items = Array.from({ length: 73 }, (_, index) => ({
	id: `item-${index + 1}`,
	title_html: `Item ${index + 1}`,
	authors: [{ full_name: 'Researcher', last_name: 'Researcher', first_name: null }],
	publication_date: '2026',
	publication_title: null
}));

test('Library pagination keeps size, sort and exact filters through navigation', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	const requests: URLSearchParams[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		requests.push(new URL(route.request().url()).searchParams);
		return route.fulfill({ json: directoryPage(items, route) });
	});
	await page.goto(
		'/workspace/workspace-1/library?q=research&sort=created&author_first_name=&page=3&page_size=10'
	);
	const pagination = page.getByRole('navigation', { name: 'Library pages' });
	const size = pagination.getByRole('combobox', { name: 'Page Size', exact: true });
	const sort = page.getByRole('combobox', { name: 'Sort By', exact: true });
	await expect(pagination.getByText('Showing 21–30 of 73')).toBeVisible();
	await expect(size).toHaveValue('10');
	await expect(sort).toHaveValue('created');
	await page.getByRole('checkbox', { name: 'Select this page' }).check();
	await size.selectOption('50');
	await expect(pagination.getByText('Showing 1–50 of 73')).toBeVisible();
	await expect(page.getByRole('checkbox', { name: 'Select this page' })).not.toBeChecked();
	expect(new URL(page.url()).searchParams.get('page')).toBeNull();
	expect(requests.at(-1)?.get('limit')).toBe('50');
	expect(requests.at(-1)?.get('offset')).toBe('0');
	expect(requests.at(-1)?.get('query')).toBe('research');
	expect(requests.at(-1)?.get('author_first_name')).toBe('');
	await pagination.getByRole('button', { name: 'Last page', exact: true }).click();
	await expect(pagination.getByText('Showing 51–73 of 73')).toBeVisible();
	await expect(pagination.getByRole('button', { name: 'Next page', exact: true })).toBeDisabled();
	expect(requests.at(-1)?.get('offset')).toBe('50');
	await sort.selectOption('title');
	await expect(pagination.getByText('Page 1 of 2')).toBeVisible();
	expect(requests.at(-1)?.get('sort')).toBe('title');
	expect(requests.at(-1)?.get('limit')).toBe('50');
	expect(requests.at(-1)?.get('offset')).toBe('0');
	await page.goBack();
	await expect(pagination.getByText('Page 2 of 2')).toBeVisible();
	await expect(sort).toHaveValue('created');
	await page.goForward();
	await expect(sort).toHaveValue('title');
	await page.reload();
	await expect(size).toHaveValue('50');
	await expect(sort).toHaveValue('title');
	await expect(pagination.getByText('Showing 1–50 of 73')).toBeVisible();
	expect(new URL(page.url()).searchParams.get('author_first_name')).toBe('');
});

test('Library deletion recovers the last valid page with filters, sorting and page size intact', async ({
	page
}) => {
	await mockSession(page);
	const remaining = items.slice(0, 21);
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({ json: directoryPage(remaining, route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		expect(route.request().postDataJSON()).toMatchObject({
			item_ids: ['item-21'],
			action: 'delete_items'
		});
		remaining.pop();
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto(
		'/workspace/workspace-1/library?q=research&sort=created&author_first_name=&page=2&page_size=20'
	);
	await expect(page.getByText('Item 21', { exact: true })).toBeVisible();
	await page.getByRole('checkbox', { name: 'Select this page', exact: true }).check();
	await openLibraryAction(page, 'delete_items');
	await page
		.getByRole('dialog')
		.getByRole('button', { name: 'Permanently delete', exact: true })
		.click();
	await expect(page.getByText('Bulk action completed', { exact: true })).toBeVisible();
	const pagination = page.getByRole('navigation', { name: 'Library pages' });
	await expect(pagination.getByText('Page 1 of 1', { exact: true })).toBeVisible();
	await expect(page.getByText('Item 1', { exact: true })).toBeVisible();
	await expect(pagination.getByRole('combobox', { name: 'Page Size', exact: true })).toHaveValue(
		'20'
	);
	await expect(page.getByRole('combobox', { name: 'Sort By', exact: true })).toHaveValue('created');
	const params = new URL(page.url()).searchParams;
	expect(params.get('q')).toBe('research');
	expect(params.get('author_first_name')).toBe('');
	expect(params.get('page')).toBeNull();
	expect(params.get('page_size')).toBe('20');
});

for (const total of [0, 1]) {
	test(`Library pagination stays usable with ${total} results on mobile`, async ({ page }) => {
		await mockSession(page);
		await page.setViewportSize({ width: 320, height: 800 });
		await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
			route.fulfill({ json: directoryPage([], route) })
		);
		await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
			route.fulfill({ json: directoryPage(items.slice(0, total), route) })
		);
		await page.goto('/workspace/workspace-1/library');
		const pagination = page.getByRole('navigation', { name: 'Library pages' });
		await expect(pagination.getByText(`Showing ${total}–${total} of ${total}`)).toBeVisible();
		for (const name of ['First page', 'Previous page', 'Next page', 'Last page']) {
			await expect(pagination.getByRole('button', { name, exact: true })).toBeDisabled();
		}
		await pagination.getByRole('combobox', { name: 'Page Size', exact: true }).selectOption('100');
		await expect(page).toHaveURL(/page_size=100/);
		await page.getByRole('combobox', { name: 'Sort By', exact: true }).selectOption('title');
		await expect(page).toHaveURL(/sort=title/);
		await expect(pagination).toHaveAttribute('aria-busy', 'false');
		expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
			true
		);
		const accessibility = await new AxeBuilder({ page })
			.include('nav[aria-label="Library pages"]')
			.analyze();
		expect(
			accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')
		).toEqual([]);
	});
}

test('Chinese pagination fits a narrow screen and remains accessible in dark mode', async ({
	page
}) => {
	await mockSession(page);
	await page.addInitScript(() => {
		localStorage.setItem('quirebase:locale', 'zh-CN');
		localStorage.setItem('quirebase:theme', 'dark');
	});
	await page.setViewportSize({ width: 320, height: 800 });
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({ json: directoryPage(items, route) })
	);
	await page.goto('/workspace/workspace-1/library');
	const pagination = page.getByRole('navigation', { name: '文献库分页' });
	await expect(pagination.getByRole('combobox', { name: '每页数量' })).toHaveValue('25');
	await expect(page.getByRole('combobox', { name: '排序方式' })).toHaveValue('updated');
	await expect(pagination.getByText('显示第 1–25 条，共 73 条')).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
	const accessibility = await new AxeBuilder({ page })
		.include('nav[aria-label="文献库分页"]')
		.analyze();
	expect(
		accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')
	).toEqual([]);
});

test('Discovery changes page size on the server and keeps the previous page on failure', async ({
	page
}) => {
	await mockSession(page);
	const requests: Array<{ page: number; per_page: number }> = [];
	let fail = false;
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) => {
		const body = route.request().postDataJSON();
		requests.push(body);
		if (fail)
			return route.fulfill({
				status: 503,
				json: { code: 'upstream_service_error', message: 'Provider unavailable' }
			});
		return route.fulfill({
			json: {
				provider: 'crossref',
				results: [],
				total: 73,
				page: body.page,
				per_page: body.per_page
			}
		});
	});
	await page.goto('/workspace/workspace-1/discovery');
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('research');
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	const pagination = page.getByRole('navigation', { name: 'Discovery result pages' });
	const size = pagination.getByRole('combobox', { name: 'Page Size', exact: true });
	await size.selectOption('50');
	await expect(pagination.getByText('Page 1 of 2')).toBeVisible();
	expect(requests.at(-1)).toMatchObject({ page: 1, per_page: 50 });
	await pagination.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(pagination.getByText('Showing 51–73 of 73')).toBeVisible();
	fail = true;
	await size.selectOption('10');
	const failure = page.getByRole('main').getByRole('alert');
	await expect(failure).toContainText('The external service is temporarily unavailable.');
	await expect(size).toHaveValue('50');
	await expect(pagination.getByText('Showing 51–73 of 73')).toBeVisible();
	fail = false;
	await failure.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(pagination.getByText('Showing 1–10 of 73')).toBeVisible();
	expect(requests.at(-1)).toMatchObject({ page: 1, per_page: 10 });
});

for (const section of [
	'workspaces',
	'projects',
	'users',
	'invitations',
	'audit',
	'overview',
	'workflows'
] as const) {
	test(`${section} pagination requests the selected size and resets its offset`, async ({
		page
	}) => {
		await mockSession(page, 'administrator');
		const rows = Array.from({ length: 61 }, (_, index) => ({
			...workspaceView(`entry-${index}`, `Entry ${index}`),
			username: `user-${index}`,
			role: 'member',
			active: true,
			state: section === 'workflows' ? 'failed' : section === 'invitations' ? 'pending' : 'active',
			item_count: 0,
			participation: 'workspace',
			is_participating: true,
			allowed_participation_changes: [],
			action: 'item.create',
			target_type: 'item',
			created_at: '2026-01-01T00:00:00Z',
			expires_at: '2027-01-01T00:00:00Z'
		}));
		const apiPath =
			section === 'workspaces'
				? 'workspaces'
				: section === 'projects'
					? 'workspaces/workspace-1/projects'
					: `admin/${section}`;
		const path =
			section === 'workspaces'
				? '/workspace'
				: section === 'projects'
					? '/workspace/workspace-1/projects'
					: section === 'overview'
						? '/admin'
						: `/admin/${section}`;
		const requests: URLSearchParams[] = [];
		await page.route(`**/api/v1/${apiPath}?*`, (route) => {
			requests.push(new URL(route.request().url()).searchParams);
			const result = directoryPage(rows, route);
			return route.fulfill({
				json:
					section === 'overview'
						? {
								user_count: 7,
								pending_invitation_count: 2,
								failed_workflow_count: 0,
								storage: { items_count: 123, total_disk_bytes: 0 },
								recent_events: result
							}
						: result
			});
		});
		await page.goto(path);
		const size = page.getByRole('combobox', { name: 'Page Size', exact: true });
		await size.selectOption('50');
		await expect(page.getByText('Page 1 of 2', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Next page', exact: true }).click();
		await expect(page.getByText('Showing 51–61 of 61')).toBeVisible();
		expect(requests.at(-1)?.get('limit')).toBe('50');
		expect(requests.at(-1)?.get('offset')).toBe('50');
		await size.selectOption('10');
		await expect(page.getByText('Showing 1–10 of 61')).toBeVisible();
		expect(
			requests.some((query) => query.get('limit') === '10' && query.get('offset') === '0')
		).toBe(true);
		if (section === 'overview') {
			await expect(page.getByText('123', { exact: true })).toBeVisible();
			await expect(page.getByText('7', { exact: true })).toBeVisible();
		}
	});
}

test('admin workflow filters reset the page and preserve page size as history changes', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let rows = Array.from({ length: 125 }, (_, index) => ({
		id: `workflow-${index}`,
		name: `Workflow ${index}`,
		state: index % 2 === 0 ? 'failed' : 'succeeded'
	}));
	const requests: URLSearchParams[] = [];
	await page.route('**/api/v1/admin/workflows?*', (route) => {
		const query = new URL(route.request().url()).searchParams;
		requests.push(query);
		const state = query.get('state');
		return route.fulfill({
			json: directoryPage(
				rows.filter((row) => !state || row.state === state),
				route
			)
		});
	});
	await page.goto('/admin/workflows');
	const pagination = page.getByRole('navigation', { name: 'Administration pages' });
	const size = pagination.getByRole('combobox', { name: 'Page Size', exact: true });
	await size.selectOption('10');
	await pagination.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(pagination.getByText('Page 2 of 13')).toBeVisible();
	await page.getByRole('combobox', { name: 'State', exact: true }).selectOption('failed');
	await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
	await expect(pagination.getByText('Page 1 of 7')).toBeVisible();
	await expect(size).toHaveValue('10');
	expect(requests.at(-1)?.get('state')).toBe('failed');
	expect(requests.at(-1)?.get('offset')).toBe('0');
	rows = rows.slice(0, 5);
	await pagination.getByRole('button', { name: 'Last page', exact: true }).click();
	await expect(pagination.getByText('Showing 1–3 of 3')).toBeVisible();
	await expect(pagination.getByText('Page 1 of 1')).toBeVisible();
	expect(requests.at(-1)?.get('offset')).toBe('0');
	await expect(size).toHaveValue('10');
});
