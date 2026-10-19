import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { chooseSearchOption, directoryPage, mockSession, tagPage } from './helpers';

test.describe.configure({ mode: 'parallel' });

const project = {
	id: 'project-1',
	name: 'Research direction',
	description: 'A Workspace research context',
	item_count: 0,
	state: 'active',
	participation: 'managed',
	is_participating: false,
	allowed_participation_changes: ['workspace', 'open', 'managed'],
	authorization: {
		allowed: [
			'project.update',
			'project.delete',
			'project_item.manage',
			'project_participation.manage',
			'project_discussion.create'
		]
	},
	active_participants: []
};
const item = {
	id: 'item-1',
	version: 1,
	latest_revision_id: 'revision-1',
	citation_key: 'Audit2026',
	metadata: {
		id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
		type: 'Other',
		title: 'Audit Item'
	},
	authorization: { allowed: ['item.update', 'workspace.export', 'file.manage'] },
	copy_targets: [],
	tags: [],
	counts: { revisions: 1, attachments: 0, annotations: 0, discussion: 0 }
};
const file = {
	id: 'revision-1',
	kind: 'revision',
	original_name: 'Audit.pdf',
	mime_type: 'application/pdf',
	size: 1024,
	created_at: '2026-10-01T00:00:00Z',
	processing_state: 'ready',
	page_count: 1
};
const account = {
	user: { id: 'user-1', username: 'reader', role: 'member' },
	sessions: [],
	api_tokens: []
};
const providers = {
	search: [{ id: 'crossref', name: 'Crossref', sorts: ['relevance'] }],
	lookup: [],
	max_search_clauses: 5
};

