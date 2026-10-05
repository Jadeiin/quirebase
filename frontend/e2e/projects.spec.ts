import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

const project = {
	id: 'project-1',
	name: 'Research direction',
	description: 'A Workspace research context',
	item_count: 0,
	state: 'active',
	participation: 'managed',
	is_member: false,
	authorization: {
		allowed: [
			'project.update',
			'project.archive',
			'project_item.manage',
			'project_membership.manage',
			'project_discussion.create'
		],
		relations: { 'project.update': ['workspace', 'open', 'managed'] }
	},
	items: [],
	members: [{ user_id: 'member-1', username: 'researcher' }]
};

async function mockWorkspaceRole(
	page: Parameters<typeof mockSession>[0],
	role: 'owner' | 'admin' | 'editor' | 'viewer',
	allowedActions: string[],
	relations: Record<string, string[]> = {}
) {
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill({
			json: {
				id: 'workspace-1',
				name: 'Research',
				owner_id: 'user-1',
				state: 'active',
				current_role: role,
				governance_suspended: false,
				authorization: { allowed: allowedActions, relations }
			}
		})
	);
}

test('Workspace admins can open and govern managed Projects without being participants', async ({
	page
}) => {
	await mockSession(page);
	await mockWorkspaceRole(page, 'admin', [
		'workspace.read',
		'project_item.manage',
		'project_membership.manage',
		'project_discussion.create'
	]);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all', (route) =>
		route.fulfill({ json: [project] })
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
	await expect(page.getByPlaceholder('Exact username')).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Items', exact: true })).toBeVisible();
});

