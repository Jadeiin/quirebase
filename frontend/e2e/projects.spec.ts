import { directoryPage } from './helpers';
import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

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
			'project.archive',
			'project_item.manage',
			'project_membership.manage',
			'project_discussion.create'
		]
	},
	active_participants: [{ user_id: 'member-1', username: 'researcher' }]
};

async function mockWorkspaceRole(
	page: Parameters<typeof mockSession>[0],
	role: 'owner' | 'admin' | 'editor' | 'viewer',
	allowedActions: string[],
	allowedProjectParticipations: string[] = []
) {
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill({
			json: {
				id: 'workspace-1',
				name: 'Research',
				owner_id: 'user-1',
				state: 'active',
				current_role: role,
				governance_frozen: false,
				allowed_project_participations: allowedProjectParticipations,
				authorization: { allowed: allowedActions }
			}
		})
	);
}

test.beforeEach(async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/members?*', (route) => {
		const search = new URL(route.request().url()).searchParams.get('search')?.toLowerCase() ?? '';
		const members = [
			{ user_id: 'member-1', username: 'researcher', role: 'editor' },
			{ user_id: 'member-2', username: 'collaborator', role: 'reviewer' }
		].filter((member) => member.username.toLowerCase().includes(search));
		return route.fulfill({ json: directoryPage(members, route) });
	});
});

