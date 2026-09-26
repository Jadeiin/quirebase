import { expect, test, type Page } from '@playwright/test';
import { mockSession, mockWorkspaces } from './helpers';

async function switchWorkspace(page: Page, name: string) {
	await page.getByRole('button', { name: 'Workspace' }).click();
	await page.getByRole('menuitem', { name: new RegExp(name) }).click();
}

test('Workspace switching and governance live in the Quirebase menu, not the daily navigation', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects', (route) =>
		route.fulfill({ json: [] })
	);

	await page.goto('/workspace/workspace-1');
	const mainNavigation = page.getByRole('navigation', { name: 'Main navigation' });
	await expect(mainNavigation.getByRole('link', { name: 'Workspace settings' })).toHaveCount(0);
	await expect(mainNavigation.getByRole('link', { name: 'Switch workspace' })).toHaveCount(0);

	await page.getByRole('button', { name: 'Workspace' }).click();
	await expect(page.getByRole('menuitem', { name: /Research/ })).toBeVisible();
	await expect(page.getByRole('menuitem', { name: /Archive/ })).toBeVisible();
	await expect(page.getByRole('menuitem', { name: 'Manage workspaces' })).toBeVisible();
	await expect(page.getByRole('menuitem', { name: 'Workspace settings' })).toBeVisible();
	await page.keyboard.press('Escape');
	await mainNavigation.getByRole('link', { name: 'Projects' }).click();
	await expect(mainNavigation.getByRole('link', { name: 'Dashboard' })).not.toHaveAttribute(
		'aria-current',
		'page'
	);
	await expect(mainNavigation.getByRole('link', { name: 'Projects' })).toHaveAttribute(
		'aria-current',
		'page'
	);
});

test('mobile workspace controls stay under the brand menu rather than More', async ({ page }) => {
	await mockSession(page);
	await page.setViewportSize({ width: 390, height: 844 });
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
	);

	await page.goto('/workspace/workspace-1');
	await page.getByRole('button', { name: 'Workspace' }).click();
	await expect(page.getByRole('menuitem', { name: 'Workspace settings' })).toBeVisible();
	await page.getByRole('button', { name: 'Workspace' }).press('Escape');
	await page.getByRole('button', { name: 'More' }).click();
	await expect(page.getByRole('menuitem', { name: 'Workspace settings' })).toHaveCount(0);
	await expect(page.getByRole('menuitem', { name: 'Switch workspace' })).toHaveCount(0);
});

