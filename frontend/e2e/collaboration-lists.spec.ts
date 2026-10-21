import { expect, test, type Locator } from '@playwright/test';
import { directoryPage, mockSession, workspaceView } from './helpers';

const members = Array.from({ length: 28 }, (_, index) => ({
	membership_id: `membership-${index}`,
	user_id: `user-${index}`,
	username: `reader-${String(index).padStart(2, '0')}`,
	role: 'viewer',
	state: 'active',
	joined_at: '2026-10-01T00:00:00Z',
	allowed_roles: ['editor'],
	authorization: { allowed: ['workspace_member.terminate'] }
}));
const invitations = members.map((member, index) => ({
	id: `invitation-${index}`,
	user_id: member.user_id,
	username: member.username,
	role: 'viewer',
	created_at: '2026-10-01T00:00:00Z',
	expires_at: '2099-01-01T00:00:00Z'
}));

async function aligned(controls: Locator[]) {
	const boxes = await Promise.all(controls.map((control) => control.boundingBox()));
	for (const box of boxes) expect(box?.height).toBe(36);
	expect(new Set(boxes.map((box) => box?.y)).size).toBe(1);
}

test('member filters, pagination and ordering restore through history and IME search', async ({
	page
}) => {
	await mockSession(page);
	await page.setViewportSize({ width: 1600, height: 1000 });
	const reads: URLSearchParams[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/governance/members?*', (route) => {
		reads.push(new URL(route.request().url()).searchParams);
		return route.fulfill({ json: directoryPage(members, route) });
	});
	await page.goto('/workspace/workspace-1/settings/members?page_size=10&page=2');
	await expect(page.getByText('Page 2 of 3', { exact: true })).toBeVisible();
	const search = page.getByLabel('Search members', { exact: true });
	const role = page.getByRole('combobox', { name: 'Role', exact: true });
	const state = page.getByRole('combobox', { name: 'State', exact: true });
	const sort = page.getByRole('combobox', { name: 'Sort By', exact: true });
	const direction = page.getByRole('button', { name: /^Sort order:/ });
	await aligned([search, role, state, sort, direction]);
	await role.selectOption('viewer');
	await expect(page.getByText('Page 1 of 3', { exact: true })).toBeVisible();
	await state.selectOption('active');
	await sort.selectOption('joined');
	await direction.click();
	await expect.poll(() => reads.at(-1)?.get('direction')).toBe('desc');
	await search.dispatchEvent('compositionstart');
	await search.fill('中');
	await page.waitForTimeout(300);
	expect(reads.at(-1)?.get('search') ?? '').toBe('');
	await search.fill('中文 ');
	await search.dispatchEvent('compositionend');
	await expect.poll(() => reads.at(-1)?.get('search')).toBe('中文');
	await expect(search).toHaveValue('中文 ');
	expect(reads.at(-1)?.get('role')).toBe('viewer');
	expect(reads.at(-1)?.get('state')).toBe('active');
	await page.reload();
	await expect(search).toHaveValue('中文');
	await expect(sort).toHaveValue('joined');
	await role.selectOption('editor');
	await expect(page).toHaveURL(/role=editor/);
	await page.goBack();
	await expect(role).toHaveValue('viewer');
	await expect(search).toHaveValue('中文');
});

test('ordinary member filters never request governance fields', async ({ page }) => {
	await mockSession(page);
	const view = workspaceView('workspace-1', 'Research');
	view.authorization.allowed = ['workspace.read'];
	view.current_role = 'viewer';
	await page.route('**/api/v1/workspaces/workspace-1', (route) => route.fulfill({ json: view }));
	let governanceReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/governance/members?*', (route) => {
		governanceReads++;
		return route.fulfill({ json: directoryPage([], route) });
	});
	const reads: URLSearchParams[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/members?*', (route) => {
		reads.push(new URL(route.request().url()).searchParams);
		return route.fulfill({
			json: directoryPage(
				members.map(({ user_id, username, role }) => ({ user_id, username, role })),
				route
			)
		});
	});
	await page.goto('/workspace/workspace-1/settings/members?state=suspended&sort=joined');
	await expect(page.getByRole('table', { name: 'Members' })).toBeVisible();
	await expect(page.getByRole('combobox', { name: 'State', exact: true })).toHaveCount(0);
	await expect(page.getByRole('option', { name: 'Date joined', exact: true })).toHaveCount(0);
	await page.getByRole('combobox', { name: 'Role', exact: true }).selectOption('viewer');
	await page.getByRole('button', { name: /^Sort order:/ }).click();
	await expect.poll(() => reads.at(-1)?.get('direction')).toBe('desc');
	expect(governanceReads).toBe(0);
	expect(reads.every((params) => !params.has('state') && !params.has('sort'))).toBe(true);
});

