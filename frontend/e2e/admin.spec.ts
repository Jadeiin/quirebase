import { chooseSearchOption } from './helpers';
import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

test('administration URL selects and loads the users section', async ({ page }) => {
	await mockSession(page, 'administrator');
	let usersRequests = 0;
	let invitationsRequests = 0;
	await page.route('**/api/v1/admin/invitations?*', (route) => {
		invitationsRequests += 1;
		return route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0 } });
	});
	await page.route('**/api/v1/admin/users*', (route) => {
		usersRequests += 1;
		return route.fulfill({
			json: {
				items: [
					{
						id: 'user-2',
						username: 'curator',
						role: 'member',
						active: true,
						created_at: '2026-01-01T00:00:00Z'
					}
				],
				total: 1,
				limit: 20,
				offset: 0,
				invitations: []
			}
		});
	});

	await page.goto('/admin/users');

	await expect.poll(() => usersRequests).toBe(1);
	await expect(page.getByRole('link', { name: 'Users' })).toHaveAttribute('aria-current', 'page');
	await expect(page.getByText('curator', { exact: true })).toBeVisible();
	await expect(
		page.getByRole('navigation', { name: 'Administration pages', exact: true })
	).toHaveCount(1);
	await expect(page.getByRole('navigation', { name: 'Invitation pages', exact: true })).toHaveCount(
		0
	);
	await expect(page.getByRole('button', { name: 'Invite user', exact: true })).toHaveCount(0);
	expect(invitationsRequests).toBe(0);
	await page.getByRole('link', { name: 'Invitations', exact: true }).click();
	await expect(page).toHaveURL(/\/admin\/invitations$/);
	await expect(page.getByRole('link', { name: 'Invitations', exact: true })).toHaveAttribute(
		'aria-current',
		'page'
	);
	await expect(page.getByRole('navigation', { name: 'Invitation pages', exact: true })).toHaveCount(
		1
	);
	await expect(
		page.getByRole('navigation', { name: 'Administration pages', exact: true })
	).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Create user', exact: true })).toHaveCount(0);
	expect(usersRequests).toBe(1);
});

test('administrators receive the one-time invitation URL after creation', async ({ page }) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/users*', (route) =>
		route.fulfill({
			json: { items: [], total: 0, limit: 20, offset: 0, invitations: [] }
		})
	);
	await page.route('**/api/v1/admin/invitations', (route) =>
		route.fulfill({
			status: 201,
			json: {
				id: 'invitation-1',
				username: 'invitee',
				role: 'member',
				expires_at: '2026-10-01T00:00:00Z',
				token: 'one-time-secret',
				accept_path: '/invite/one-time-secret'
			}
		})
	);
	await page.route('**/api/v1/invitations/one-time-secret', (route) =>
		route.fulfill({
			json: {
				kind: 'account',
				username: 'invitee',
				role: 'member',
				expires_at: '2026-10-01T00:00:00Z'
			}
		})
	);

	await page.goto('/admin/invitations');
	await page.getByRole('button', { name: 'Invite user', exact: true }).click();
	await page
		.locator('form')
		.filter({ hasText: 'Create invitation' })
		.locator('input[name="username"]')
		.fill('invitee');
	await page.getByRole('button', { name: 'Create invitation' }).click();

	const invitationLink = page.getByRole('link', { name: /invite\/one-time-secret/ });
	await expect(invitationLink).toHaveAttribute('href', /\/invite\/one-time-secret$/);
	await invitationLink.click();
	await expect(page).toHaveURL(/\/invite\/one-time-secret$/);
	await expect(page.getByText('Create a password for')).toBeVisible();
});

