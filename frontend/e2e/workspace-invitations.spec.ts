import { expect, test } from '@playwright/test';
import { mockSession, workspaceView } from './helpers';

test('revoking a Workspace invitation retires its displayed one-time link', async ({ page }) => {
	await mockSession(page);
	const view = workspaceView('workspace-1', 'Research');
	await page.route('**/api/v1/workspaces/workspace-1', (route) => route.fulfill({ json: view }));
	await page.route('**/api/v1/workspaces/workspace-1/governance/members?*', (route) =>
		route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
	);
	let created = false;
	const revoked = new Set<string>();
	let failRevoke = true;
	await page.route('**/api/v1/workspaces/workspace-1/invitations', (route) => {
		if (route.request().method() === 'POST') {
			created = true;
			return route.fulfill({
				status: 201,
				json: {
					id: 'workspace-invitation',
					user_id: 'invited-user-id',
					username: 'invited-user',
					role: 'viewer',
					expires_at: '2099-01-01T00:00:00Z',
					token: 'workspace-audit-token'
				}
			});
		}
		const items = [
			{
				id: 'older-invitation',
				username: 'earlier-invitee',
				role: 'viewer',
				expires_at: '2099-01-01T00:00:00Z'
			}
		];
		if (created)
			items.push({
				id: 'workspace-invitation',
				username: 'invited-user',
				role: 'viewer',
				expires_at: '2099-01-01T00:00:00Z'
			});
		return route.fulfill({ json: items.filter((invitation) => !revoked.has(invitation.id)) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/invitations/*', (route) => {
		if (failRevoke) {
			failRevoke = false;
			return route.fulfill({
				status: 500,
				json: { code: 'internal_error', message: 'Revoke failed' }
			});
		}
		revoked.add(route.request().url().split('/').at(-1)!);
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/settings');
	await page.getByLabel('Exact username').fill('invited-user');
	await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
	await expect(page.getByText(/invite\/workspace-audit-token/)).toBeVisible();
	const currentRow = page.getByRole('listitem').filter({ hasText: 'invited-user' });
	await currentRow.getByRole('button', { name: 'Revoke', exact: true }).click();
	await expect(page.getByRole('alert')).toBeVisible();
	await expect(page.getByText(/invite\/workspace-audit-token/)).toBeVisible();
	await page
		.getByRole('listitem')
		.filter({ hasText: 'earlier-invitee' })
		.getByRole('button', { name: 'Revoke', exact: true })
		.click();
	await expect(page.getByText('Invitation revoked', { exact: true })).toBeVisible();
	await expect(page.getByText(/invite\/workspace-audit-token/)).toBeVisible();
	await currentRow.getByRole('button', { name: 'Revoke', exact: true }).click();
	await expect(page.getByText('Invitation revoked', { exact: true })).toBeVisible();
	await expect(page.getByText(/invite\/workspace-audit-token/)).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Copy one-time link', exact: true })).toHaveCount(
		0
	);
});
