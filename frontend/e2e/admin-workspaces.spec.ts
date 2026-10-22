import { expect, test, type Page, type Route } from '@playwright/test';
import { chooseSearchOption, mockSession } from './helpers';

type WorkspaceFixture = {
	id: string;
	name: string;
	owner_id: string;
	owner_username: string;
	owner_active: boolean;
	can_reassign_owner: boolean;
	state: string;
	governance_frozen_at: string | null;
	governance_frozen_by: string | null;
	created_at?: string;
};

const adminWorkspace = (id: string): WorkspaceFixture => ({
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

function workspacePage(rows: WorkspaceFixture[], route: Route) {
	const parameters = new URL(route.request().url()).searchParams;
	const search = parameters.get('search')?.toLowerCase() ?? '';
	const visible = rows
		.filter(
			(workspace) =>
				[workspace.name, workspace.id, workspace.owner_username, workspace.owner_id].some((value) =>
					value.toLowerCase().includes(search)
				) &&
				(!parameters.get('state') || workspace.state === parameters.get('state')) &&
				(!parameters.get('frozen') ||
					Boolean(workspace.governance_frozen_at) === (parameters.get('frozen') === 'true')) &&
				(!parameters.get('owner_active') ||
					workspace.owner_active === (parameters.get('owner_active') === 'true'))
		)
		.map((workspace) => ({ created_at: '2026-01-01T00:00:00Z', ...workspace }));
	const sort = parameters.get('sort');
	visible.sort((a, b) => {
		const field = sort === 'owner' ? 'owner_username' : sort === 'created' ? 'created_at' : 'name';
		return (
			(a[field].localeCompare(b[field]) || a.id.localeCompare(b.id)) *
			(parameters.get('direction') === 'desc' ? -1 : 1)
		);
	});
	const limit = Number(parameters.get('limit') ?? 20);
	const offset = Number(parameters.get('offset') ?? 0);
	return { items: visible.slice(offset, offset + limit), total: visible.length, limit, offset };
}

async function mockWorkspaceDirectory(
	page: Page,
	rows: () => WorkspaceFixture[],
	status: () => number = () => 200
) {
	const reads: URLSearchParams[] = [];
	await page.route('**/api/v1/admin/workspaces?*', (route) => {
		reads.push(new URL(route.request().url()).searchParams);
		return status() === 200
			? route.fulfill({ json: workspacePage(rows(), route) })
			: route.fulfill({
					status: status(),
					json: {
						code: status() === 403 ? 'permission_denied' : 'internal_error',
						message: 'Unavailable'
					}
				});
	});
	await page.route(/\/api\/v1\/admin\/workspaces\/[^/?]+$/, (route) => {
		if (route.request().method() !== 'GET') return route.fallback();
		const id = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)!);
		const workspace = rows().find((entry) => entry.id === id);
		return workspace
			? route.fulfill({ json: { created_at: '2026-01-01T00:00:00Z', ...workspace } })
			: route.fulfill({ status: 404, json: { code: 'not_found', message: 'Unavailable' } });
	});
	return reads;
}

