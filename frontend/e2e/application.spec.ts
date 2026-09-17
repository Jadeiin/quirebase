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
	const accountMenu = page.locator('[role="menu"]');
	await expect
		.poll(async () => {
			await accountMenu.press('Escape');
			return accountMenu.isHidden();
		})
		.toBe(true);
	await page.getByRole('link', { name: 'Library' }).first().click();
	await expect(page.getByRole('heading', { name: 'Library' })).toBeVisible();
});
