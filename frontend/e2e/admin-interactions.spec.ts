import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

const adminUser = (id: string) => ({
	id,
	username: id,
	role: 'member',
	active: true,
	created_at: '2026-01-01T00:00:00Z'
});

test('user table preserves collapsed management drafts and delegates sorting to the server', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	const reads: URLSearchParams[] = [];
	await page.route('**/api/v1/admin/users?*', (route) => {
		reads.push(new URL(route.request().url()).searchParams);
		return route.fulfill({
			json: { items: [adminUser('curator')], total: 1, limit: 20, offset: 0 }
		});
	});
	const started = Promise.withResolvers<void>();
	const release = Promise.withResolvers<void>();
	let submitted: unknown;
	await page.route('**/api/v1/admin/users/curator/role', async (route) => {
		submitted = route.request().postDataJSON();
		started.resolve();
		await release.promise;
		await route.fulfill({
			status: 422,
			json: { code: 'validation_failed', message: 'Unable to update role' }
		});
	});
	await page.goto('/admin/users');
	const row = page.getByRole('rowgroup', { name: 'curator', exact: true });
	const manage = row.getByRole('button', { name: 'Manage user', exact: true });
	await expect(manage).toHaveAttribute('aria-expanded', 'false');
	await expect(row.getByLabel('New password for curator')).not.toBeVisible();
	await manage.click();
	await expect(manage).toHaveAttribute('aria-expanded', 'true');
	await row.getByLabel('Role for curator').selectOption('administrator');
	await row.getByLabel('New password for curator').fill('preserved-password-draft');
	await manage.click();
	await expect(row.getByLabel('New password for curator')).not.toBeVisible();
	await manage.click();
	await expect(row.getByLabel('Role for curator')).toHaveValue('administrator');
	await expect(row.getByLabel('New password for curator')).toHaveValue('preserved-password-draft');
	await row.getByRole('button', { name: 'Save role', exact: true }).click();
	await started.promise;
	try {
		await expect(manage).toBeDisabled();
		await expect(row.getByRole('button', { name: 'Reset password', exact: true })).toBeDisabled();
		release.resolve();
		await expect(page.getByRole('main').getByRole('alert')).toBeVisible();
		await expect(manage).toBeEnabled();
		await expect(row.getByLabel('Role for curator')).toHaveValue('administrator');
		await expect(row.getByLabel('New password for curator')).toHaveValue(
			'preserved-password-draft'
		);
		expect(submitted).toEqual({ role: 'administrator' });
		await expect.poll(() => reads[0]?.get('sort')).toBe('username');
		expect(reads[0].get('direction')).toBe('asc');
		await page.getByRole('combobox', { name: 'Sort By', exact: true }).selectOption('created');
		await expect.poll(() => reads.at(-1)?.get('sort')).toBe('created');
		expect(reads.at(-1)?.get('direction')).toBe('desc');
		await expect(page).toHaveURL(/sort=created/);
		await page.goBack();
		await expect(page.getByRole('combobox', { name: 'Sort By', exact: true })).toHaveValue(
			'username'
		);
	} finally {
		release.resolve();
	}
});

