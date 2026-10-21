import { expect, test } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { directoryPage, mockSession, workspaceView } from './helpers';

test('workspace directory exposes global navigation and distinguishes an empty search', async ({
	page
}) => {
	await mockSession(page);
	await page.route(/\/api\/v1\/workspaces(?:\?.*)?$/, (route) => {
		const search = new URL(route.request().url()).searchParams.get('search');
		return route.fulfill({
			json: directoryPage(search ? [] : [workspaceView('workspace-1', 'Research')], route)
		});
	});
	await page.goto('/workspace');
	await expect(page.getByRole('heading', { name: 'My workspaces', exact: true })).toBeVisible();
	await expect(
		page
			.getByRole('navigation', { name: 'Main navigation' })
			.getByRole('link', { name: 'Library', exact: true })
	).toHaveCount(0);
	await page.getByLabel('Search workspaces', { exact: true }).fill('missing');
	await expect(
		page.getByRole('status').filter({ hasText: 'No matching workspaces.' })
	).toBeVisible();
	await page.reload();
	await expect(page.getByLabel('Search workspaces', { exact: true })).toHaveValue('missing');
	await page.getByRole('button', { name: 'Clear search', exact: true }).click();
	await expect(page.getByRole('link', { name: /Research.*Open Workspace/ })).toBeVisible();
});

test('settings sections load their own data and preserve member search across navigation and refresh', async ({
	page
}) => {
	await mockSession(page);
	let memberReads = 0;
	let invitationReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/governance/members?*', (route) => {
		memberReads += 1;
		return route.fulfill({ json: directoryPage([], route) });
	});
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/invitations(?:\?.*)?$/, (route) => {
		invitationReads += 1;
		return route.fulfill({ json: directoryPage([], route) });
	});
	await page.goto('/workspace/workspace-1/settings');
	const sections = page.getByRole('navigation', { name: 'Workspace settings', exact: true });
	await expect(sections.getByRole('link', { name: 'General', exact: true })).toHaveAttribute(
		'aria-current',
		'page'
	);
	expect(memberReads).toBe(0);
	expect(invitationReads).toBe(0);
	await expect(page.getByRole('button', { name: 'Archive workspace', exact: true })).toHaveCount(0);
	await sections.getByRole('link', { name: 'Members', exact: true }).click();
	await page.getByRole('searchbox', { name: 'Search members', exact: true }).fill('reader');
	await expect(page).toHaveURL(/settings\/members\?q=reader$/);
	await page.reload();
	await expect(page.getByRole('searchbox', { name: 'Search members', exact: true })).toHaveValue(
		'reader'
	);
	await sections.getByRole('link', { name: 'General', exact: true }).click();
	await expect(page).toHaveURL(/\/settings$/);
	await page.goBack();
	await expect(page.getByRole('searchbox', { name: 'Search members', exact: true })).toHaveValue(
		'reader'
	);
	expect(memberReads).toBeGreaterThan(0);
	expect(invitationReads).toBe(0);
});

test('invitation read errors offer a local retry', async ({ page }) => {
	await mockSession(page);
	let fail = true;
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/invitations(?:\?.*)?$/, (route) =>
		route.fulfill(
			fail
				? { status: 500, json: { code: 'internal_error', message: 'Fixture failure' } }
				: { json: directoryPage([], route) }
		)
	);
	await page.goto('/workspace/workspace-1/settings/invitations');
	await expect(
		page.getByRole('alert').filter({ hasText: 'Unable to load invitations.' })
	).toBeVisible();
	fail = false;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByText('No pending invitations.', { exact: true })).toBeVisible();
});

test('archive uses a product dialog and cancellation never sends a command', async ({ page }) => {
	await mockSession(page);
	let archives = 0;
	await page.route('**/api/v1/workspaces/workspace-1/archive', (route) => {
		archives += 1;
		return route.fulfill({ json: { ok: true } });
	});
	page.on('dialog', async (dialog) => {
		await dialog.dismiss();
		throw new Error('Unexpected native dialog');
	});
	await page.goto('/workspace/workspace-1/settings/advanced');
	await page.getByRole('button', { name: 'Archive workspace', exact: true }).click();
	const dialog = page.getByRole('dialog');
	await expect(dialog).toContainText('Research');
	await dialog.getByRole('button', { name: 'Cancel', exact: true }).press('Enter');
	await expect(dialog).toHaveCount(0);
	expect(archives).toBe(0);
	await page.getByRole('button', { name: 'Archive workspace', exact: true }).click();
	await page
		.getByRole('dialog')
		.getByRole('button', { name: 'Archive workspace', exact: true })
		.click();
	await expect(page.getByText('Workspace archived', { exact: true })).toBeVisible();
	expect(archives).toBe(1);
});

