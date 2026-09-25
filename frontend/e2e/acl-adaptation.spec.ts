import { expect, test, type Page } from '@playwright/test';
import { mockSession } from './helpers';

async function projectCapabilities(
	page: Page,
	role: string,
	capabilities: string[],
	suspended = false
) {
	const workspace = {
		id: 'workspace-1',
		name: 'Research',
		owner_id: 'user-1',
		state: 'active',
		current_role: role,
		governance_suspended: suspended,
		effective_capabilities: capabilities
	};
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill({ json: workspace })
	);
	await page.route('**/api/v1/workspaces', (route) => route.fulfill({ json: [workspace] }));
}

const overview = {
	item: { id: 'item-1', title_html: 'Item', version: 1 },
	latest_revision: null,
	allowed_actions: { edit: false, delete: false },
	counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 2 },
	tags: [],
	identifiers: []
};

test('instance administrator gets no Item Discussion privilege without Workspace capability', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	await projectCapabilities(page, 'viewer', ['workspace.read', 'workspace.export']);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({ json: overview })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/discussions', (route) =>
		route.fulfill({
			json: [
				{
					id: 'own',
					author_id: 'user-1',
					author_username: 'reader',
					body: 'Own message',
					created_at: '2026-09-01T00:00:00Z'
				},
				{
					id: 'other',
					author_id: 'user-2',
					author_username: 'other',
					body: 'Other message',
					created_at: '2026-09-01T00:00:00Z'
				}
			]
		})
	);
	await page.goto('/workspace/workspace-1/item/item-1/discussion');
	await expect(page.getByText('Other message')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Post message' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Delete' })).toHaveCount(0);
});

