import AxeBuilder from '@axe-core/playwright';
import { expect, type Page, test } from '@playwright/test';
import { tagPage, mockWorkspaces, directoryPage } from './helpers';

async function mockSession(page: Page, role: 'member' | 'administrator' = 'member') {
	await mockWorkspaces(page);
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
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({
			json: { new_items: [], recent_items: [], projects: [], session_count: 1 }
		})
	);

	await page.goto('/');
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	await expectNoHighImpactViolations(page);
});

test('Item detail has no high-impact accessibility violations', async ({ page }) => {
	await useDarkTheme(page);
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: '<i>Accessible</i> Item',
					date_published: '2026',
					container: { title: 'Journal' }
				},
				citation_key: null,
				id: 'item-1',
				version: 1,
				latest_revision_id: null,
				authorization: {
					allowed: [
						'item.update',
						'item.delete',
						'workspace.export',
						'file.manage',
						'tag.use',
						'tag.create',
						'project_item.manage'
					]
				},
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1', (route) =>
		route.fulfill({
			json: {
				id: 'item-1',
				version: 1,
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: '<i>Accessible</i> Item'
				}
			}
		})
	);

	await page.goto('/workspace/workspace-1/item/item-1');
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect(page.getByRole('heading', { name: 'Accessible Item' })).toBeVisible();
	await expectNoHighImpactViolations(page);
});

test('administration overview has no high-impact accessibility violations', async ({ page }) => {
	await useDarkTheme(page);
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/overview?*', (route) =>
		route.fulfill({
			json: {
				user_count: 1,
				pending_invitation_count: 0,
				storage: { items_count: 0, total_disk_bytes: 0 },
				failed_workflow_count: 0,
				recent_events: directoryPage([], route)
			}
		})
	);

	await page.goto('/admin');
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	await expect(page.getByRole('heading', { name: 'Administration' })).toBeVisible();
	await expectNoHighImpactViolations(page);
});

for (const theme of ['light', 'dark']) {
	test(`year calendar and searchable Library filters have no high-impact accessibility violations in ${theme} mode`, async ({
		page
	}) => {
		await page.addInitScript(
			(preference) => localStorage.setItem('quirebase:theme', preference),
			theme
		);
		await mockSession(page);
		await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
			route.fulfill({
				json: tagPage(
					Array.from({ length: 30 }, (_, index) => ({
						id: `tag-${index + 1}`,
						name: index === 0 ? 'Methods' : `Tag ${index + 1}`
					})),
					route
				)
			})
		);
		await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
			route.fulfill({ json: { entries: [], total: 0, limit: 25, offset: 0 } })
		);
		await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
			route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
		);
		await page.goto('/workspace/workspace-1/library');
		await page.getByRole('button', { name: 'Filters', exact: true }).click();
		await page.getByRole('textbox', { name: 'Year', exact: true }).fill('2024');
		await page.getByRole('button', { name: 'Choose date for Year', exact: true }).click();
		const calendar = page.getByRole('application', { name: 'Calendar for Year', exact: true });
		await expect(calendar).toBeVisible();
		await expectNoHighImpactViolations(page);
		await calendar.getByRole('button', { name: '2023', exact: true }).press('Escape');
		await page.getByRole('button', { name: 'Show options for Tag', exact: true }).click();
		await expect(page.getByRole('button', { name: 'Load more Tags', exact: true })).toBeVisible();
		await expectNoHighImpactViolations(page);
		await page.getByRole('combobox', { name: 'Tag', exact: true }).fill('Meth');
		await expect(page.getByRole('option', { name: 'Methods', exact: true })).toBeVisible();
		await expectNoHighImpactViolations(page);
	});
}
