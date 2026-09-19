import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

test('stored locale activates navigation without an unrelated rerender', async ({ page }) => {
	await page.addInitScript(() => localStorage.setItem('quirebase:locale', 'zh-CN'));
	await mockSession(page);
	await page.route('**/api/v1/dashboard', (route) =>
		route.fulfill({
			json: { new_items: [], recent_items: [], projects: [], session_count: 1 }
		})
	);
	await page.route('**/api/v1/items*', (route) =>
		route.fulfill({ json: { items: [], total: 0, page: 1, per_page: 25 } })
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
