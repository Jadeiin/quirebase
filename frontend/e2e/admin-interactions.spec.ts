import { expect, test } from '@playwright/test';
import { chooseSearchOption, mockSession } from './helpers';

const adminWorkspace = (id: string) => ({
	id,
	name: `Research ${id}`,
	owner_id: `owner-${id}`,
	owner_username: `owner-${id}`,
	owner_active: true,
	can_reassign_owner: true,
	state: 'active',
	governance_frozen_at: null,
	governance_frozen_by: null
});
const adminUser = (id: string) => ({
	id,
	username: id,
	role: 'member',
	active: true,
	created_at: '2026-01-01T00:00:00Z'
});

for (const ownerFilter of ['initial-owner-name', 'initial-owner-id']) {
	test(`owner conflict preserves the reassignment draft filtered by ${ownerFilter}`, async ({
		page
	}) => {
		await mockSession(page, 'administrator');
		let currentOwner = { id: 'initial-owner-id', username: 'initial-owner-name' };
		const workspace = () => ({
			...adminWorkspace('A'),
			owner_id: currentOwner.id,
			owner_username: currentOwner.username
		});
		await page.route('**/api/v1/admin/workspaces', (route) =>
			route.fulfill({ json: [workspace()] })
		);
		await page.route('**/api/v1/admin/users?*', (route) =>
			route.fulfill({ json: { items: [adminUser('successor')], total: 1, offset: 0, limit: 20 } })
		);
		const submissions: unknown[] = [];
		await page.route('**/api/v1/admin/workspaces/A/owner', (route) => {
			submissions.push(route.request().postDataJSON());
			if (submissions.length === 1) {
				currentOwner = { id: 'competing-owner-id', username: 'competing-owner-name' };
				return route.fulfill({
					status: 409,
					json: { code: 'version_conflict', message: 'Owner changed' }
				});
			}
			currentOwner = { id: 'successor', username: 'successor' };
			return route.fulfill({ json: workspace() });
		});
		await page.goto('/admin/workspaces');
		await page.getByLabel('Search', { exact: true }).fill(ownerFilter);
		await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
		const row = page
			.locator('article')
			.filter({ has: page.getByText('Research A', { exact: true }) });
		await row.getByRole('button', { name: 'Reassign owner', exact: true }).click();
		await chooseSearchOption(page, 'New owner', 'successor');
		const reason = row.getByLabel('Reason (at least 10 characters)');
		await reason.fill('Preserve this draft through an ownership conflict');
		await row.getByRole('button', { name: 'Confirm owner reassignment' }).click();
		await expect(page.getByRole('alert')).toContainText('Ownership changed.');
		await expect(row.getByText('Current owner: competing-owner-name')).toBeVisible();
		await expect(
			row.getByText('This Workspace stays visible while its owner reassignment form is open.')
		).toBeVisible();
		await expect(reason).toHaveValue('Preserve this draft through an ownership conflict');
		await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
		await expect(row.getByText('Current owner: competing-owner-name')).toBeVisible();
		await expect(reason).toHaveValue('Preserve this draft through an ownership conflict');
		await expect(row.getByRole('combobox', { name: 'New owner' })).toHaveValue('successor');
		await page.getByLabel('Search', { exact: true }).fill(ownerFilter);
		await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
		await row.getByRole('button', { name: 'Confirm owner reassignment' }).click();
		await expect(row).toHaveCount(0);
		await expect(page.getByText('No matching workspaces.', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
		await expect(row.getByRole('combobox', { name: 'New owner' })).toHaveCount(0);
		await expect(row.locator('p').first()).toContainText('successor');
		expect(submissions).toEqual([
			{
				new_owner_user_id: 'successor',
				expected_owner_user_id: 'initial-owner-id',
				reason: 'Preserve this draft through an ownership conflict'
			},
			{
				new_owner_user_id: 'successor',
				expected_owner_user_id: 'competing-owner-id',
				reason: 'Preserve this draft through an ownership conflict'
			}
		]);
	});
}

test('a created one-time invitation link survives a list refresh failure', async ({ page }) => {
	await mockSession(page, 'administrator');
	let created = false;
	await page.route('**/api/v1/admin/invitations**', (route) => {
		if (route.request().method() === 'POST') {
			created = true;
			return route.fulfill({
				status: 201,
				json: {
					id: 'invitation-created',
					username: 'invitee',
					role: 'member',
					expires_at: '2099-01-01T00:00:00Z',
					token: 'one-time-audit-token',
					accept_path: '/invite/one-time-audit-token'
				}
			});
		}
		return created
			? route.fulfill({
					status: 500,
					json: { code: 'internal_error', message: 'List unavailable' }
				})
			: route.fulfill({ json: { items: [], total: 0, limit: 20, offset: 0 } });
	});
	await page.goto('/admin/invitations');
	await page.getByRole('button', { name: 'Invite user', exact: true }).click();
	await page.getByLabel('Username', { exact: true }).fill('invitee');
	await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
	await expect(page.getByText('Invitation created', { exact: true })).toBeVisible();
	await expect(page.getByText('Unable to load administration.', { exact: true })).toBeVisible();
	await expect(page.getByRole('link', { name: /one-time-audit-token/ })).toBeVisible();
});

test('invitation links survive unrelated or failed actions until their own revocation succeeds', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	const old = {
		id: 'older-invitation',
		username: 'older-invitee',
		role: 'member',
		state: 'expired',
		created_at: '2020-01-01T00:00:00Z',
		expires_at: '2020-01-02T00:00:00Z',
		accepted_at: null,
		revoked_at: null as string | null
	};
	const current = {
		...old,
		id: 'new-invitation',
		username: 'new-invitee',
		state: 'pending',
		expires_at: '2099-01-01T00:00:00Z'
	};
	let created = false;
	let failRevoke = true;
	await page.route('**/api/v1/admin/invitations**', (route) => {
		const request = route.request();
		if (request.method() === 'DELETE') {
			if (failRevoke) {
				failRevoke = false;
				return route.fulfill({
					status: 500,
					json: { code: 'internal_error', message: 'Revoke failed' }
				});
			}
			const invitation = request.url().endsWith(old.id) ? old : current;
			invitation.state = 'revoked';
			invitation.revoked_at = '2026-01-01T00:00:00Z';
			return route.fulfill({ json: { ok: true } });
		}
		if (request.method() === 'POST') {
			if (created)
				return route.fulfill({
					status: 422,
					json: { code: 'validation_failed', message: 'Unable to issue invitation' }
				});
			created = true;
			return route.fulfill({
				status: 201,
				json: {
					id: current.id,
					username: current.username,
					role: 'member',
					expires_at: current.expires_at,
					token: 'valid-new-link',
					accept_path: '/invite/valid-new-link'
				}
			});
		}
		const items = created ? [old, current] : [old];
		return route.fulfill({ json: { items, total: items.length, limit: 20, offset: 0 } });
	});
	await page.goto('/admin/invitations');
	await page.getByRole('button', { name: 'Invite user', exact: true }).click();
	await page.getByLabel('Username', { exact: true }).fill('new-invitee');
	await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
	const link = page.getByRole('link', { name: /valid-new-link/ });
	await expect(link).toBeVisible();
	const oldRow = page
		.locator('article')
		.filter({ has: page.getByText(old.username, { exact: true }) });
	const currentRow = page
		.locator('article')
		.filter({ has: page.getByText(current.username, { exact: true }) });
	await oldRow.getByRole('button', { name: 'Revoke invitation', exact: true }).click();
	await expect(page.getByRole('alert')).toBeVisible();
	await expect(link).toBeVisible();
	await oldRow.getByRole('button', { name: 'Revoke invitation', exact: true }).click();
	await expect(oldRow.getByText('Revoked', { exact: true })).toBeVisible();
	await expect(link).toBeVisible();
	await currentRow.getByRole('button', { name: 'Reissue invitation link', exact: true }).click();
	await expect(page.getByRole('alert')).toBeVisible();
	await expect(link).toBeVisible();
	await page.getByLabel('Username', { exact: true }).fill('another-invitee');
	await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
	await expect(page.getByRole('alert')).toBeVisible();
	await expect(link).toBeVisible();
	await currentRow.getByRole('button', { name: 'Revoke invitation', exact: true }).click();
	await expect(currentRow.getByText('Revoked', { exact: true })).toBeVisible();
	await expect(link).toHaveCount(0);
});
test('reassignment failure remains visible after switching forms', async ({ page }) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/workspaces', (route) =>
		route.fulfill({ json: [adminWorkspace('A'), adminWorkspace('B')] })
	);
	await page.route('**/api/v1/admin/users?*', (route) =>
		route.fulfill({ json: { items: [adminUser('successor')], total: 1, offset: 0, limit: 20 } })
	);
	const started = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	await page.route('**/api/v1/admin/workspaces/A/owner', async (route) => {
		started.resolve();
		await release.promise;
		await route.fulfill({
			status: 422,
			json: { code: 'validation_failed', message: 'Receiver inactive' }
		});
	});
	await page.goto('/admin/workspaces');
	const rowA = page.locator('article').filter({ hasText: 'Research A' });
	const rowB = page.locator('article').filter({ hasText: 'Research B' });
	await rowA.getByRole('button', { name: 'Reassign owner', exact: true }).click();
	await chooseSearchOption(page, 'New owner', 'successor');
	await rowA.getByLabel('Reason (at least 10 characters)').fill('Requested ownership handover');
	await rowA.getByRole('button', { name: 'Confirm owner reassignment' }).click();
	await started.promise;
	try {
		await rowB.getByRole('button', { name: 'Reassign owner', exact: true }).click();
		await chooseSearchOption(page, 'New owner', 'successor');
		await rowB.getByLabel('Reason (at least 10 characters)').fill('Keep this new Workspace draft');
		const response = page.waitForResponse((res) => res.url().endsWith('/admin/workspaces/A/owner'));
		release.resolve();
		await response;
		await expect(page.getByRole('alert')).toContainText('Research A');
		await expect(rowB.getByRole('combobox', { name: 'New owner' })).toHaveValue('successor');
		await expect(rowB.getByLabel('Reason (at least 10 characters)')).toHaveValue(
			'Keep this new Workspace draft'
		);
	} finally {
		release.resolve();
	}
});