for (const draftWorkspace of ['B', 'A']) {
	test(`completing Workspace A reassignment preserves the newer Workspace ${draftWorkspace} form`, async ({
		page
	}) => {
		await mockSession(page, 'administrator');
		let ownerA = 'owner-A';
		const workspaces = () =>
			['A', 'B'].map((id) => ({
				id,
				name: `Workspace ${id}`,
				owner_id: id === 'A' ? ownerA : 'owner-B',
				owner_username: id === 'A' ? ownerA : 'owner-B',
				owner_active: true,
				can_reassign_owner: true,
				state: 'active',
				governance_frozen_at: null,
				governance_frozen_by: null
			}));
		await mockWorkspaceDirectory(page, () => workspaces());
		await page.route('**/api/v1/admin/users?*', (route) =>
			route.fulfill({
				json: {
					items: ['successor-A', 'successor-B'].map((id) => ({
						id,
						username: id,
						role: 'member',
						active: true,
						created_at: '2026-01-01T00:00:00Z'
					})),
					total: 2,
					limit: 20,
					offset: 0
				}
			})
		);
		const started = Promise.withResolvers<void>();
		const release = Promise.withResolvers<void>();
		await page.route('**/api/v1/admin/workspaces/A/owner', async (route) => {
			started.resolve();
			await release.promise;
			ownerA = 'successor-A';
			await route.fulfill({ json: workspaces()[0] });
		});
		await page.goto('/admin/workspaces');
		const rowA = page.getByRole('rowgroup', { name: 'Workspace A', exact: true });
		const rowB = page.getByRole('rowgroup', { name: 'Workspace B', exact: true });
		await rowA.getByRole('button', { name: 'Reassign owner', exact: true }).click();
		const formA = page.getByRole('form', { name: 'Reassign owner for Workspace A', exact: true });
		await chooseSearchOption(page, 'New owner', 'successor-A');
		await formA.getByLabel('Reason (at least 10 characters)').fill('First ownership handover');
		await formA.getByRole('button', { name: 'Confirm owner reassignment' }).click();
		await started.promise;
		try {
			await rowB.getByRole('button', { name: 'Reassign owner', exact: true }).click();
			if (draftWorkspace === 'A')
				await rowA.getByRole('button', { name: 'Reassign owner', exact: true }).click();
			const draftRow = page.getByRole('form', {
				name: `Reassign owner for Workspace ${draftWorkspace}`,
				exact: true
			});
			await chooseSearchOption(page, 'New owner', 'successor-B');
			await draftRow
				.getByLabel('Reason (at least 10 characters)')
				.fill('Preserve this independent draft');
			release.resolve();
			await expect(rowA).toContainText('successor-A');
			await expect(draftRow.getByRole('combobox', { name: 'New owner' })).toHaveValue(
				'successor-B'
			);
			await expect(draftRow.getByLabel('Reason (at least 10 characters)')).toHaveValue(
				'Preserve this independent draft'
			);
			await draftRow.getByRole('button', { name: 'Cancel', exact: true }).click();
			await expect(draftRow.getByRole('combobox', { name: 'New owner' })).toHaveCount(0);
		} finally {
			release.resolve();
		}
	});
}

test('owner reassignment retains a searched user outside the first page through conflict and submission', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let currentOwner = 'owner';
	const workspace = () => ({
		id: 'workspace-governance',
		name: 'Research',
		owner_id: currentOwner,
		owner_username: currentOwner,
		owner_active: true,
		can_reassign_owner: true,
		state: 'active',
		governance_frozen_at: null,
		governance_frozen_by: null
	});
	await mockWorkspaceDirectory(page, () => [workspace()]);
	const user = (id: string) => ({
		id,
		username: id,
		role: 'member',
		active: true,
		created_at: '2026-01-01T00:00:00Z'
	});
	let searched = false;
	await page.route('**/api/v1/admin/users?*', (route) => {
		const search = new URL(route.request().url()).searchParams.get('search');
		const items = search
			? [user('zz-successor')]
			: Array.from({ length: 20 }, (_, index) => user(`user-${index}`));
		if (search) searched = true;
		return route.fulfill({ json: { items, total: search ? 1 : 21, limit: 20, offset: 0 } });
	});
	const requests: unknown[] = [];
	await page.route('**/api/v1/admin/workspaces/workspace-governance/owner', (route) => {
		requests.push(route.request().postDataJSON());
		if (requests.length === 1) {
			currentOwner = 'competing-owner';
			return route.fulfill({
				status: 409,
				json: { code: 'version_conflict', message: 'Owner changed' }
			});
		}
		currentOwner = 'zz-successor';
		return route.fulfill({ json: workspace() });
	});
	await page.goto('/admin/workspaces');
	await page.getByRole('button', { name: 'Reassign owner', exact: true }).click();
	const input = page.getByRole('combobox', { name: 'New owner' });
	await input.fill('zz-successor');
	await page.getByRole('option', { name: 'zz-successor', exact: true }).click();
	await page
		.getByLabel('Reason (at least 10 characters)')
		.first()
		.fill('Hand over to a searched successor');
	await expect(input).toHaveValue('zz-successor');
	await page.getByRole('button', { name: 'Confirm owner reassignment' }).click();
	await expect(page.getByText(/Ownership changed/)).toBeVisible();
	await expect(input).toHaveValue('zz-successor');
	await page.getByRole('button', { name: 'Confirm owner reassignment' }).click();
	await expect(input).toHaveCount(0);
	await expect(page.locator('tbody[aria-label]').getByText(/zz-successor/)).toBeVisible();
	expect(searched).toBe(true);
	expect(requests).toEqual([
		{
			new_owner_user_id: 'zz-successor',
			expected_owner_user_id: 'owner',
			reason: 'Hand over to a searched successor'
		},
		{
			new_owner_user_id: 'zz-successor',
			expected_owner_user_id: 'competing-owner',
			reason: 'Hand over to a searched successor'
		}
	]);
});

