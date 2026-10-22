import { tagPage, directoryPage } from './helpers';
import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

for (const failure of ['network', 'server'] as const) {
	test(`session bootstrap ${failure} failure offers retry without showing a sign-in form`, async ({
		page
	}) => {
		let attempts = 0;
		await page.route('**/api/v1/session', (route) => {
			attempts += 1;
			if (attempts === 1)
				return failure === 'network'
					? route.abort('failed')
					: route.fulfill({
							status: 503,
							json: { code: 'request_failed', message: 'Request failed' }
						});
			return route.fulfill({ json: { authenticated: false, user: null } });
		});

		await page.goto('/');
		await expect(page.getByText('Unable to check your account.', { exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toHaveCount(0);
		await page.getByRole('button', { name: 'Retry', exact: true }).click();
		await expect(page.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible();
		expect(attempts).toBe(2);
	});

	test(`invitation ${failure} failure can be retried without reporting the invitation expired`, async ({
		page
	}) => {
		await page.route('**/api/v1/session', (route) =>
			route.fulfill({ json: { authenticated: false, user: null } })
		);
		let attempts = 0;
		await page.route('**/api/v1/invitations/retry-token', (route) => {
			attempts += 1;
			if (attempts === 1)
				return failure === 'network'
					? route.abort('failed')
					: route.fulfill({
							status: 503,
							json: { code: 'request_failed', message: 'Request failed' }
						});
			return route.fulfill({
				json: {
					kind: 'account',
					username: 'invited-reader',
					role: 'member',
					expires_at: '2027-01-01T00:00:00Z'
				}
			});
		});

		await page.goto('/invite/retry-token');
		await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
		await expect(page.getByText(/invalid or.*expired/)).toHaveCount(0);
		await expect(page.getByRole('button', { name: 'Create account', exact: true })).toHaveCount(0);
		await page.getByRole('button', { name: 'Retry', exact: true }).click();
		await expect(page.getByRole('button', { name: 'Create account', exact: true })).toBeVisible();
		await expect(page.getByText('invited-reader', { exact: true })).toBeVisible();
		expect(attempts).toBe(2);
	});
}

test('an authoritative invitation denial still reports that the invitation is invalid', async ({
	page
}) => {
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({ json: { authenticated: false, user: null } })
	);
	await page.route('**/api/v1/invitations/expired-token', (route) =>
		route.fulfill({
			status: 404,
			json: { code: 'invitation_not_found', message: 'Invitation not found' }
		})
	);
	await page.goto('/invite/expired-token');
	await expect(page.getByText('This invitation is invalid or has expired.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Create account', exact: true })).toHaveCount(0);
});

test('stored locale activates navigation without an unrelated rerender', async ({ page }) => {
	await page.addInitScript(() => localStorage.setItem('quirebase:locale', 'zh-CN'));
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({
			json: { new_items: [], recent_items: [], projects: [], session_count: 1 }
		})
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

	await expect(page.getByRole('link', { name: '文献库' }).first()).toBeVisible();
	await expect(page.getByRole('heading', { name: '概览' })).toBeVisible();
	await expect(page.getByText('继续阅读或打开一个研究项目。')).toBeVisible();
	await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
	await page.getByRole('link', { name: '文献库' }).first().click();
	await expect(page.getByRole('heading', { name: '文献库' })).toBeVisible();
	await expect(page.getByPlaceholder('搜索标题、作者、标签或全文')).toBeVisible();
});
