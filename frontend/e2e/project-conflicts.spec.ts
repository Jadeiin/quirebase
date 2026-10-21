import { openLibraryAction } from './helpers';
import { tagPage, chooseSearchOption } from './helpers';
import { directoryPage, projectPage } from './helpers';
import { expect, test, type Page } from '@playwright/test';
import type { AnnotationPlugin, PluginRegistry } from '@embedpdf/svelte-pdf-viewer';
import { annotationList, minimalPdf, mockSession, setAnnotationWriteSource } from './helpers';

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

test('Organize prioritizes working contexts without restricting other Project assignments', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Reading Item'
				},
				citation_key: null,
				id: 'item-1',
				version: 1,
				latest_revision_id: null,
				authorization: { allowed: [] },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				copy_targets: []
			}
		})
	);
	const projects = [
		{
			id: 'workspace',
			name: 'Shared Workspace',
			assigned: false,
			is_participating: true,
			participation: 'workspace'
		},
		{
			id: 'joined',
			name: 'Joined direction',
			assigned: false,
			is_participating: true,
			participation: 'open'
		},
		{
			id: 'assigned',
			name: 'Already assigned',
			assigned: true,
			is_participating: false,
			participation: 'open'
		},
		{
			id: 'other',
			name: 'Other open direction',
			assigned: false,
			is_participating: false,
			participation: 'open'
		},
		{
			id: 'managed',
			name: 'Governed direction',
			assigned: false,
			is_participating: false,
			participation: 'managed'
		}
	];
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/organize', (route) =>
		route.fulfill({
			json: {
				authorization: { allowed: ['project_item.manage'] },
				projects,
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
	const writes: string[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/projects/*/items/item-1', (route) => {
		writes.push(new URL(route.request().url()).pathname);
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/item/item-1/organize');
	await expect(page.getByText('Shared Workspace', { exact: true })).toBeVisible();
	await expect(page.getByText('Joined direction', { exact: true })).toBeVisible();
	await expect(page.getByText('Already assigned', { exact: true })).toBeVisible();
	await expect(page.getByText('Other open direction', { exact: true })).toBeHidden();
	await expect(page.getByText('Governed direction', { exact: true })).toBeHidden();
	const other = page.locator('details').filter({ hasText: 'Other open Projects' });
	await other.locator('summary').click();
	await other.getByRole('textbox', { name: 'Search Projects' }).fill('absent');
	await expect(other.getByText('No matching Projects.')).toBeVisible();
	await other.getByRole('textbox', { name: 'Search Projects' }).fill('open');
	await other.getByRole('button', { name: 'Add', exact: true }).click();
	await expect
		.poll(() => writes)
		.toContain('/api/v1/workspaces/workspace-1/projects/other/items/item-1');
	const managed = page.locator('details').filter({ hasText: 'Managed Projects' });
	await managed.locator('summary').click();
	await managed.getByRole('button', { name: 'Add', exact: true }).click();
	await expect
		.poll(() => writes)
		.toContain('/api/v1/workspaces/workspace-1/projects/managed/items/item-1');
});

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
					metadata: {
						id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
						type: 'Other',
						title: 'Reading Item'
					},
					citation_key: null,
					id: 'item-1',
					version: 1,
					latest_revision_id: null,
					authorization: { allowed: [] },
					counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
					tags: [],
					copy_targets: []
				}
			})
		);
		await page.route('**/api/v1/workspaces/workspace-1/items/item-1/organize', (route) =>
			route.fulfill({
				json: {
					authorization: { allowed: ['project_item.manage'] },
					projects: archived
						? []
						: [
								{
									id: 'project-1',
									name: 'Reading Project',
									assigned,
									participation: 'workspace',
									is_participating: true
								}
							],
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
		if (assigned) {
			const dialog = page.getByRole('dialog', { name: 'Remove Item from Project?' });
			await dialog.getByRole('button', { name: 'Remove from Project' }).click();
			await expect(dialog).toContainText('This Project is read only in its current state.');
			await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
		}
		await expect(page.getByRole('main').getByRole('alert')).toHaveText(
			'This Project is read only in its current state.'
		);
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
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	const projects = () => [
		{
			id: 'project-1',
			name: 'Reading Project',
			state: archived ? 'archived' : 'active',
			participation: 'workspace',
			is_participating: true,
			item_count: 0,
			created_at: '2026-09-01T00:00:00Z',
			updated_at: '2026-09-02T00:00:00Z',
			description: null,
			authorization: { allowed: archived ? [] : ['project_item.manage'] }
		},
		{
			id: 'project-2',
			name: 'Another Project',
			state: 'active',
			participation: 'workspace',
			is_participating: true,
			item_count: 0,
			created_at: '2026-09-01T00:00:00Z',
			updated_at: '2026-09-02T00:00:00Z',
			description: null,
			authorization: { allowed: ['project_item.manage'] }
		}
	];
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: projectPage(projects(), route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-*', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-1);
		return route.fulfill({
			json: { ...projects().find((project) => project.id === id), active_participants: [] }
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'item-1',
						title_html: 'Reading Item',
						authors: [],
						publication_date: null,
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 1,
				limit: 25,
				offset: 0
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
	await openLibraryAction(page, 'add_project');
	const target = page.getByRole('combobox', { name: 'Select Project', exact: true });
	await chooseSearchOption(page, 'Select Project', 'Reading Project');
	const initialWorkspaceReads = [...workspaceReads];
	await page
		.getByRole('dialog')
		.getByRole('button', { name: 'Add to Project', exact: true })
		.click();
	await expect(page.getByText('This Project is read only in its current state.')).toBeVisible();
	await page
		.getByRole('dialog')
		.getByRole('button', { name: 'Change options', exact: true })
		.click();
	await expect(target).toHaveValue('');
	await expect(
		page.getByRole('dialog').getByRole('button', { name: 'Add to Project', exact: true })
	).toBeDisabled();
	await expect(page.locator('#library-results [data-library-item-select]:checked')).toHaveCount(1);
	// The failed target is removed from assignable choices without probing Workspace.
	expect(workspaceReads).toEqual(initialWorkspaceReads);

	await target.click();
	await expect(page.getByRole('listbox', { name: 'Select Project', exact: true })).toBeVisible();
	await expect(page.getByRole('option', { name: 'Reading Project', exact: true })).toHaveCount(0);
	await chooseSearchOption(page, 'Select Project', 'Another Project');
	await page
		.getByRole('dialog')
		.getByRole('button', { name: 'Add to Project', exact: true })
		.click();
	await expect(page.getByText('Bulk action completed')).toBeVisible();
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await page.getByRole('combobox', { name: 'Project', exact: true }).click();
	await expect(page.getByRole('option', { name: 'Reading Project', exact: true })).toBeVisible();
	await page.getByRole('combobox', { name: 'Project', exact: true }).press('Escape');
	expect(submissions.map(({ project_id, item_ids }) => ({ project_id, item_ids }))).toEqual([
		{ project_id: 'project-1', item_ids: ['item-1'] },
		{ project_id: 'project-2', item_ids: ['item-1'] }
	]);
});

for (const code of ['project_participation_conflict', 'project_lifecycle_error']) {
	test(`Projects refreshes its collection after Join returns ${code}`, async ({ page }) => {
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
				participation: changed && code === 'project_participation_conflict' ? 'managed' : 'open',
				is_participating: false,
				item_count: 0,
				created_at: '2026-09-01T00:00:00Z',
				updated_at: '2026-09-02T00:00:00Z',
				description: '',
				authorization: { allowed: changed ? [] : ['project_participation.join'] }
			};
			return route.fulfill({
				json: directoryPage(view === 'joinable' && changed ? [] : [project], route)
			});
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
		await expect(join).toHaveCount(0);
		const row = page
			.getByRole('list', { name: 'Projects', exact: true })
			.getByRole('listitem', { name: 'Reading Project', exact: true });
		await expect(row.getByRole('link', { name: 'Reading Project', exact: true })).toBeVisible();
		await expect(
			row.getByText(code === 'project_participation_conflict' ? 'Managed' : 'Archived', {
				exact: true
			})
		).toBeVisible();
		expect(listReads).toEqual({ all: 2, joinable: 0 });
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
					created_at: '2026-09-01T00:00:00Z',
					updated_at: '2026-09-02T00:00:00Z',
					active_participants: [],
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
		await setAnnotationWriteSource(page, 'Shared');
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
				const original = scope.getAnnotationById('annotation:project-note')!.object;
				scope.createAnnotation(0, { ...original, id: 'rejected-note', contents: 'Rejected mark' });
			} else {
				scope.updateAnnotation(
					0,
					operation === 'reply' ? 'reply:reply-1' : 'annotation:project-note',
					{
						contents: 'Rejected edit'
					}
				);
			}
		}, operation);
		await expect.poll(() => writes.length).toBe(1);
		if (operation === 'reply') expect(writes[0]).toContain('/replies/reply-1');
		await expect.poll(() => annotationReads).toBeGreaterThan(1);
		const readonly = operation !== 'version';
		const sources = page.getByRole('button', { name: 'Displayed annotation sources', exact: true });
		await sources.click();
		if (readonly)
			await expect(page.getByRole('radio', { name: 'Shared', exact: true })).toBeDisabled();
		else await expect(page.getByRole('radio', { name: 'Shared', exact: true })).toBeEnabled();
		await sources.click();
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
							scope
								.getAnnotationById('annotation:project-note')
								?.object.flags?.includes('readOnly') ?? false,
						privateReadonly:
							scope
								.getAnnotationById('annotation:private-note')
								?.object.flags?.includes('readOnly') ?? false,
						replyBody: scope.getAnnotationById('reply:reply-1')?.object.contents
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
		await setAnnotationWriteSource(page, 'Private annotations');
		await modeSelector.click();
		await expect(page.getByRole('menuitem', { name: 'Annotate', exact: true })).toBeEnabled();
	});
}