for (const width of [1280, 1024, 390]) {
	test(`administrator reassigns an inactive owner's Workspace and recovers a conflict at ${width}px`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 900 });
		await mockSession(page, 'administrator');
		let currentOwner = 'disabled-owner';
		const workspace = () => ({
			id: 'workspace-governance',
			name: 'Offboarding research',
			owner_id: currentOwner,
			owner_username: currentOwner,
			owner_active: currentOwner !== 'disabled-owner',
			can_reassign_owner: true,
			state: 'archived',
			governance_frozen_at: null,
			governance_frozen_by: null
		});
		await mockWorkspaceDirectory(page, () => [workspace()]);
		await page.route('**/api/v1/admin/users?*', (route) => {
			const params = new URL(route.request().url()).searchParams;
			expect(params.get('active')).toBe('true');
			expect(params.get('limit')).toBe('20');
			return route.fulfill({
				json: {
					items: [
						{
							id: 'successor',
							username: 'successor',
							role: 'member',
							active: true,
							created_at: '2026-01-01T00:00:00Z'
						}
					],
					total: 1,
					limit: 20,
					offset: 0
				}
			});
		});
		const requests: unknown[] = [];
		await page.route('**/api/v1/admin/workspaces/workspace-governance/owner', (route) => {
			requests.push(route.request().postDataJSON());
			if (requests.length === 1) {
				currentOwner = 'competing-owner';
				return route.fulfill({
					status: 409,
					json: { code: 'version_conflict', message: 'Owner changed' }
				});
			}
			currentOwner = 'successor';
			return route.fulfill({ json: workspace() });
		});
		await page.goto('/admin/workspaces');
		await expect(page.getByText('Owner account disabled', { exact: true })).toBeVisible();
		await expect(page.getByRole('table', { name: 'Workspaces', exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Reassign owner', exact: true }).click();
		await expect(page.getByText(/The selected user gains Workspace owner access/)).toBeVisible();
		await chooseSearchOption(page, 'New owner', 'successor');
		const form = page.getByRole('form', {
			name: 'Reassign owner for Offboarding research',
			exact: true
		});
		await form
			.getByLabel('Reason (at least 10 characters)')
			.fill('Explicit handover after offboarding');
		await form.getByRole('button', { name: 'Confirm owner reassignment' }).click();
		await expect(page.getByRole('main').getByRole('alert')).toContainText(
			'Offboarding research: Ownership changed.'
		);
		await expect(form.getByText('Current owner: competing-owner')).toBeVisible();
		await expect(form.getByLabel('Reason (at least 10 characters)')).toHaveValue(
			'Explicit handover after offboarding'
		);
		await expect(form.getByRole('combobox', { name: 'New owner' })).toHaveValue('successor');
		await form.getByRole('button', { name: 'Confirm owner reassignment' }).click();
		await expect(form).toHaveCount(0);
		await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
		await expect(page.locator('tbody[aria-label]').getByText(/successor/)).toBeVisible();
		expect(requests).toEqual([
			{
				new_owner_user_id: 'successor',
				expected_owner_user_id: 'disabled-owner',
				reason: 'Explicit handover after offboarding'
			},
			{
				new_owner_user_id: 'successor',
				expected_owner_user_id: 'competing-owner',
				reason: 'Explicit handover after offboarding'
			}
		]);
		expect(
			await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
		).toBe(true);
	});
}

