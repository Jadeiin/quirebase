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
		allowed_invitation_roles: ['viewer', 'reviewer', 'editor', 'admin'],
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
				'project.update',
				'project.archive',
				'project.delete',
				'project_item.manage',
				'workspace_invitation.read',
				'workspace_invitation.revoke',
				'workspace_member.read',
				'item_discussion.create',
				'project_discussion.create',
				'private_annotation.create',
				'project_annotation.create',
				'project_annotation.review'
			],
			variants: {
				'project.create': ['managed', 'open', 'workspace']
			}
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
	// EmbedPDF waits for its default stamp pack during initialization. Keep the
	// mocked browser suite independent of CDN latency with a valid local pack.
	await page.route('https://cdn.jsdelivr.net/npm/@embedpdf/default-stamps/**', (route) => {
		if (new URL(route.request().url()).pathname.endsWith('/manifest.json')) {
			return route.fulfill({
				json: {
					id: 'standard',
					name: 'Standard Stamps',
					categories: ['sidebar'],
					pdf: 'stamps.pdf',
					stamps: [{ id: 'approved', pageIndex: 0, name: 'Approved', subject: 'Approved' }]
				}
			});
		}
		return route.fulfill({ contentType: 'application/pdf', body: minimalPdf() });
	});
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

export function minimalPdf(nativeComments = false): Buffer {
	const objects = [
		'1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n',
		'2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n',
		`3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 400]${nativeComments ? '/Annots[4 0 R 5 0 R]' : ''}>>\nendobj\n`
	];
	if (nativeComments) {
		objects.push(
			'4 0 obj\n<</Type/Annot/Subtype/Text/P 3 0 R/Rect[20 300 44 324]/T(PDF author)/Contents(Native PDF comment)/NM(native-comment)/Name/Comment/F 4>>\nendobj\n',
			'5 0 obj\n<</Type/Annot/Subtype/Text/P 3 0 R/Rect[20 300 44 324]/T(PDF author)/Contents(Native PDF reply)/NM(native-reply)/IRT 4 0 R/RT/R/F 4>>\nendobj\n'
		);
	}
	let body = '%PDF-1.4\n';
	const offsets = objects.map((object) => {
		const offset = Buffer.byteLength(body);
		body += object;
		return offset;
	});
	const xref = Buffer.byteLength(body);
	body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n `).join('\n')}\n`;
	body += `trailer\n<</Size ${objects.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
	return Buffer.from(body);
}

export function annotationList(
	annotations: unknown[],
	page = 1,
	perPage = 100,
	total = annotations.length,
	nextCursor: string | null = null
) {
	return {
		revisions: [],
		projects: [],
		annotations,
		page,
		per_page: perPage,
		total,
		next_cursor: nextCursor
	};
}

export async function setAnnotationSource(page: Page, name: string, checked = true) {
	const sources = page.locator('details').filter({ hasText: 'Displayed annotation sources' });
	await sources.locator('summary').click();
	await sources.getByLabel(name, { exact: true }).setChecked(checked);
	await sources.locator('summary').click();
}