test('settings lock fields during submission and preserve a failed draft for retry', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let settings = {
		registration_policy: 'invitation_only',
		workspace_creation_policy: 'admins_only',
		metadata_contact_email: '',
		ncbi_api_key: 'initial-value',
		openalex_api_key: '',
		nasa_ads_token: '',
		ieee_api_key: '',
		session_days: 30,
		max_pdf_bytes: 1000000,
		max_attachment_bytes: 1000000,
		export_ttl_hours: 24,
		database_url: 'sqlite:///audit.db',
		data_dir: '/tmp/audit'
	};
	let failNextSave = true;
	const started = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	await page.route('**/api/v1/admin/settings', async (route) => {
		if (route.request().method() === 'PUT') {
			const submitted = route.request().postDataJSON();
			started.resolve();
			await release.promise;
			if (failNextSave) {
				failNextSave = false;
				await route.fulfill({
					status: 422,
					json: { code: 'validation_failed', message: 'Invalid settings' }
				});
				return;
			}
			settings = { ...settings, ...submitted };
			await route.fulfill({ json: { ok: true } });
		} else await route.fulfill({ json: settings });
	});
	await page.goto('/admin/settings');
	const input = page.getByLabel('NCBI API key', { exact: true });
	await input.fill('submitted-value');
	await page.getByRole('button', { name: 'Save settings', exact: true }).click();
	await started.promise;
	try {
		await expect(input).toBeDisabled();
		await expect(page.getByRole('combobox', { name: /^Registration policy/ })).toBeDisabled();
		await expect(page.getByRole('combobox', { name: /^Workspace creation policy/ })).toBeDisabled();
		await expect(page.getByRole('spinbutton', { name: 'Session lifetime in days' })).toBeDisabled();
		release.resolve();
		await expect(page.getByRole('alert')).toBeVisible();
		await expect(input).toBeEnabled();
		await expect(input).toHaveValue('submitted-value');
		await input.fill('retry-value');
		await page.getByRole('button', { name: 'Save settings', exact: true }).click();
		await expect(page.getByText('Settings saved', { exact: true })).toBeVisible();
		await expect(input).toHaveValue('retry-value');
		await expect(input).toBeEnabled();
	} finally {
		release.resolve();
	}
});

