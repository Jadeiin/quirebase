import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import type { components } from '../src/lib/api/schema.js';
import { directoryPage, mockSession, workspaceView } from './helpers';

test.describe.configure({ mode: 'parallel' });

type Invitation = components['schemas']['ReceivedWorkspaceInvitationView'];
const invitation: Invitation = {
	id: 'invitation-1',
	workspace_id: 'workspace-new',
	workspace_name: 'New research group',
	inviter_username: 'collaborator',
	role: 'editor',
	created_at: '2026-10-18T00:00:00Z',
	expires_at: '2027-01-01T00:00:00Z',
	state: 'pending',
	can_accept: true,
	can_open: false,
	unavailable_reason: null
};

async function setup(page: Page, invitations: Invitation[] = [invitation]) {
	await mockSession(page);
	const states = new Map(invitations.map((item) => [item.id, { ...item }]));
	await page.route('**/api/v1/me/workspace-invitations?*', (route) =>
		route.fulfill({
			json: directoryPage(
				[...states.values()].filter((item) => item.state === 'pending'),
				route
			)
		})
	);
	await page.route(/\/api\/v1\/me\/workspace-invitations\/[^/]+$/, (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-1)!;
		return route.fulfill({ json: states.get(id) });
	});
	await page.route('**/api/v1/me/workspace-invitations/*/accept', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		states.set(id, { ...states.get(id)!, state: 'accepted', can_accept: false, can_open: true });
		return route.fulfill({ json: { workspace_id: states.get(id)!.workspace_id } });
	});
	return { states };
}