test('an explicit Workspace URL wins over the saved default, and switching changes the URL context', async ({
	page
}) => {
	await mockSession(page);
	await page.addInitScript(() =>
		localStorage.setItem('quirebase:default-workspace', 'workspace-2')
	);
	const itemRequests: string[] = [];
	await page.route('**/api/v1/workspaces/*/items*', (route) => {
		const pathname = new URL(route.request().url()).pathname;
		const workspaceId = pathname.split('/')[4];
		itemRequests.push(pathname);
		return route.fulfill({
			json: {
				items: [
					{
						id: `item-${workspaceId}`,
						title_html: `Result ${workspaceId}`,
						authors: null,
						publication_date: null,
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 1,
				page: 1,
				per_page: 25
			}
		});
	});
	await page.route('**/api/v1/workspaces/*/tags', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/workspaces/*/projects', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/workspaces/*/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);

	await page.goto('/workspace/workspace-1/library');
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/library$/);
	await expect(page.getByText('Result workspace-1')).toBeVisible();

	await switchWorkspace(page, 'Archive');
	await expect(page).toHaveURL(/\/workspace\/workspace-2$/);
	await page.getByRole('link', { name: 'Library' }).first().click();
	await expect(page.getByText('Result workspace-2')).toBeVisible();
	await expect.poll(() => itemRequests).toContain('/api/v1/workspaces/workspace-2/items');
});

test('workspace creation submits an explicit owner and opens the Workspace when assigned to self', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	const workspace = {
		id: 'workspace-created',
		name: 'New research',
		owner_id: 'user-1',
		state: 'active',
		current_role: 'owner',
		governance_suspended: false,
		effective_capabilities: ['workspace.read', 'workspace.settings.manage', 'items.create']
	};
	let createBody: unknown;
	let workspaceCreated = false;
	await page.route('**/api/v1/workspaces', (route) => {
		if (route.request().method() === 'POST') {
			createBody = route.request().postDataJSON();
			workspaceCreated = true;
			return route.fulfill({ status: 201, json: { id: workspace.id } });
		}
		return route.fulfill({ json: workspaceCreated ? [workspace] : [] });
	});
	await page.route(`**/api/v1/workspaces/${workspace.id}`, (route) =>
		route.fulfill({ json: workspace })
	);
	await page.route(`**/api/v1/workspaces/${workspace.id}/dashboard`, (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
	);

	await page.goto('/workspace');
	await expect(page.getByRole('heading', { name: 'Create a workspace' })).toBeVisible();
	await page.getByLabel('Workspace name').fill('New research');
	await page.getByLabel('Owner username (exact match)').fill('reader');
	await page.getByRole('button', { name: 'Create workspace' }).click();

	await expect(page).toHaveURL(/\/workspace\/workspace-created$/);
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	await page.getByRole('button', { name: 'Workspace' }).click();
	await expect(page.getByRole('menuitem', { name: /New research/ })).toBeVisible();
	expect(createBody).toEqual({ name: 'New research', owner_username: 'reader' });
});

test('an instance administrator who assigns another owner is not added to Workspace content', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let openedWorkspace = false;
	await page.route('**/api/v1/workspaces', (route) => {
		if (route.request().method() === 'POST')
			return route.fulfill({ status: 201, json: { id: 'workspace-created' } });
		return route.fulfill({
			json: [
				{
					id: 'workspace-1',
					name: 'Research',
					owner_id: 'user-1',
					state: 'active',
					current_role: 'owner',
					governance_suspended: false,
					effective_capabilities: ['workspace.read']
				}
			]
		});
	});
	await page.route('**/api/v1/workspaces/workspace-created', (route) => {
		openedWorkspace = true;
		return route.fulfill({ status: 403, json: { code: 'workspace_membership_required' } });
	});

	await page.goto('/workspace');
	await page.getByLabel('Workspace name').fill('Assigned workspace');
	await page.getByLabel('Owner username (exact match)').fill('target-owner');
	await page.getByRole('button', { name: 'Create workspace' }).click();

	await expect(
		page.getByText(
			'Workspace created. Its owner can open it; you have no content access unless you are also a member.'
		)
	).toBeVisible();
	await expect(page).toHaveURL(/\/workspace$/);
	expect(openedWorkspace).toBe(false);
});

test('a user with no Workspace is sent to the chooser without a repair request', async ({
	page
}) => {
	await mockSession(page);
	let repairRequested = false;
	await page.route('**/api/v1/workspaces', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/account/initial-workspace/repair', (route) => {
		repairRequested = true;
		return route.fulfill({ status: 404, json: { code: 'not_found', message: 'not found' } });
	});

	await page.goto('/');
	await expect(page).toHaveURL(/\/workspace$/);
	await expect(page.getByText('No workspaces are available for this account yet.')).toBeVisible();
	expect(repairRequested).toBe(false);
});

