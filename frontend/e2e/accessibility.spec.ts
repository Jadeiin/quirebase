import AxeBuilder from '@axe-core/playwright';
import { expect, type Page, test } from '@playwright/test';

async function mockSession(page: Page, role: 'member' | 'administrator' = 'member') {
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: {
				authenticated: true,
				user: { id: 'user-1', username: 'reader', role }
			}
		})
	);
}

async function useDarkTheme(page: Page) {
	await page.addInitScript(() => localStorage.setItem('quirebase:theme', 'dark'));
}

async function expectNoHighImpactViolations(page: Page) {
	const results = await new AxeBuilder({ page })
		.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
		.analyze();
	const violations = results.violations
		.filter(({ impact }) => impact === 'serious' || impact === 'critical')
		.map(({ id, impact, help, nodes }) => ({
			id,
			impact,
			help,
			targets: nodes.map(({ target }) => target)
		}));
	expect(violations).toEqual([]);
}

test('login has no high-impact accessibility violations', async ({ page }) => {
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({ json: { authenticated: false, user: null } })
	);

	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Quirebase' })).toBeVisible();
	await expectNoHighImpactViolations(page);
});

test('dashboard shell has no high-impact accessibility violations', async ({ page }) => {
	await useDarkTheme(page);
	await mockSession(page);
	await page.route('**/api/v1/dashboard', (route) =>
		route.fulfill({
			json: { new_items: [], recent_items: [], projects: [], session_count: 1 }
		})
	);

	await page.goto('/');
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	await expectNoHighImpactViolations(page);
});

test('Item workspace has no high-impact accessibility violations', async ({ page }) => {
	await useDarkTheme(page);
	await mockSession(page);
	await page.route('**/api/v1/items/item-1/workspace', (route) =>
		route.fulfill({
			json: {
				item: {
					id: 'item-1',
					title_html: '<i>Accessible</i> Item',
					authors: 'A. Author',
					publication_date: '2026',
					publication_title: 'Journal',
					doi: null,
					version: 1
				},
				latest_revision: null,
				permissions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/items/item-1', (route) =>
		route.fulfill({
			json: {
				id: 'item-1',
				title_html: '<i>Accessible</i> Item',
				authors: 'A. Author',
				publication_date: '2026',
				publication_title: 'Journal',
				doi: null,
				version: 1,
				metadata: {
					title: '<i>Accessible</i> Item',
					keywords: [],
					urls: [],
					authors: [],
					editors: [],
					identifiers: [],
					custom_fields: []
				},
				abstract_html: null
			}
		})
	);

	await page.goto('/item/item-1');
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect(page.getByRole('heading', { name: 'Accessible Item' })).toBeVisible();
	await expectNoHighImpactViolations(page);
});

test('administration overview has no high-impact accessibility violations', async ({ page }) => {
	await useDarkTheme(page);
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/overview', (route) =>
		route.fulfill({
			json: {
				user_count: 1,
				pending_invitation_count: 0,
				storage: { items_count: 0, total_disk_bytes: 0 },
				failed_workflows: [],
				recent_events: []
			}
		})
	);

	await page.goto('/admin');
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect(page.getByRole('heading', { name: 'Administration' })).toBeVisible();
	await expectNoHighImpactViolations(page);
});