test('global invitation entry works with no memberships; joining leaves the default unchanged', async ({
	page
}) => {
	await setup(page);
	await page.route(/\/api\/v1\/workspaces(?:\?.*)?$/, (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.goto('/workspace');
	await page.getByRole('button', { name: /Quirebase Choose workspace/ }).click();
	await page.getByRole('menuitem', { name: /Workspace invitations/ }).click();
	await expect(page).toHaveURL(/\/workspace#invitations$/);
	await expect(page.getByRole('article', { name: invitation.workspace_name })).toContainText(
		'collaborator'
	);
	await page.getByRole('button', { name: 'Accept invitation', exact: true }).click();
	await expect(page.getByText('Invitation accepted.', { exact: true })).toBeVisible();
	await expect(page).toHaveURL(/\/workspace#invitations$/);
	await expect
		.poll(() => page.evaluate(() => localStorage.getItem('quirebase:default-workspace')))
		.toBe('workspace-1');
	await expect(page.getByRole('article')).toHaveCount(0);
	await expect(page.getByLabel('1 pending invitations')).toHaveCount(0);
	await page.route('**/api/v1/workspaces/workspace-new', (route) =>
		route.fulfill({ json: workspaceView('workspace-new', invitation.workspace_name) })
	);
	await page.route('**/api/v1/workspaces/workspace-new/overview', (route) =>
		route.fulfill({ json: {} })
	);
	await page.getByRole('link', { name: 'Open Workspace', exact: true }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-new$/);
	await expect
		.poll(() => page.evaluate(() => localStorage.getItem('quirebase:default-workspace')))
		.toBe('workspace-new');
});

test('no pending invitations leaves no invitation section, shortcut or badge', async ({ page }) => {
	await setup(page, []);
	await Promise.all([
		page.waitForResponse(
			(response) =>
				response.url().includes('/me/workspace-invitations?') &&
				new URL(response.url()).searchParams.get('limit') === '25'
		),
		page.goto('/workspace')
	]);
	await expect(page.getByRole('heading', { name: 'My workspaces', exact: true })).toBeVisible();
	await expect(
		page.getByRole('region', { name: 'Workspace invitations', exact: true })
	).toHaveCount(0);
	await expect(page.getByRole('link', { name: 'Workspace invitations', exact: true })).toHaveCount(
		0
	);
	await expect(page.getByLabel(/pending invitations/)).toHaveCount(0);
	await page.getByRole('button', { name: /Quirebase Choose workspace/ }).click();
	await expect(page.getByRole('menuitem', { name: /Workspace invitations/ })).toHaveCount(0);
	await expect(page.getByRole('menuitem', { name: 'My workspaces', exact: true })).toBeVisible();
});

test('accepting the last invitation preserves its result until dismissed', async ({ page }) => {
	await setup(page);
	await page.goto('/workspace');
	const section = page.getByRole('region', { name: 'Workspace invitations', exact: true });
	await expect(section.getByLabel('1 pending invitations')).toBeVisible();
	await section.getByRole('button', { name: 'Accept invitation', exact: true }).click();
	await expect(section.getByText('Invitation accepted.', { exact: true })).toBeVisible();
	await expect(section.getByRole('link', { name: 'Open Workspace', exact: true })).toBeVisible();
	await expect(page.getByLabel('1 pending invitations')).toHaveCount(0);
	await page.getByRole('button', { name: /Quirebase Choose workspace/ }).click();
	await expect(page.getByRole('menuitem', { name: /Workspace invitations/ })).toHaveCount(0);
	await page.keyboard.press('Escape');
	await section.getByRole('button', { name: 'Dismiss', exact: true }).click();
	await expect(section).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'My workspaces', exact: true })).toBeVisible();
});

for (const responseLost of [true, false]) {
	test(`accept reconciliation handles ${responseLost ? 'lost response' : 'another tab accepting'} without replay`, async ({
		page
	}) => {
		const { states } = await setup(page);
		let commands = 0;
		await page.route('**/api/v1/me/workspace-invitations/invitation-1/accept', async (route) => {
			commands++;
			states.set(invitation.id, {
				...invitation,
				state: 'accepted',
				can_accept: false,
				can_open: true
			});
			if (responseLost) await route.abort('failed');
			else await route.fulfill({ status: 404, json: { code: 'not_found' } });
		});
		await page.goto('/workspace');
		await page.getByRole('button', { name: 'Accept invitation', exact: true }).click();
		await expect(page.getByText('Invitation accepted.', { exact: true })).toBeVisible();
		await expect(page.getByRole('link', { name: 'Open Workspace', exact: true })).toBeVisible();
		expect(commands).toBe(1);
		await expect(page.getByRole('alert')).toHaveCount(0);
	});
}

test('unknown outcome offers status checking and blocks duplicate acceptance', async ({ page }) => {
	await setup(page);
	let commands = 0;
	let readable = false;
	await page.route('**/api/v1/me/workspace-invitations/invitation-1/accept', (route) => {
		commands++;
		return route.abort('failed');
	});
	await page.route('**/api/v1/me/workspace-invitations/invitation-1', (route) =>
		readable
			? route.fulfill({ json: invitation })
			: route.fulfill({ status: 503, json: { code: 'internal_error' } })
	);
	await page.goto('/workspace');
	await page.getByRole('button', { name: 'Accept invitation', exact: true }).click();
	await expect(
		page.getByText('Unable to confirm whether you joined. Check status before trying again.')
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Accept invitation', exact: true })).toBeDisabled();
	await expect(page.getByRole('button', { name: 'Dismiss', exact: true })).toHaveCount(0);
	readable = true;
	await page.getByRole('button', { name: 'Check status', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Accept invitation', exact: true })).toBeEnabled();
	expect(commands).toBe(1);
});

test('read failure has a local retry; pending accept prevents double submission', async ({
	page
}) => {
	const { states } = await setup(page);
	let failing = true;
	await page.route('**/api/v1/me/workspace-invitations?*', (route) =>
		failing
			? route.fulfill({ status: 500, json: { code: 'internal_error' } })
			: route.fulfill({ json: directoryPage([invitation], route) })
	);
	let release!: () => void;
	const held = new Promise<void>((resolve) => {
		release = resolve;
	});
	let commands = 0;
	await page.route('**/api/v1/me/workspace-invitations/invitation-1/accept', async (route) => {
		commands++;
		if (commands === 1) {
			await held;
			await route.fulfill({
				status: 500,
				json: { code: 'internal_error', message: 'Temporary failure' }
			});
		} else {
			states.set(invitation.id, {
				...invitation,
				state: 'accepted',
				can_accept: false,
				can_open: true
			});
			await route.fulfill({ json: { workspace_id: invitation.workspace_id } });
		}
	});
	await page.goto('/workspace');
	await expect(page.getByText('Unable to load workspace invitations.')).toBeVisible();
	await expect(page.getByText('No pending workspace invitations.', { exact: true })).toHaveCount(0);
	failing = false;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await page.getByRole('button', { name: 'Accept invitation', exact: true }).click();
	try {
		await expect.poll(() => commands).toBe(1);
		await expect(
			page.getByRole('button', { name: 'Accept invitation', exact: true })
		).toBeDisabled();
	} finally {
		release();
	}
	await expect(page.getByRole('alert')).toContainText('Something went wrong. Try again.');
	await expect(page.getByRole('button', { name: 'Accept invitation', exact: true })).toBeEnabled();
	await page.getByRole('button', { name: 'Accept invitation', exact: true }).click();
	await expect(page.getByText('Invitation accepted.', { exact: true })).toBeVisible();
	expect(commands).toBe(2);
});

for (const state of ['revoked', 'expired'] as const) {
	test(`${state} invitation discovered while accepting is explained`, async ({ page }) => {
		const { states } = await setup(page);
		await page.route('**/api/v1/me/workspace-invitations/invitation-1/accept', (route) => {
			states.set(invitation.id, { ...invitation, state, can_accept: false });
			return route.fulfill({ status: 404, json: { code: 'not_found' } });
		});
		await page.goto('/workspace');
		await page.getByRole('button', { name: 'Accept invitation', exact: true }).click();
		await expect(
			page.getByText(
				'This invitation is no longer available. Ask the inviter for a new invitation.'
			)
		).toBeVisible();
		await expect(page.getByRole('link', { name: 'Open Workspace', exact: true })).toHaveCount(0);
	});
}

test('read only invitation exposes the reason and no acceptance command', async ({ page }) => {
	await setup(page, [
		{ ...invitation, can_accept: false, unavailable_reason: 'workspace_read_only' }
	]);
	await page.goto('/workspace');
	await expect(
		page.getByText(
			'This workspace is read only. You can accept when membership changes are available again.'
		)
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Accept invitation', exact: true })).toBeDisabled();
});

test('invitation pagination survives refresh and browser history', async ({ page }) => {
	await setup(
		page,
		Array.from({ length: 26 }, (_, index) => ({
			...invitation,
			id: `invite-${index}`,
			workspace_name: `Group ${index + 1}`
		}))
	);
	await page.goto('/workspace');
	await page
		.getByRole('navigation', { name: 'Workspace invitations', exact: true })
		.getByRole('button', { name: 'Next page', exact: true })
		.click();
	await expect(page).toHaveURL(/invitation_page=2#invitations$/);
	await expect(page.getByRole('article')).toHaveCount(1);
	await page.reload();
	await expect(page.getByRole('article')).toHaveCount(1);
	await page.goBack();
	await expect(page.getByRole('article')).toHaveCount(25);
});

test('invitation pagination and workspace search and pagination remain independent', async ({
	page
}) => {
	await setup(
		page,
		Array.from({ length: 26 }, (_, index) => ({
			...invitation,
			id: `invite-${index}`,
			workspace_name: `Group ${index + 1}`
		}))
	);
	await page.route(/\/api\/v1\/workspaces(?:\?.*)?$/, (route) =>
		route.fulfill({
			json: directoryPage(
				Array.from({ length: 26 }, (_, index) =>
					workspaceView(`workspace-${index}`, `Research ${index + 1}`)
				),
				route
			)
		})
	);
	await page.goto('/workspace?q=Research&page=2&page_size=10');
	const invitationPages = page.getByRole('navigation', {
		name: 'Workspace invitations',
		exact: true
	});
	const workspacePages = page.getByRole('navigation', { name: 'Workspaces', exact: true });
	await invitationPages.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page).toHaveURL(/q=Research&page=2&page_size=10&invitation_page=2#invitations$/);
	await expect(page.getByRole('article')).toHaveCount(1);
	await expect(workspacePages).toContainText('Page 2 of 3');
	await page.getByRole('textbox', { name: 'Search workspaces', exact: true }).fill('Group');
	await expect(page).toHaveURL(/q=Group/);
	await expect(page).toHaveURL(/invitation_page=2/);
	await expect(workspacePages).toContainText('Page 1 of 3');
	await expect(page.getByRole('article')).toHaveCount(1);
	await workspacePages.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(workspacePages).toContainText('Page 2 of 3');
	await expect(page).toHaveURL(/invitation_page=2/);
	await page.reload();
	await expect(page.getByRole('article', { name: 'Group 26', exact: true })).toBeVisible();
	await expect(workspacePages).toContainText('Page 2 of 3');
	await page.goBack();
	await expect(workspacePages).toContainText('Page 1 of 3');
	await expect(page.getByRole('article', { name: 'Group 26', exact: true })).toBeVisible();
	await invitationPages
		.getByRole('combobox', { name: 'Page Size', exact: true })
		.selectOption('10');
	await expect(page).toHaveURL(/invitation_page_size=10/);
	await expect(page).toHaveURL(/q=Group/);
	await expect(page.getByRole('article')).toHaveCount(10);
});

for (const scenario of [
	{ width: 1440, locale: 'en-US', mode: 'light' },
	{ width: 390, locale: 'zh-CN', mode: 'dark' }
]) {
	test(`inbox wraps long content and is accessible at ${scenario.width}px in ${scenario.locale}`, async ({
		page
	}, testInfo) => {
		await page.setViewportSize({ width: scenario.width, height: 900 });
		await page.addInitScript(({ locale, mode }) => {
			localStorage.setItem('quirebase:locale', locale);
			localStorage.setItem('quirebase:theme', mode);
		}, scenario);
		const { states } = await setup(page);
		await page.route('**/api/v1/workspaces/creation-availability', (route) =>
			route.fulfill({
				json: { allowed: true, owner_username_required: true }
			})
		);
		await page.goto('/workspace');
		await expect(page.getByRole('article')).toBeVisible();
		await page.screenshot({
			path: testInfo.outputPath('workspace-invitations.png'),
			fullPage: true
		});
		states.set(invitation.id, {
			...invitation,
			workspace_name: '研究空间'.repeat(65),
			inviter_username: 'researcher'.repeat(20)
		});
		await page.locator('#invitations header button').click();
		await expect(page.getByRole('article')).toContainText('researcher'.repeat(20));
		expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
			true
		);
		await page.screenshot({
			path: testInfo.outputPath('workspace-long-invitation.png'),
			fullPage: true
		});
		const results = await new AxeBuilder({ page }).analyze();
		expect(results.violations).toEqual([]);
		if (scenario.locale === 'zh-CN')
			await expect(page.getByRole('heading', { level: 2 })).toHaveText('工作区邀请');
		states.clear();
		await page.locator('#invitations header button').click();
		await expect(page.locator('#invitations')).toHaveCount(0);
		await page.screenshot({
			path: testInfo.outputPath('workspace-no-invitations.png'),
			fullPage: true
		});
	});
}

test('missing invitation reconciles the pending badge and retires the stale accept action', async ({
	page
}) => {
	const { states } = await setup(page);
	let commands = 0;
	await page.route('**/api/v1/me/workspace-invitations/invitation-1/accept', (route) => {
		commands++;
		states.clear();
		return route.fulfill({
			status: 404,
			json: { code: 'not_found', message: 'Missing invitation' }
		});
	});
	await page.route('**/api/v1/me/workspace-invitations/invitation-1', (route) =>
		route.fulfill({ status: 404, json: { code: 'not_found', message: 'Missing invitation' } })
	);
	await page.goto('/workspace');
	await page.getByRole('button', { name: 'Accept invitation', exact: true }).click();
	await expect(
		page.getByText('This invitation is no longer available. Ask the inviter for a new invitation.')
	).toBeVisible();
	await expect(page.getByRole('article')).toHaveCount(0);
	await expect(page.getByLabel('1 pending invitations')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Accept invitation', exact: true })).toHaveCount(0);
	expect(commands).toBe(1);
});