async function setup(page: Page, admin = false) {
	await mockSession(page, admin ? 'administrator' : 'member');
	await page.route('**/api/v1/account', (route) => route.fulfill({ json: account }));
	await page.route('**/api/v1/account/citation-key-preview*', (route) =>
		route.fulfill({ json: { key: 'Reader2026' } })
	);
	await page.route('**/api/v1/workspaces/*/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [{ key: 'apa', name: 'APA', scope: 'builtin' }] } })
	);
	await page.route('**/api/v1/workspaces/*/tags?*', (route) =>
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
	await page.route('**/api/v1/workspaces/*/projects?*', (route) =>
		route.fulfill({ json: directoryPage([project], route) })
	);
	await page.route('**/api/v1/workspaces/*/projects/project-1', (route) =>
		route.fulfill({ json: project })
	);
	await page.route('**/api/v1/workspaces/*/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/*/items?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/*/items/item-1/overview', (route) =>
		route.fulfill({ json: item })
	);
	await page.route('**/api/v1/workspaces/*/items/item-1/documents', (route) =>
		route.fulfill({ json: { item_id: 'item-1', files: [file] } })
	);
}

for (const scenario of [
	'account',
	'duplicates',
	'styles',
	'providers',
	'export-styles',
	'documents'
] as const) {
	test(`${scenario} distinguishes a failed read from empty data and retries in place`, async ({
		page
	}) => {
		await setup(page);
		let failing = true;
		const endpoint =
			scenario === 'account'
				? '**/api/v1/account'
				: scenario === 'duplicates'
					? '**/api/v1/workspaces/*/duplicates*'
					: scenario === 'providers'
						? '**/api/v1/workspaces/*/discovery/providers'
						: scenario === 'documents'
							? '**/api/v1/workspaces/*/items/item-1/documents'
							: '**/api/v1/workspaces/*/citation-styles*';
		const data =
			scenario === 'account'
				? account
				: scenario === 'duplicates'
					? { groups: [] }
					: scenario === 'providers'
						? providers
						: scenario === 'documents'
							? { item_id: 'item-1', files: [file] }
							: { styles: [{ key: 'apa', name: 'APA', scope: 'builtin' }] };
		await page.route(endpoint, (route) =>
			route.fulfill(failing ? { status: 500, json: { code: 'internal_error' } } : { json: data })
		);
		await page.goto(
			scenario === 'account' || scenario === 'export-styles'
				? '/account'
				: scenario === 'providers'
					? '/workspace/workspace-1/discovery'
					: scenario === 'documents'
						? '/workspace/workspace-1/item/item-1'
						: '/workspace/workspace-1/tools'
		);
		if (scenario === 'duplicates')
			await page.getByRole('button', { name: 'Check for duplicates', exact: true }).click();
		if (scenario === 'styles')
			await page.getByRole('tab', { name: 'Citation Styles', exact: true }).click();
		if (scenario === 'export-styles')
			await chooseSearchOption(page, 'Workspace for citation style', 'Research');
		if (scenario === 'documents')
			await page.getByRole('button', { name: 'Download', exact: true }).click();
		const scope = scenario === 'documents' ? page.getByRole('dialog') : page.getByRole('main');
		const alert = scope.getByRole('alert');
		await expect(alert).toBeVisible();
		await expect(scope.getByText('No duplicate groups found.', { exact: true })).toHaveCount(0);
		await expect(
			scope.getByText('No Citation Styles match this search.', { exact: true })
		).toHaveCount(0);
		failing = false;
		await alert.getByRole('button', { name: 'Retry', exact: true }).click();
		await expect(alert).toHaveCount(0);
		if (scenario === 'account') await expect(page.getByPlaceholder('Token name')).toBeVisible();
		if (scenario === 'duplicates')
			await expect(page.getByText('No duplicate groups found.', { exact: true })).toBeVisible();
		if (scenario === 'styles') await expect(page.getByText('APA', { exact: true })).toBeVisible();
		if (scenario === 'providers')
			await expect(
				page.getByRole('button', { name: 'Search Discovery', exact: true })
			).toBeEnabled();
		if (scenario === 'export-styles')
			await expect(page.getByRole('option', { name: 'APA', exact: true })).toBeVisible();
		if (scenario === 'documents')
			await expect(
				scope.getByRole('button', { name: 'Download bundle', exact: true })
			).toBeEnabled();
	});
}

test('creating a Project retains its draft and exposes errors inside the modal', async ({
	page
}) => {
	await setup(page);
	let failing = true;
	const started = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/projects$/, async (route) => {
		if (failing) {
			started.resolve();
			await release.promise;
		}
		return route.fulfill(
			failing
				? { status: 500, json: { code: 'internal_error' } }
				: { status: 201, json: { id: 'project-1' } }
		);
	});
	await page.goto('/workspace/workspace-1/projects');
	await page.getByRole('button', { name: 'New Project', exact: true }).click();
	const dialog = page.getByRole('dialog', { name: 'Create Project', exact: true });
	await dialog.getByLabel('Name', { exact: true }).fill('New research');
	await dialog.getByRole('button', { name: 'Create Project', exact: true }).click();
	await started.promise;
	await expect(dialog.getByLabel('Name', { exact: true })).toBeDisabled();
	await page.keyboard.press('Escape');
	await expect(dialog).toBeVisible();
	release.resolve();
	await expect(dialog.getByRole('alert')).toBeVisible();
	await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('New research');
	failing = false;
	await dialog.getByRole('button', { name: 'Create Project', exact: true }).click();
	await expect(page).toHaveURL(/\/projects\/project-1$/);
});

test('renaming a Tag retains the edited name on failure and retries without reopening', async ({
	page
}) => {
	await setup(page);
	let failing = true;
	const names: string[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/tags/tag-1', (route) => {
		names.push(route.request().postDataJSON().name);
		return route.fulfill(
			failing ? { status: 500, json: { code: 'internal_error' } } : { json: { ok: true } }
		);
	});
	await page.goto('/workspace/workspace-1/tools');
	await page.getByRole('tab', { name: 'Manage Tags', exact: true }).click();
	await page.getByRole('button', { name: 'Rename', exact: true }).click();
	const dialog = page.getByRole('dialog', { name: 'Rename Tag', exact: true });
	await dialog.getByRole('textbox').fill('Results');
	await dialog.getByRole('button', { name: 'Rename', exact: true }).click();
	await expect(dialog.getByRole('alert')).toBeVisible();
	await expect(dialog.getByRole('textbox')).toHaveValue('Results');
	failing = false;
	await dialog.getByRole('button', { name: 'Rename', exact: true }).click();
	await expect(dialog).toHaveCount(0);
	expect(names).toEqual(['Results', 'Results']);
});

