import { expect, test } from '@playwright/test';

test('authenticated shell loads dashboard and navigates to Library', async ({ page }) => {
	const pageErrors: string[] = [];
	let sessionRequests = 0;
	page.on('pageerror', (error) => pageErrors.push(error.message));
	await page.route('**/api/v1/session', (route) => {
		sessionRequests += 1;
		return route.fulfill({
			json: {
				authenticated: true,
				locale: 'en-US',
				user: { id: 'user-1', username: 'reader', role: 'member' }
			}
		});
	});
	await page.route('**/api/v1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);
	await page.route('**/api/v1/items*', (route) =>
		route.fulfill({ json: { items: [], total: 0, page: 1, per_page: 25 } })
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

test('theme preference persists and system mode follows the browser', async ({ page }) => {
	await page.emulateMedia({ colorScheme: 'dark' });
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: {
				authenticated: true,
				locale: 'en-US',
				user: { id: 'user-1', username: 'reader', role: 'member' }
			}
		})
	);
	await page.route('**/api/v1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);

	await page.goto('/');
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');

	await page.getByRole('button', { name: /reader/i }).click();
	await page.getByRole('menuitem', { name: 'Light theme' }).click();
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'light');
	await expect
		.poll(() => page.evaluate(() => localStorage.getItem('quirebase:theme')))
		.toBe('light');

	await page.reload();
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'light');
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
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: {
				authenticated: true,
				locale: 'en-US',
				user: { id: 'user-1', username: 'reader', role: 'member' }
			}
		})
	);
	await page.route('**/api/v1/dashboard', (route) =>
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
