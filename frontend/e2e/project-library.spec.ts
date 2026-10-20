import { expect, test, type Page } from '@playwright/test';
import { directoryPage, mockSession, openLibraryAction, tagPage, workspaceView } from './helpers';

const projectPath = '/workspace/workspace-1/projects/project-1';
const libraryPath = '/workspace/workspace-1/library';
const projectName = 'Reading Project';
const projectFilterName = `Remove filter Project: ${projectName}`;

async function mockProjectLibrary(
	page: Page,
	options: { archived?: boolean; viewer?: boolean } = {}
) {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill({
			json: options.viewer
				? {
						...workspaceView('workspace-1', 'Research'),
						current_role: 'viewer',
						authorization: { allowed: ['workspace.read', 'workspace.export'] }
					}
				: workspaceView('workspace-1', 'Research')
		})
	);
	const rows = Array.from({ length: 12 }, (_, index) => ({
		id: `item-${index + 1}`,
		title_html: `Reading Item ${String(index + 1).padStart(2, '0')}`,
		authors: [],
		publication_date: '2025',
		publication_title: 'Research Journal',
		doi: null,
		version: 1
	}));
	const removed = new Set<string>();
	const project = () => ({
		id: 'project-1',
		name: projectName,
		description: 'A shared reading list',
		item_count: rows.length - removed.size,
		state: options.archived ? 'archived' : 'active',
		participation: 'workspace',
		is_participating: true,
		allowed_participation_changes: [],
		authorization: {
			allowed: options.archived || options.viewer ? [] : ['project_item.manage']
		},
		active_participants: []
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({ json: project() })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: directoryPage([project()], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	const reads: URL[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const url = new URL(route.request().url());
		reads.push(url);
		const query = url.searchParams.get('query')?.toLowerCase() ?? '';
		const items = rows.filter(
			(row) =>
				(!url.searchParams.has('project') || !removed.has(row.id)) &&
				row.title_html.toLowerCase().includes(query)
		);
		return route.fulfill({ json: directoryPage(items, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/*/overview', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		const row = rows.find((item) => item.id === id)!;
		return route.fulfill({
			json: {
				id,
				version: 1,
				citation_key: null,
				metadata: { id: `urn:${id}`, type: 'JournalArticle', title: row.title_html },
				authorization: { allowed: [] },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				latest_revision_id: null,
				thumbnail: null,
				copy_targets: []
			}
		});
	});
	const mutations: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		const body = route.request().postDataJSON();
		mutations.push(body);
		if (body.action === 'remove_project') for (const id of body.item_ids) removed.add(id);
		return route.fulfill({ json: { ok: true } });
	});
	return { reads, mutations };
}

test('Project Library keeps the reading context through sorting, bulk removal and clearing its scope', async ({
	page
}) => {
	await page.setViewportSize({ width: 1440, height: 1000 });
	const { reads, mutations } = await mockProjectLibrary(page);
	await page.goto(`${projectPath}?q=Reading&sort=created&page=2&page_size=10`);
	const open = page.getByRole('link', { name: 'Open in Library', exact: true });
	const destination = new URL((await open.getAttribute('href'))!, page.url());
	expect(destination.pathname).toBe(libraryPath);
	expect(Object.fromEntries(destination.searchParams)).toEqual({
		q: 'Reading',
		project: 'project-1',
		sort: 'created',
		page: '2',
		page_size: '10'
	});
	await open.click();
	await expect(page).toHaveURL(destination.href);
	const scope = page.getByRole('group', { name: 'Applied filters', exact: true });
	await expect(
		scope.getByRole('link', { name: `Project: ${projectName}`, exact: true })
	).toHaveAttribute('href', projectPath);
	await expect(scope.getByRole('button', { name: projectFilterName, exact: true })).toBeVisible();
	await expect(page.getByRole('textbox', { name: 'Library Search', exact: true })).toHaveValue(
		'Reading'
	);
	await page.getByRole('combobox', { name: 'Sort By', exact: true }).selectOption('title');
	await expect(page).not.toHaveURL(/[?&]page=/);
	await page.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.locator('[data-library-item-select="item-11"]')).toBeVisible();
	await page.getByLabel('Select this page', { exact: true }).check();
	await openLibraryAction(page, 'remove_project');
	const dialog = page.getByRole('dialog', {
		name: `Remove the selected Items from ${projectName}?`,
		exact: true
	});
	await expect(dialog).toContainText(
		'This permanently deletes their Annotations and Replies in this Project.'
	);
	await expect(dialog).toContainText(
		'Items, files, private Annotations, and other Projects are preserved.'
	);
	expect(mutations).toEqual([]);
	await dialog.getByRole('button', { name: 'Remove from Project', exact: true }).click();
	await expect(dialog).toHaveCount(0);
	await expect(page.getByText('Page 1 of 1', { exact: true })).toBeVisible();
	await expect(page.locator('[data-library-item-select="item-11"]')).toHaveCount(0);
	expect(mutations).toEqual([
		{ action: 'remove_project', item_ids: ['item-11', 'item-12'], project_id: 'project-1' }
	]);
	expect(reads.every((url) => url.searchParams.get('project') === 'project-1')).toBe(true);
	await scope.getByRole('button', { name: projectFilterName, exact: true }).click();
	await expect(page).toHaveURL(`${libraryPath}?q=Reading&sort=title&page_size=10`);
	await expect(scope.getByRole('button', { name: projectFilterName, exact: true })).toHaveCount(0);
	await expect(
		scope.getByRole('button', { name: 'Remove filter Search: Reading', exact: true })
	).toBeVisible();
	await page.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.locator('[data-library-item-select="item-11"]')).toBeVisible();
	await expect(page.locator('[data-library-item-select="item-12"]')).toBeVisible();
	await expect.poll(() => reads.at(-1)?.searchParams.get('project')).toBeNull();
	await expect.poll(() => reads.at(-1)?.searchParams.get('query')).toBe('Reading');
	await expect.poll(() => reads.at(-1)?.searchParams.get('sort')).toBe('title');
});

test('Project Item links return to its filtered Library and retain continuous preview navigation', async ({
	page
}) => {
	await page.setViewportSize({ width: 1440, height: 1000 });
	await mockProjectLibrary(page);
	await page.goto(`${projectPath}?q=Reading&sort=title&page_size=10`);
	const item = page.getByRole('link', { name: 'Reading Item 01', exact: true });
	const itemUrl = new URL((await item.getAttribute('href'))!, page.url());
	const returnTo = itemUrl.searchParams.get('return_to')!;
	const destination = new URL(`/${returnTo}`, page.url());
	expect(itemUrl.pathname).toBe('/workspace/workspace-1/item/item-1');
	expect(destination.pathname).toBe(libraryPath);
	expect(Object.fromEntries(destination.searchParams)).toEqual({
		q: 'Reading',
		project: 'project-1',
		sort: 'title',
		page_size: '10'
	});
	expect(destination.hash).toBe('#library-item-item-1');
	await item.click();
	await expect(page.getByRole('heading', { name: 'Reading Item 01', level: 1 })).toBeVisible();
	const back = page.getByRole('main').getByRole('link', { name: 'Library', exact: true });
	await expect(back).toHaveAttribute('href', `/${returnTo}`);
	await back.click();
	await expect(page.locator('[data-library-item-select="item-1"]')).toBeFocused();
	await page.getByRole('button', { name: 'Preview Item 1', exact: true }).click();
	const preview = page.locator('#library-preview');
	await expect(
		preview.getByRole('heading', { name: 'Reading Item 01', exact: true })
	).toBeVisible();
	await preview.getByRole('button', { name: 'Next Item', exact: true }).click();
	await expect(
		preview.getByRole('heading', { name: 'Reading Item 02', exact: true })
	).toBeVisible();
	await expect(page).toHaveURL(/project=project-1.*preview=item-2/);
	await expect(
		preview.getByRole('link', { name: 'Open full details', exact: true })
	).toHaveAttribute('href', new RegExp('return_to=.*project%3Dproject-1'));
});

for (const scenario of ['archived', 'viewer'] as const) {
	test(`${scenario} Project scope retains navigation and permitted Workspace actions without Project removal`, async ({
		page
	}) => {
		await mockProjectLibrary(page, {
			archived: scenario === 'archived',
			viewer: scenario === 'viewer'
		});
		await page.goto(projectPath);
		await page.getByRole('link', { name: 'Open in Library', exact: true }).click();
		const scope = page.getByRole('group', { name: 'Applied filters', exact: true });
		await expect(
			scope.getByRole('link', { name: `Project: ${projectName}`, exact: true })
		).toHaveAttribute('href', projectPath);
		await expect(scope.getByRole('button', { name: projectFilterName, exact: true })).toBeVisible();
		await page.locator('[data-library-item-select="item-1"]').check();
		const actions = page.getByRole('region', { name: 'Bulk actions', exact: true });
		await expect(
			actions.getByRole('button', { name: 'Export bibliography', exact: true })
		).toBeEnabled();
		if (scenario === 'archived')
			await expect(actions.getByRole('button', { name: 'Add Tag', exact: true })).toBeEnabled();
		else await expect(actions.getByRole('button', { name: 'Add Tag', exact: true })).toHaveCount(0);
		await actions.getByRole('button', { name: 'More actions', exact: true }).click();
		await expect(
			page.getByRole('menuitem', { name: 'Remove from current Project', exact: true })
		).toHaveCount(0);
		await expect(
			page.getByRole('menuitem', { name: 'Download documents', exact: true })
		).toBeEnabled();
		if (scenario === 'viewer')
			await expect(
				page.getByRole('menuitem', { name: 'Permanently delete', exact: true })
			).toHaveCount(0);
	});
}