test('the root route surfaces Workspace list failures and retries', async ({ page }) => {
	await mockSession(page);
	let listAvailable = false;
	let listRequests = 0;
	await page.route('**/api/v1/workspaces', (route) => {
		listRequests += 1;
		if (!listAvailable)
			return route.fulfill({
				status: 503,
				json: { code: 'request_failed', message: 'temporarily unavailable' }
			});
		return route.fulfill({
			json: [
				{
					id: 'workspace-1',
					name: 'Research',
					owner_id: 'user-1',
					state: 'active',
					current_role: 'owner',
					governance_suspended: false,
					effective_capabilities: ['workspace.read']
				}
			]
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
	);

	await page.goto('/');
	await expect(page.getByText('Unable to load workspaces.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible();

	listAvailable = true;
	await page.getByRole('button', { name: 'Retry' }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1$/);
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	expect(listRequests).toBeGreaterThanOrEqual(2);
});

test('a failed availability refetch preserves an explicit Workspace route', async ({ page }) => {
	await mockSession(page);
	let listRequests = 0;
	await page.route('**/api/v1/workspaces', (route) => {
		listRequests += 1;
		return route.fulfill({
			status: 503,
			json: { code: 'request_failed', message: 'temporarily unavailable' }
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill({
			status: 503,
			json: { code: 'request_failed', message: 'temporarily unavailable' }
		})
	);

	await page.goto('/workspace/workspace-1');
	await expect.poll(() => listRequests).toBeGreaterThanOrEqual(2);
	await expect(page.getByRole('alert')).toContainText('The request could not be completed.');
	expect(listRequests).toBe(2);
	await expect(page).toHaveURL(/\/workspace\/workspace-1$/);
	expect(await page.evaluate(() => localStorage.getItem('quirebase:default-workspace'))).toBe(
		'workspace-1'
	);
});

test('membership revoked while a page is open returns the user to the Workspace chooser', async ({
	page
}) => {
	await mockSession(page);
	let membershipRevoked = false;
	await page.route('**/api/v1/workspaces', (route) =>
		route.fulfill({
			json: membershipRevoked
				? []
				: [
						{
							id: 'workspace-1',
							name: 'Research',
							owner_id: 'user-1',
							state: 'active',
							current_role: 'owner',
							governance_suspended: false,
							effective_capabilities: ['workspace.read']
						}
					]
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/tags', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/workspaces/workspace-1/projects', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items*', (route) => {
		if (membershipRevoked)
			return route.fulfill({
				status: 403,
				json: { code: 'workspace_membership_required', message: 'membership revoked' }
			});
		return route.fulfill({
			json: { items: [], total: 0, page: 1, per_page: 25 }
		});
	});

	await page.goto('/workspace/workspace-1');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	membershipRevoked = true;
	await page.goto('/workspace/workspace-1/library');

	await expect(page).toHaveURL(/\/workspace$/);
	await expect(page.getByText('No workspaces are available for this account yet.')).toBeVisible();
});

test('a user who is not yet a Workspace member can sign in and accept the global invitation route', async ({
	page
}) => {
	await mockWorkspaces(page);
	let authenticated = false;
	let acceptedWorkspace = '';
	let signedInUsername = '';
	await page.route('**/api/v1/session', (route) => {
		if (route.request().method() === 'POST') {
			signedInUsername = route.request().postDataJSON().username;
			authenticated = true;
			return route.fulfill({
				json: { authenticated: true, user: { id: 'user-1', username: 'reader', role: 'member' } }
			});
		}
		if (authenticated)
			return route.fulfill({
				json: { authenticated: true, user: { id: 'user-1', username: 'reader', role: 'member' } }
			});
		return route.fulfill({
			status: 401,
			json: { code: 'authentication_required', message: 'sign in required' }
		});
	});
	await page.route('**/api/v1/invitations/workspace-token', (route) =>
		route.fulfill({ status: 404, json: { code: 'invitation_not_found', message: 'not found' } })
	);
	await page.route('**/api/v1/workspace-invitations/workspace-token', (route) =>
		route.fulfill({
			json: {
				username: 'reader',
				role: 'reviewer',
				workspace_name: 'Research',
				expires_at: '2026-10-01T00:00:00Z'
			}
		})
	);
	await page.route('**/api/v1/workspace-invitations/workspace-token/accept', (route) => {
		acceptedWorkspace = 'workspace-1';
		return route.fulfill({ json: { workspace_id: acceptedWorkspace } });
	});
	await page.route('**/api/v1/workspaces/*/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);

	await page.goto('/invite/workspace-token');
	await expect(page.getByText('Join', { exact: false })).toBeVisible();
	await page.getByLabel('Username').fill('reader');
	await page.getByLabel('Password').fill('correct horse battery staple');
	await page.getByRole('button', { name: 'Accept invitation' }).click();

	await expect(page).toHaveURL(/\/workspace\/workspace-1$/);
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	expect(signedInUsername).toBe('reader');
	expect(acceptedWorkspace).toBe('workspace-1');
});

test('a pending Workspace A response cannot replace Workspace B after switching', async ({
	page
}) => {
	await mockSession(page);
	let releaseWorkspaceA: (() => void) | undefined;
	let workspaceAStarted: (() => void) | undefined;
	const workspaceARequest = new Promise<void>((resolve) => (workspaceAStarted = resolve));
	await page.route('**/api/v1/workspaces/*/items*', async (route) => {
		const workspaceId = new URL(route.request().url()).pathname.split('/')[4];
		if (workspaceId === 'workspace-1') {
			workspaceAStarted?.();
			await new Promise<void>((resolve) => (releaseWorkspaceA = resolve));
		}
		return route.fulfill({
			json: {
				items: [
					{
						id: `item-${workspaceId}`,
						title_html: `Result ${workspaceId}`,
						authors: null,
						publication_date: null,
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 1,
				page: 1,
				per_page: 25
			}
		});
	});
	await page.route('**/api/v1/workspaces/*/tags', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/workspaces/*/projects', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/workspaces/*/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);

	await page.goto('/workspace/workspace-1/library');
	await workspaceARequest;
	await switchWorkspace(page, 'Archive');
	await expect(page).toHaveURL(/\/workspace\/workspace-2$/);
	await page.getByRole('link', { name: 'Library' }).first().click();
	await expect(page.getByText('Result workspace-2')).toBeVisible();
	releaseWorkspaceA?.();
	await expect(page.getByText('Result workspace-2')).toBeVisible();
	await expect(page.getByText('Result workspace-1')).toHaveCount(0);
});

test('Workspace admins do not get governance controls for other admin members', async ({
	page
}) => {
	await mockSession(page);
	const workspace = {
		id: 'workspace-1',
		name: 'Research',
		owner_id: 'owner-1',
		state: 'active',
		current_role: 'admin',
		governance_suspended: false,
		effective_capabilities: ['workspace.read', 'workspace.members.manage']
	};
	await page.route('**/api/v1/workspaces', (route) => route.fulfill({ json: [workspace] }));
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill({ json: workspace })
	);
	await page.route('**/api/v1/workspaces/workspace-1/governance/members', (route) =>
		route.fulfill({
			json: [
				{
					membership_id: 'admin-membership',
					user_id: 'other-admin-user',
					username: 'other-admin',
					role: 'admin',
					state: 'active',
					joined_at: '2026-01-01T00:00:00Z'
				},
				{
					membership_id: 'editor-membership',
					user_id: 'editor-user',
					username: 'editor',
					role: 'editor',
					state: 'active',
					joined_at: '2026-01-02T00:00:00Z'
				}
			]
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/invitations', (route) =>
		route.fulfill({ json: [] })
	);

	await page.goto('/workspace/workspace-1/settings');

	const adminRow = page.getByRole('row').filter({ hasText: 'other-admin' });
	await expect(adminRow.getByRole('combobox')).toHaveCount(0);
	await expect(adminRow.getByRole('button')).toHaveCount(0);
	const editorRow = page.getByRole('row').filter({ hasText: 'editor' });
	await expect(editorRow.getByRole('combobox', { name: 'Role for editor' })).toBeVisible();
	await expect(editorRow.getByRole('button', { name: 'Suspend' })).toBeVisible();
});

test('Workspace members see the active directory without governance data', async ({ page }) => {
	await mockSession(page);
	const workspace = {
		id: 'workspace-1',
		name: 'Research',
		owner_id: 'owner-1',
		state: 'active',
		current_role: 'editor',
		governance_suspended: false,
		effective_capabilities: ['workspace.read', 'workspace.export', 'items.edit']
	};
	await page.route('**/api/v1/workspaces', (route) => route.fulfill({ json: [workspace] }));
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill({ json: workspace })
	);
	await page.route('**/api/v1/workspaces/workspace-1/members', (route) =>
		route.fulfill({
			json: [
				{
					user_id: 'editor-user',
					username: 'editor',
					role: 'editor'
				},
				{ user_id: 'owner-user', username: 'owner', role: 'owner' }
			]
		})
	);
	let governanceRequests = 0;
	await page.route('**/api/v1/workspaces/workspace-1/governance/members', (route) => {
		governanceRequests += 1;
		return route.fulfill({ status: 403, json: { code: 'forbidden', message: 'forbidden' } });
	});

	await page.goto('/workspace/workspace-1/settings');

	await expect(page.getByRole('row').filter({ hasText: 'editor' })).toBeVisible();
	await expect(page.getByRole('row').filter({ hasText: 'owner' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Suspend' })).toHaveCount(0);
	await expect.poll(() => governanceRequests).toBe(0);
});

test('browser history and two tabs retain their explicit Workspace URLs across refresh', async ({
	page,
	context
}) => {
	await mockSession(page);
	const secondTab = await context.newPage();
	await mockSession(secondTab);
	for (const activePage of [page, secondTab]) {
		await activePage.route('**/api/v1/workspaces/*/items*', (route) => {
			const workspaceId = new URL(route.request().url()).pathname.split('/')[4];
			return route.fulfill({
				json: {
					items: [
						{
							id: `item-${workspaceId}`,
							title_html: `Result ${workspaceId}`,
							authors: null,
							publication_date: null,
							publication_title: null,
							doi: null,
							version: 1
						}
					],
					total: 1,
					page: 1,
					per_page: 25
				}
			});
		});
		await activePage.route('**/api/v1/workspaces/*/tags', (route) => route.fulfill({ json: [] }));
		await activePage.route('**/api/v1/workspaces/*/projects', (route) =>
			route.fulfill({ json: [] })
		);
		await activePage.route('**/api/v1/workspaces/*/dashboard', (route) =>
			route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
		);
	}

	await page.goto('/workspace/workspace-1/library');
	await expect(page.getByText('Result workspace-1')).toBeVisible();
	await switchWorkspace(page, 'Archive');
	await expect(page).toHaveURL(/\/workspace\/workspace-2$/);
	await page.goBack();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/library$/);
	await expect(page.getByText('Result workspace-1')).toBeVisible();
	await page.goForward();
	await expect(page).toHaveURL(/\/workspace\/workspace-2$/);

	await secondTab.goto('/workspace/workspace-2/library');
	await expect(secondTab.getByText('Result workspace-2')).toBeVisible();
	await secondTab.reload();
	await expect(secondTab).toHaveURL(/\/workspace\/workspace-2\/library$/);
	await expect(secondTab.getByText('Result workspace-2')).toBeVisible();
	await expect(page).toHaveURL(/\/workspace\/workspace-2$/);
});

test('an inaccessible default Workspace is cleared before root navigation recovers', async ({
	page
}) => {
	await mockSession(page);
	await page.addInitScript(() =>
		localStorage.setItem('quirebase:default-workspace', 'workspace-removed')
	);
	await page.route('**/api/v1/workspaces', (route) =>
		route.fulfill({
			json: [
				{
					...{
						id: 'workspace-1',
						name: 'Research',
						owner_id: 'user-1',
						state: 'active',
						current_role: 'owner',
						governance_suspended: false,
						effective_capabilities: ['workspace.read', 'items.create']
					}
				}
			]
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);

	await page.goto('/');
	await expect(page).toHaveURL(/\/workspace\/workspace-1$/);
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	expect(await page.evaluate(() => localStorage.getItem('quirebase:default-workspace'))).toBeNull();
});