test('disabling an owner refreshes cached Workspace governance independently of account management', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let active = true;
	await mockWorkspaceDirectory(page, () => [
		{
			id: 'workspace-1',
			name: 'Offboarding research',
			owner_id: 'user-2',
			owner_username: 'curator',
			owner_active: active,
			can_reassign_owner: true,
			state: 'active',
			governance_frozen_at: null,
			governance_frozen_by: null
		}
	]);
	await page.route('**/api/v1/admin/users?*', (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'user-2',
						username: 'curator',
						role: 'member',
						active,
						created_at: '2026-01-01T00:00:00Z'
					}
				],
				total: 1,
				limit: 20,
				offset: 0
			}
		})
	);
	await page.route('**/api/v1/admin/users/user-2/status', (route) => {
		active = route.request().postDataJSON().active;
		return route.fulfill({
			json: {
				id: 'user-2',
				username: 'curator',
				role: 'member',
				active,
				created_at: '2026-01-01T00:00:00Z'
			}
		});
	});
	await page.goto('/admin/workspaces');
	await expect(page.locator('tbody[aria-label]').getByText(/curator/)).toBeVisible();
	await page.getByRole('link', { name: 'Users', exact: true }).click();
	await page.getByText('Manage user', { exact: true }).click();
	await expect(
		page.getByText(/Disabling a user ends all sessions and blocks access/)
	).toBeVisible();
	await page.getByRole('button', { name: 'Disable user', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Enable user', exact: true })).toBeVisible();
	await page.getByRole('link', { name: 'Workspaces', exact: true }).click();
	await expect(page.getByText('Owner account disabled', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Reassign owner', exact: true })).toBeVisible();
});

test('Workspace governance freezes, unfreezes, and performs reason-bound break-glass inspection', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let frozen = false;
	let freezeRequests = 0;
	let unfreezeRequests = 0;
	let inspectionBody: unknown;
	await mockWorkspaceDirectory(page, () => [
		{
			id: 'workspace-1',
			name: 'Research',
			owner_id: 'user-1',
			owner_username: 'owner',
			owner_active: true,
			can_reassign_owner: !frozen,
			state: 'active',
			governance_frozen_at: frozen ? '2026-09-01T00:00:00Z' : null,
			governance_frozen_by: frozen ? 'admin-1' : null
		}
	]);
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
					authors: [{ full_name: 'A. Reader', last_name: 'A. Reader', first_name: null }],
					publication_date: '2026',
					publication_title: null,
					doi: null,
					version: 1
				}
			]
		});
	});

	await page.goto('/admin/workspaces');
	await expect(
		page.locator('tbody[aria-label]').getByText('Research', { exact: true })
	).toBeVisible();
	await page.getByRole('button', { name: 'Freeze writes' }).click();
	await expect.poll(() => freezeRequests).toBe(1);
	await page.getByRole('button', { name: 'Unfreeze writes' }).click();
	await expect.poll(() => unfreezeRequests).toBe(1);
	await page.getByText('BREAK GLASS · read-only item inspection', { exact: true }).click();
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
	await mockWorkspaceDirectory(page, () => [
		{
			id: 'workspace-1',
			name: 'Research',
			owner_id: 'owner-1',
			owner_username: 'owner-1',
			owner_active: true,
			can_reassign_owner: true,
			state: 'active',
			governance_frozen_at: null,
			governance_frozen_by: null
		},
		{
			id: 'workspace-2',
			name: 'Archive',
			owner_id: 'owner-2',
			owner_username: 'owner-2',
			owner_active: true,
			can_reassign_owner: true,
			state: 'active',
			governance_frozen_at: null,
			governance_frozen_by: null
		}
	]);
	await page.route('**/api/v1/admin/workspaces/*/break-glass/items', (route) => {
		const workspaceId = new URL(route.request().url()).pathname.split('/')[5];
		return route.fulfill({
			json: [
				{
					id: `item-${workspaceId}`,
					title_html: `Inspected ${workspaceId}`,
					authors: [],
					publication_date: null,
					publication_title: null,
					doi: null,
					version: 1
				}
			]
		});
	});

	await page.goto('/admin/workspaces');
	await page.getByText('BREAK GLASS · read-only item inspection', { exact: true }).click();
	await chooseSearchOption(page, 'Target Workspace', 'Research');
	await page.getByLabel(/Reason/).fill('Investigating a reported access issue');
	await page.getByRole('button', { name: 'Inspect Items once' }).click();
	await expect(page.getByText('Inspected workspace-1')).toBeVisible();
	await chooseSearchOption(page, 'Target Workspace', 'Archive');
	await expect(page.getByText('Scope: Workspace workspace-1')).toBeVisible();
	await expect(page.getByText('Scope: Workspace workspace-2')).toHaveCount(0);
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
		await mockWorkspaceDirectory(page, () => [workspace()]);
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
		const row = page.getByRole('rowgroup', { name: 'Research A', exact: true });
		await row.getByRole('button', { name: 'Reassign owner', exact: true }).click();
		await chooseSearchOption(page, 'New owner', 'successor');
		const form = page.getByRole('form', { name: 'Reassign owner for Research A', exact: true });
		const reason = form.getByLabel('Reason (at least 10 characters)');
		await reason.fill('Preserve this draft through an ownership conflict');
		await form.getByRole('button', { name: 'Confirm owner reassignment' }).click();
		await expect(page.getByRole('main').getByRole('alert')).toContainText('Ownership changed.');
		await expect(form.getByText('Current owner: competing-owner-name')).toBeVisible();
		await expect(row).toHaveCount(0);
		await expect(reason).toHaveValue('Preserve this draft through an ownership conflict');
		await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
		await expect(form.getByText('Current owner: competing-owner-name')).toBeVisible();
		await expect(reason).toHaveValue('Preserve this draft through an ownership conflict');
		await expect(form.getByRole('combobox', { name: 'New owner' })).toHaveValue('successor');
		await page.getByLabel('Search', { exact: true }).fill(ownerFilter);
		await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
		await form.getByRole('button', { name: 'Confirm owner reassignment' }).click();
		await expect(row).toHaveCount(0);
		await expect(page.getByText('No matching workspaces.', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
		await expect(form.getByRole('combobox', { name: 'New owner' })).toHaveCount(0);
		await expect(row).toContainText('successor');
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

test('reassignment failure remains visible after switching forms', async ({ page }) => {
	await mockSession(page, 'administrator');
	await mockWorkspaceDirectory(page, () => [adminWorkspace('A'), adminWorkspace('B')]);
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
	const rowA = page.getByRole('rowgroup', { name: 'Research A', exact: true });
	const rowB = page.getByRole('rowgroup', { name: 'Research B', exact: true });
	await rowA.getByRole('button', { name: 'Reassign owner', exact: true }).click();
	await chooseSearchOption(page, 'New owner', 'successor');
	const formA = page.getByRole('form', { name: 'Reassign owner for Research A', exact: true });
	await formA.getByLabel('Reason (at least 10 characters)').fill('Requested ownership handover');
	await formA.getByRole('button', { name: 'Confirm owner reassignment' }).click();
	await started.promise;
	try {
		await rowB.getByRole('button', { name: 'Reassign owner', exact: true }).click();
		await chooseSearchOption(page, 'New owner', 'successor');
		const formB = page.getByRole('form', { name: 'Reassign owner for Research B', exact: true });
		await formB.getByLabel('Reason (at least 10 characters)').fill('Keep this new Workspace draft');
		const response = page.waitForResponse((res) => res.url().endsWith('/admin/workspaces/A/owner'));
		release.resolve();
		await response;
		await expect(page.getByRole('main').getByRole('alert')).toContainText('Research A');
		await expect(formB.getByRole('combobox', { name: 'New owner' })).toHaveValue('successor');
		await expect(formB.getByLabel('Reason (at least 10 characters)')).toHaveValue(
			'Keep this new Workspace draft'
		);
	} finally {
		release.resolve();
	}
});

test('workspace search filters names, owners and IDs without narrowing the inspection selector', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	const reads = await mockWorkspaceDirectory(page, () => [
		{ ...adminWorkspace('Alpha'), id: 'workspace-42' },
		adminWorkspace('Beta')
	]);
	await page.goto('/admin/workspaces');
	await expect(page.locator('tbody[aria-label]')).toHaveCount(2);
	await expect.poll(() => reads.length).toBe(1);
	await expect(
		page.getByRole('combobox', { name: 'Target Workspace', exact: true, includeHidden: true })
	).toBeHidden();
	const search = page.getByLabel('Search', { exact: true });
	for (const [query, name] of [
		['alpha', 'Research Alpha'],
		['owner-beta', 'Research Beta'],
		['WORKSPACE-42', 'Research Alpha']
	]) {
		await search.fill(query);
		await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
		await expect(page.locator('tbody[aria-label]').getByText(name, { exact: true })).toBeVisible();
		await expect(page.locator('tbody[aria-label]')).toHaveCount(1);
	}
	const beforeInspection = reads.length;
	await page.getByText('BREAK GLASS · read-only item inspection', { exact: true }).click();
	await expect.poll(() => reads.length).toBeGreaterThan(beforeInspection);
	expect(reads.at(-1)?.get('search') ?? '').toBe('');
	expect(reads.at(-1)?.get('sort')).toBe('name');
	expect(reads.at(-1)?.get('direction')).toBe('asc');
	await chooseSearchOption(page, 'Target Workspace', 'Research Beta');
	await expect(page.getByRole('combobox', { name: 'Target Workspace' })).toHaveValue(
		'Research Beta'
	);
	await search.fill('no-such-workspace');
	await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
	await expect(page.getByText('No matching workspaces.', { exact: true })).toBeVisible();
	await expect(page.locator('tbody[aria-label]')).toHaveCount(0);
	await expect(page.getByRole('combobox', { name: 'Target Workspace' })).toHaveValue(
		'Research Beta'
	);
	await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
	await expect(page.locator('tbody[aria-label]')).toHaveCount(2);
});

test('workspace directory errors offer retry instead of reporting an empty directory', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let available = false;
	await mockWorkspaceDirectory(
		page,
		() => [adminWorkspace('Alpha')],
		() => (available ? 200 : 500)
	);
	await page.goto('/admin/workspaces');
	await expect(page.getByRole('main').getByRole('alert')).toContainText(
		'Unable to load administration.'
	);
	await expect(page.getByText('No workspaces.', { exact: true })).toHaveCount(0);
	available = true;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(
		page.locator('tbody[aria-label]').getByText('Research Alpha', { exact: true })
	).toBeVisible();
	await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
});