test('a lost revoke response reconciles the last invitation page', async ({ page }) => {
	await mockSession(page);
	const revoked = new Set<string>();
	await page.route('**/api/v1/workspaces/workspace-1/invitations?*', (route) =>
		route.fulfill({
			json: directoryPage(
				invitations.slice(0, 11).filter((row) => !revoked.has(row.id)),
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/invitations/*', (route) => {
		revoked.add(new URL(route.request().url()).pathname.split('/').at(-1)!);
		return route.abort('failed');
	});
	await page.goto('/workspace/workspace-1/settings/invitations?page_size=10&page=2');
	await expect(page.getByText('Page 2 of 2', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Revoke invitation for reader-10', exact: true }).click();
	await expect(page.getByText('Page 1 of 1', { exact: true })).toBeVisible();
	await expect(page).not.toHaveURL(/[?&]page=2/);
	await expect(page.getByRole('button', { name: /^Revoke invitation for / })).toHaveCount(10);
	expect(revoked.size).toBe(1);
});

for (const kind of ['members', 'invitations'] as const) {
	test(`${kind} retains transient data and hides denied cache variants offline`, async ({
		page,
		context
	}) => {
		await mockSession(page);
		let mode: 'ok' | 'temporary' | 'denied' = 'ok';
		const endpoint = kind === 'members' ? 'governance/members' : 'invitations';
		await page.route(`**/api/v1/workspaces/workspace-1/${endpoint}?*`, (route) =>
			route.fulfill(
				mode === 'ok'
					? { json: directoryPage(kind === 'members' ? members : invitations, route) }
					: {
							status: mode === 'temporary' ? 500 : 403,
							json: {
								code: mode === 'temporary' ? 'internal_error' : 'permission_denied',
								message: 'Unavailable'
							}
						}
			)
		);
		await page.goto(`/workspace/workspace-1/settings/${kind}`);
		const sort = page.getByRole('combobox', { name: 'Sort By', exact: true });
		const alternate = kind === 'members' ? 'joined' : 'username';
		const initial = kind === 'members' ? 'username' : 'created';
		await expect(page.getByRole('table')).toBeVisible();
		await Promise.all([
			page.waitForResponse(
				(response) =>
					response.url().includes(`/${endpoint}?`) &&
					new URL(response.url()).searchParams.get('sort') === alternate
			),
			sort.selectOption(alternate)
		]);
		await expect(page.getByRole('table')).toBeVisible();
		mode = 'temporary';
		await sort.selectOption(initial);
		const retry = page.getByRole('button', { name: 'Retry', exact: true });
		await expect(retry).toBeVisible();
		await expect(page.getByRole('table')).toBeVisible();
		mode = 'denied';
		await retry.click();
		await expect(page.getByRole('table')).toHaveCount(0);
		await context.setOffline(true);
		await sort.selectOption(alternate);
		await expect(retry).toBeVisible();
		await expect(page.getByRole('table')).toHaveCount(0);
		await expect(page.getByText(/No (matching|pending) (members|invitations)/)).toHaveCount(0);
	});
}

test('sent invitation filters and sort restore after refresh and reset pagination', async ({
	page
}) => {
	await mockSession(page);
	const rows = invitations.map((row, index) => ({ ...row, role: index % 2 ? 'viewer' : 'editor' }));
	const reads: URLSearchParams[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/invitations?*', (route) => {
		const params = new URL(route.request().url()).searchParams;
		reads.push(params);
		let filtered = rows.filter(
			(row) =>
				(!params.get('role') || row.role === params.get('role')) &&
				row.username.includes(params.get('search') ?? '')
		);
		if (params.get('sort') === 'username')
			filtered = filtered.toSorted((a, b) => a.username.localeCompare(b.username));
		if (params.get('direction') === 'desc') filtered.reverse();
		return route.fulfill({ json: directoryPage(filtered, route) });
	});
	await page.goto('/workspace/workspace-1/settings/invitations?page_size=10&page=2');
	await expect(page.getByText('Page 2 of 3', { exact: true })).toBeVisible();
	const role = page.getByRole('combobox', { name: 'Role', exact: true }).last();
	await role.selectOption('editor');
	await expect(page.getByText('Page 1 of 2', { exact: true })).toBeVisible();
	const search = page.getByLabel('Search invitations', { exact: true });
	await search.fill('reader-2');
	await expect(page.getByText('Page 1 of 1', { exact: true })).toBeVisible();
	const sort = page.getByRole('combobox', { name: 'Sort By', exact: true });
	await sort.selectOption('username');
	await expect(
		page.getByRole('button', { name: 'Sort order: A–Z. Switch to Z–A.', exact: true })
	).toBeVisible();
	await page.getByRole('button', { name: /^Sort order:/ }).click();
	await expect.poll(() => reads.at(-1)?.get('direction')).toBe('desc');
	await page.reload();
	await expect(role).toHaveValue('editor');
	await expect(search).toHaveValue('reader-2');
	await expect(sort).toHaveValue('username');
	await expect(
		page.getByRole('button', { name: /^Revoke invitation for / }).first()
	).toHaveAccessibleName('Revoke invitation for reader-26');
	await page.goBack();
	await expect(
		page.getByRole('button', { name: 'Sort order: A–Z. Switch to Z–A.', exact: true })
	).toBeVisible();
});

test('an invitation creation cannot restore its one-time link after read access is denied', async ({
	page
}) => {
	await mockSession(page);
	let created = false;
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/invitations(?:\?.*)?$/, (route) => {
		if (route.request().method() === 'POST') {
			created = true;
			return route.fulfill({
				status: 201,
				json: { ...invitations[0], token: 'lost-access-token' }
			});
		}
		return route.fulfill(
			created
				? { status: 403, json: { code: 'permission_denied', message: 'Denied' } }
				: { json: directoryPage([], route) }
		);
	});
	await page.goto('/workspace/workspace-1/settings/invitations');
	await expect(page.getByText('No pending invitations.', { exact: true })).toBeVisible();
	await page.getByLabel('Exact username').fill('reader-00');
	await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
	await expect(page.getByLabel('Exact username')).toBeEnabled();
	await expect(page.getByText(/invite\/lost-access-token/)).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Copy one-time link', exact: true })).toHaveCount(
		0
	);
});

test('a transient Workspace reconciliation keeps the invitation link and newer form draft', async ({
	page
}) => {
	await mockSession(page);
	let rootStatus = 200;
	let created = false;
	const view = workspaceView('workspace-1', 'Research');
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill(
			rootStatus === 200
				? { json: view }
				: {
						status: rootStatus,
						json: {
							code: rootStatus === 404 ? 'workspace_unavailable' : 'internal_error',
							message: 'Workspace read failed'
						}
					}
		)
	);
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/invitations(?:\?.*)?$/, (route) => {
		if (route.request().method() === 'POST') {
			created = true;
			return route.fulfill({
				status: 201,
				json: { ...invitations[0], token: 'retained-invitation-token' }
			});
		}
		return route.fulfill(
			rootStatus === 500
				? { status: 500, json: { code: 'internal_error', message: 'Invitation read failed' } }
				: {
						json: directoryPage(created ? invitations.slice(0, 2) : invitations.slice(1, 2), route)
					}
		);
	});
	await page.route('**/api/v1/workspaces/workspace-1/invitations/invitation-1', (route) => {
		rootStatus = 500;
		return route.fulfill({
			status: 500,
			json: { code: 'internal_error', message: 'Revoke failed' }
		});
	});
	await page.goto('/workspace/workspace-1/settings/invitations');
	const username = page.getByLabel('Exact username');
	await username.fill('reader-00');
	await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
	await expect(page.getByText(/invite\/retained-invitation-token/)).toBeVisible();
	await username.fill('another-reader');
	await page.getByRole('button', { name: 'Revoke invitation for reader-01', exact: true }).click();
	await expect(
		page.getByRole('alert').filter({ hasText: 'Unable to load workspace.' })
	).toBeVisible();
	await expect(page.getByText(/invite\/retained-invitation-token/)).toBeVisible();
	await expect(username).toHaveValue('another-reader');
	rootStatus = 404;
	await page
		.getByRole('alert')
		.filter({ hasText: 'Unable to load workspace.' })
		.getByRole('button', { name: 'Retry', exact: true })
		.click();
	await expect(page.getByText(/invite\/retained-invitation-token/)).toHaveCount(0);
	await expect(page).toHaveURL(/\/workspace$/);
});

test('a denied invitation command retains a prior link while invitation reads remain authorized', async ({
	page
}) => {
	await mockSession(page);
	let creations = 0;
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/invitations(?:\?.*)?$/, (route) => {
		if (route.request().method() === 'POST') {
			creations++;
			return route.fulfill(
				creations === 1
					? { status: 201, json: { ...invitations[0], token: 'still-authorized-token' } }
					: {
							status: 403,
							json: { code: 'permission_denied', message: 'Invitation command denied' }
						}
			);
		}
		return route.fulfill({ json: directoryPage(invitations.slice(0, 2), route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/invitations/invitation-1', (route) =>
		route.fulfill({
			status: 403,
			json: { code: 'permission_denied', message: 'Invitation command denied' }
		})
	);
	await page.goto('/workspace/workspace-1/settings/invitations');
	const username = page.getByLabel('Exact username');
	await username.fill('reader-00');
	await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
	const link = page.getByText(/invite\/still-authorized-token/);
	await expect(link).toBeVisible();
	await username.fill('reader-01');
	await page.getByRole('button', { name: 'Create invitation', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText(
		'You do not have permission to perform this action.'
	);
	await expect(username).toHaveValue('reader-01');
	await expect(link).toBeVisible();
	await page.getByRole('button', { name: 'Revoke invitation for reader-01', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText(
		'You do not have permission to perform this action.'
	);
	await expect(
		page.getByRole('button', { name: 'Revoke invitation for reader-01', exact: true })
	).toBeEnabled();
	await expect(link).toBeVisible();
	expect(creations).toBe(2);
});