test('invitation filters, pagination and sort survive URL navigation and reload', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	const invitations = Array.from({ length: 26 }, (_, index) => ({
		id: `invitation-${index}`,
		username: `invitee-${String(index).padStart(2, '0')}`,
		role: 'member',
		state: index === 25 ? 'expired' : 'pending',
		created_at: `2026-01-${String(index + 1).padStart(2, '0')}T00:00:00Z`,
		expires_at: '2099-01-01T00:00:00Z'
	}));
	const reads: URLSearchParams[] = [];
	await page.route('**/api/v1/admin/invitations?*', (route) => {
		const params = new URL(route.request().url()).searchParams;
		reads.push(params);
		const rows = invitations
			.filter(
				(invitation) =>
					(!params.get('search') || invitation.username.includes(params.get('search')!)) &&
					(!params.get('state') || invitation.state === params.get('state')) &&
					(!params.get('role') || invitation.role === params.get('role'))
			)
			.sort((a, b) => {
				const field = params.get('sort') === 'username' ? 'username' : 'created_at';
				return a[field].localeCompare(b[field]) * (params.get('direction') === 'asc' ? 1 : -1);
			});
		const offset = Number(params.get('offset'));
		const limit = Number(params.get('limit'));
		return route.fulfill({
			json: { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset }
		});
	});
	await page.goto(
		'/admin/invitations?q=invitee&state=pending&role=member&page=2&page_size=10&sort=username&direction=asc'
	);
	const pagination = page.getByRole('navigation', { name: 'Invitation pages', exact: true });
	await expect(page.getByRole('rowgroup', { name: 'invitee-10', exact: true })).toBeVisible();
	await expect(page.getByLabel('Search', { exact: true })).toHaveValue('invitee');
	await expect(page.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue('pending');
	await expect(page.getByRole('combobox', { name: 'Role', exact: true })).toHaveValue('member');
	await expect(page.getByRole('combobox', { name: 'Sort By', exact: true })).toHaveValue(
		'username'
	);
	expect(reads.at(-1)?.get('offset')).toBe('10');
	expect(reads.at(-1)?.get('search')).toBe('invitee');
	expect(reads.at(-1)?.get('state')).toBe('pending');
	expect(reads.at(-1)?.get('role')).toBe('member');
	await page.getByLabel('Search', { exact: true }).fill('unsubmitted invitation draft');
	await pagination.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.getByRole('rowgroup', { name: 'invitee-20', exact: true })).toBeVisible();
	await expect(page.getByLabel('Search', { exact: true })).toHaveValue(
		'unsubmitted invitation draft'
	);
	await page.getByRole('combobox', { name: 'Sort By', exact: true }).selectOption('created');
	await page
		.getByRole('button', { name: 'Sort order: Newest first. Switch to Oldest first.', exact: true })
		.click();
	await expect(pagination.getByText('Page 1 of 3', { exact: true })).toBeVisible();
	await expect.poll(() => reads.at(-1)?.get('sort')).toBe('created');
	await expect.poll(() => reads.at(-1)?.get('direction')).toBe('asc');
	expect(reads.at(-1)?.get('offset')).toBe('0');
	expect(reads.at(-1)?.get('search')).toBe('invitee');
	await expect(page.getByLabel('Search', { exact: true })).toHaveValue(
		'unsubmitted invitation draft'
	);
	await page.goBack();
	await expect(page.getByRole('combobox', { name: 'Sort By', exact: true })).toHaveValue('created');
	await expect(
		page.getByRole('button', {
			name: 'Sort order: Newest first. Switch to Oldest first.',
			exact: true
		})
	).toBeVisible();
	await page.goBack();
	await expect(pagination.getByText('Page 3 of 3', { exact: true })).toBeVisible();
	await expect(page.getByRole('combobox', { name: 'Sort By', exact: true })).toHaveValue(
		'username'
	);
	await expect(page.getByLabel('Search', { exact: true })).toHaveValue('invitee');
	await page.reload();
	await expect(page.getByRole('rowgroup', { name: 'invitee-20', exact: true })).toBeVisible();
	await expect(page.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue('pending');
	await expect(page.getByRole('combobox', { name: 'Role', exact: true })).toHaveValue('member');
	await page.getByRole('combobox', { name: 'Status', exact: true }).selectOption('expired');
	await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
	await expect(pagination.getByText('Page 1 of 1', { exact: true })).toBeVisible();
	await expect(page.getByRole('rowgroup', { name: 'invitee-25', exact: true })).toBeVisible();
	await expect(page).toHaveURL(/state=expired/);
	await page.goBack();
	await expect(page.getByRole('combobox', { name: 'Status', exact: true })).toHaveValue('pending');
	await expect(pagination.getByText('Page 3 of 3', { exact: true })).toBeVisible();
});

