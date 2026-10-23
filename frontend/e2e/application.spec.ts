import { tagPage, directoryPage } from './helpers';
import { expect, test } from '@playwright/test';
import { mockSession, mockWorkspaces } from './helpers';

test('authenticated shell loads dashboard and navigates to Library', async ({ page }) => {
	const pageErrors: string[] = [];
	let sessionRequests = 0;
	page.on('pageerror', (error) => pageErrors.push(error.message));
	await mockWorkspaces(page);
	await page.route('**/api/v1/session', (route) => {
		sessionRequests += 1;
		return route.fulfill({
			json: {
				authenticated: true,
				user: { id: 'user-1', username: 'reader', role: 'member' }
			}
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items*', (route) =>
		route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);

	await page.goto('/');
	await expect.poll(() => sessionRequests).toBe(1);
	await expect.poll(() => pageErrors).toEqual([]);
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	await page.getByRole('button', { name: /reader/i }).click();
	await expect(page.getByRole('menuitem', { name: 'Account settings' })).toBeVisible();
	const accountMenu = page.getByRole('menu', { name: 'R reader Member' });
	await expect
		.poll(async () => {
			await accountMenu.press('Escape');
			return accountMenu.isHidden();
		})
		.toBe(true);
	await page.getByRole('link', { name: 'Library' }).first().click();
	await expect(page.getByRole('heading', { name: 'Library' })).toBeVisible();
});

for (const width of [1440, 390]) {
	test(`dashboard wraps unbroken titles inside both reading lists at ${width}px`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 1000 });
		await mockSession(page);
		const title = 'UnbrokenResearchTitle'.repeat(8);
		const item = {
			id: 'item-long',
			title_html: title,
			authors: [],
			publication_date: '2026',
			publication_title: null,
			doi: null,
			version: 1
		};
		await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
			route.fulfill({
				json: {
					new_items: [item],
					recent_items: [{ item, last_read_at: '2026-10-23T00:00:00Z' }],
					projects: [],
					project_count: 0,
					session_count: 1
				}
			})
		);
		await page.goto('/workspace/workspace-1');
		const titles = page.getByRole('main').locator('strong').filter({ hasText: title });
		await expect(titles).toHaveCount(2);
		for (const element of await titles.all()) {
			await expect(element).toBeVisible();
			const layout = await element.evaluate((node) => ({
				width: node.clientWidth,
				contentWidth: node.scrollWidth,
				height: node.getBoundingClientRect().height,
				lineHeight: Number.parseFloat(getComputedStyle(node).lineHeight)
			}));
			expect(layout.contentWidth).toBeLessThanOrEqual(layout.width + 1);
			expect(layout.height).toBeGreaterThan(layout.lineHeight);
		}
	});
}

for (const [role, choices] of [
	['owner', ['managed']],
	['admin', ['workspace']],
	['editor', ['open']],
	['owner', []]
] as const) {
	test(`Dashboard New Project shortcut follows ${role}'s projected participation choices: ${choices.join(',') || 'none'}`, async ({
		page
	}) => {
		await mockSession(page);
		const workspace = {
			id: 'workspace-1',
			name: 'Research',
			owner_id: 'user-1',
			state: 'active',
			current_role: role,
			governance_frozen: false,
			allowed_project_participations: choices,
			authorization: { allowed: ['workspace.read'] }
		};
		await page.route(/\/api\/v1\/workspaces(?:\?.*)?$/, (route) =>
			route.fulfill({ json: directoryPage([workspace], route) })
		);
		await page.route('**/api/v1/workspaces/workspace-1', (route) =>
			route.fulfill({ json: workspace })
		);
		await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
			route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
		);
		await page.route('**/api/v1/workspaces/workspace-1/projects?view=*', (route) =>
			route.fulfill({ json: directoryPage([], route) })
		);
		await page.goto('/workspace/workspace-1');
		await expect(page.getByRole('heading', { name: 'Quick actions' })).toBeVisible();
		const shortcut = page.getByRole('link', { name: /New Project/ });
		if (choices.length > 0) {
			await expect(shortcut).toBeVisible();
			await shortcut.click();
			await expect(page).toHaveURL(/\/workspace\/workspace-1\/projects$/);
			await expect(page.getByRole('button', { name: 'New Project' })).toBeVisible();
		} else {
			await expect(shortcut).toHaveCount(0);
		}
	});
}

test('theme preference persists and system mode follows the browser', async ({ page }) => {
	await page.emulateMedia({ colorScheme: 'dark' });
	await mockWorkspaces(page);
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: {
				authenticated: true,
				user: { id: 'user-1', username: 'reader', role: 'member' }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);

	await page.goto('/');
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();

	await page.getByRole('button', { name: /reader/i }).click();
	await page.getByRole('menuitem', { name: 'Light theme' }).click();
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'light');
	await expect
		.poll(() => page.evaluate(() => localStorage.getItem('quirebase:theme')))
		.toBe('light');

	await page.reload();
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'light');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	await page.getByRole('button', { name: /reader/i }).click();
	await page.getByRole('menuitem', { name: 'Dark theme' }).click();
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect
		.poll(() => page.evaluate(() => localStorage.getItem('quirebase:theme')))
		.toBe('dark');

	await page.getByRole('button', { name: /reader/i }).click();
	await page.getByRole('menuitem', { name: 'System theme' }).click();
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect.poll(() => page.evaluate(() => localStorage.getItem('quirebase:theme'))).toBeNull();
	await page.emulateMedia({ colorScheme: 'light' });
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'light');
	await page.emulateMedia({ colorScheme: 'dark' });
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
});

