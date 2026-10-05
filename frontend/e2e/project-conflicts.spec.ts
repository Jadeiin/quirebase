import { expect, test, type Page } from '@playwright/test';
import type { AnnotationPlugin, PluginRegistry } from '@embedpdf/svelte-pdf-viewer';
import { annotationList, minimalPdf, mockSession } from './helpers';

function trackWorkspaceReads(page: Page) {
	const reads: string[] = [];
	page.on('request', (request) => {
		const path = new URL(request.url()).pathname;
		if (
			request.method() === 'GET' &&
			(path === '/api/v1/workspaces' || path === '/api/v1/workspaces/workspace-1')
		) {
			reads.push(path);
		}
	});
	return reads;
}

for (const assigned of [false, true]) {
	test(`Organize refreshes after a Project is archived during ${assigned ? 'Remove' : 'Add'}`, async ({
		page
	}) => {
		await mockSession(page);
		const workspaceReads = trackWorkspaceReads(page);
		let archived = false;
		const methods: string[] = [];
		await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
			route.fulfill({
				json: {
					item: { id: 'item-1', title_html: 'Reading Item', version: 1 },
					latest_revision: null,
					authorization: { allowed: [] },
					counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
					tags: [],
					identifiers: [],
					copy_targets: []
				}
			})
		);
		await page.route('**/api/v1/workspaces/workspace-1/items/item-1/organize', (route) =>
			route.fulfill({
				json: {
					authorization: { allowed: ['project_item.manage'] },
					projects: archived ? [] : [{ id: 'project-1', name: 'Reading Project', assigned }],
					tags: [],
					tag_matrix: {
						groups: [],
						assigned_ids: [],
						recommended_ids: [],
						suggested_names: [],
						recommendation_error: null,
						recommendation_state: 'pending'
					}
				}
			})
		);
		await page.route(
			'**/api/v1/workspaces/workspace-1/projects/project-1/items/item-1',
			(route) => {
				methods.push(route.request().method());
				archived = true;
				return route.fulfill({
					status: 409,
					json: { code: 'project_lifecycle_error', message: 'archived' }
				});
			}
		);

		await page.goto('/workspace/workspace-1/item/item-1/organize');
		const action = page.getByRole('button', { name: assigned ? 'Remove' : 'Add', exact: true });
		await expect(action).toBeEnabled();
		const initialWorkspaceReads = [...workspaceReads];
		await action.click();
		await expect(page.getByText('This Project is read only in its current state.')).toBeVisible();
		await expect(page.getByText('No available projects.')).toBeVisible();
		await expect(action).toHaveCount(0);
		expect(methods).toEqual([assigned ? 'DELETE' : 'PUT']);
		expect(workspaceReads).toEqual(initialWorkspaceReads);
	});
}