test('active user removal clamps a now empty last page', async ({ page }) => {
	await mockSession(page, 'administrator');
	const users = Array.from({ length: 21 }, (_, index) => adminUser(`audit-user-${index}`));
	await page.route('**/api/v1/admin/users?*', (route) => {
		const query = new URL(route.request().url()).searchParams;
		const visible = users.filter((item) => query.get('active') !== 'true' || item.active);
		const offset = Number(query.get('offset'));
		const limit = Number(query.get('limit'));
		return route.fulfill({
			json: { items: visible.slice(offset, offset + limit), total: visible.length, offset, limit }
		});
	});
	await page.route('**/api/v1/admin/users/audit-user-20/status', (route) => {
		users[20].active = false;
		return route.fulfill({ json: users[20] });
	});
	await page.goto('/admin/users');
	await page.getByLabel(/^Status/).selectOption('true');
	await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
	await page.getByRole('button', { name: 'Next page', exact: true }).click();
	const row = page.getByRole('article', { name: 'audit-user-20', exact: true });
	await expect(row).toBeVisible();
	await row.getByText('Manage user', { exact: true }).click();
	await row.getByRole('button', { name: 'Disable user', exact: true }).click();
	await expect(page.getByText('User disabled', { exact: true })).toBeVisible();
	await expect(page.getByText('Page 1 of 1', { exact: true })).toBeVisible();
	await expect(page.getByRole('article', { name: 'audit-user-0', exact: true })).toBeVisible();
	await expect(page.getByText('No users.', { exact: true })).toHaveCount(0);
});