test('Discussion writer can delete only their own message', async ({ page }) => {
	await mockSession(page);
	await projectCapabilities(page, 'reviewer', ['workspace.read', 'discussion.write']);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({ json: overview })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/discussions', (route) =>
		route.fulfill({
			json: [
				{
					id: 'own',
					author_id: 'user-1',
					author_username: 'reader',
					body: 'Own message',
					created_at: '2026-09-01T00:00:00Z'
				},
				{
					id: 'other',
					author_id: 'user-2',
					author_username: 'other',
					body: 'Other message',
					created_at: '2026-09-01T00:00:00Z'
				}
			]
		})
	);
	await page.goto('/workspace/workspace-1/item/item-1/discussion');
	await expect(page.getByRole('button', { name: 'Post message' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Delete' })).toHaveCount(1);
});

for (const [role, capabilities, visible] of [
	['viewer', ['workspace.read', 'workspace.export'], ['bibliography', 'documents']],
	[
		'reviewer',
		['workspace.read', 'workspace.export', 'discussion.write'],
		['bibliography', 'documents']
	],
	[
		'editor',
		['workspace.read', 'workspace.export', 'projects.manage', 'tags.use'],
		['add_project', 'add_tag', 'bibliography', 'documents']
	],
	[
		'admin',
		['workspace.read', 'workspace.export', 'projects.manage', 'tags.use', 'items.delete'],
		['add_project', 'add_tag', 'bibliography', 'documents', 'delete']
	],
	[
		'owner',
		['workspace.read', 'workspace.export', 'projects.manage', 'tags.use', 'items.delete'],
		['add_project', 'add_tag', 'bibliography', 'documents', 'delete']
	]
] as const) {
	test(`${role} sees only permitted Library bulk actions`, async ({ page }) => {
		await mockSession(page);
		await projectCapabilities(page, role, [...capabilities]);
		await page.route('**/api/v1/workspaces/workspace-1/tags', (route) =>
			route.fulfill({ json: [] })
		);
		await page.route('**/api/v1/workspaces/workspace-1/projects', (route) =>
			route.fulfill({ json: [] })
		);
		await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
			route.fulfill({
				json: {
					items: [
						{
							id: 'item-1',
							title_html: 'Item',
							authors: null,
							publication_date: null,
							publication_title: null,
							doi: null,
							version: 1
						}
					],
					total: 1,
					page: 1,
					per_page: 25
				}
			})
		);
		await page.goto('/workspace/workspace-1/library');
		await page.getByLabel('Select this page').check();
		const options = await page
			.getByLabel('Bulk action')
			.locator('option')
			.evaluateAll((nodes) =>
				nodes.map((node) => (node as HTMLOptionElement).value).filter(Boolean)
			);
		expect(options).toEqual(visible);
	});
}

test('viewer can search Discovery but cannot stage Import or use write shortcuts', async ({
	page
}) => {
	await mockSession(page);
	await projectCapabilities(page, 'viewer', ['workspace.read', 'workspace.export']);
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({ json: [{ id: 'openalex', name: 'OpenAlex' }] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/search', (route) =>
		route.fulfill({
			json: {
				results: [
					{
						provider: 'openalex',
						identifier_provider: 'doi',
						identifier: '10.1/x',
						title: 'Candidate',
						imported: false
					}
				],
				total: 1,
				page: 1,
				per_page: 20
			}
		})
	);
	await page.goto('/workspace/workspace-1');
	await expect(page.getByRole('link', { name: /Import Items/ })).toHaveCount(0);
	await expect(page.getByRole('link', { name: /New Project/ })).toHaveCount(0);
	await page.goto('/workspace/workspace-1/import');
	await expect(page.getByRole('button', { name: 'Stage PDFs' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Open metadata editor' })).toHaveCount(0);
	await page.goto('/workspace/workspace-1/discovery');
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('paper');
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	await expect(page.getByRole('heading', { name: 'Candidate', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Review and import' })).toHaveCount(0);
});

test('governance suspension is visible and hides Workspace mutations', async ({ page }) => {
	await mockSession(page);
	await projectCapabilities(page, 'owner', ['workspace.read', 'workspace.export'], true);
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
	);
	await page.goto('/workspace/workspace-1');
	await expect(page.getByText(/Workspace governance is suspended/)).toBeVisible();
	await expect(page.getByRole('link', { name: /Import Items/ })).toHaveCount(0);
	await page.goto('/workspace/workspace-1/settings');
	await expect(page.getByRole('button', { name: 'Save name' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Reindex Workspace' })).toHaveCount(0);
});

test('Item actions require source export and file management capabilities', async ({ page }) => {
	await mockSession(page);
	await projectCapabilities(page, 'viewer', ['workspace.read']);
	await page.route('**/api/v1/workspaces', (route) =>
		route.fulfill({
			json: [
				{ id: 'workspace-1', name: 'Research', effective_capabilities: ['workspace.read'] },
				{ id: 'workspace-2', name: 'Target', effective_capabilities: ['items.create'] }
			]
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				...overview,
				latest_revision: {
					id: 'revision-1',
					original_name: 'paper.pdf',
					size: 100,
					processing_state: 'ready'
				},
				allowed_actions: { edit: true, delete: false }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1', (route) =>
		route.fulfill({
			json: {
				id: 'item-1',
				title_html: 'Item',
				version: 1,
				metadata: {
					title: 'Item',
					keywords: [],
					urls: [],
					authors: [],
					editors: [],
					identifiers: [],
					custom_fields: []
				}
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/documents', (route) =>
		route.fulfill({
			json: {
				files: [
					{
						id: 'revision-1',
						kind: 'revision',
						original_name: 'paper.pdf',
						size: 100,
						processing_state: 'ready'
					}
				]
			}
		})
	);
	await page.goto('/workspace/workspace-1/item/item-1/files');
	await expect(page.getByRole('button', { name: 'Export' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Download', exact: true })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Copy to Workspace' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Upload PDF' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Delete' })).toHaveCount(0);
});

test('Workspace rename refreshes the chooser cache and reindex tracks a scoped workflow', async ({
	page
}) => {
	await mockSession(page);
	let name = 'Research';
	let reindexRequests = 0;
	const projection = () => ({
		id: 'workspace-1',
		name,
		owner_id: 'user-1',
		state: 'active',
		current_role: 'admin',
		governance_suspended: false,
		effective_capabilities: ['workspace.read', 'workspace.settings.manage']
	});
	await page.route('**/api/v1/workspaces', (route) => route.fulfill({ json: [projection()] }));
	await page.route('**/api/v1/workspaces/workspace-1', (route) => {
		if (route.request().method() === 'PATCH') {
			name = (route.request().postDataJSON() as { name: string }).name;
			return route.fulfill({ json: { id: 'workspace-1' } });
		}
		return route.fulfill({ json: projection() });
	});
	await page.route('**/api/v1/workspaces/workspace-1/governance/members', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/invitations', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/maintenance/reindex', (route) => {
		reindexRequests += 1;
		return route.fulfill({ json: { id: 'maintenance:reindex:workspace-1:job' } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/workflows/*', (route) =>
		route.fulfill({
			json: { id: 'maintenance:reindex:workspace-1:job', state: 'succeeded', error: null }
		})
	);
	await page.goto('/workspace/workspace-1/settings');
	await page.getByLabel('Name', { exact: true }).fill('Renamed Research');
	await page.getByRole('button', { name: 'Save name' }).click();
	await expect(page.getByText('Workspace name updated')).toBeVisible();
	await page.getByRole('button', { name: 'Workspace', exact: true }).click();
	await expect(page.getByRole('menuitem', { name: /Renamed Research/ })).toBeVisible();
	await page.keyboard.press('Escape');
	await page.getByRole('button', { name: 'Reindex Workspace' }).click();
	await expect.poll(() => reindexRequests).toBe(1);
});

test('a lifecycle conflict refreshes the Workspace capability projection', async ({ page }) => {
	await mockSession(page);
	let archived = false;
	const projection = () => ({
		id: 'workspace-1',
		name: 'Research',
		owner_id: 'user-1',
		state: archived ? 'archived' : 'active',
		current_role: 'owner',
		governance_suspended: false,
		effective_capabilities: archived
			? ['workspace.read', 'workspace.archive']
			: ['workspace.read', 'workspace.settings.manage', 'workspace.archive']
	});
	await page.route('**/api/v1/workspaces', (route) => route.fulfill({ json: [projection()] }));
	await page.route('**/api/v1/workspaces/workspace-1', (route) => {
		if (route.request().method() === 'PATCH') {
			archived = true;
			return route.fulfill({
				status: 409,
				json: { code: 'workspace_lifecycle_error', message: 'archived' }
			});
		}
		return route.fulfill({ json: projection() });
	});
	await page.route('**/api/v1/workspaces/workspace-1/governance/members', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/invitations', (route) =>
		route.fulfill({ json: [] })
	);
	await page.goto('/workspace/workspace-1/settings');
	await page.getByLabel('Name', { exact: true }).fill('Attempted rename');
	await page.getByRole('button', { name: 'Save name' }).click();
	await expect(page.getByText(/Archived workspace/)).toBeVisible();
	await expect(page.getByRole('button', { name: 'Save name' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Restore workspace' })).toBeVisible();
});

test('missing Workspace context opens recovery and emits a diagnostic', async ({ page }) => {
	await mockSession(page);
	await projectCapabilities(page, 'owner', ['workspace.read', 'workspace.settings.manage']);
	await page.route('**/api/v1/workspaces/workspace-1/governance/members', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/invitations', (route) =>
		route.fulfill({ json: [] })
	);
	await page.addInitScript(() => {
		(window as Window & { diagnostics?: unknown[] }).diagnostics = [];
		window.addEventListener('quirebase:api-diagnostic', (event) =>
			(window as Window & { diagnostics: unknown[] }).diagnostics.push(
				(event as CustomEvent).detail
			)
		);
	});
	await page.route('**/api/v1/workspaces/workspace-1', (route) => {
		if (route.request().method() === 'PATCH')
			return route.fulfill({
				status: 400,
				json: { code: 'workspace_context_required', message: 'missing' }
			});
		return route.fulfill({
			json: {
				id: 'workspace-1',
				name: 'Research',
				owner_id: 'user-1',
				state: 'active',
				current_role: 'owner',
				governance_suspended: false,
				effective_capabilities: ['workspace.read', 'workspace.settings.manage']
			}
		});
	});
	await page.goto('/workspace/workspace-1/settings');
	await page.getByLabel('Name', { exact: true }).fill('Rename');
	await page.getByRole('button', { name: 'Save name' }).click();
	await expect(page.getByRole('button', { name: 'Refresh page' })).toBeVisible();
	await expect
		.poll(() =>
			page.evaluate(() => (window as Window & { diagnostics?: unknown[] }).diagnostics?.length)
		)
		.toBe(1);
});

test('metadata version conflict loads the latest Item before explicit retry', async ({ page }) => {
	await mockSession(page);
	await projectCapabilities(page, 'editor', ['workspace.read', 'items.edit']);
	let version = 1;
	const submittedVersions: number[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				...overview,
				item: {
					id: 'item-1',
					title_html: version === 1 ? 'Initial' : 'Updated elsewhere',
					version
				},
				allowed_actions: { edit: true, delete: false }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1', (route) => {
		if (route.request().method() === 'PUT') {
			const body = route.request().postDataJSON() as { expected_version: number };
			submittedVersions.push(body.expected_version);
			if (version === 1) {
				version = 2;
				return route.fulfill({ status: 409, json: { code: 'version_conflict', message: 'stale' } });
			}
			return route.fulfill({ json: { id: 'item-1', version: 3 } });
		}
		return route.fulfill({
			json: {
				id: 'item-1',
				title_html: version === 1 ? 'Initial' : 'Updated elsewhere',
				version,
				metadata: {
					title: version === 1 ? 'Initial' : 'Updated elsewhere',
					keywords: [],
					urls: [],
					authors: [],
					editors: [],
					identifiers: [],
					custom_fields: []
				},
				abstract_html: null,
				editors: [],
				structured_authors: [],
				reference_type: null,
				volume: null,
				issue: null,
				pages: null,
				keywords: null,
				urls: null
			}
		});
	});
	await page.goto('/workspace/workspace-1/item/item-1/metadata');
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Initial');
	await page.getByLabel('Title', { exact: true }).fill('My edit');
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect(page.getByText(/Latest metadata was loaded/)).toBeVisible();
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Updated elsewhere');
	await page.getByLabel('Title', { exact: true }).fill('Reviewed edit');
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect.poll(() => submittedVersions).toEqual([1, 2]);
});
