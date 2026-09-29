import type { Page } from '@playwright/test';

export const defaultCitationKeyFormula = 'auth.capitalize + year + shorttitle(1).capitalize';
export const WORKSPACE_ID = 'workspace-1';

function workspaceView(id: string, name: string) {
	return {
		id,
		name,
		owner_id: 'user-1',
		state: 'active',
		current_role: 'owner',
		governance_suspended: false,
		authorization: {
			allowed: [
				'workspace.read',
				'workspace.export',
				'workspace.update',
				'workspace.archive',
				'workspace.delete',
				'item.create',
				'item.update',
				'item.delete',
				'file.manage',
				'file.delete',
				'tag.use',
				'tag.create',
				'tag.manage',
				'citation_style.manage',
				'project.create',
				'project.update',
				'project.archive',
				'project.delete',
				'project_item.manage',
				'workspace_invitation.read',
				'workspace_invitation.create',
				'workspace_invitation.revoke',
				'workspace_member.read',
				'item_discussion.create',
				'project_discussion.create',
				'private_annotation.create',
				'project_annotation.create',
				'project_annotation.review'
			],
			relations: { 'project.create': ['managed', 'open', 'workspace'] }
		}
	};
}

export async function mockWorkspaces(page: Page, creationAllowed = false) {
	const workspaces = [
		workspaceView(WORKSPACE_ID, 'Research'),
		workspaceView('workspace-2', 'Archive')
	];
	await page.route('**/api/v1/workspaces', (route) => {
		if (route.request().method() === 'POST')
			return route.fulfill({ status: 201, json: workspaceView('workspace-new', 'New Workspace') });
		return route.fulfill({ json: workspaces });
	});
	await page.route('**/api/v1/workspaces/*', (route) => {
		const workspaceId = new URL(route.request().url()).pathname.split('/').at(-1);
		const workspace = workspaces.find((candidate) => candidate.id === workspaceId);
		if (!workspace)
			return route.fulfill({
				status: 404,
				json: { code: 'not_found', message: 'not found' }
			});
		return route.fulfill({ json: workspace });
	});
	await page.route('**/api/v1/workspaces/creation-availability', (route) =>
		route.fulfill({
			json: { allowed: creationAllowed, owner_username_required: creationAllowed }
		})
	);
}

export async function mockSession(page: Page, role: 'member' | 'administrator' = 'member') {
	// Download E2E tests assert the request payload. Disable the native picker,
	// which is unavailable in headless CI and would otherwise block the fetch
	// while waiting for a user to choose a path.
	await page.addInitScript(() => {
		Object.defineProperty(window, 'showSaveFilePicker', { value: undefined });
		localStorage.setItem('quirebase:default-workspace', 'workspace-1');
	});
	await mockWorkspaces(page, role === 'administrator');
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: {
				authenticated: true,
				user: {
					id: 'user-1',
					username: 'reader',
					role,
					authorization: {
						allowed: role === 'administrator' ? ['audit.read'] : []
					}
				}
			}
		})
	);
}

export function minimalPdf(): Buffer {
	const objects = [
		'1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n',
		'2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n',
		'3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 400]>>\nendobj\n'
	];
	let body = '%PDF-1.4\n';
	const offsets = objects.map((object) => {
		const offset = Buffer.byteLength(body);
		body += object;
		return offset;
	});
	const xref = Buffer.byteLength(body);
	body += `xref\n0 4\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n `).join('\n')}\n`;
	body += `trailer\n<</Size 4/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
	return Buffer.from(body);
}