test('Workspace-wide Projects are listed separately from joined Projects', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all', (route) =>
		route.fulfill({
			json: [
				{
					...project,
					id: 'workspace-project',
					name: 'Shared library',
					participation: 'workspace',
					is_member: true
				},
				{
					...project,
					id: 'joined-project',
					name: 'My reading group',
					participation: 'open',
					is_member: true
				}
			]
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable', (route) =>
		route.fulfill({ json: [] })
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
	await mockSession(page);
	await mockWorkspaceRole(page, 'viewer', ['workspace.read']);
	await page.route('**/api/v1/workspaces/workspace-1/projects/visible-project', (route) =>
		route.fulfill({
			json: {
				...project,
				id: 'visible-project',
				name: 'Shared reading group',
				participation: 'workspace',
				is_member: true,
				authorization: { allowed: [] },
				members: []
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
	await mockSession(page);
	await mockWorkspaceRole(page, 'viewer', ['workspace.read']);
	const archivedProject = {
		...project,
		id: 'archived-open',
		name: 'Archived reading group',
		state: 'archived',
		participation: 'open',
		is_member: false,
		authorization: { allowed: [] },
		members: []
	};
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all', (route) =>
		route.fulfill({ json: [archivedProject] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable', (route) =>
		route.fulfill({ json: [] })
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
	await mockSession(page);
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
	await mockSession(page);
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
	await mockSession(page);
	await mockWorkspaceRole(
		page,
		'editor',
		['workspace.read', 'project_item.manage', 'project_discussion.create'],
		{ 'project.create': ['open', 'workspace'] }
	);
	let creation: Record<string, unknown> | null = null;
	await page.route('**/api/v1/workspaces/workspace-1/projects*', (route) => {
		if (route.request().method() === 'POST') {
			creation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'project-1' } });
		}
		return route.fulfill({ json: [] });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable', (route) =>
		route.fulfill({ json: [] })
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
				is_member: true,
				participation: 'open',
				authorization: {
					allowed: [
						'project.update',
						'project.archive',
						'project_item.manage',
						'project_discussion.create'
					]
				},
				members: [{ user_id: 'user-1', username: 'reader' }]
			}
		})
	);

	await page.goto('/workspace/workspace-1/projects');
	await page.getByRole('button', { name: 'New Project' }).click();
	await page.getByLabel('Name').fill('Members research');
	await page.getByLabel('Description').fill('Scoped reading list');
	await expect(page.getByLabel('Participation').locator('option[value="managed"]')).toHaveCount(0);
	await page.getByLabel('Participation').selectOption('open');
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
	await mockSession(page);
	await mockWorkspaceRole(
		page,
		'owner',
		['workspace.read', 'project_item.manage', 'project_membership.manage'],
		{ 'project.create': ['managed', 'open', 'workspace'] }
	);
	let creation: Record<string, unknown> | null = null;
	await page.route('**/api/v1/workspaces/workspace-1/projects*', (route) => {
		if (route.request().method() === 'POST') {
			creation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'managed-project' } });
		}
		return route.fulfill({ json: [] });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable', (route) =>
		route.fulfill({ json: [] })
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
				members: []
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
	await mockSession(page);
	await mockWorkspaceRole(page, 'owner', ['workspace.read'], {
		'project.create': ['open']
	});
	let participation = '';
	await page.route('**/api/v1/workspaces/workspace-1/projects*', (route) => {
		if (route.request().method() === 'POST') {
			participation = route.request().postDataJSON().participation;
			return route.fulfill({ status: 201, json: { id: 'project-1' } });
		}
		return route.fulfill({ json: [] });
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

test('an action without relation projection exposes no Project creation variants', async ({
	page
}) => {
	await mockSession(page);
	await mockWorkspaceRole(page, 'owner', ['workspace.read', 'project.create']);
	await page.route('**/api/v1/workspaces/workspace-1/projects*', (route) =>
		route.fulfill({ json: [] })
	);
	await page.goto('/workspace/workspace-1/projects');
	await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'New Project' })).toHaveCount(0);
});

test('Project settings cannot submit a participation without relation projection', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({ json: { ...project, authorization: { allowed: ['project.update'] } } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.goto('/workspace/workspace-1/projects/project-1');
	await expect(page.getByRole('heading', { name: 'Project settings' })).toBeVisible();
	await expect(page.getByLabel('Participation').locator('option')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Save Project settings' })).toBeDisabled();
});

test('a Workspace viewer cannot discover or deep-link into a managed Project they do not join', async ({
	page
}) => {
	await mockSession(page);
	await mockWorkspaceRole(page, 'viewer', ['workspace.read']);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=joinable', (route) =>
		route.fulfill({ json: [] })
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
	await mockSession(page);
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
		{ 'project.create': ['managed', 'open', 'workspace'] }
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
					is_member: currentParticipation === 'workspace',
					authorization: {
						allowed: [
							'project.update',
							'project.archive',
							'project_item.manage',
							...(currentParticipation === 'managed' ? ['project_membership.manage'] : []),
							'project.delete',
							'project_discussion.create'
						],
						relations: { 'project.update': ['workspace', 'open', 'managed'] }
					},
					members: participants
				}
			});
		const body = request.postDataJSON();
		mutations.push({ method: request.method(), path, body });
		if (request.method() === 'PATCH')
			currentParticipation = body.participation as 'workspace' | 'managed';
		if (request.method() === 'PUT')
			participants = [...participants, { user_id: 'member-2', username: 'collaborator' }];
		return route.fulfill({ json: { ok: true, id: 'project-1' } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all', (route) =>
		route.fulfill({ json: [] })
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
	await page.getByPlaceholder('Exact username').fill('collaborator');
	await page.getByRole('button', { name: 'Add participant' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/workspaces/workspace-1/projects/project-1/members',
			body: { username: 'collaborator' }
		});
});

test('a managed Project may have zero participants', async ({ page }) => {
	await mockSession(page);
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
		if (request.method() === 'DELETE' && path.endsWith('/members/user-1')) {
			participants = [];
			return route.fulfill({ json: { ok: true } });
		}
		return route.fulfill({
			json: {
				...project,
				id: 'empty-project',
				name: 'Paused direction',
				authorization: { allowed: ['project_membership.manage'] },
				members: participants
			}
		});
	});

	await page.goto('/workspace/workspace-1/projects/empty-project');
	await expect(page.getByRole('heading', { name: 'Paused direction' })).toBeVisible();
	await page.getByRole('button', { name: 'Remove', exact: true }).click();
	await expect(page.getByText('No Project participants yet.')).toBeVisible();
});
