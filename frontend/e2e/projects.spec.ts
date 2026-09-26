import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

const project = {
	id: 'project-1',
	name: 'Research direction',
	description: 'A Workspace research context',
	item_count: 0,
	state: 'active',
	visibility: 'managed',
	is_member: false,
	allowed_actions: ['settings', 'archive', 'items.manage', 'members.manage', 'discussion.write'],
	items: [],
	members: [{ user_id: 'member-1', username: 'researcher' }]
};

async function mockWorkspaceRole(
	page: Parameters<typeof mockSession>[0],
	role: 'owner' | 'admin' | 'editor' | 'viewer',
	capabilities: string[]
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
				effective_capabilities: capabilities
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
		'projects.manage',
		'projects.members.manage',
		'discussion.write'
	]);
	await page.route('**/api/v1/workspaces/workspace-1/projects/joinable', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects', (route) =>
		route.fulfill({ json: [{ ...project, allowed_actions: [...project.allowed_actions] }] })
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
				visibility: 'workspace',
				is_member: true,
				allowed_actions: [],
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
						body: 'Read-only project note',
						allowed_actions: [],
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
		visibility: 'open',
		is_member: false,
		allowed_actions: [],
		members: []
	};
	await page.route('**/api/v1/workspaces/workspace-1/projects', (route) =>
		route.fulfill({ json: [archivedProject] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/joinable', (route) =>
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
					body: 'Preserved discussion',
					allowed_actions: [],
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

test('Workspace admin moderates managed Project Discussion with an audited reason', async ({
	page
}) => {
	await mockSession(page);
	await mockWorkspaceRole(page, 'admin', [
		'workspace.read',
		'discussion.write',
		'discussion.moderate'
	]);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({
			json: { ...project, allowed_actions: ['discussion.write', 'discussion.moderate'] }
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({
			json: [
				{
					id: 'message-1',
					author_id: 'member-1',
					author_username: 'researcher',
					body: 'Project note',
					created_at: '2026-09-01T12:00:00Z',
					allowed_actions: ['moderate']
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
	await mockWorkspaceRole(page, 'editor', [
		'workspace.read',
		'projects.create',
		'projects.manage',
		'discussion.write'
	]);
	let creation: Record<string, unknown> | null = null;
	await page.route('**/api/v1/workspaces/workspace-1/projects', (route) => {
		if (route.request().method() === 'POST') {
			creation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'project-1' } });
		}
		return route.fulfill({ json: [] });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects/joinable', (route) =>
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
				visibility: 'open',
				allowed_actions: ['settings', 'archive', 'items.manage', 'discussion.write'],
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
		.toEqual({ name: 'Members research', description: 'Scoped reading list', visibility: 'open' });
	await expect(page.getByRole('listitem').getByText('reader', { exact: true })).toBeVisible();
});

test('a Workspace owner can create an empty managed Project', async ({ page }) => {
	await mockSession(page);
	await mockWorkspaceRole(page, 'owner', [
		'workspace.read',
		'projects.create',
		'projects.create_managed',
		'projects.manage',
		'projects.members.manage'
	]);
	let creation: Record<string, unknown> | null = null;
	await page.route('**/api/v1/workspaces/workspace-1/projects', (route) => {
		if (route.request().method() === 'POST') {
			creation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'managed-project' } });
		}
		return route.fulfill({ json: [] });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects/joinable', (route) =>
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
				visibility: 'managed',
				allowed_actions: ['settings', 'archive', 'items.manage', 'members.manage'],
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
	await expect.poll(() => creation).toMatchObject({ name: 'ICRA 2027', visibility: 'managed' });
	await expect(page.getByText('No Project participants yet.')).toBeVisible();
});

test('a Workspace viewer cannot discover or deep-link into a managed Project they do not join', async ({
	page
}) => {
	await mockSession(page);
	await mockWorkspaceRole(page, 'viewer', ['workspace.read']);
	await page.route('**/api/v1/workspaces/workspace-1/projects', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/joinable', (route) =>
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

test('Workspace capabilities govern Project settings and managed participation', async ({
	page
}) => {
	await mockSession(page);
	await mockWorkspaceRole(page, 'owner', [
		'workspace.read',
		'projects.create_managed',
		'projects.manage',
		'projects.members.manage',
		'projects.delete',
		'discussion.write'
	]);
	const mutations: Array<{ method: string; path: string; body: unknown }> = [];
	let currentVisibility: 'workspace' | 'managed' = 'workspace';
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
					visibility: currentVisibility,
					is_member: currentVisibility === 'workspace',
					allowed_actions: [
						'settings',
						'archive',
						'items.manage',
						...(currentVisibility === 'managed' ? ['members.manage'] : []),
						'delete',
						'discussion.write'
					],
					members: participants
				}
			});
		const body = request.postDataJSON();
		mutations.push({ method: request.method(), path, body });
		if (request.method() === 'PATCH')
			currentVisibility = body.visibility as 'workspace' | 'managed';
		if (request.method() === 'PUT')
			participants = [...participants, { user_id: 'member-2', username: 'collaborator' }];
		return route.fulfill({ json: { ok: true, id: 'project-1' } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects', (route) =>
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
			body: { name: 'Renamed research', description: 'Updated', visibility: 'managed' }
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
		'projects.manage',
		'projects.members.manage'
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
				allowed_actions: ['members.manage'],
				members: participants
			}
		});
	});

	await page.goto('/workspace/workspace-1/projects/empty-project');
	await expect(page.getByRole('heading', { name: 'Paused direction' })).toBeVisible();
	await page.getByRole('button', { name: 'Remove', exact: true }).click();
	await expect(page.getByText('No Project participants yet.')).toBeVisible();
});