for (const section of ['users', 'invitations'] as const) {
	test(`${section} sort controls separate fields and order and support the keyboard`, async ({
		page
	}) => {
		await mockSession(page, 'administrator');
		const reads: URLSearchParams[] = [];
		await page.route(`**/api/v1/admin/${section}?*`, (route) => {
			const params = new URL(route.request().url()).searchParams;
			reads.push(params);
			return route.fulfill({
				json: { items: [], total: 30, limit: 10, offset: Number(params.get('offset')) }
			});
		});
		await page.goto(`/admin/${section}?q=kept&page=2&page_size=10`);
		const group = page.getByRole('group', { name: 'Sort', exact: true });
		const field = group.getByRole('combobox', { name: 'Sort By', exact: true });
		const direction = group.getByRole('button');
		await expect(field.locator('option')).toHaveText(
			section === 'users' ? ['Username', 'Created'] : ['Created', 'Expires', 'Username']
		);
		await expect(direction).toHaveAccessibleName(
			section === 'users'
				? 'Sort order: A–Z. Switch to Z–A.'
				: 'Sort order: Newest first. Switch to Oldest first.'
		);
		await page.getByLabel('Search', { exact: true }).fill('unsubmitted draft');
		await field.selectOption(section === 'users' ? 'created' : 'expires');
		const current = section === 'users' ? 'Newest first' : 'Earliest first';
		const next = section === 'users' ? 'Oldest first' : 'Latest first';
		await expect(direction).toHaveAccessibleName(`Sort order: ${current}. Switch to ${next}.`);
		await expect
			.poll(() => reads.at(-1)?.get('direction'))
			.toBe(section === 'users' ? 'desc' : 'asc');
		await direction.focus();
		await direction.press('Enter');
		await expect
			.poll(() => reads.at(-1)?.get('direction'))
			.toBe(section === 'users' ? 'asc' : 'desc');
		await expect(direction).toHaveAccessibleName(`Sort order: ${next}. Switch to ${current}.`);
		await expect(direction).toBeFocused();
		expect(reads.at(-1)?.get('search')).toBe('kept');
		expect(reads.at(-1)?.get('offset')).toBe('0');
		await expect(page.getByLabel('Search', { exact: true })).toHaveValue('unsubmitted draft');
		await field.selectOption('username');
		await expect(direction).toHaveAccessibleName('Sort order: A–Z. Switch to Z–A.');
		await expect.poll(() => reads.at(-1)?.get('direction')).toBe('asc');
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
	const oldRow = page.getByRole('rowgroup', { name: old.username, exact: true });
	const currentRow = page.getByRole('rowgroup', { name: current.username, exact: true });
	await oldRow.getByRole('button', { name: 'Revoke invitation', exact: true }).click();
	await expect(page.getByRole('main').getByRole('alert')).toBeVisible();
	await expect(link).toBeVisible();
	await oldRow.getByRole('button', { name: 'Revoke invitation', exact: true }).click();
	await expect(oldRow.getByText('Revoked', { exact: true })).toBeVisible();
	await expect(link).toBeVisible();
	await currentRow.getByRole('button', { name: 'Reissue invitation link', exact: true }).click();
	await expect(page.getByRole('main').getByRole('alert')).toBeVisible();
	await expect(link).toBeVisible();
	await page.getByLabel('Username', { exact: true }).fill('another-invitee');
	await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
	await expect(page.getByRole('main').getByRole('alert')).toBeVisible();
	await expect(link).toBeVisible();
	await currentRow.getByRole('button', { name: 'Revoke invitation', exact: true }).click();
	await expect(currentRow.getByText('Revoked', { exact: true })).toBeVisible();
	await expect(link).toHaveCount(0);
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
		await expect(page.getByRole('main').getByRole('alert')).toBeVisible();
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
	const row = page.getByRole('rowgroup', { name: 'audit-user-20', exact: true });
	await expect(row).toBeVisible();
	await row.getByText('Manage user', { exact: true }).click();
	await row.getByRole('button', { name: 'Disable user', exact: true }).click();
	await expect(page.getByText('User disabled', { exact: true })).toBeVisible();
	await expect(page.getByText('Page 1 of 1', { exact: true })).toBeVisible();
	await expect(page.getByRole('rowgroup', { name: 'audit-user-0', exact: true })).toBeVisible();
	await expect(page.getByText('No users.', { exact: true })).toHaveCount(0);
});