test('Library refreshes Project targets on a lifecycle conflict and keeps selected Items', async ({
	page
}) => {
	await mockSession(page);
	const workspaceReads = trackWorkspaceReads(page);
	let archived = false;
	const submissions: Array<{ project_id: string; item_ids: string[] }> = [];
	await page.route('**/api/v1/workspaces/workspace-1/tags', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all', (route) =>
		route.fulfill({
			json: [
				{
					id: 'project-1',
					name: 'Reading Project',
					state: archived ? 'archived' : 'active',
					participation: 'workspace',
					is_member: true,
					item_count: 0,
					description: null,
					authorization: { allowed: archived ? [] : ['project_item.manage'] }
				},
				{
					id: 'project-2',
					name: 'Another Project',
					state: 'active',
					participation: 'workspace',
					is_member: true,
					item_count: 0,
					description: null,
					authorization: { allowed: ['project_item.manage'] }
				}
			]
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'item-1',
						title_html: 'Reading Item',
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
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		const body = route.request().postDataJSON();
		submissions.push(body);
		if (body.project_id === 'project-1') {
			archived = true;
			return route.fulfill({
				status: 409,
				json: { code: 'project_lifecycle_error', message: 'archived' }
			});
		}
		return route.fulfill({ json: { ok: true } });
	});

	await page.goto('/workspace/workspace-1/library');
	await page.getByLabel('Select this page').check();
	await page.getByLabel('Bulk action').selectOption('add_project');
	const target = page.getByLabel('Select Project', { exact: true });
	await target.selectOption('project-1');
	const initialWorkspaceReads = [...workspaceReads];
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	await expect(page.getByText('This Project is read only in its current state.')).toBeVisible();
	await expect(target.locator('option[value="project-1"]')).toHaveCount(0);
	await expect(target).toHaveValue('');
	await expect(page.getByRole('button', { name: 'Apply', exact: true })).toBeDisabled();
	await expect(page.getByText('1 selected')).toBeVisible();
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await expect(
		page
			.getByRole('combobox', { name: 'Project', exact: true })
			.locator('option[value="project-1"]')
	).toHaveText('Reading Project');
	// An archived Project remains a read filter, but cannot receive selected Items.
	expect(workspaceReads).toEqual(initialWorkspaceReads);

	await target.selectOption('project-2');
	await page.getByRole('button', { name: 'Apply', exact: true }).click();
	await expect(page.getByText('Bulk action completed')).toBeVisible();
	expect(submissions.map(({ project_id, item_ids }) => ({ project_id, item_ids }))).toEqual([
		{ project_id: 'project-1', item_ids: ['item-1'] },
		{ project_id: 'project-2', item_ids: ['item-1'] }
	]);
});

for (const code of ['project_member_conflict', 'project_lifecycle_error']) {
	test(`Projects refreshes both lists after Join returns ${code}`, async ({ page }) => {
		await mockSession(page);
		const workspaceReads = trackWorkspaceReads(page);
		let changed = false;
		const listReads = { all: 0, joinable: 0 };
		await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) => {
			const view = new URL(route.request().url()).searchParams.get('view') as 'all' | 'joinable';
			listReads[view]++;
			const project = {
				id: 'project-1',
				name: 'Reading Project',
				state: changed && code === 'project_lifecycle_error' ? 'archived' : 'active',
				participation: changed && code === 'project_member_conflict' ? 'managed' : 'open',
				is_member: false,
				item_count: 0,
				description: '',
				authorization: { allowed: [] }
			};
			return route.fulfill({ json: view === 'joinable' && changed ? [] : [project] });
		});
		await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/join', (route) => {
			changed = true;
			return route.fulfill({ status: 409, json: { code, message: 'changed elsewhere' } });
		});

		await page.goto('/workspace/workspace-1/projects');
		const join = page.getByRole('button', { name: 'Join', exact: true });
		await expect(join).toBeEnabled();
		const initialWorkspaceReads = [...workspaceReads];
		await join.click();
		await expect(page.getByText('No open Projects are available to join.')).toBeVisible();
		await expect(join).toHaveCount(0);
		await expect(
			page.getByRole('heading', {
				name: code === 'project_member_conflict' ? 'Managed participation' : 'Archived Projects',
				exact: true
			})
		).toBeVisible();
		expect(listReads).toEqual({ all: 2, joinable: 2 });
		expect(workspaceReads).toEqual(initialWorkspaceReads);
	});
}