test('workspace directory refresh errors and retry preserve an open reassignment draft', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let available = true;
	const workspaceB = { ...adminWorkspace('B'), governance_frozen_at: null as string | null };
	await mockWorkspaceDirectory(
		page,
		() => [adminWorkspace('A'), workspaceB],
		() => (available ? 200 : 500)
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
	const rowA = page.getByRole('rowgroup', { name: 'Research A', exact: true });
	const rowB = page.getByRole('rowgroup', { name: 'Research B', exact: true });
	await rowA.getByRole('button', { name: 'Reassign owner', exact: true }).click();
	await chooseSearchOption(page, 'New owner', 'successor');
	const form = page.getByRole('form', { name: 'Reassign owner for Research A', exact: true });
	const reason = form.getByLabel('Reason (at least 10 characters)');
	await reason.fill('Keep this draft across refresh errors');
	await rowB.getByRole('button', { name: 'Freeze writes', exact: true }).click();
	await expect(page.getByRole('main').getByRole('alert')).toContainText(
		'Unable to load administration.'
	);
	await expect(reason).toHaveValue('Keep this draft across refresh errors');
	await expect(form.getByRole('combobox', { name: 'New owner' })).toHaveValue('successor');
	available = true;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(rowB.getByRole('button', { name: 'Unfreeze writes', exact: true })).toBeVisible();
	await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
	await expect(reason).toHaveValue('Keep this draft across refresh errors');
	await expect(form.getByRole('combobox', { name: 'New owner' })).toHaveValue('successor');
});