test('workspace search filters names, owners and IDs without narrowing the inspection selector', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/workspaces', (route) =>
		route.fulfill({
			json: [{ ...adminWorkspace('Alpha'), id: 'workspace-42' }, adminWorkspace('Beta')]
		})
	);
	await page.goto('/admin/workspaces');
	await expect(page.locator('article')).toHaveCount(2);
	const search = page.getByLabel('Search', { exact: true });
	for (const [query, name] of [
		['alpha', 'Research Alpha'],
		['owner-beta', 'Research Beta'],
		['WORKSPACE-42', 'Research Alpha']
	]) {
		await search.fill(query);
		await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
		await expect(page.locator('article').getByText(name, { exact: true })).toBeVisible();
		await expect(page.locator('article')).toHaveCount(1);
	}
	await chooseSearchOption(page, 'Target Workspace', 'Research Beta');
	await expect(page.getByRole('combobox', { name: 'Target Workspace' })).toHaveValue(
		'Research Beta'
	);
	await search.fill('no-such-workspace');
	await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
	await expect(page.getByText('No matching workspaces.', { exact: true })).toBeVisible();
	await expect(page.locator('article')).toHaveCount(0);
	await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
	await expect(page.locator('article')).toHaveCount(2);
});

test('workspace directory errors offer retry instead of reporting an empty directory', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let available = false;
	await page.route('**/api/v1/admin/workspaces', (route) =>
		available
			? route.fulfill({ json: [adminWorkspace('Alpha')] })
			: route.fulfill({ status: 500, json: { code: 'internal_error', message: 'Unavailable' } })
	);
	await page.goto('/admin/workspaces');
	await expect(page.getByRole('alert')).toContainText('Unable to load workspaces.');
	await expect(page.getByText('No workspaces.', { exact: true })).toHaveCount(0);
	available = true;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.locator('article').getByText('Research Alpha', { exact: true })).toBeVisible();
	await expect(page.getByRole('alert')).toHaveCount(0);
});

test('workspace directory refresh errors and retry preserve an open reassignment draft', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let available = true;
	const workspaceB = { ...adminWorkspace('B'), governance_frozen_at: null as string | null };
	await page.route('**/api/v1/admin/workspaces', (route) =>
		available
			? route.fulfill({ json: [adminWorkspace('A'), workspaceB] })
			: route.fulfill({ status: 500, json: { code: 'internal_error', message: 'Unavailable' } })
	);
	await page.route('**/api/v1/admin/users?*', (route) =>
		route.fulfill({ json: { items: [adminUser('successor')], total: 1, offset: 0, limit: 20 } })
	);
	await page.route('**/api/v1/admin/workspaces/B/freeze', (route) => {
		workspaceB.governance_frozen_at = '2026-01-01T00:00:00Z';
		available = false;
		return route.fulfill({ json: workspaceB });
	});
	await page.goto('/admin/workspaces');
	const rowA = page
		.locator('article')
		.filter({ has: page.getByText('Research A', { exact: true }) });
	const rowB = page
		.locator('article')
		.filter({ has: page.getByText('Research B', { exact: true }) });
	await rowA.getByRole('button', { name: 'Reassign owner', exact: true }).click();
	await chooseSearchOption(page, 'New owner', 'successor');
	const reason = rowA.getByLabel('Reason (at least 10 characters)');
	await reason.fill('Keep this draft across refresh errors');
	await rowB.getByRole('button', { name: 'Freeze writes', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('Unable to load workspaces.');
	await expect(reason).toHaveValue('Keep this draft across refresh errors');
	await expect(rowA.getByRole('combobox', { name: 'New owner' })).toHaveValue('successor');
	available = true;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(rowB.getByRole('button', { name: 'Unfreeze writes', exact: true })).toBeVisible();
	await expect(page.getByRole('alert')).toHaveCount(0);
	await expect(reason).toHaveValue('Keep this draft across refresh errors');
	await expect(rowA.getByRole('combobox', { name: 'New owner' })).toHaveValue('successor');
});