test('Project directories wrap valid long names in every group on narrow screens', async ({
	page
}) => {
	await setup(page);
	await page.setViewportSize({ width: 390, height: 900 });
	const name = 'LongProjectName'.repeat(12);
	const projects = [
		{ ...project, id: 'managed', name },
		{ ...project, id: 'workspace', name, participation: 'workspace' },
		{ ...project, id: 'mine', name, is_participating: true },
		{ ...project, id: 'joinable', name, participation: 'open' },
		{ ...project, id: 'archived', name, participation: 'open', state: 'archived' }
	];
	await page.route('**/api/v1/workspaces/*/projects?*', (route) =>
		route.fulfill({ json: directoryPage(projects, route) })
	);
	await page.goto('/workspace/workspace-1/projects');
	await expect(page.getByText(name, { exact: true })).toHaveCount(5);
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('Tools restores its URL position and fetches only the active tool, without starting a scan', async ({
	page
}) => {
	await setup(page);
	let scans = 0,
		styles = 0;
	await page.route('**/api/v1/workspaces/*/duplicates*', (route) => {
		scans++;
		return route.fulfill({ json: { groups: [] } });
	});
	await page.route('**/api/v1/workspaces/*/citation-styles*', (route) => {
		styles++;
		return route.fulfill({ json: { styles: [] } });
	});
	await page.goto('/workspace/workspace-1/tools');
	await page.getByRole('tab', { name: 'Manage Tags', exact: true }).click();
	await page.getByPlaceholder('Filter Tags').fill('Methods');
	await expect(page).toHaveURL(/tag_search=Methods/);
	await page.reload();
	await expect(page.getByRole('tab', { name: 'Manage Tags', exact: true })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await expect(page.getByPlaceholder('Filter Tags')).toHaveValue('Methods');
	expect(styles).toBe(0);
	await page.getByRole('tab', { name: 'Duplicate review', exact: true }).click();
	await expect(page.getByRole('tab', { name: 'Duplicate review', exact: true })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await page.reload();
	await expect(
		page.getByRole('button', { name: 'Check for duplicates', exact: true })
	).toBeVisible();
	expect(scans).toBe(0);
	await page.goBack();
	await expect(page.getByRole('tab', { name: 'Manage Tags', exact: true })).toHaveAttribute(
		'aria-selected',
		'true'
	);
});

for (const section of ['users', 'workflows'] as const) {
	test(`admin ${section} page recovery preserves drafts and replaces only corrected history`, async ({
		page
	}) => {
		await setup(page, true);
		const items = Array.from({ length: 21 }, (_, index) =>
			section === 'users'
				? {
						id: `user-${index}`,
						username: `reader-${index}`,
						role: 'member',
						active: true,
						created_at: '2026-10-01T00:00:00Z'
					}
				: { id: `workflow-${index}`, name: `backup-${index}`, state: 'succeeded' }
		);
		const started = Promise.withResolvers<void>();
		const release = Promise.withResolvers<void>();
		let firstRead = true;
		await page.route(`**/api/v1/admin/${section}?*`, async (route) => {
			if (firstRead) {
				firstRead = false;
				started.resolve();
				await release.promise;
			}
			await route.fulfill({ json: directoryPage(items, route) });
		});
		await page.goto('/account');
		await expect(page.getByPlaceholder('Token name')).toBeVisible();
		await page.goto(`/admin/${section}?page=999`);
		await started.promise;
		const draft =
			section === 'users'
				? page.getByRole('textbox', { name: 'Search', exact: true })
				: page.getByRole('combobox', { name: 'State', exact: true });
		if (section === 'users') {
			await draft.fill(' reader-1 ');
			await page.getByRole('combobox', { name: 'Role', exact: true }).selectOption('administrator');
			await page.getByRole('combobox', { name: 'Status', exact: true }).selectOption('false');
		} else await draft.selectOption('failed');
		release.resolve();
		await expect(page).toHaveURL(new RegExp(`/admin/${section}\\?page=2$`));
		await expect(page.getByText('Page 2 of 2', { exact: true })).toBeVisible();
		await expect(draft).toHaveValue(section === 'users' ? ' reader-1 ' : 'failed');
		if (section === 'users') {
			await expect(page.getByRole('combobox', { name: 'Role', exact: true })).toHaveValue(
				'administrator'
			);
			await expect(page.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue(
				'false'
			);
		}
		await page.getByRole('button', { name: 'Previous page', exact: true }).click();
		await expect(page).toHaveURL(new RegExp(`/admin/${section}$`));
		await expect(draft).toHaveValue(section === 'users' ? ' reader-1 ' : 'failed');
		await page.getByRole('combobox', { name: 'Page Size', exact: true }).selectOption('10');
		await expect(page).toHaveURL(new RegExp(`/admin/${section}\\?page_size=10$`));
		await expect(page.getByText('Page 1 of 3', { exact: true })).toBeVisible();
		await expect(draft).toHaveValue(section === 'users' ? ' reader-1 ' : 'failed');
		await page.goBack();
		await expect(page).toHaveURL(new RegExp(`/admin/${section}$`));
		await expect(draft).toHaveValue('');
		await page.goBack();
		await expect(page).toHaveURL(new RegExp(`/admin/${section}\\?page=2$`));
		await expect(draft).toHaveValue('');
		if (section === 'users') {
			await expect(page.getByRole('combobox', { name: 'Role', exact: true })).toHaveValue('');
			await expect(page.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue('');
		}
		await page.goBack();
		await expect(page).toHaveURL(/\/account$/);
	});
}

test('admin drafts reset on explicit clear and section changes', async ({ page }) => {
	await setup(page, true);
	for (const section of ['audit', 'workspaces']) {
		await page.route(`**/api/v1/admin/${section}?*`, (route) =>
			route.fulfill({ json: directoryPage([], route) })
		);
	}
	await page.goto('/admin/audit');
	const search = page.getByRole('textbox', { name: 'Search', exact: true });
	const action = page.getByRole('textbox', { name: 'Action', exact: true });
	const targetType = page.getByRole('textbox', { name: 'Target type', exact: true });
	await search.fill(' local search ');
	await action.fill('workspace.deleted');
	await targetType.fill('workspace');
	await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
	await expect(search).toHaveValue('');
	await expect(action).toHaveValue('');
	await expect(targetType).toHaveValue('');
	await expect(page).toHaveURL(/\/admin\/audit$/);

	await search.fill(' local search ');
	await action.fill('workspace.deleted');
	await targetType.fill('workspace');
	const sections = page.getByRole('navigation', { name: 'Administration sections', exact: true });
	await sections.getByRole('link', { name: 'Workspaces', exact: true }).click();
	await expect(page).toHaveURL(/\/admin\/workspaces$/);
	await expect(search).toHaveValue('');
	await search.fill('another draft');
	await sections.getByRole('link', { name: 'Audit', exact: true }).click();
	await expect(page).toHaveURL(/\/admin\/audit$/);
	await expect(search).toHaveValue('');
	await expect(action).toHaveValue('');
	await expect(targetType).toHaveValue('');

	await action.fill('workspace.deleted');
	await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
	await expect(page).toHaveURL(/action=workspace.deleted/);
	await expect(action).toHaveValue('workspace.deleted');
	await action.fill('unsubmitted edit');
	await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
	await expect(page).toHaveURL(/\/admin\/audit$/);
	await expect(action).toHaveValue('');
	await page.goBack();
	await expect(page).toHaveURL(/action=workspace.deleted/);
	await expect(action).toHaveValue('workspace.deleted');
});

for (const scope of ['directory', 'items', 'audit'] as const) {
	test(`${scope} filters restore from URLs and browser history`, async ({ page }) => {
		await setup(page, scope === 'audit');
		await page.route('**/api/v1/admin/audit?*', (route) =>
			route.fulfill({ json: directoryPage([], route) })
		);
		const path =
			scope === 'audit'
				? '/admin/audit'
				: `/workspace/workspace-1/projects${scope === 'items' ? '/project-1' : ''}`;
		await page.goto(path);
		const input =
			scope === 'audit'
				? page.getByLabel('Action', { exact: true })
				: scope === 'items'
					? page.getByPlaceholder('Search Items', { exact: true })
					: page.getByLabel('Search Projects', { exact: true });
		await input.fill(scope === 'audit' ? 'workspace.deleted' : 'Methods');
		if (scope === 'audit')
			await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
		await expect(page).toHaveURL(scope === 'audit' ? /action=workspace.deleted/ : /q=Methods/);
		await page.reload();
		await expect(input).toHaveValue(scope === 'audit' ? 'workspace.deleted' : 'Methods');
		await page.goto('/account');
		await page.goBack();
		await expect(input).toHaveValue(scope === 'audit' ? 'workspace.deleted' : 'Methods');
	});
}

for (const theme of ['light', 'dark']) {
	test(`task headings, selected tabs and file controls are accessible in ${theme} mode`, async ({
		page
	}) => {
		await setup(page);
		await page.setViewportSize({ width: 390, height: 900 });
		await page.addInitScript((mode) => localStorage.setItem('quirebase:theme', mode), theme);
		for (const [path, tab] of [
			['/account', ''],
			['/workspace/workspace-1/projects', ''],
			['/workspace/workspace-1/tools', 'Manage Tags'],
			['/workspace/workspace-1/tools', 'Citation Styles'],
			['/workspace/workspace-1/import', 'Bibliography'],
			['/workspace/workspace-1/import', 'PDFs'],
			['/workspace/workspace-1/item/item-1/files', '']
		]) {
			await page.goto(path);
			if (tab) await page.getByRole('tab', { name: tab, exact: true }).click();
			await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
			const result = await new AxeBuilder({ page })
				.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
				.analyze();
			expect(
				result.violations
					.filter((v) => v.impact === 'serious' || v.impact === 'critical')
					.map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target) })),
				path
			).toEqual([]);
		}
	});
}

for (const scope of ['tag', 'style', 'project'] as const) {
	test(`${scope} deletion stays open on failure and retries the same target`, async ({ page }) => {
		await setup(page);
		let failing = true;
		const deleted: string[] = [];
		const endpoint =
			scope === 'tag'
				? '**/api/v1/workspaces/workspace-1/tags/tag-1'
				: scope === 'style'
					? '**/api/v1/workspaces/workspace-1/citation-styles/custom-style'
					: '**/api/v1/workspaces/workspace-1/projects/project-1';
		await page.route(endpoint, (route) => {
			if (route.request().method() !== 'DELETE') return route.fulfill({ json: project });
			deleted.push(route.request().url().split('/').at(-1)!);
			return route.fulfill(
				failing ? { status: 500, json: { code: 'internal_error' } } : { json: { ok: true } }
			);
		});
		if (scope === 'style')
			await page.route('**/api/v1/workspaces/workspace-1/citation-styles?*', (route) =>
				route.fulfill({
					json: { styles: [{ key: 'custom-style', name: 'House style', scope: 'custom' }] }
				})
			);
		await page.goto(
			`/workspace/workspace-1/${scope === 'project' ? 'projects/project-1' : 'tools'}`
		);
		if (scope !== 'project')
			await page
				.getByRole('tab', {
					name: scope === 'tag' ? 'Manage Tags' : 'Citation Styles',
					exact: true
				})
				.click();
		await page
			.getByRole('button', { name: scope === 'project' ? 'Delete Project' : 'Delete', exact: true })
			.click();
		const dialog = page.getByRole('dialog');
		if (scope === 'project') await dialog.getByRole('textbox').fill(project.name);
		const confirm = dialog.getByRole('button', {
			name: scope === 'tag' ? 'Delete Tag' : scope === 'style' ? 'Delete Style' : 'Delete Project',
			exact: true
		});
		await confirm.click();
		await expect(dialog.getByRole('alert')).toBeVisible();
		failing = false;
		await confirm.click();
		await expect(dialog).toHaveCount(0);
		expect(deleted).toHaveLength(2);
		expect(deleted[0]).toBe(deleted[1]);
	});
}

test('administration retries failed reads without losing audit filters', async ({ page }) => {
	await setup(page, true);
	let failing = true;
	const requests: string[] = [];
	await page.route('**/api/v1/admin/audit?*', (route) => {
		requests.push(route.request().url());
		return route.fulfill(
			failing
				? { status: 500, json: { code: 'internal_error' } }
				: { json: directoryPage([], route) }
		);
	});
	await page.goto('/admin/audit?action=workspace.deleted');
	await expect(page.getByRole('alert')).toBeVisible();
	failing = false;
	await page.getByRole('alert').getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByText('No audit events.', { exact: true })).toBeVisible();
	await expect(page.getByLabel('Action', { exact: true })).toHaveValue('workspace.deleted');
	expect(
		requests.every((url) => new URL(url).searchParams.get('action') === 'workspace.deleted')
	).toBe(true);
});

for (const scope of ['directory', 'items', 'audit'] as const) {
	test(`${scope} restores page size, page and list choices after refresh`, async ({ page }) => {
		await setup(page, scope === 'audit');
		const rows = Array.from({ length: 60 }, (_, index) =>
			scope === 'audit'
				? {
						id: `event-${index}`,
						action: 'user.created',
						target_type: 'user',
						target_id: 'synthetic-user',
						actor_id: 'user-1',
						created_at: '2026-10-01T00:00:00Z'
					}
				: scope === 'items'
					? { id: `item-${index}`, title_html: `Record ${index}`, authors: 'Reader' }
					: { ...project, id: `project-${index}`, name: `Research ${index}` }
		);
		const endpoint =
			scope === 'audit'
				? '**/api/v1/admin/audit?*'
				: scope === 'items'
					? '**/api/v1/workspaces/workspace-1/items?*'
					: '**/api/v1/workspaces/workspace-1/projects?*';
		await page.route(endpoint, (route) => route.fulfill({ json: directoryPage(rows, route) }));
		const path =
			scope === 'audit'
				? '/admin/audit'
				: `/workspace/workspace-1/projects${scope === 'items' ? '/project-1' : ''}`;
		await page.goto(path);
		await page.getByRole('combobox', { name: 'Page Size', exact: true }).selectOption('10');
		await expect(page).toHaveURL(/page_size=10/);
		await page.getByRole('button', { name: 'Next page', exact: true }).click();
		await expect(page).toHaveURL(/[?&]page=2(?:&|$)/);
		await page.reload();
		await expect(page.getByText('Page 2 of 6', { exact: true })).toBeVisible();
		await expect(page.getByRole('combobox', { name: 'Page Size', exact: true })).toHaveValue('10');
		if (scope === 'items') {
			await page.getByRole('combobox', { name: 'Sort By', exact: true }).selectOption('title');
			await expect(page).toHaveURL(/sort=title/);
			await expect(page.getByText('Page 1 of 6', { exact: true })).toBeVisible();
			await page.reload();
			await expect(page.getByRole('combobox', { name: 'Sort By', exact: true })).toHaveValue(
				'title'
			);
		}
		if (scope === 'directory') {
			await page.getByRole('combobox', { name: 'Projects', exact: true }).selectOption('mine');
			await expect(page).toHaveURL(/view=mine/);
			await expect(page.getByText('Page 1 of 6', { exact: true })).toBeVisible();
			await page.reload();
			await expect(page.getByRole('combobox', { name: 'Projects', exact: true })).toHaveValue(
				'mine'
			);
		}
	});
}

test('Chinese narrow layouts keep selected tools and upload controls accessible', async ({
	page
}) => {
	await setup(page);
	await page.setViewportSize({ width: 390, height: 900 });
	await page.addInitScript(() => {
		localStorage.setItem('quirebase:locale', 'zh-CN');
		localStorage.setItem('quirebase:theme', 'light');
	});
	const views: [string, number | null][] = [
		['/account', null],
		['/workspace/workspace-1/tools', 1],
		['/workspace/workspace-1/tools', 2],
		['/workspace/workspace-1/import', 1],
		['/workspace/workspace-1/import', 2],
		['/workspace/workspace-1/item/item-1/files', null]
	];
	for (const [path, tab] of views) {
		await page.goto(path);
		if (tab !== null) await page.getByRole('tab').nth(tab).click();
		await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
		const result = await new AxeBuilder({ page })
			.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
			.analyze();
		expect(
			result.violations
				.filter((v) => v.impact === 'serious' || v.impact === 'critical')
				.map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target) })),
			path
		).toEqual([]);
		expect(await page.evaluate(() => document.documentElement.scrollWidth), path).toBe(390);
	}
});

test('short names remain readable beside row actions on narrow screens', async ({ page }) => {
	await setup(page);
	await page.setViewportSize({ width: 390, height: 900 });
	await page.goto('/workspace/workspace-1/tools?tool=tags');
	const tag = page.locator('strong').filter({ hasText: /^Methods$/ });
	await expect(tag).toBeVisible();
	expect((await tag.boundingBox())!.height).toBeLessThanOrEqual(28);
	await page.goto('/workspace/workspace-1/item/item-1/files');
	const filename = page.locator('strong').filter({ hasText: /^Audit.pdf$/ });
	await expect(filename).toBeVisible();
	expect(await filename.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(
		false
	);
});