test('Workspace filters, sorting and pagination round-trip through the URL and browser history', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	const workspaces = Array.from({ length: 25 }, (_, index) => ({
		...adminWorkspace(String(index).padStart(2, '0')),
		state: 'archived',
		owner_active: false,
		governance_frozen_at: '2026-01-01T00:00:00Z',
		created_at: `2026-01-${String(index + 1).padStart(2, '0')}T00:00:00Z`
	}));
	const reads = await mockWorkspaceDirectory(page, () => [
		...workspaces,
		{ ...workspaces[0], id: 'active', name: 'Research active', state: 'active' },
		{ ...workspaces[0], id: 'unfrozen', name: 'Research unfrozen', governance_frozen_at: null },
		{ ...workspaces[0], id: 'enabled', name: 'Research enabled', owner_active: true }
	]);
	await page.goto(
		'/admin/workspaces?q=Research&state=archived&frozen=true&owner_active=false&page=2&page_size=10&sort=owner&direction=desc'
	);
	const pagination = page.getByRole('navigation', { name: 'Administration pages', exact: true });
	const field = page.getByRole('combobox', { name: 'Sort By', exact: true });
	const direction = page.getByRole('group', { name: 'Sort', exact: true }).getByRole('button');
	await expect(pagination.getByText('Page 2 of 3', { exact: true })).toBeVisible();
	await expect(page.getByRole('rowgroup', { name: 'Research 14', exact: true })).toBeVisible();
	await expect(page.getByRole('combobox', { name: 'State', exact: true })).toHaveValue('archived');
	await expect(page.getByRole('combobox', { name: 'Write freeze', exact: true })).toHaveValue(
		'true'
	);
	await expect(page.getByRole('combobox', { name: 'Owner account', exact: true })).toHaveValue(
		'false'
	);
	await expect(field.locator('option')).toHaveText(['Name', 'Owner', 'Created']);
	await expect(direction).toHaveAccessibleName('Sort order: Z–A. Switch to A–Z.');
	expect(Object.fromEntries(reads.at(-1)!)).toMatchObject({
		search: 'Research',
		state: 'archived',
		frozen: 'true',
		owner_active: 'false',
		sort: 'owner',
		direction: 'desc',
		offset: '10',
		limit: '10'
	});
	await page.getByLabel('Search', { exact: true }).fill('unsubmitted Workspace draft');
	await pagination.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.getByRole('rowgroup', { name: 'Research 04', exact: true })).toBeVisible();
	await expect(page.getByLabel('Search', { exact: true })).toHaveValue(
		'unsubmitted Workspace draft'
	);
	await field.selectOption('created');
	await expect(pagination.getByText('Page 1 of 3', { exact: true })).toBeVisible();
	await expect(page.getByRole('rowgroup', { name: 'Research 24', exact: true })).toBeVisible();
	await expect(direction).toHaveAccessibleName('Sort order: Newest first. Switch to Oldest first.');
	await direction.focus();
	await direction.press('Enter');
	await expect(page.getByRole('rowgroup', { name: 'Research 00', exact: true })).toBeVisible();
	await expect(direction).toHaveAccessibleName('Sort order: Oldest first. Switch to Newest first.');
	await expect(direction).toBeFocused();
	await field.selectOption('name');
	await expect(direction).toHaveAccessibleName('Sort order: A–Z. Switch to Z–A.');
	await expect.poll(() => reads.at(-1)?.get('sort')).toBe('name');
	expect(reads.at(-1)?.get('direction')).toBe('asc');
	expect(reads.at(-1)?.get('search')).toBe('Research');
	await expect(page.getByLabel('Search', { exact: true })).toHaveValue(
		'unsubmitted Workspace draft'
	);
	await page.goBack();
	await expect(field).toHaveValue('created');
	await expect(direction).toHaveAccessibleName('Sort order: Oldest first. Switch to Newest first.');
	await expect(page.getByLabel('Search', { exact: true })).toHaveValue('Research');
	await page.reload();
	await expect(page.getByRole('rowgroup', { name: 'Research 00', exact: true })).toBeVisible();
	await expect(page.getByRole('combobox', { name: 'State', exact: true })).toHaveValue('archived');
	await expect(page.getByRole('combobox', { name: 'Write freeze', exact: true })).toHaveValue(
		'true'
	);
	await expect(page.getByRole('combobox', { name: 'Owner account', exact: true })).toHaveValue(
		'false'
	);
	await field.selectOption('owner');
	await expect(direction).toHaveAccessibleName('Sort order: A–Z. Switch to Z–A.');
	await page.getByRole('combobox', { name: 'State', exact: true }).selectOption('active');
	await page.getByRole('combobox', { name: 'Write freeze', exact: true }).selectOption('');
	await page.getByRole('combobox', { name: 'Owner account', exact: true }).selectOption('');
	await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
	await expect(page.locator('tbody[aria-label]')).toHaveCount(1);
	await expect(page.getByRole('rowgroup', { name: 'Research active', exact: true })).toBeVisible();
	await expect(pagination.getByText('Page 1 of 1', { exact: true })).toBeVisible();
	await page.goBack();
	await expect(page.getByRole('combobox', { name: 'State', exact: true })).toHaveValue('archived');
	await expect(pagination.getByText('Page 1 of 3', { exact: true })).toBeVisible();
});