test('member removal retains a failed confirmation for retry', async ({ page }) => {
	await mockSession(page);
	let removed = false;
	let attempts = 0;
	await page.route('**/api/v1/workspaces/workspace-1/governance/members?*', (route) =>
		route.fulfill({
			json: directoryPage(
				removed
					? []
					: [
							{
								membership_id: 'target-member',
								user_id: 'target-user',
								username: 'collaborator',
								role: 'viewer',
								state: 'active',
								joined_at: '2026-01-01T00:00:00Z',
								allowed_roles: [],
								authorization: { allowed: ['workspace_member.terminate'] }
							}
						],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/members/target-member', (route) => {
		attempts += 1;
		removed = attempts > 1;
		return route.fulfill(
			removed
				? { json: { ok: true } }
				: { status: 500, json: { code: 'internal_error', message: 'Fixture failure' } }
		);
	});
	await page.goto('/workspace/workspace-1/settings/members');
	await page.getByRole('button', { name: 'Actions for collaborator' }).click();
	await page.getByRole('menuitem', { name: 'Terminate', exact: true }).click();
	const dialog = page.getByRole('dialog');
	await expect(dialog).toContainText('collaborator');
	await dialog.getByRole('button', { name: 'Terminate', exact: true }).click();
	await expect(dialog.getByRole('alert')).toBeVisible();
	await dialog.getByRole('button', { name: 'Terminate', exact: true }).click();
	await expect(dialog).toHaveCount(0);
	await expect(page.getByText('Member removed', { exact: true })).toBeVisible();
	expect(attempts).toBe(2);
});

test('permanent deletion requires the workspace name and keeps errors in the dialog', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill({ json: { ...workspaceView('workspace-1', 'Research'), state: 'archived' } })
	);
	let deletions = 0;
	await page.route('**/api/v1/workspaces/workspace-1', (route) => {
		if (route.request().method() !== 'DELETE') return route.fallback();
		deletions += 1;
		return route.fulfill({
			status: 409,
			json: { code: 'workspace_lifecycle_error', message: 'Retention period' }
		});
	});
	await page.goto('/workspace/workspace-1/settings/advanced');
	await page.getByRole('button', { name: 'Permanently delete workspace', exact: true }).click();
	const dialog = page.getByRole('dialog');
	const confirmation = dialog.getByRole('button', {
		name: 'Permanently delete workspace',
		exact: true
	});
	await dialog.getByLabel('Type the workspace name to confirm').fill('wrong');
	await expect(confirmation).toBeDisabled();
	expect(deletions).toBe(0);
	await dialog.getByLabel('Type the workspace name to confirm').fill('Research');
	await confirmation.click();
	await expect(dialog.getByRole('alert')).toBeVisible();
	await expect(dialog.getByLabel('Type the workspace name to confirm')).toHaveValue('Research');
	expect(deletions).toBe(1);
});

for (const scenario of [
	{ width: 1440, locale: 'en-US' },
	{ width: 390, locale: 'zh-CN' }
]) {
	test(`workspace pages fit long content and remain accessible at ${scenario.width}px in ${scenario.locale}`, async ({
		page
	}, testInfo) => {
		await page.setViewportSize({ width: scenario.width, height: 900 });
		await mockSession(page, 'administrator');
		await page.addInitScript(
			(locale) => localStorage.setItem('quirebase:locale', locale),
			scenario.locale
		);
		const view = workspaceView('workspace-1', 'Research'.repeat(18));
		view.authorization.allowed.push('workspace_maintenance.run');
		await page.route('**/api/v1/workspaces/workspace-1', (route) => route.fulfill({ json: view }));
		await page.route('**/api/v1/workspaces/workspace-1/governance/members?*', (route) =>
			route.fulfill({
				json: directoryPage(
					[
						{
							membership_id: 'target-member',
							user_id: 'target-user',
							username: 'collaborator'.repeat(8),
							role: 'viewer',
							state: 'active',
							joined_at: '2026-01-01T00:00:00Z',
							allowed_roles: ['editor', 'reviewer'],
							authorization: {
								allowed: ['workspace_member.terminate', 'workspace_member.transfer_ownership']
							}
						}
					],
					route
				)
			})
		);
		await page.route(/\/api\/v1\/workspaces\/workspace-1\/invitations(?:\?.*)?$/, (route) =>
			route.fulfill({ json: directoryPage([], route) })
		);
		for (const path of [
			'/workspace',
			'/workspace/workspace-1/settings',
			'/workspace/workspace-1/settings/members',
			'/workspace/workspace-1/settings/invitations',
			'/workspace/workspace-1/settings/advanced'
		]) {
			await page.goto(path);
			await expect(page.getByRole('main').getByRole('heading', { level: 1 })).toBeVisible();
			if (path.endsWith('/members')) await expect(page.getByRole('table')).toBeVisible();
			await expect
				.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
				.toBe(true);
			const results = await new AxeBuilder({ page })
				.withTags(['wcag2a', 'wcag2aa', 'wcag21aa'])
				.analyze();
			expect(
				results.violations
					.filter(({ impact }) => impact === 'serious' || impact === 'critical')
					.map(({ id, nodes }) => ({ id, targets: nodes.map(({ target }) => target) }))
			).toEqual([]);
			const name = `${path.split('/').at(-1)}-${scenario.width}`;
			const screenshot = testInfo.outputPath(`${name}.png`);
			await page.screenshot({ path: screenshot, fullPage: true });
			await testInfo.attach(name, {
				path: screenshot,
				contentType: 'image/png'
			});
		}
	});
}