test('user creation opens on demand and remains in the users section', async ({ page }) => {
	await mockSession(page, 'administrator');
	const users: Array<{
		id: string;
		username: string;
		role: string;
		active: boolean;
		created_at: string;
	}> = [];
	let submitted: unknown;
	await page.route('**/api/v1/admin/users**', (route) => {
		if (route.request().method() === 'POST') {
			submitted = route.request().postDataJSON();
			users.push({
				id: 'new-user',
				username: 'new-reader',
				role: 'member',
				active: true,
				created_at: '2026-10-17T00:00:00Z'
			});
			return route.fulfill({ status: 201, json: users[0] });
		}
		return route.fulfill({ json: { items: users, total: users.length, limit: 20, offset: 0 } });
	});
	await page.goto('/admin/users');
	await expect(page.getByLabel('Username', { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Create user', exact: true }).click();
	const form = page
		.locator('form')
		.filter({ has: page.getByRole('heading', { name: 'Create user', exact: true }) });
	await form.getByLabel('Username', { exact: true }).fill('new-reader');
	await form.getByLabel('Password', { exact: true }).fill('new-reader-password');
	await form.getByRole('button', { name: 'Create user', exact: true }).click();
	await expect(page.getByRole('status')).toHaveText('User created');
	expect(submitted).toEqual({
		username: 'new-reader',
		password: 'new-reader-password',
		role: 'member'
	});
	await expect(page.getByRole('article', { name: 'new-reader', exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Invite user', exact: true })).toHaveCount(0);
});

for (const width of [390, 1440]) {
	test(`separate management lists fit at ${width}px`, async ({ page }) => {
		await page.setViewportSize({ width, height: 950 });
		await mockSession(page, 'administrator');
		await page.route('**/api/v1/admin/users?*', (route) =>
			route.fulfill({
				json: {
					items: [
						{
							id: 'curator',
							username: 'research-curator',
							role: 'member',
							active: true,
							created_at: '2026-01-01T00:00:00Z'
						}
					],
					total: 1,
					limit: 20,
					offset: 0
				}
			})
		);
		await page.route('**/api/v1/admin/invitations?*', (route) =>
			route.fulfill({
				json: {
					items: [
						{
							id: 'invitation',
							username: 'new-researcher',
							role: 'member',
							state: 'pending',
							created_at: '2026-10-17T00:00:00Z',
							expires_at: '2026-10-24T00:00:00Z'
						}
					],
					total: 1,
					limit: 20,
					offset: 0
				}
			})
		);
		await page.goto('/admin/users');
		await page.getByText('Manage user', { exact: true }).click();
		await expect(page.getByRole('button', { name: 'Reset password', exact: true })).toBeVisible();
		await expect
			.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
			.toBe(true);
		await page.screenshot({ path: `/tmp/quirebase-admin-users-${width}.png`, fullPage: true });
		await page.getByRole('link', { name: 'Invitations', exact: true }).click();
		await expect(page.getByText('new-researcher', { exact: true })).toBeVisible();
		await expect(
			page.getByRole('navigation', { name: 'Invitation pages', exact: true })
		).toHaveCount(1);
		await expect
			.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
			.toBe(true);
		await page.screenshot({
			path: `/tmp/quirebase-admin-invitations-${width}.png`,
			fullPage: true
		});
	});
}

test('invitation page owns its pagination, statuses, revocation and reissue', async ({ page }) => {
	await mockSession(page, 'administrator');
	let usersRequests = 0;
	await page.route('**/api/v1/admin/users?*', (route) => {
		usersRequests += 1;
		return route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0 } });
	});
	const invitations = Array.from({ length: 21 }, (_, index) => ({
		id: `invitation-${index}`,
		username: `invitee-${index}`,
		role: 'member',
		state: ['pending', 'expired', 'revoked', 'accepted'][Math.min(index, 3)],
		created_at: '2026-01-01T00:00:00Z',
		expires_at: '2027-01-01T00:00:00Z'
	}));
	await page.route('**/api/v1/admin/invitations?*', (route) => {
		const params = new URL(route.request().url()).searchParams;
		const state = params.get('state');
		const rows = invitations.filter((invitation) => !state || invitation.state === state);
		const offset = Number(params.get('offset') ?? 0);
		const limit = Number(params.get('limit') ?? 20);
		return route.fulfill({
			json: { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset }
		});
	});
	await page.route('**/api/v1/admin/invitations/*/reissue', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2);
		const invitation = invitations.find((row) => row.id === id)!;
		invitation.state = 'revoked';
		invitations.unshift({ ...invitation, id: 'replacement', state: 'pending' });
		return route.fulfill({
			status: 201,
			json: {
				...invitations[0],
				token: 'replacement-secret',
				accept_path: '/invite/replacement-secret'
			}
		});
	});
	await page.route('**/api/v1/admin/invitations/replacement', (route) => {
		invitations.find((row) => row.id === 'replacement')!.state = 'revoked';
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/admin/invitations');
	await expect(page.getByRole('button', { name: 'Reissue invitation link' })).toHaveCount(2);
	await expect(
		page.locator('article').getByText('Accepted', { exact: true }).first()
	).toBeVisible();
	await expect(page.locator('article').getByText('Revoked', { exact: true }).first()).toBeVisible();
	const pagination = page.getByRole('navigation', { name: 'Invitation pages', exact: true });
	await pagination.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.getByText('invitee-20', { exact: true })).toBeVisible();
	expect(usersRequests).toBe(0);
	await page.getByLabel('Invitation status', { exact: true }).selectOption('pending');
	await expect(pagination.getByText('Page 1 of 1')).toBeVisible();
	await page.getByRole('button', { name: 'Reissue invitation link' }).click();
	const link = page.getByRole('link', { name: /invite\/replacement-secret/ });
	await expect(link).toBeVisible();
	await page.getByRole('button', { name: 'Revoke invitation', exact: true }).click();
	await expect(link).toHaveCount(0);
	await expect(page.getByText('No invitations.', { exact: true })).toBeVisible();
});

test('administrators can respond to compromised user accounts', async ({ page }) => {
	await mockSession(page, 'administrator');
	const mutations: Array<{ method: string; path: string; body: unknown }> = [];
	await page.route('**/api/v1/admin/users**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (request.method() === 'GET' && path === '/api/v1/admin/users') {
			return route.fulfill({
				json: {
					items: [
						{
							id: 'user-2',
							username: 'curator',
							role: 'member',
							active: true,
							created_at: '2026-01-01T00:00:00Z'
						}
					],
					total: 1,
					limit: 20,
					offset: 0,
					invitations: []
				}
			});
		}
		mutations.push({ method: request.method(), path, body: request.postDataJSON() });
		return route.fulfill({ json: { ok: true } });
	});

	await page.goto('/admin/users');
	await expect(page.getByLabel('Role for curator')).not.toBeVisible();
	await page.getByText('Manage user', { exact: true }).click();
	await page.getByLabel('Role for curator').selectOption('administrator');
	await page.getByRole('button', { name: 'Save role' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/admin/users/user-2/role',
			body: { role: 'administrator' }
		});
	await expect(page.getByRole('status')).toHaveText('User role saved');

	const statusButton = page.getByRole('button', { name: 'Disable user' });
	await expect(statusButton).toBeEnabled();
	await statusButton.click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/admin/users/user-2/status',
			body: { active: false }
		});
	await expect(page.getByRole('status')).toHaveText('User disabled');

	await page.getByLabel('New password for curator').fill('replacement-password');
	const resetPasswordButton = page.getByRole('button', { name: 'Reset password' });
	await expect(resetPasswordButton).toBeEnabled();
	await resetPasswordButton.click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/admin/users/user-2/password',
			body: { password: 'replacement-password' }
		});
	await expect(page.getByRole('status')).toHaveText('User password reset');

	const revokeSessionsButton = page.getByRole('button', { name: 'Revoke sessions' });
	await expect(revokeSessionsButton).toBeEnabled();
	await revokeSessionsButton.click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'DELETE',
			path: '/api/v1/admin/users/user-2/sessions',
			body: null
		});
});