test('an owner draft reconciles its original Workspace after paging away', async ({ page }) => {
	await mockSession(page, 'administrator');
	const workspaces = Array.from({ length: 21 }, (_, index) =>
		adminWorkspace(String(index).padStart(2, '0'))
	);
	await mockWorkspaceDirectory(page, () => workspaces);
	await page.route('**/api/v1/admin/users?*', (route) =>
		route.fulfill({ json: { items: [adminUser('successor')], total: 1, offset: 0, limit: 20 } })
	);
	const submissions: unknown[] = [];
	await page.route('**/api/v1/admin/workspaces/00/owner', (route) => {
		submissions.push(route.request().postDataJSON());
		const newOwner = submissions.length === 1 ? 'competing-owner' : 'successor';
		workspaces[0] = { ...workspaces[0], owner_id: newOwner, owner_username: newOwner };
		return submissions.length === 1
			? route.fulfill({ status: 409, json: { code: 'version_conflict', message: 'Owner changed' } })
			: route.fulfill({ json: workspaces[0] });
	});
	await page.goto('/admin/workspaces?page_size=10');
	await page
		.getByRole('rowgroup', { name: 'Research 00', exact: true })
		.getByRole('button', { name: 'Reassign owner', exact: true })
		.click();
	const form = page.getByRole('form', { name: 'Reassign owner for Research 00', exact: true });
	await chooseSearchOption(page, 'New owner', 'successor');
	await form.getByLabel('Reason (at least 10 characters)').fill('Keep this handover across pages');
	const pagination = page.getByRole('navigation', { name: 'Administration pages', exact: true });
	await pagination.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.getByRole('rowgroup', { name: 'Research 00', exact: true })).toHaveCount(0);
	await expect(page.getByRole('rowgroup', { name: 'Research 10', exact: true })).toBeVisible();
	await expect(form.getByLabel('Reason (at least 10 characters)')).toHaveValue(
		'Keep this handover across pages'
	);
	await form.getByRole('button', { name: 'Confirm owner reassignment', exact: true }).click();
	await expect(form.getByText('Current owner: competing-owner', { exact: true })).toBeVisible();
	await expect(form.getByRole('combobox', { name: 'New owner', exact: true })).toHaveValue(
		'successor'
	);
	await expect(pagination.getByText('Page 2 of 3', { exact: true })).toBeVisible();
	await form.getByRole('button', { name: 'Confirm owner reassignment', exact: true }).click();
	await expect(form).toHaveCount(0);
	await expect(pagination.getByText('Page 2 of 3', { exact: true })).toBeVisible();
	expect(submissions).toEqual([
		{
			new_owner_user_id: 'successor',
			expected_owner_user_id: 'owner-00',
			reason: 'Keep this handover across pages'
		},
		{
			new_owner_user_id: 'successor',
			expected_owner_user_id: 'competing-owner',
			reason: 'Keep this handover across pages'
		}
	]);
});

