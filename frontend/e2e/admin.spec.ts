import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

test('administration URL selects and loads the users section', async ({ page }) => {
	await mockSession(page, 'administrator');
	let usersRequests = 0;
	await page.route('**/api/v1/admin/users*', (route) => {
		usersRequests += 1;
		return route.fulfill({
			json: {
				users: [
					{
						id: 'user-2',
						username: 'curator',
						role: 'member',
						active: true,
						created_at: '2026-01-01T00:00:00Z'
					}
				],
				total: 1,
				page: 1,
				per_page: 20,
				invitations: []
			}
		});
	});

	await page.goto('/admin/users');

	await expect.poll(() => usersRequests).toBe(1);
	await expect(page.getByRole('link', { name: 'Users' })).toHaveAttribute('aria-current', 'page');
	await expect(page.getByText('curator', { exact: true })).toBeVisible();
});

test('administrators receive the one-time invitation URL after creation', async ({ page }) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/users*', (route) =>
		route.fulfill({
			json: { users: [], total: 0, page: 1, per_page: 20, invitations: [] }
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
			json: { username: 'invitee', role: 'member', expires_at: '2026-10-01T00:00:00Z' }
		})
	);

	await page.goto('/admin/users');
	await page
		.locator('form')
		.filter({ hasText: 'Invite user' })
		.locator('input[name="username"]')
		.fill('invitee');
	await page.getByRole('button', { name: 'Create invitation' }).click();

	const invitationLink = page.getByRole('link', { name: /invite\/one-time-secret/ });
	await expect(invitationLink).toHaveAttribute('href', /\/invite\/one-time-secret$/);
	await invitationLink.click();
	await expect(page).toHaveURL(/\/invite\/one-time-secret$/);
	await expect(page.getByText('Create a password for')).toBeVisible();
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
					users: [
						{
							id: 'user-2',
							username: 'curator',
							role: 'member',
							active: true,
							created_at: '2026-01-01T00:00:00Z'
						}
					],
					total: 1,
					page: 1,
					per_page: 20,
					invitations: []
				}
			});
		}
		mutations.push({ method: request.method(), path, body: request.postDataJSON() });
		return route.fulfill({ json: { ok: true } });
	});

	await page.goto('/admin/users');
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

test('Workspace governance suspends, recovers, and performs reason-bound break-glass inspection', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let suspended = false;
	let suspendRequests = 0;
	let recoverRequests = 0;
	let inspectionBody: unknown;
	await page.route('**/api/v1/admin/workspaces', (route) =>
		route.fulfill({
			json: [
				{
					id: 'workspace-1',
					name: 'Research',
					owner_id: 'user-1',
					state: 'active',
					governance_suspended_at: suspended ? '2026-09-01T00:00:00Z' : null,
					governance_suspended_by: suspended ? 'admin-1' : null
				}
			]
		})
	);
	await page.route('**/api/v1/admin/workspaces/workspace-1/suspend', (route) => {
		suspendRequests += 1;
		suspended = true;
		return route.fulfill({ json: { ok: true } });
	});
	await page.route('**/api/v1/admin/workspaces/workspace-1/recover', (route) => {
		recoverRequests += 1;
		suspended = false;
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
	await page.getByRole('button', { name: 'Suspend governance' }).click();
	await expect.poll(() => suspendRequests).toBe(1);
	await page.getByRole('button', { name: 'Recover' }).click();
	await expect.poll(() => recoverRequests).toBe(1);
	await page.getByLabel('Target Workspace').selectOption('workspace-1');
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
					governance_suspended_at: null,
					governance_suspended_by: null
				},
				{
					id: 'workspace-2',
					name: 'Archive',
					owner_id: 'owner-2',
					state: 'active',
					governance_suspended_at: null,
					governance_suspended_by: null
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
	await page.getByLabel('Target Workspace').selectOption('workspace-1');
	await page.getByLabel(/Reason/).fill('Investigating a reported access issue');
	await page.getByRole('button', { name: 'Inspect Items once' }).click();
	await expect(page.getByText('Inspected workspace-1')).toBeVisible();
	await page.getByLabel('Target Workspace').selectOption('workspace-2');
	await expect(page.getByText('Scope: Workspace workspace-1')).toBeVisible();
	await expect(page.getByText('Scope: Workspace workspace-2')).toHaveCount(0);
});

test('admin workflow rows render their state contract', async ({ page }) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/workflows', (route) =>
		route.fulfill({
			json: { workflows: [{ id: 'workflow-1', name: 'backup', state: 'succeeded' }] }
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