test('account menu keeps the active theme during client-side navigation', async ({ page }) => {
	let documentRequests = 0;
	page.on('request', (request) => {
		if (request.resourceType() === 'document') documentRequests += 1;
	});
	await page.addInitScript(() => localStorage.setItem('quirebase:theme', 'dark'));
	await mockWorkspaces(page);
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: {
				authenticated: true,
				user: { id: 'user-1', username: 'reader', role: 'member' }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);
	await page.route('**/api/v1/account', (route) =>
		route.fulfill({
			json: {
				user: { id: 'user-1', username: 'reader', role: 'member' },
				sessions: [],
				api_tokens: []
			}
		})
	);

	await page.goto('/');
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect.poll(() => documentRequests).toBe(1);
	await page.getByRole('button', { name: /reader/i }).click();
	await page.getByRole('menuitem', { name: 'Account settings' }).click();

	await expect(page).toHaveURL(/\/account$/);
	await expect(page.getByRole('heading', { name: 'Account' })).toBeVisible();
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect.poll(() => documentRequests).toBe(1);
});

test('mobile navigation keeps primary destinations visible and moves utilities into More', async ({
	page
}) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/workspaces/workspace-1/items*', (route) =>
		route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.goto('/workspace/workspace-1/library');

	const navigation = page.getByRole('navigation', { name: 'Mobile navigation' });
	await expect(navigation.getByRole('link', { name: 'Library' })).toBeVisible();
	await expect(navigation.getByRole('link', { name: 'Discovery' })).toBeVisible();
	await expect(navigation.getByRole('link', { name: 'Projects' })).toBeVisible();
	await navigation.getByRole('button', { name: 'More' }).click();
	await expect(page.getByRole('menuitem', { name: 'Import' })).toBeVisible();
	await expect(page.getByRole('menuitem', { name: 'Tools' })).toBeVisible();
	await expect(page.getByRole('menuitem', { name: 'Administration' })).toBeVisible();
});

test('desktop sidebar collapse persists across navigation reloads', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);

	await page.goto('/');
	await page.getByRole('button', { name: 'Collapse sidebar' }).click();
	await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Library', exact: true })).toHaveAttribute(
		'title',
		'Library'
	);
	await page.reload();
	await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible();
});

for (const width of [1280, 390]) {
	test(`Workspace menu contains long names without horizontal overflow at ${width}px`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 844 });
		await mockSession(page);
		const { workspaceView } = await import('./helpers');
		const workspace = workspaceView('workspace-1', 'A very long Workspace name '.repeat(8));
		await page.route(/\/api\/v1\/workspaces(?:\?.*)?$/, (route) =>
			route.fulfill({ json: directoryPage([workspace], route) })
		);
		await page.route('**/api/v1/workspaces/workspace-1', (route) =>
			route.fulfill({ json: workspace })
		);
		await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
			route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
		);
		await page.goto('/workspace/workspace-1');
		await page.getByRole('button', { name: 'Quirebase' }).click();
		const menu = page.getByRole('menu', { name: 'Quirebase' });
		await expect(menu).toBeVisible();
		await expect(menu.getByRole('menuitem', { name: /A very long Workspace name/ })).toBeVisible();
		await expect
			.poll(() => menu.evaluate((element) => element.scrollWidth <= element.clientWidth))
			.toBe(true);
		const bounds = await menu.boundingBox();
		expect(bounds!.x).toBeGreaterThanOrEqual(0);
		expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
	});
}

test('Appearance labels stay aligned when the selected theme changes', async ({ page }) => {
	await page.addInitScript(() => localStorage.setItem('quirebase:theme', 'dark'));
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
	);
	await page.goto('/workspace/workspace-1');
	for (const active of ['Dark theme', 'Light theme']) {
		await page.getByRole('button', { name: /reader/i }).click();
		for (const name of ['Light theme', 'Dark theme', 'System theme']) {
			const item = page.getByRole('menuitem', { name });
			await expect(item).toHaveAttribute('data-active', String(name === active));
			await expect(item.locator('span').last()).toHaveText(name === active ? '✓' : '');
		}
		await expect
			.poll(() =>
				page.getByRole('menuitem', { name: /^(Light|Dark|System) theme$/ }).evaluateAll((items) => {
					// Measure one layout frame; the menu can reposition while opening.
					const positions = items.map(
						(item) => item.querySelector('span.min-w-0')!.getBoundingClientRect().x
					);
					return Math.max(...positions) - Math.min(...positions);
				})
			)
			.toBeLessThan(1);
		await page.getByRole('menuitem', { name: 'Light theme' }).click();
	}
});
