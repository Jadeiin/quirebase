import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

test.beforeEach(async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				id: 'item-1',
				version: 1,
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Workspace requests'
				},
				citation_key: null,
				authorization: { allowed: [] },
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				latest_revision_id: null
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/organize', (route) =>
		route.fulfill({
			json: {
				authorization: { allowed: [] },
				projects: [],
				tag_matrix: {
					groups: [],
					assigned_ids: [],
					recommended_ids: [],
					suggested_names: [],
					recommendation_state: 'ready',
					recommendation_error: null
				}
			}
		})
	);
});

for (const section of [
	{ name: 'Overview', path: '', heading: 'Abstract' },
	{ name: 'Organize', path: '/organize', heading: 'Tag matrix' }
]) {
	test(`Item ${section.name} loads the workspace directory once on entry and refresh`, async ({
		page
	}) => {
		const workspaceRequests: string[] = [];
		page.on('request', (request) => {
			const url = new URL(request.url());
			if (url.pathname === '/api/v1/workspaces') workspaceRequests.push(url.pathname + url.search);
		});
		await page.goto(`/workspace/workspace-1/item/item-1${section.path}`);
		await expect(page.getByRole('heading', { name: section.heading, exact: true })).toBeVisible();
		await page.waitForLoadState('networkidle');
		expect.soft(workspaceRequests).toEqual(['/api/v1/workspaces?limit=25&offset=0']);

		workspaceRequests.length = 0;
		await page.reload();
		await expect(page.getByRole('heading', { name: section.heading, exact: true })).toBeVisible();
		await page.waitForLoadState('networkidle');
		expect(workspaceRequests).toEqual(['/api/v1/workspaces?limit=25&offset=0']);
	});
}
