import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { directoryPage, mockSession, workspaceView } from './helpers';

test.describe.configure({ mode: 'parallel' });

async function setup(page: Page, role = 'viewer') {
	await mockSession(page);
	const state = {
		departed: false,
		view: {
			...workspaceView('workspace-1', 'Research'),
			current_role: role,
			authorization: { allowed: ['workspace.read', 'workspace_member.leave'] }
		},
		commands: [] as string[]
	};
	await page.route(/\/api\/v1\/workspaces(?:\?.*)?$/, (route) =>
		route.fulfill({
			json: directoryPage(
				[...(state.departed ? [] : [state.view]), workspaceView('workspace-2', 'Archive')],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		state.departed
			? route.fulfill({
					status: 404,
					json: { code: 'workspace_unavailable', message: 'Workspace unavailable' }
				})
			: route.fulfill({ json: state.view })
	);
	await page.route('**/api/v1/workspaces/workspace-1/leave', (route) => {
		state.commands.push(route.request().postDataJSON().membership_id);
		state.departed = true;
		return route.fulfill({ json: { ok: true } });
	});
	return state;
}

async function openLeaveSettingsFromAnotherWorkspace(page: Page) {
	await page.goto('/workspace/workspace-2/settings');
	// Use client-side navigation so the pending command's JavaScript survives Back.
	await page.getByRole('button', { name: 'Quirebase' }).click();
	await page.getByRole('menuitem', { name: /Research/ }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1$/);
	await page.getByRole('button', { name: 'Quirebase' }).click();
	await page.getByRole('menuitem', { name: 'Workspace settings' }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/settings$/);
}

for (const role of ['viewer', 'admin']) {
	test(`${role} can cancel or confirm leaving and return to the directory`, async ({ page }) => {
		const state = await setup(page, role);
		await page.goto('/workspace/workspace-1/settings');
		await page.getByRole('button', { name: 'Leave workspace', exact: true }).click();
		const dialog = page.getByRole('dialog');
		await expect(dialog).toContainText('Leave Research?');
		await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
		expect(state.commands).toEqual([]);
		await page.getByRole('button', { name: 'Leave workspace', exact: true }).click();
		await dialog.getByRole('button', { name: 'Leave workspace', exact: true }).click();
		await expect(page).toHaveURL(/\/workspace$/);
		await expect(page.getByRole('link', { name: /Research.*Open Workspace/ })).toHaveCount(0);
		await expect(page.getByRole('link', { name: /Archive.*Open Workspace/ })).toBeVisible();
		expect(state.commands).toEqual(['membership-workspace-1']);
		expect(
			await page.evaluate(() => localStorage.getItem('quirebase:default-workspace'))
		).toBeNull();
	});
}

test('owner and read-only states explain prerequisites without a leave command', async ({
	page
}) => {
	await mockSession(page);
	await page.goto('/workspace/workspace-1/settings');
	await expect(
		page.getByText('Transfer workspace ownership to another member before leaving.')
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Leave workspace', exact: true })).toHaveCount(0);
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill({
			json: {
				...workspaceView('workspace-1', 'Research'),
				governance_frozen: true,
				authorization: { allowed: ['workspace.read'] }
			}
		})
	);
	await page.reload();
	await expect(page.getByText('You cannot leave while this workspace is read only.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Leave workspace', exact: true })).toHaveCount(0);
});

test('pending leave blocks dismissal and duplicate submission; a failed confirmation can retry', async ({
	page
}) => {
	const state = await setup(page);
	let release!: () => void;
	const held = new Promise<void>((resolve) => {
		release = resolve;
	});
	let attempts = 0;
	await page.route('**/api/v1/workspaces/workspace-1/leave', async (route) => {
		attempts++;
		if (attempts === 1) {
			await held;
			await route.fulfill({
				status: 503,
				json: { code: 'internal_error', message: 'Temporary failure' }
			});
		} else {
			state.departed = true;
			await route.fulfill({ json: { ok: true } });
		}
	});
	await page.goto('/workspace/workspace-1/settings');
	await page.getByRole('button', { name: 'Leave workspace', exact: true }).click();
	const dialog = page.getByRole('dialog');
	await dialog.getByRole('button', { name: 'Leave workspace', exact: true }).click();
	try {
		await expect.poll(() => attempts).toBe(1);
		await expect(
			dialog.getByRole('button', { name: 'Leave workspace', exact: true })
		).toBeDisabled();
		await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
		await page.keyboard.press('Escape');
		await expect(dialog).toBeVisible();
	} finally {
		release();
	}
	await expect(dialog.getByRole('alert')).toBeVisible();
	await expect(dialog.getByRole('button', { name: 'Leave workspace', exact: true })).toBeEnabled();
	await dialog.getByRole('button', { name: 'Leave workspace', exact: true }).click();
	await expect(page).toHaveURL(/\/workspace$/);
	expect(attempts).toBe(2);
});

test('a lost leave response recovers availability without replay and preserves another default', async ({
	page
}) => {
	const state = await setup(page);
	await page.addInitScript(() =>
		localStorage.setItem('quirebase:default-workspace', 'workspace-2')
	);
	await page.route('**/api/v1/workspaces/workspace-1/leave', (route) => {
		state.commands.push(route.request().postDataJSON().membership_id);
		state.departed = true;
		return route.abort('failed');
	});
	await page.goto('/workspace/workspace-1/settings');
	await page.getByRole('button', { name: 'Quirebase' }).click();
	await expect(page.getByRole('menuitem', { name: /Research/ })).toBeVisible();
	await expect(page.getByRole('menuitem', { name: /Archive/ })).toBeVisible();
	await page.keyboard.press('Escape');
	await page.getByRole('button', { name: 'Leave workspace', exact: true }).click();
	await page
		.getByRole('dialog')
		.getByRole('button', { name: 'Leave workspace', exact: true })
		.click();
	await expect(page).toHaveURL(/\/workspace$/);
	await expect(page.getByRole('link', { name: /Research.*Open Workspace/ })).toHaveCount(0);
	await expect(page.getByRole('link', { name: /Archive.*Open Workspace/ })).toBeVisible();
	await page.getByRole('button', { name: 'Quirebase' }).click();
	await expect(page.getByRole('menuitem', { name: /Research/ })).toHaveCount(0);
	await expect(page.getByRole('menuitem', { name: /Archive/ })).toBeVisible();
	expect(state.commands).toEqual(['membership-workspace-1']);
	expect(await page.evaluate(() => localStorage.getItem('quirebase:default-workspace'))).toBe(
		'workspace-2'
	);
});

test('a confirmation keeps its submitted generation when membership changes in another tab', async ({
	page
}) => {
	const state = await setup(page);
	await page.route('**/api/v1/workspaces/workspace-1/leave', (route) => {
		const membershipId = route.request().postDataJSON().membership_id;
		state.commands.push(membershipId);
		state.view.current_membership_id = 'membership-rejoined';
		if (membershipId !== state.view.current_membership_id)
			return route.fulfill({
				status: 404,
				json: { code: 'not_found', message: 'Membership changed' }
			});
		state.departed = true;
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/settings');
	await page.getByRole('button', { name: 'Leave workspace', exact: true }).click();
	const dialog = page.getByRole('dialog');
	await dialog.getByRole('button', { name: 'Leave workspace', exact: true }).click();
	await expect(dialog.getByRole('alert')).toBeVisible();
	await dialog.getByRole('button', { name: 'Leave workspace', exact: true }).click();
	await expect.poll(() => state.commands.length).toBe(2);
	expect(state.commands).toEqual(['membership-workspace-1', 'membership-workspace-1']);
	await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toBeEnabled();
	await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
	await page.getByRole('button', { name: 'Leave workspace', exact: true }).click();
	await dialog.getByRole('button', { name: 'Leave workspace', exact: true }).click();
	await expect(page).toHaveURL(/\/workspace$/);
	expect(state.commands.at(-1)).toBe('membership-rejoined');
});

for (const outcome of ['successful', 'lost-response']) {
	for (const savedWorkspace of ['workspace-1', 'workspace-2']) {
		test(`a ${outcome} leave reconciles after navigation with default ${savedWorkspace}`, async ({
			page
		}) => {
			const state = await setup(page);
			let release!: () => void;
			const held = new Promise<void>((resolve) => {
				release = resolve;
			});
			let availabilityChecks = 0;
			await page.route('**/api/v1/workspaces/workspace-1', (route) => {
				if (!state.departed) return route.fallback();
				availabilityChecks++;
				return route.fulfill({
					status: 404,
					json: { code: 'workspace_unavailable', message: 'Workspace unavailable' }
				});
			});
			await page.route('**/api/v1/workspaces/workspace-1/leave', async (route) => {
				state.commands.push(route.request().postDataJSON().membership_id);
				await held;
				state.departed = true;
				if (outcome === 'lost-response') await route.abort('failed');
				else await route.fulfill({ json: { ok: true } });
			});
			await openLeaveSettingsFromAnotherWorkspace(page);
			await page.getByRole('button', { name: 'Leave workspace', exact: true }).click();
			await page
				.getByRole('dialog')
				.getByRole('button', { name: 'Leave workspace', exact: true })
				.click();
			try {
				await expect.poll(() => state.commands.length).toBe(1);
				await page.goBack();
				await expect(page).toHaveURL(/\/workspace\/workspace-1$/);
				await page.goBack();
				await expect(page).toHaveURL(/\/workspace\/workspace-2\/settings$/);
				await page.evaluate(
					(value) => localStorage.setItem('quirebase:default-workspace', value),
					savedWorkspace
				);
			} finally {
				release();
			}
			await expect.poll(() => state.departed).toBe(true);
			await page.getByRole('button', { name: 'Quirebase' }).click();
			await expect(page.getByRole('menuitem', { name: /Research/ })).toHaveCount(0);
			await expect(page.getByRole('menuitem', { name: /Archive/ })).toBeVisible();
			await expect(page).toHaveURL(/\/workspace\/workspace-2\/settings$/);
			await expect(page.getByRole('heading', { name: 'Workspace settings' })).toBeVisible();
			if (outcome === 'lost-response') expect(availabilityChecks).toBeGreaterThan(0);
			expect(state.commands).toEqual(['membership-workspace-1']);
			expect(await page.evaluate(() => localStorage.getItem('quirebase:default-workspace'))).toBe(
				savedWorkspace === 'workspace-1' ? null : savedWorkspace
			);
		});
	}
}

test('navigation during a failed leave availability read still reconciles the captured workspace', async ({
	page
}) => {
	const state = await setup(page);
	let release!: () => void;
	const held = new Promise<void>((resolve) => {
		release = resolve;
	});
	let verificationStarted = false;
	await page.route('**/api/v1/workspaces/workspace-1', async (route) => {
		if (!state.departed) return route.fallback();
		verificationStarted = true;
		await held;
		await route.fulfill({
			status: 404,
			json: { code: 'workspace_unavailable', message: 'Workspace unavailable' }
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/leave', (route) => {
		state.commands.push(route.request().postDataJSON().membership_id);
		state.departed = true;
		return route.abort('failed');
	});
	await openLeaveSettingsFromAnotherWorkspace(page);
	await page.getByRole('button', { name: 'Leave workspace', exact: true }).click();
	await page
		.getByRole('dialog')
		.getByRole('button', { name: 'Leave workspace', exact: true })
		.click();
	try {
		await expect.poll(() => verificationStarted).toBe(true);
		await page.goBack();
		await expect(page).toHaveURL(/\/workspace\/workspace-1$/);
		await page.goBack();
		await expect(page).toHaveURL(/\/workspace\/workspace-2\/settings$/);
	} finally {
		release();
	}
	await page.getByRole('button', { name: 'Quirebase' }).click();
	await expect(page.getByRole('menuitem', { name: /Research/ })).toHaveCount(0);
	await expect(page.getByRole('menuitem', { name: /Archive/ })).toBeVisible();
	await expect(page).toHaveURL(/\/workspace\/workspace-2\/settings$/);
	expect(await page.evaluate(() => localStorage.getItem('quirebase:default-workspace'))).toBeNull();
	expect(state.commands).toEqual(['membership-workspace-1']);
});

test('mobile Chinese leave confirmation fits long names and remains accessible', async ({
	page
}, testInfo) => {
	await page.setViewportSize({ width: 390, height: 900 });
	await page.addInitScript(() => {
		localStorage.setItem('quirebase:locale', 'zh-CN');
		localStorage.setItem('quirebase:theme', 'dark');
	});
	const state = await setup(page);
	state.view.name = '跨学科文献研究工作区'.repeat(12);
	await page.goto('/workspace/workspace-1/settings');
	await page.getByRole('button', { name: '离开工作区', exact: true }).click();
	await expect(page.getByRole('dialog')).toContainText(state.view.name);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
	const results = await new AxeBuilder({ page }).analyze();
	expect(results.violations).toEqual([]);
	await page.screenshot({
		path: testInfo.outputPath('leave-workspace-mobile.png'),
		fullPage: true
	});
});
