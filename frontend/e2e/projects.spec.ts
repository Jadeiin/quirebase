import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

test('Project creation preserves description and visibility', async ({ page }) => {
	await mockSession(page);
	let creation: Record<string, unknown> | null = null;
	await page.route('**/api/v1/projects/joinable', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/projects', (route) => {
		if (route.request().method() === 'POST') {
			creation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'project-1' } });
		}
		return route.fulfill({ json: [] });
	});

	await page.goto('/projects');
	await page.getByRole('button', { name: 'New Project' }).click();
	await page.getByLabel('Name').fill('Open research');
	await page.getByLabel('Description').fill('Shared reading list');
	await page.getByLabel('Visibility').selectOption('public');
	await page.getByRole('button', { name: 'Create Project' }).click();
	await expect
		.poll(() => creation)
		.toEqual({
			name: 'Open research',
			description: 'Shared reading list',
			visibility: 'public'
		});
});

test('Project owners can manage settings and members', async ({ page }) => {
	await mockSession(page);
	const mutations: Array<{ method: string; path: string; body: unknown }> = [];
	await page.route('**/api/v1/projects/project-1**', (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (request.method() === 'GET' && path === '/api/v1/projects/project-1') {
			return route.fulfill({
				json: {
					id: 'project-1',
					name: 'Research',
					description: 'Initial',
					role: 'owner',
					item_count: 0,
					state: 'active',
					visibility: 'private',
					items: [],
					members: [{ user_id: 'user-1', username: 'reader', role: 'owner' }]
				}
			});
		}
		mutations.push({ method: request.method(), path, body: request.postDataJSON() });
		return route.fulfill({ json: { ok: true, id: 'project-1' } });
	});

	await page.goto('/projects/project-1');
	await page.getByLabel('Name', { exact: true }).fill('Renamed research');
	await page.getByLabel('Description').fill('Updated');
	await page.getByLabel('Visibility').selectOption('public');
	await page.getByRole('button', { name: 'Save Project settings' }).click();
	await expect.poll(() => mutations.length).toBe(1);
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PATCH',
			path: '/api/v1/projects/project-1',
			body: { name: 'Renamed research', description: 'Updated', visibility: 'public' }
		});
	await page.getByPlaceholder('Username').fill('collaborator');
	await page.getByRole('button', { name: 'Save member' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/projects/project-1/members',
			body: { username: 'collaborator', role: 'viewer' }
		});
	await page.getByRole('button', { name: 'Delete Project' }).click();
	await page.getByLabel('Project name').fill('Research');
	await page.getByRole('dialog').getByRole('button', { name: 'Delete Project' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'DELETE',
			path: '/api/v1/projects/project-1',
			body: { confirmation: 'Research' }
		});
});