test('freezing the final filtered Workspace replaces the exhausted page', async ({ page }) => {
	await mockSession(page, 'administrator');
	const workspaces = Array.from({ length: 21 }, (_, index) =>
		adminWorkspace(String(index).padStart(2, '0'))
	);
	await mockWorkspaceDirectory(page, () => workspaces);
	await page.route('**/api/v1/admin/workspaces/20/freeze', (route) => {
		workspaces[20].governance_frozen_at = '2026-01-01T00:00:00Z';
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/admin/workspaces?frozen=false&page=3&page_size=10');
	const row = page.getByRole('rowgroup', { name: 'Research 20', exact: true });
	await row.getByRole('button', { name: 'Freeze writes', exact: true }).click();
	const pagination = page.getByRole('navigation', { name: 'Administration pages', exact: true });
	await expect(pagination.getByText('Page 2 of 2', { exact: true })).toBeVisible();
	await expect(page.getByRole('rowgroup', { name: 'Research 10', exact: true })).toBeVisible();
	await expect(row).toHaveCount(0);
	await expect(page.getByText('No matching workspaces.', { exact: true })).toHaveCount(0);
	await expect(page).toHaveURL(/page=2/);
	await page.goBack();
	await expect(page).not.toHaveURL(/page=3/);
});

test('transient directory errors retain governance and inspection while denial removes both', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let status = 200;
	await mockWorkspaceDirectory(
		page,
		() => [adminWorkspace('A')],
		() => status
	);
	await page.route('**/api/v1/admin/workspaces/A/break-glass/items', (route) =>
		route.fulfill({
			json: [
				{
					id: 'private-item',
					title_html: 'Sensitive inspection evidence',
					authors: [],
					publication_date: null,
					publication_title: null,
					doi: null,
					version: 1
				}
			]
		})
	);
	await page.goto('/admin/workspaces');
	const row = page.getByRole('rowgroup', { name: 'Research A', exact: true });
	await expect(row).toBeVisible();
	await page.getByText('BREAK GLASS · read-only item inspection', { exact: true }).click();
	await chooseSearchOption(page, 'Target Workspace', 'Research A');
	await page
		.getByLabel('Reason (at least 10 characters)', { exact: true })
		.fill('Investigating an access support request');
	await page.getByRole('button', { name: 'Inspect Items once', exact: true }).click();
	await expect(page.getByText('Sensitive inspection evidence', { exact: true })).toBeVisible();
	status = 500;
	await page.getByRole('button', { name: 'Refresh', exact: true }).click();
	await expect(page.getByRole('alert')).toContainText('Unable to load administration.');
	await expect(row).toBeVisible();
	await expect(page.getByText('Sensitive inspection evidence', { exact: true })).toBeVisible();
	status = 403;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(row).toHaveCount(0);
	await expect(page.getByText('Sensitive inspection evidence', { exact: true })).toHaveCount(0);
	await expect(page.getByText('Scope: Workspace A', { exact: false })).toHaveCount(0);
	await expect(page.getByText('No matching workspaces.', { exact: true })).toHaveCount(0);
	await expect(
		page.getByRole('button', { name: 'Inspect Items once', exact: true })
	).toBeDisabled();
});