for (const action of ['Delete', 'Moderate']) {
	test(`Project Discussion refreshes message permissions after ${action} conflicts with archiving`, async ({
		page
	}) => {
		await mockSession(page);
		const workspaceReads = trackWorkspaceReads(page);
		let archived = false;
		await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
			route.fulfill({
				json: {
					id: 'project-1',
					name: 'Reading Project',
					description: '',
					state: archived ? 'archived' : 'active',
					participation: 'workspace',
					item_count: 0,
					items: [],
					members: [],
					authorization: { allowed: archived ? [] : ['project_discussion.create'] }
				}
			})
		);
		await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
			route.fulfill({
				json: [true, false].map((mine) => ({
					id: mine ? 'own' : 'other',
					author_id: mine ? 'user-1' : 'user-2',
					author_username: mine ? 'reader' : 'another',
					mine,
					body: mine ? 'Own message' : 'Other message',
					created_at: '2026-09-16T00:00:00Z',
					authorization: { allowed: archived ? [] : ['project_discussion.delete'] }
				}))
			})
		);
		await page.route(
			'**/api/v1/workspaces/workspace-1/projects/project-1/discussions/**',
			(route) => {
				archived = true;
				return route.fulfill({
					status: 409,
					json: { code: 'project_lifecycle_error', message: 'archived' }
				});
			}
		);

		await page.goto('/workspace/workspace-1/projects/project-1');
		await expect(page.getByRole('button', { name: 'Delete', exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Moderate', exact: true })).toBeVisible();
		const initialWorkspaceReads = [...workspaceReads];
		await page.getByRole('button', { name: action, exact: true }).click();
		if (action === 'Moderate') {
			await page.getByRole('textbox', { name: 'Moderation reason' }).fill('Policy violation');
			await page.getByRole('button', { name: 'Remove message', exact: true }).click();
		}
		await expect(page.getByText('This Project is read only in its current state.')).toBeVisible();
		await expect(page.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0);
		await expect(page.getByRole('button', { name: 'Moderate', exact: true })).toHaveCount(0);
		await expect(page.getByRole('button', { name: 'Post', exact: true })).toHaveCount(0);
		await expect(page.getByText('Own message', { exact: true })).toBeVisible();
		await expect(page.getByText('Other message', { exact: true })).toBeVisible();
		expect(workspaceReads).toEqual(initialWorkspaceReads);
	});
}

for (const operation of ['create', 'update', 'reply', 'version']) {
	test(`PDF refreshes only the affected permissions after a ${operation} conflict`, async ({
		page
	}) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await mockSession(page);
		const workspaceReads = trackWorkspaceReads(page);
		let archived = false;
		let viewerReads = 0;
		let annotationReads = 0;
		let contentReads = 0;
		const writes: string[] = [];
		await page.route(
			'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/viewer',
			(route) => {
				viewerReads++;
				return route.fulfill({
					json: {
						item: { id: 'item-1', title_html: 'Reading Item', version: 1 },
						editable: true,
						annotation_author: 'reader',
						projects: [{ id: 'project-1', name: 'Shared', editable: !archived }],
						revision: {
							id: 'revision-1',
							original_name: 'paper.pdf',
							page_count: 1,
							processing_state: 'ready',
							page_geometry: [[0, 0, 300, 400]],
							content_url:
								'/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content'
						}
					}
				});
			}
		);
		await page.route(
			'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/content',
			(route) => {
				contentReads++;
				return route.fulfill({ contentType: 'application/pdf', body: minimalPdf() });
			}
		);
		await page.route('**/api/v1/workspaces/workspace-1/items/item-1/annotations**', (route) => {
			const request = route.request();
			if (request.method() !== 'GET') {
				writes.push(new URL(request.url()).pathname);
				archived = operation !== 'version';
				return route.fulfill({
					status: 409,
					json: {
						code: archived ? 'project_lifecycle_error' : 'version_conflict',
						message: 'changed elsewhere'
					}
				});
			}
			annotationReads++;
			return route.fulfill({
				json: annotationList(
					['private', 'project'].map((scope) => ({
						id: `${scope}-note`,
						revision_id: 'revision-1',
						page_index: 0,
						kind: 'note',
						scope,
						project_id: scope === 'project' ? 'project-1' : null,
						body: `${scope} note`,
						selected_text: null,
						payload: { type: 'note', rect: { x: 20, y: 30, width: 24, height: 24 } },
						version: 1,
						author_display_name: 'reader',
						editable: scope === 'private' || !archived,
						created_at: '2026-09-16T00:00:00Z',
						updated_at: '2026-09-16T00:00:00Z',
						replies:
							scope === 'project'
								? [
										{
											id: 'reply-1',
											annotation_id: 'project-note',
											body: 'Original reply',
											version: 1,
											editable: !archived,
											author_display_name: 'reader',
											created_at: '2026-09-16T00:00:00Z',
											updated_at: '2026-09-16T00:00:00Z'
										}
									]
								: []
					}))
				)
			});
		});

		await page.goto('/workspace/workspace-1/item/item-1/pdf/revision-1?project_id=project-1');
		await expect(page.getByText('2 annotations loaded')).toBeAttached();
		const destination = page.getByRole('combobox', { name: 'New annotation source', exact: true });
		await destination.selectOption('project-1');
		const modeSelector = page.locator('[data-epdf-i="mode-select-button"] button');
		await expect(modeSelector).toBeVisible();
		const initialWorkspaceReads = [...workspaceReads];
		const initialContentReads = contentReads;
		await page.locator('embedpdf-container').evaluate(async (element, operation) => {
			const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
				.registry;
			const scope = registry
				.getPlugin<AnnotationPlugin>('annotation')!
				.provides()
				.forDocument('revision-1');
			if (operation === 'create') {
				const original = scope.getAnnotationById('project-note')!.object;
				scope.createAnnotation(0, { ...original, id: 'rejected-note', contents: 'Rejected mark' });
			} else {
				scope.updateAnnotation(0, operation === 'reply' ? 'reply-1' : 'project-note', {
					contents: 'Rejected edit'
				});
			}
		}, operation);
		await expect.poll(() => writes.length).toBe(1);
		if (operation === 'reply') expect(writes[0]).toContain('/replies/reply-1');
		await expect.poll(() => annotationReads).toBeGreaterThan(1);
		const readonly = operation !== 'version';
		await expect(destination.locator('option[value="project-1"]')).toHaveJSProperty(
			'disabled',
			readonly
		);
		if (await page.getByText('private note', { exact: true }).isVisible()) {
			// Creating a note opens a mobile drawer; dismiss its backdrop before using the toolbar.
			await page.locator('embedpdf-container .bg-bg-overlay').click({ position: { x: 5, y: 5 } });
		}
		if (readonly) {
			await expect(modeSelector).toBeHidden();
			await expect(page.getByRole('button', { name: 'Annotate', exact: true })).toBeHidden();
		} else {
			await modeSelector.click();
			await expect(page.getByRole('menuitem', { name: 'Annotate', exact: true })).toBeEnabled();
			await page.getByRole('menuitem', { name: 'View', exact: true }).click();
		}
		await expect
			.poll(() =>
				page.locator('embedpdf-container').evaluate(async (element) => {
					const registry = await (element as HTMLElement & { registry: Promise<PluginRegistry> })
						.registry;
					const scope = registry
						.getPlugin<AnnotationPlugin>('annotation')!
						.provides()
						.forDocument('revision-1');
					return {
						rejected: Boolean(scope.getAnnotationById('rejected-note')),
						projectReadonly:
							scope.getAnnotationById('project-note')?.object.flags?.includes('readOnly') ?? false,
						privateReadonly:
							scope.getAnnotationById('private-note')?.object.flags?.includes('readOnly') ?? false,
						replyBody: scope.getAnnotationById('reply-1')?.object.contents
					};
				})
			)
			.toEqual({
				rejected: false,
				projectReadonly: readonly,
				privateReadonly: false,
				replyBody: 'Original reply'
			});
		expect(viewerReads).toBe(readonly ? 2 : 1);
		expect(contentReads).toBe(initialContentReads);
		expect(workspaceReads).toEqual(initialWorkspaceReads);
		await destination.selectOption('');
		await modeSelector.click();
		await expect(page.getByRole('menuitem', { name: 'Annotate', exact: true })).toBeEnabled();
	});
}