test('Workspace governance freezes, unfreezes, and performs reason-bound break-glass inspection', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let frozen = false;
	let freezeRequests = 0;
	let unfreezeRequests = 0;
	let inspectionBody: unknown;
	await page.route('**/api/v1/admin/workspaces', (route) =>
		route.fulfill({
			json: [
				{
					id: 'workspace-1',
					name: 'Research',
					owner_id: 'user-1',
					state: 'active',
					governance_frozen_at: frozen ? '2026-09-01T00:00:00Z' : null,
					governance_frozen_by: frozen ? 'admin-1' : null
				}
			]
		})
	);
	await page.route('**/api/v1/admin/workspaces/workspace-1/freeze', (route) => {
		freezeRequests += 1;
		frozen = true;
		return route.fulfill({ json: { ok: true } });
	});
	await page.route('**/api/v1/admin/workspaces/workspace-1/unfreeze', (route) => {
		unfreezeRequests += 1;
		frozen = false;
		return route.fulfill({ json: { ok: true } });
	});
	await page.route('**/api/v1/admin/workspaces/workspace-1/break-glass/items', (route) => {
		inspectionBody = route.request().postDataJSON();
		return route.fulfill({
			json: [
				{
					id: 'item-1',
					title_html: 'Read-only inspection',
					authors: 'A. Reader',
					publication_date: '2026',
					publication_title: null,
					doi: null,
					version: 1
				}
			]
		});
	});

	await page.goto('/admin/workspaces');
	await expect(page.locator('article').getByText('Research', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Freeze writes' }).click();
	await expect.poll(() => freezeRequests).toBe(1);
	await page.getByRole('button', { name: 'Unfreeze writes' }).click();
	await expect.poll(() => unfreezeRequests).toBe(1);
	await chooseSearchOption(page, 'Target Workspace', 'Research');
	await page.getByLabel(/Reason/).fill('Investigating a reported access issue');
	await page.getByRole('button', { name: 'Inspect Items once' }).click();
	await expect
		.poll(() => inspectionBody)
		.toEqual({ reason: 'Investigating a reported access issue' });
	await expect(page.getByText('BREAK GLASS', { exact: true }).last()).toBeVisible();
	await expect(page.getByText('Read-only inspection')).toBeVisible();
});

test('break-glass inspection keeps the Workspace that authorized the displayed result', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/workspaces', (route) =>
		route.fulfill({
			json: [
				{
					id: 'workspace-1',
					name: 'Research',
					owner_id: 'owner-1',
					state: 'active',
					governance_frozen_at: null,
					governance_frozen_by: null
				},
				{
					id: 'workspace-2',
					name: 'Archive',
					owner_id: 'owner-2',
					state: 'active',
					governance_frozen_at: null,
					governance_frozen_by: null
				}
			]
		})
	);
	await page.route('**/api/v1/admin/workspaces/*/break-glass/items', (route) => {
		const workspaceId = new URL(route.request().url()).pathname.split('/')[5];
		return route.fulfill({
			json: [
				{
					id: `item-${workspaceId}`,
					title_html: `Inspected ${workspaceId}`,
					authors: null,
					publication_date: null,
					publication_title: null,
					doi: null,
					version: 1
				}
			]
		});
	});

	await page.goto('/admin/workspaces');
	await chooseSearchOption(page, 'Target Workspace', 'Research');
	await page.getByLabel(/Reason/).fill('Investigating a reported access issue');
	await page.getByRole('button', { name: 'Inspect Items once' }).click();
	await expect(page.getByText('Inspected workspace-1')).toBeVisible();
	await chooseSearchOption(page, 'Target Workspace', 'Archive');
	await expect(page.getByText('Scope: Workspace workspace-1')).toBeVisible();
	await expect(page.getByText('Scope: Workspace workspace-2')).toHaveCount(0);
});

test('admin workflow rows render their state contract', async ({ page }) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/workflows?*', (route) =>
		route.fulfill({
			json: {
				items: [{ id: 'workflow-1', name: 'backup', state: 'succeeded' }],
				total: 1,
				limit: 20,
				offset: 0
			}
		})
	);

	await page.goto('/admin/workflows');

	await expect(page.locator('section').getByText('Succeeded', { exact: true })).toBeVisible();

	await page.route('**/api/v1/admin/maintenance', (route) =>
		route.fulfill({
			json: {
				storage: { items_count: 1, total_disk_bytes: 100 },
				workflows: [{ id: 'workflow-2', name: 'reindex', state: 'running' }]
			}
		})
	);
	await page.goto('/admin/maintenance');
	await expect(page.getByText('Running', { exact: true })).toBeVisible();
});
