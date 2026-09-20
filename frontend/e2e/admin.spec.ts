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
				accept_path: '/invitation/one-time-secret'
			}
		})
	);

	await page.goto('/admin/users');
	await page
		.locator('form')
		.filter({ hasText: 'Invite user' })
		.locator('input[name="username"]')
		.fill('invitee');
	await page.getByRole('button', { name: 'Create invitation' }).click();

	await expect(page.getByRole('link', { name: /invitation\/one-time-secret/ })).toBeVisible();
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

test('administration filters and paginates server-side collections', async ({ page }) => {
	await mockSession(page, 'administrator');
	const requests: string[] = [];
	await page.route('**/api/v1/admin/items*', (route) => {
		requests.push(route.request().url());
		const pageNumber = Number(new URL(route.request().url()).searchParams.get('page') ?? '1');
		return route.fulfill({
			json: {
				items: [],
				total: 40,
				page: pageNumber,
				per_page: 20,
				storage: { total_disk_bytes: 0 }
			}
		});
	});

	await page.goto('/admin/items');
	await page.getByLabel('PDF availability').selectOption('true');
	await page.getByRole('button', { name: 'Apply filters' }).click();
	await expect
		.poll(() => requests.some((url) => new URL(url).searchParams.get('has_pdf') === 'true'))
		.toBe(true);
	await page.getByRole('button', { name: 'Next' }).click();
	await expect
		.poll(() => requests.some((url) => new URL(url).searchParams.get('page') === '2'))
		.toBe(true);
});

test('administration resets section-specific filters during navigation', async ({ page }) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/users*', (route) =>
		route.fulfill({
			json: { users: [], total: 0, page: 1, per_page: 20, invitations: [] }
		})
	);
	let projectRequest = '';
	await page.route('**/api/v1/admin/projects*', (route) => {
		projectRequest = route.request().url();
		return route.fulfill({ json: { projects: [], total: 0, page: 1, per_page: 20 } });
	});

	await page.goto('/admin/users');
	await page.getByLabel('Role').selectOption('member');
	await page.getByRole('button', { name: 'Apply filters' }).click();
	await page
		.getByRole('navigation', { name: 'Administration sections' })
		.getByRole('link', { name: 'Projects' })
		.click();

	await expect.poll(() => projectRequest).not.toBe('');
	expect(new URL(projectRequest).searchParams.get('state')).toBeNull();
	expect(new URL(projectRequest).searchParams.get('visibility')).toBeNull();
	expect(new URL(projectRequest).searchParams.get('page')).toBe('1');
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