test('Workspace admins can open and govern managed Projects without being participants', async ({
	page
}) => {
	await mockWorkspaceRole(page, 'admin', [
		'workspace.read',
		'project_item.manage',
		'project_membership.manage',
		'project_discussion.create'
	]);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([project], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({ json: project })
	);

	await page.goto('/workspace/workspace-1/projects');
	await page.getByRole('link', { name: /Research direction/ }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/projects\/project-1$/);
	await expect(page.getByRole('heading', { name: 'Participation' })).toBeVisible();
	await expect(page.getByText('researcher', { exact: true })).toBeVisible();
	await expect(page.getByRole('combobox', { name: 'Workspace member' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Items', exact: true })).toBeVisible();
});

test('Workspace-wide Projects are listed separately from joined Projects', async ({ page }) => {
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({
			json: directoryPage(
				[
					{
						...project,
						id: 'workspace-project',
						name: 'Shared library',
						participation: 'workspace',
						is_participating: true
					},
					{
						...project,
						id: 'joined-project',
						name: 'My reading group',
						participation: 'open',
						is_participating: true
					}
				],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);

	await page.goto('/workspace/workspace-1/projects');
	const shared = page.getByRole('heading', { name: 'Workspace Projects' }).locator('..');
	const mine = page.getByRole('heading', { name: 'Your Projects' }).locator('..');
	await expect(shared.getByRole('link', { name: /Shared library/ })).toBeVisible();
	await expect(mine.getByRole('link', { name: /My reading group/ })).toBeVisible();
	await expect(mine.getByRole('link', { name: /Shared library/ })).toHaveCount(0);
});

test('Workspace viewers can read Project Discussion without mutation controls', async ({
	page
}) => {
	await mockWorkspaceRole(page, 'viewer', ['workspace.read']);
	await page.route('**/api/v1/workspaces/workspace-1/projects/visible-project', (route) =>
		route.fulfill({
			json: {
				...project,
				id: 'visible-project',
				name: 'Shared reading group',
				participation: 'workspace',
				is_participating: true,
				authorization: { allowed: [] },
				active_participants: []
			}
		})
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/projects/visible-project/discussions',
		(route) =>
			route.fulfill({
				json: [
					{
						id: 'message-1',
						author_id: 'editor-1',
						author_username: 'editor',
						mine: false,
						body: 'Read-only project note',
						authorization: { allowed: [] },
						created_at: '2026-09-01T12:00:00Z'
					}
				]
			})
	);

	await page.goto('/workspace/workspace-1/projects/visible-project');
	await expect(page.getByRole('heading', { name: 'Discussion' })).toBeVisible();
	await expect(page.getByText('Read-only project note')).toBeVisible();
	await expect(page.getByPlaceholder('Write a message')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0);
});

test('an unjoined archived open Project stays discoverable and its Discussion loads', async ({
	page
}) => {
	await mockWorkspaceRole(page, 'viewer', ['workspace.read']);
	const archivedProject = {
		...project,
		id: 'archived-open',
		name: 'Archived reading group',
		state: 'archived',
		participation: 'open',
		is_participating: false,
		authorization: { allowed: [] },
		active_participants: []
	};
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([archivedProject], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/archived-open', (route) =>
		route.fulfill({ json: archivedProject })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/archived-open/discussions', (route) =>
		route.fulfill({
			json: [
				{
					id: 'archived-message',
					author_id: 'editor-1',
					author_username: 'editor',
					mine: false,
					body: 'Preserved discussion',
					authorization: { allowed: [] },
					created_at: '2026-09-01T12:00:00Z'
				}
			]
		})
	);

	await page.goto('/workspace/workspace-1/projects');
	const archivedSection = page.getByRole('heading', { name: 'Archived Projects' }).locator('..');
	await expect(archivedSection.getByRole('link', { name: /Archived reading group/ })).toBeVisible();
	await expect(archivedSection.getByRole('button', { name: 'Join' })).toHaveCount(0);
	await page.goto('/workspace/workspace-1/projects/archived-open');
	await expect(page.getByText('Preserved discussion')).toBeVisible();
	await expect(page.getByPlaceholder('Write a message')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0);
});

test('an archived Project with delete authority exposes its delete control', async ({ page }) => {
	await mockWorkspaceRole(page, 'admin', ['workspace.read']);
	await page.route(
		'**/api/v1/workspaces/workspace-1/projects/archived-project/discussions',
		(route) => route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/archived-project', (route) =>
		route.fulfill({
			json: {
				...project,
				id: 'archived-project',
				state: 'archived',
				authorization: { allowed: ['project.delete'] }
			}
		})
	);

	await page.goto('/workspace/workspace-1/projects/archived-project');
	await expect(page.getByRole('heading', { name: 'Project settings' })).toHaveCount(0);
	await page.getByRole('button', { name: 'Delete Project' }).click();
	await expect(page.getByText('Permanently delete this Project?')).toBeVisible();
});

test('Workspace admin moderates managed Project Discussion with an audited reason', async ({
	page
}) => {
	await mockWorkspaceRole(page, 'admin', [
		'workspace.read',
		'project_discussion.create',
		'project_discussion.delete'
	]);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({
			json: {
				...project,
				authorization: {
					allowed: ['project_discussion.create', 'project_discussion.delete']
				}
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({
			json: [
				{
					id: 'message-1',
					author_id: 'member-1',
					author_username: 'researcher',
					mine: false,
					body: 'Project note',
					created_at: '2026-09-01T12:00:00Z',
					authorization: { allowed: ['project_discussion.delete'] }
				}
			]
		})
	);
	let reason = '';
	await page.route(
		'**/api/v1/workspaces/workspace-1/projects/project-1/discussions/message-1/moderation',
		async (route) => {
			reason = (route.request().postDataJSON() as { reason: string }).reason;
			await route.fulfill({ json: { ok: true } });
		}
	);
	await page.goto('/workspace/workspace-1/projects/project-1');
	await expect(page.getByText('Project note')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Moderate' }).click();
	await page.getByRole('textbox', { name: 'Moderation reason' }).fill('Off topic');
	await page.getByRole('button', { name: 'Remove message' }).click();
	await expect.poll(() => reason).toBe('Off topic');
});

test('a Workspace editor can create an open Project but not a managed Project', async ({
	page
}) => {
	await mockWorkspaceRole(
		page,
		'editor',
		['workspace.read', 'project_item.manage', 'project_discussion.create'],
		['workspace', 'open']
	);
	let creation: Record<string, unknown> | null = null;
	await page.route('**/api/v1/workspaces/workspace-1/projects*', (route) => {
		if (route.request().method() === 'POST') {
			creation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'project-1' } });
		}
		return route.fulfill({ json: directoryPage([], route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({
			json: {
				...project,
				name: 'Members research',
				description: 'Scoped reading list',
				is_participating: true,
				participation: 'open',
				authorization: {
					allowed: [
						'project.update',
						'project.archive',
						'project_item.manage',
						'project_discussion.create'
					]
				},
				active_participants: [{ user_id: 'user-1', username: 'reader' }]
			}
		})
	);

	await page.goto('/workspace/workspace-1/projects');
	await page.getByRole('button', { name: 'New Project' }).click();
	await page.getByLabel('Name').fill('Members research');
	await page.getByLabel('Description').fill('Scoped reading list');
	await expect(page.getByLabel('Participation').locator('option[value="managed"]')).toHaveCount(0);
	await expect(page.getByLabel('Participation')).toHaveValue('open');
	await page.getByRole('button', { name: 'Create Project' }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/projects\/project-1$/);
	await expect
		.poll(() => creation)
		.toEqual({
			name: 'Members research',
			description: 'Scoped reading list',
			participation: 'open'
		});
	await expect(page.getByRole('listitem').getByText('reader', { exact: true })).toBeVisible();
});

test('a Workspace owner can create an empty managed Project', async ({ page }) => {
	await mockWorkspaceRole(
		page,
		'owner',
		['workspace.read', 'project_item.manage', 'project_membership.manage'],
		['managed', 'open', 'workspace']
	);
	let creation: Record<string, unknown> | null = null;
	await page.route('**/api/v1/workspaces/workspace-1/projects*', (route) => {
		if (route.request().method() === 'POST') {
			creation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'managed-project' } });
		}
		return route.fulfill({ json: directoryPage([], route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/projects/managed-project/discussions',
		(route) => route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/managed-project', (route) =>
		route.fulfill({
			json: {
				...project,
				id: 'managed-project',
				name: 'ICRA 2027',
				participation: 'managed',
				authorization: {
					allowed: [
						'project.update',
						'project.archive',
						'project_item.manage',
						'project_membership.manage'
					]
				},
				active_participants: []
			}
		})
	);

	await page.goto('/workspace/workspace-1/projects');
	await page.getByRole('button', { name: 'New Project' }).click();
	await page.getByLabel('Name').fill('ICRA 2027');
	await page.getByLabel('Participation').selectOption('managed');
	await page.getByRole('button', { name: 'Create Project' }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/projects\/managed-project$/);
	await expect.poll(() => creation).toMatchObject({ name: 'ICRA 2027', participation: 'managed' });
	await expect(page.getByText('No Project participants yet.')).toBeVisible();
});

test('Project creation defaults and submits only the projected participation variant', async ({
	page
}) => {
	await mockWorkspaceRole(page, 'owner', ['workspace.read'], ['open']);
	let participation = '';
	await page.route('**/api/v1/workspaces/workspace-1/projects*', (route) => {
		if (route.request().method() === 'POST') {
			participation = route.request().postDataJSON().participation;
			return route.fulfill({ status: 201, json: { id: 'project-1' } });
		}
		return route.fulfill({ json: directoryPage([], route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({ json: { ...project, participation: 'open', authorization: { allowed: [] } } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.goto('/workspace/workspace-1/projects');
	await page.getByRole('button', { name: 'New Project' }).click();
	const selection = page.getByLabel('Participation');
	await expect(selection.locator('option')).toHaveCount(1);
	await expect(selection).toHaveValue('open');
	await page.getByLabel('Name').fill('Projected Project');
	await page.getByRole('button', { name: 'Create Project' }).click();
	await expect.poll(() => participation).toBe('open');
	await expect(page).toHaveURL(/\/projects\/project-1$/);
});

test('an action without variant projection exposes no Project creation variants', async ({
	page
}) => {
	await mockWorkspaceRole(page, 'owner', ['workspace.read', 'project.create']);
	await page.route('**/api/v1/workspaces/workspace-1/projects*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.goto('/workspace/workspace-1/projects');
	await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'New Project' })).toHaveCount(0);
});

test('Project metadata can change independently of participation variants', async ({ page }) => {
	let submitted: unknown;
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) => {
		if (route.request().method() === 'PATCH') {
			submitted = route.request().postDataJSON();
			return route.fulfill({ json: { id: project.id } });
		}
		return route.fulfill({
			json: {
				...project,
				allowed_participation_changes: [],
				authorization: { allowed: ['project.update'] }
			}
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.goto('/workspace/workspace-1/projects/project-1');
	await expect(page.getByRole('heading', { name: 'Project settings' })).toBeVisible();
	await expect(page.getByLabel('Participation').locator('option')).toHaveCount(1);
	await expect(page.getByLabel('Participation')).toHaveValue('managed');
	await expect(page.getByRole('button', { name: 'Save Project settings' })).toBeEnabled();
	await page.getByLabel('Name', { exact: true }).fill('Updated metadata');
	await page.getByRole('button', { name: 'Save Project settings' }).click();
	await expect
		.poll(() => submitted)
		.toEqual({
			name: 'Updated metadata'
		});
	await expect(page.getByText('Project settings saved')).toBeVisible();
});

test('switching an open Project to managed preserves the participant guidance', async ({
	page
}) => {
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({ json: { ...project, participation: 'open' } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.goto('/workspace/workspace-1/projects/project-1');
	await page.getByLabel('Participation').selectOption('managed');
	await expect(
		page.getByText(
			'Switching between open and managed participation preserves current participants.'
		)
	).toBeVisible();
	await expect(
		page.getByText(
			'A managed Project starts with no participants; Workspace owners/admins can add them.'
		)
	).toHaveCount(0);
});

test('a Workspace viewer cannot discover or deep-link into a managed Project they do not join', async ({
	page
}) => {
	await mockWorkspaceRole(page, 'viewer', ['workspace.read']);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/managed-secret', (route) =>
		route.fulfill({
			status: 404,
			json: { code: 'not_found', message: 'Project not found' }
		})
	);

	await page.goto('/workspace/workspace-1/projects');
	await expect(page.getByText('ICRA 2027', { exact: true })).toHaveCount(0);
	await page.goto('/workspace/workspace-1/projects/managed-secret');
	await expect(page.getByText('Unable to load Project.')).toBeVisible();
});

test('Workspace resource actions govern Project settings and managed participation', async ({
	page
}) => {
	await mockWorkspaceRole(
		page,
		'owner',
		[
			'workspace.read',
			'project_item.manage',
			'project_membership.manage',
			'project.delete',
			'project_discussion.create'
		],
		['managed', 'open', 'workspace']
	);
	const mutations: Array<{ method: string; path: string; body: unknown }> = [];
	let currentParticipation: 'workspace' | 'managed' = 'workspace';
	let participants: Array<{ user_id: string; username: string }> = [];
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1**', (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (request.method() === 'GET' && path.endsWith('/discussions'))
			return route.fulfill({ json: [] });
		if (request.method() === 'GET')
			return route.fulfill({
				json: {
					...project,
					name: 'Research',
					description: 'Initial',
					participation: currentParticipation,
					is_participating: currentParticipation === 'workspace',
					authorization: {
						allowed: [
							'project.update',
							'project.archive',
							'project_item.manage',
							...(currentParticipation === 'managed' ? ['project_membership.manage'] : []),
							'project.delete',
							'project_discussion.create'
						]
					},
					active_participants: participants
				}
			});
		const body = request.postDataJSON();
		mutations.push({ method: request.method(), path, body });
		if (request.method() === 'PATCH')
			currentParticipation = body.participation as 'workspace' | 'managed';
		if (request.method() === 'POST')
			participants = [...participants, { user_id: 'member-2', username: 'collaborator' }];
		return route.fulfill({ json: { ok: true, id: 'project-1' } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);

	await page.goto('/workspace/workspace-1/projects/project-1');
	await expect(page.getByRole('heading', { name: 'Research' })).toBeVisible();
	await page.getByLabel('Name', { exact: true }).fill('Renamed research');
	await page.getByLabel('Description').fill('Updated');
	await page.getByLabel('Participation').selectOption('managed');
	await expect(
		page.getByText(
			'A managed Project starts with no participants; Workspace owners/admins can add them.'
		)
	).toBeVisible();
	await page.getByRole('button', { name: 'Save Project settings' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PATCH',
			path: '/api/v1/workspaces/workspace-1/projects/project-1',
			body: { name: 'Renamed research', description: 'Updated', participation: 'managed' }
		});
	await page.getByRole('combobox', { name: 'Workspace member' }).fill('collab');
	await page.getByRole('option', { name: 'collaborator', exact: true }).click();
	await page.getByRole('button', { name: 'Add participant' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'POST',
			path: '/api/v1/workspaces/workspace-1/projects/project-1/participants',
			body: { username: 'collaborator' }
		});
});

test('a managed Project may have zero participants', async ({ page }) => {
	await mockWorkspaceRole(page, 'owner', [
		'workspace.read',
		'project_item.manage',
		'project_membership.manage'
	]);
	let participants = [{ user_id: 'user-1', username: 'reader' }];
	await page.route('**/api/v1/workspaces/workspace-1/projects/empty-project**', (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (request.method() === 'GET' && path.endsWith('/discussions'))
			return route.fulfill({ json: [] });
		if (request.method() === 'DELETE' && path.endsWith('/participants/user-1')) {
			participants = [];
			return route.fulfill({ json: { ok: true } });
		}
		return route.fulfill({
			json: {
				...project,
				id: 'empty-project',
				name: 'Paused direction',
				authorization: { allowed: ['project_membership.manage'] },
				active_participants: participants
			}
		});
	});

	await page.goto('/workspace/workspace-1/projects/empty-project');
	await expect(page.getByRole('heading', { name: 'Paused direction' })).toBeVisible();
	await page.getByRole('button', { name: 'Remove', exact: true }).click();
	await expect(page.getByText('No Project participants yet.')).toBeVisible();
});

test('managed participant selection filters existing participants and requires a directory choice', async ({
	page
}) => {
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({ json: project })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.goto('/workspace/workspace-1/projects/project-1');
	const selection = page.getByRole('combobox', { name: 'Workspace member' });
	await selection.click();
	await expect(page.getByRole('option', { name: 'researcher', exact: true })).toHaveCount(0);
	await expect(page.getByRole('option', { name: 'collaborator', exact: true })).toBeVisible();
	await Promise.all([
		page.waitForResponse((response) => {
			const url = new URL(response.url());
			return (
				url.pathname.endsWith('/members') && url.searchParams.get('search') === 'unlisted-user'
			);
		}),
		selection.fill('unlisted-user')
	]);
	await expect(page.getByText('No matching members.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Add participant' })).toBeDisabled();
	await selection.fill('collab');
	await page.getByRole('option', { name: 'collaborator', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Add participant' })).toBeEnabled();
	await selection.fill('researcher');
	await expect(page.getByRole('button', { name: 'Add participant' })).toBeDisabled();
});

for (const mode of ['open', 'managed']) {
	test(`switching ${mode} to Workspace participation confirms permanent selection loss even with no visible participants`, async ({
		page
	}) => {
		let writes = 0;
		let submitted: unknown;
		await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) => {
			if (route.request().method() === 'PATCH') {
				writes++;
				submitted = route.request().postDataJSON();
				return route.fulfill({ json: { id: project.id } });
			}
			// Suspended participants are retained in storage but omitted from this read model.
			return route.fulfill({ json: { ...project, participation: mode, active_participants: [] } });
		});
		await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
			route.fulfill({ json: [] })
		);
		await page.goto('/workspace/workspace-1/projects/project-1');
		await page.getByLabel('Participation').selectOption('workspace');
		await page.getByRole('button', { name: 'Save Project settings' }).click();
		const confirmation = page.getByRole('dialog');
		await expect(confirmation).toContainText('including suspended members');
		expect(writes).toBe(0);
		await confirmation.getByRole('button', { name: 'Cancel' }).click();
		await expect(confirmation).toHaveCount(0);
		expect(writes).toBe(0);
		await page.getByRole('button', { name: 'Save Project settings' }).click();
		await page.getByRole('button', { name: 'Clear selection and save' }).click();
		await expect.poll(() => submitted).toEqual({ participation: 'workspace' });
		expect(writes).toBe(1);
	});
}

test('Project history navigation discards pending participant-clear changes', async ({ page }) => {
	const patches: Array<{ projectId: string; body: unknown }> = [];
	for (const id of ['project-a', 'project-b']) {
		await page.route(`**/api/v1/workspaces/workspace-1/projects/${id}`, (route) => {
			if (route.request().method() === 'PATCH') {
				patches.push({ projectId: id, body: route.request().postDataJSON() });
				return route.fulfill({ json: { id } });
			}
			return route.fulfill({ json: { ...project, id, name: id } });
		});
		await page.route(`**/api/v1/workspaces/workspace-1/projects/${id}/discussions`, (route) =>
			route.fulfill({ json: [] })
		);
	}
	await page.goto('/workspace/workspace-1/projects/project-b');
	await expect(page.getByRole('heading', { name: 'project-b', exact: true })).toBeVisible();
	// Use the client router to create adjacent detail entries that reuse the component.
	await page.evaluate(() => {
		const link = document.createElement('a');
		link.href = '/workspace/workspace-1/projects/project-a';
		link.textContent = 'Open Project A';
		document.body.append(link);
	});
	await page.getByRole('link', { name: 'Open Project A', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'project-a', exact: true })).toBeVisible();
	await page.getByLabel('Name', { exact: true }).fill('Unconfirmed Project A rename');
	await page.getByLabel('Participation').selectOption('workspace');
	await page.getByRole('button', { name: 'Save Project settings' }).click();
	const confirmation = page.getByRole('dialog', { name: 'Clear Project participant selection?' });
	await expect(confirmation).toBeVisible();

	await page.goBack();
	await expect(page).toHaveURL(/\/projects\/project-b$/);
	await expect(confirmation).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'project-b', exact: true })).toBeVisible();
	await expect(page.getByLabel('Name', { exact: true })).toHaveValue('project-b');
	await expect(page.getByText('researcher', { exact: true })).toBeVisible();
	expect(patches).toEqual([]);
	await page.getByLabel('Name', { exact: true }).fill('Unconfirmed Project B rename');
	await page.getByLabel('Participation').selectOption('workspace');
	await page.getByRole('button', { name: 'Save Project settings' }).click();
	await expect(confirmation).toBeVisible();

	await page.goForward();
	await expect(page).toHaveURL(/\/projects\/project-a$/);
	await expect(confirmation).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'project-a', exact: true })).toBeVisible();
	await expect(page.getByLabel('Name', { exact: true })).toHaveValue('project-a');
	expect(patches).toEqual([]);
	await page.getByLabel('Participation').selectOption('workspace');
	await page.getByRole('button', { name: 'Save Project settings' }).click();
	await confirmation.getByRole('button', { name: 'Clear selection and save' }).click();
	await expect
		.poll(() => patches)
		.toEqual([{ projectId: 'project-a', body: { participation: 'workspace' } }]);
});

test('Project groups come from one collection while Join follows the server capability', async ({
	page
}) => {
	const requests: string[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) => {
		requests.push(new URL(route.request().url()).searchParams.get('view') ?? 'all');
		return route.fulfill({
			json: directoryPage(
				[
					{
						...project,
						id: 'joinable',
						name: 'Joinable direction',
						participation: 'open',
						authorization: { allowed: ['project_membership.join'] }
					},
					{
						...project,
						id: 'visible',
						name: 'Visible direction',
						participation: 'open',
						authorization: { allowed: [] }
					}
				],
				route
			)
		});
	});
	await page.goto('/workspace/workspace-1/projects');
	const open = page.getByRole('heading', { name: 'Open Projects', exact: true }).locator('..');
	await expect(open.getByText('Visible direction')).toBeVisible();
	await expect(open.getByRole('button', { name: 'Join', exact: true })).toHaveCount(1);
	expect(requests).toEqual(['all']);
});

test('participant selection reaches later member pages and clears after adding', async ({
	page
}) => {
	const members = Array.from({ length: 28 }, (_, index) => ({
		user_id: `person-${index}`,
		username: `researcher-${String(index).padStart(2, '0')}`,
		role: 'editor'
	}));
	const selected = members[27];
	const added: string[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/members?*', (route) => {
		const search = new URL(route.request().url()).searchParams.get('search') ?? '';
		return route.fulfill({
			json: directoryPage(
				members.filter((member) => member.username.includes(search)),
				route
			)
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({
			json: {
				...project,
				active_participants: members.filter((member) => added.includes(member.username))
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/participants', (route) => {
		added.push(route.request().postDataJSON().username);
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/projects/project-1');
	await page.getByRole('button', { name: 'Load more members' }).click();
	const input = page.getByRole('combobox', { name: 'Workspace member' });
	await input.click();
	await page.getByRole('option', { name: selected.username, exact: true }).click();
	await expect(input).toHaveValue(selected.username);
	const add = page.getByRole('button', { name: 'Add participant', exact: true });
	await expect(add).toBeEnabled();
	await add.click();
	await expect(page.getByText('Project participant added', { exact: true })).toBeVisible();
	await expect(add).toBeDisabled();
	await expect(input).toHaveValue('');
	expect(added).toEqual([selected.username]);
	await input.fill('missing-person');
	await expect(page.getByText('No matching members.')).toBeVisible();
	await expect(input).toHaveValue('missing-person');
	await expect(add).toBeDisabled();
	await input.fill('researcher-26');
	await page.getByRole('option', { name: 'researcher-26', exact: true }).click();
	await expect(add).toBeEnabled();
	await input.fill('edited-input');
	await expect(add).toBeDisabled();
});

test('Project Item pages recover after removing the last Item and support search', async ({
	page
}) => {
	let assigned = Array.from({ length: 26 }, (_, index) => ({
		id: `item-${index}`,
		title_html: `Assigned Item ${String(index).padStart(2, '0')}`,
		version: 1,
		authors: null
	}));
	const requests: Array<{ project: string | null; offset: number }> = [];
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({
			json: {
				...project,
				participation: 'workspace',
				item_count: assigned.length,
				active_participants: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const params = new URL(route.request().url()).searchParams;
		requests.push({ project: params.get('project'), offset: Number(params.get('offset')) });
		const search = params.get('query') ?? '';
		return route.fulfill({
			json: directoryPage(
				assigned.filter((item) => item.title_html.includes(search)),
				route
			)
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/items/item-25', (route) => {
		assigned = assigned.filter((item) => item.id !== 'item-25');
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/projects/project-1');
	const pager = page.getByRole('navigation', { name: 'Items pagination' });
	await pager.getByRole('button', { name: 'Next', exact: true }).click();
	const last = page.getByRole('link', { name: 'Assigned Item 25', exact: true }).locator('..');
	await expect(last).toBeVisible();
	await last.getByRole('button', { name: 'Remove', exact: true }).click();
	await expect(pager.getByText('Page 1 of 1')).toBeVisible();
	await expect(page.getByText('Assigned Item 00', { exact: true })).toBeVisible();
	expect(requests.some((request) => request.offset === 25)).toBe(true);
	expect(requests.every((request) => request.project === 'project-1')).toBe(true);
	await page.getByRole('textbox', { name: 'Search Items' }).fill('Assigned Item 12');
	await expect(page.getByText('Assigned Item 12', { exact: true })).toBeVisible();
	await expect(page.getByText('Assigned Item 00', { exact: true })).toHaveCount(0);
});
