import { expect, test } from '@playwright/test';
import { directoryPage, mockSession } from './helpers';

const permissions = {
	allowed: ['item.update', 'item.delete', 'project_item.manage', 'item_discussion.create']
};
const overview = (id = 'item-1') => ({
	id,
	version: 1,
	metadata: {
		id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
		type: 'Dataset',
		title: 'Audit Item'
	},
	citation_key: 'Audit2026',
	authorization: permissions,
	copy_targets: [],
	tags: [],
	latest_revision_id: null,
	counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
});
const project = () => ({
	id: 'project-1',
	name: 'Audit Project',
	description: 'Existing description',
	item_count: 0,
	state: 'active',
	participation: 'workspace',
	is_participating: true,
	allowed_participation_changes: ['workspace', 'open', 'managed'],
	authorization: {
		allowed: [
			'project.update',
			'project.delete',
			'project_discussion.create',
			'project_item.manage'
		]
	},
	active_participants: []
});
const message = (body: string) => ({
	id: 'message-1',
	body,
	author_username: 'reader',
	mine: true,
	created_at: '2026-10-01T00:00:00Z',
	authorization: { allowed: [] }
});
for (const scope of ['Item', 'Project']) {
	test(`${scope} discussion posting preserves a newer unsent message`, async ({ page }) => {
		await mockSession(page);
		const messages: ReturnType<typeof message>[] = [];
		const started = Promise.withResolvers<void>();
		const release = Promise.withResolvers<void>();
		const path = scope === 'Item' ? 'items/item-1' : 'projects/project-1';
		await page.route(`**/api/v1/workspaces/workspace-1/${path}/discussions`, async (route) => {
			if (route.request().method() === 'POST') {
				started.resolve();
				await release.promise;
				messages.push({
					...message(route.request().postDataJSON().body),
					id: `message-${messages.length + 1}`
				});
				return route.fulfill({ status: 201, json: messages.at(-1) });
			}
			return route.fulfill({ json: messages });
		});
		if (scope === 'Item')
			await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
				route.fulfill({ json: overview() })
			);
		else {
			await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
				route.fulfill({ json: project() })
			);
			await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
				route.fulfill({ json: directoryPage([], route) })
			);
		}
		await page.goto(
			`/workspace/workspace-1/${scope === 'Item' ? 'item/item-1/discussion' : 'projects/project-1'}`
		);
		const input =
			scope === 'Item' ? page.getByLabel('Add message') : page.getByPlaceholder('Write a message');
		await input.fill('  Submitted discussion message  ');
		await page
			.getByRole('button', { name: scope === 'Item' ? 'Post message' : 'Post', exact: true })
			.click();
		await started.promise;
		try {
			await input.fill('Newer unsent discussion draft');
			release.resolve();
			await expect(page.getByText('Submitted discussion message', { exact: true })).toBeVisible();
			await expect(input).toHaveValue('Newer unsent discussion draft');
			await page
				.getByRole('button', { name: scope === 'Item' ? 'Post message' : 'Post', exact: true })
				.click();
			await expect(page.getByText('Newer unsent discussion draft', { exact: true })).toBeVisible();
			await expect(input).toHaveValue('');
		} finally {
			release.resolve();
		}
	});
}
