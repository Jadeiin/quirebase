import { expect, type Page, test } from '@playwright/test';

const defaultCitationKeyFormula = 'auth.capitalize + year + shorttitle(1).capitalize';

async function mockSession(
	page: Page,
	role: 'member' | 'administrator' = 'member',
	locale = 'en-US'
) {
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: {
				authenticated: true,
				locale,
				user: { id: 'user-1', username: 'reader', role }
			}
		})
	);
}

function minimalPdf(): Buffer {
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

test('pending PDF imports refresh until they can be committed', async ({ page }) => {
	await mockSession(page);
	let previewRequests = 0;
	await page.route('**/api/v1/imports/pdfs', (route) =>
		route.fulfill({
			status: 202,
			json: { id: 'batch-1', status: 'pending', workflow_id: 'workflow-1', records: [], errors: [] }
		})
	);
	await page.route('**/api/v1/imports/batch-1', (route) => {
		previewRequests += 1;
		return route.fulfill({
			json: {
				id: 'batch-1',
				status: previewRequests > 1 ? 'ready' : 'pending',
				workflow_id: 'workflow-1',
				records: previewRequests > 1 ? [{ title: 'Imported PDF' }] : [],
				errors: []
			}
		});
	});

	await page.goto('/import');
	await page.locator('input[name="pdfs"]').setInputFiles({
		name: 'paper.pdf',
		mimeType: 'application/pdf',
		buffer: Buffer.from('%PDF-1.4\n')
	});
	await page.getByRole('button', { name: 'Stage PDFs' }).click();

	await expect.poll(() => previewRequests, { timeout: 5_000 }).toBeGreaterThan(1);
	await expect(page.getByRole('button', { name: 'Commit' })).toBeEnabled();
	await expect(page.getByText('Imported PDF')).toBeVisible();
});

test('PDF import accumulates and deduplicates repeated file selections', async ({ page }) => {
	await mockSession(page);
	let uploadBody = '';
	await page.route('**/api/v1/imports/pdfs', (route) => {
		uploadBody = route.request().postData() ?? '';
		return route.fulfill({
			status: 202,
			json: { id: 'batch-files', status: 'ready', workflow_id: null, records: [], errors: [] }
		});
	});
	await page.goto('/import');
	const input = page.locator('input[name="pdfs"]');
	await input.setInputFiles({
		name: 'first.pdf',
		mimeType: 'application/pdf',
		buffer: Buffer.from('%PDF-1.4 first')
	});
	await input.setInputFiles({
		name: 'second.pdf',
		mimeType: 'application/pdf',
		buffer: Buffer.from('%PDF-1.4 second')
	});
	await expect(page.getByText('first.pdf', { exact: true })).toBeVisible();
	await expect(page.getByText('second.pdf', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Stage PDFs' }).click();
	await expect.poll(() => uploadBody).toContain('first.pdf');
	await expect.poll(() => uploadBody).toContain('second.pdf');
});

test('item workspace URL selects and loads the metadata section', async ({ page }) => {
	await mockSession(page);
	let metadataRequests = 0;
	await page.route('**/api/v1/items/item-1/workspace', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: '<i>Visible</i> Item', version: 1 },
				latest_revision: null,
				permissions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/items/item-1', (route) => {
		metadataRequests += 1;
		return route.fulfill({
			json: {
				id: 'item-1',
				title_html: '<i>Visible</i> Item',
				authors: 'A. Author',
				publication_date: '2026',
				publication_title: 'Journal',
				doi: null,
				version: 1,
				metadata: {
					title: '<i>Visible</i> Item',
					keywords: [],
					urls: [],
					authors: [],
					editors: [],
					identifiers: [],
					custom_fields: []
				},
				abstract_html: null,
				editors: [],
				structured_authors: [],
				reference_type: null,
				volume: null,
				issue: null,
				pages: null,
				keywords: null,
				urls: null
			}
		});
	});

	await page.goto('/item/item-1/metadata');

	await expect.poll(() => metadataRequests).toBe(1);
	await expect(page.getByRole('link', { name: 'Metadata' })).toHaveAttribute(
		'aria-current',
		'page'
	);
	await expect(page.getByRole('heading', { name: 'Metadata' })).toBeVisible();
});

test('read-only Item metadata does not expose mutation controls', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/items/item-readonly/workspace', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-readonly', title_html: 'Read-only Item', version: 1 },
				latest_revision: null,
				permissions: { edit: false, delete: false },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-2', username: 'owner' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/items/item-readonly', (route) =>
		route.fulfill({
			json: {
				id: 'item-readonly',
				title_html: 'Read-only Item',
				version: 1,
				metadata: {
					title: 'Read-only Item',
					abstract: 'Shared abstract',
					keywords: ['shared'],
					urls: [],
					authors: [{ first_name: 'Ada', last_name: 'Reader', is_corresponding: false }],
					editors: [],
					identifiers: [],
					custom_fields: []
				},
				abstract_html: 'Shared abstract'
			}
		})
	);

	await page.goto('/item/item-readonly/metadata');

	await expect(page.getByText('Ada Reader')).toBeVisible();
	await expect(page.getByText('Shared abstract')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Save metadata' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Record tools' })).toHaveCount(0);
});

test('Item annotation review spans every PDF revision', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/items/item-annotations/workspace', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-annotations', title_html: 'Annotated Item', version: 1 },
				latest_revision: {
					id: 'revision-new',
					original_name: 'new.pdf',
					size: 200,
					page_count: 2,
					processing_state: 'ready'
				},
				permissions: { edit: false, delete: false },
				counts: { revisions: 2, attachments: 0, annotations: 2, discussion: 0 },
				tags: [],
				owner: { id: 'user-2', username: 'owner' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/items/item-annotations/documents', (route) =>
		route.fulfill({
			json: {
				item_id: 'item-annotations',
				files: [
					{
						id: 'revision-new',
						kind: 'revision',
						original_name: 'new.pdf',
						mime_type: 'application/pdf',
						size: 200,
						created_at: '2026-02-01T00:00:00Z',
						processing_state: 'ready'
					},
					{
						id: 'revision-old',
						kind: 'revision',
						original_name: 'old.pdf',
						mime_type: 'application/pdf',
						size: 100,
						created_at: '2026-01-01T00:00:00Z',
						processing_state: 'ready'
					}
				]
			}
		})
	);
	await page.route('**/api/v1/items/item-annotations/annotations?*', (route) => {
		const revisionId = new URL(route.request().url()).searchParams.get('revision_id')!;
		return route.fulfill({
			json: [
				{
					id: `annotation-${revisionId}`,
					revision_id: revisionId,
					page_index: 0,
					kind: 'note',
					body: revisionId === 'revision-new' ? 'New revision note' : 'Old revision note',
					selected_text: null,
					author_display_name: 'reader',
					replies: []
				}
			]
		});
	});

	await page.goto('/item/item-annotations/annotations');

	await expect(page.getByText('New revision note')).toBeVisible();
	await expect(page.getByText('Old revision note')).toBeVisible();
	await page.getByLabel('PDF revision').selectOption('revision-old');
	await expect(page.getByText('New revision note')).toHaveCount(0);
	await expect(page.getByText('Old revision note')).toBeVisible();
});

test('Item file uploads wait for durable processing before refreshing', async ({ page }) => {
	await mockSession(page);
	let documentReads = 0;
	let workflowReads = 0;
	await page.route('**/api/v1/items/item-1/workspace', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Files Item' },
				latest_revision: null,
				permissions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/items/item-1/documents', (route) => {
		documentReads += 1;
		return route.fulfill({
			json: {
				item_id: 'item-1',
				files:
					documentReads > 1
						? [
								{
									id: 'revision-1',
									kind: 'revision',
									original_name: 'paper.pdf',
									mime_type: 'application/pdf',
									size: 100,
									created_at: '2026-01-01T00:00:00Z',
									processing_state: 'ready'
								}
							]
						: []
			}
		});
	});
	await page.route('**/api/v1/items/item-1', (route) =>
		route.fulfill({
			json: {
				id: 'item-1',
				title_html: 'Files Item',
				version: 1,
				metadata: {
					title: 'Files Item',
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
	await page.route('**/api/v1/items/item-1/revisions', (route) =>
		route.fulfill({ status: 202, json: { id: 'workflow-1' } })
	);
	await page.route('**/api/v1/workflows/workflow-1', (route) => {
		workflowReads += 1;
		return route.fulfill({
			json: { id: 'workflow-1', state: workflowReads > 1 ? 'succeeded' : 'running', error: null }
		});
	});

	await page.goto('/item/item-1/files');
	await page.locator('input[name="pdf"]').setInputFiles({
		name: 'paper.pdf',
		mimeType: 'application/pdf',
		buffer: minimalPdf()
	});
	await page.getByRole('button', { name: 'Upload PDF' }).click();
	await expect.poll(() => workflowReads).toBeGreaterThan(1);
	await expect(page.getByText('paper.pdf')).toBeVisible();
});

test('Item Files acquires URL imports through the same-origin API', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/items/item-remote/workspace', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-remote', title_html: 'Remote PDF Item', version: 1 },
				latest_revision: null,
				permissions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/items/item-remote/documents', (route) =>
		route.fulfill({ json: { item_id: 'item-remote', files: [] } })
	);
	await page.route('**/api/v1/items/item-remote', (route) =>
		route.fulfill({
			json: {
				id: 'item-remote',
				title_html: 'Remote PDF Item',
				version: 1,
				metadata: {
					title: 'Remote PDF Item',
					keywords: [],
					urls: ['https://papers.example/article.pdf'],
					authors: [],
					editors: [],
					identifiers: [],
					custom_fields: []
				},
				abstract_html: null
			}
		})
	);
	let browserRemoteRequests = 0;
	await page.route('https://papers.example/**', (route) => {
		browserRemoteRequests += 1;
		return route.fulfill({ body: minimalPdf(), contentType: 'application/pdf' });
	});
	let revisionImport: Record<string, unknown> | null = null;
	let attachmentImport: Record<string, unknown> | null = null;
	await page.route('**/api/v1/items/item-remote/revisions/remote', (route) => {
		revisionImport = route.request().postDataJSON();
		return route.fulfill({ status: 202, json: { id: 'workflow-remote' } });
	});
	await page.route('**/api/v1/items/item-remote/attachments/remote', (route) => {
		attachmentImport = route.request().postDataJSON();
		return route.fulfill({ status: 202, json: { id: 'workflow-attachment' } });
	});
	await page.route('**/api/v1/workflows/workflow-remote', (route) =>
		route.fulfill({ json: { id: 'workflow-remote', state: 'succeeded', error: null } })
	);
	await page.route('**/api/v1/workflows/workflow-attachment', (route) =>
		route.fulfill({ json: { id: 'workflow-attachment', state: 'succeeded', error: null } })
	);

	await page.goto('/item/item-remote/files');
	await expect(page.locator('input[name="url"]').first()).toHaveValue(
		'https://papers.example/article.pdf'
	);
	await page.getByRole('button', { name: 'Download and add PDF' }).click();
	await expect
		.poll(() => revisionImport)
		.toEqual({
			source: 'https://papers.example/article.pdf'
		});

	await page.locator('input[name="url"]').nth(1).fill('https://papers.example/supplement.zip');
	await page.getByRole('button', { name: 'Download and add attachment' }).click();
	await expect
		.poll(() => attachmentImport)
		.toEqual({
			source: 'https://papers.example/supplement.zip',
			graphical_abstract: false
		});

	expect(browserRemoteRequests).toBe(0);
});

test('administration URL selects and loads the users section', async ({ page }) => {
	await mockSession(page, 'administrator');
	let usersRequests = 0;
	await page.route('**/api/v1/admin/users*', (route) => {
		usersRequests += 1;
		return route.fulfill({
			json: {
				users: [
					{
						id: 'user-2',
						username: 'curator',
						role: 'member',
						active: true,
						created_at: '2026-01-01T00:00:00Z'
					}
				],
				total: 1,
				page: 1,
				per_page: 20,
				invitations: []
			}
		});
	});

	await page.goto('/admin/users');

	await expect.poll(() => usersRequests).toBe(1);
	await expect(page.getByRole('link', { name: 'Users' })).toHaveAttribute('aria-current', 'page');
	await expect(page.getByText('curator', { exact: true })).toBeVisible();
});

test('administrators receive the one-time invitation URL after creation', async ({ page }) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/users*', (route) =>
		route.fulfill({
			json: { users: [], total: 0, page: 1, per_page: 20, invitations: [] }
		})
	);
	await page.route('**/api/v1/admin/invitations', (route) =>
		route.fulfill({
			status: 201,
			json: {
				id: 'invitation-1',
				username: 'invitee',
				role: 'member',
				expires_at: '2026-10-01T00:00:00Z',
				token: 'one-time-secret',
				accept_path: '/invitation/one-time-secret'
			}
		})
	);

	await page.goto('/admin/users');
	await page
		.locator('form')
		.filter({ hasText: 'Invite user' })
		.locator('input[name="username"]')
		.fill('invitee');
	await page.getByRole('button', { name: 'Create invitation' }).click();

	await expect(page.getByRole('link', { name: /invitation\/one-time-secret/ })).toBeVisible();
});

test('account settings expose credential and session security controls', async ({ page }) => {
	await mockSession(page);
	const mutations: Array<{ method: string; path: string; body: unknown }> = [];
	await page.route('**/api/v1/account**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (request.method() === 'GET' && path === '/api/v1/account') {
			return route.fulfill({
				json: {
					user: { id: 'user-1', username: 'reader', role: 'member' },
					sessions: [
						{
							id: 'session-2',
							current: false,
							created_at: '2026-01-01T00:00:00Z',
							expires_at: '2026-10-01T00:00:00Z'
						}
					],
					api_tokens: [
						{
							id: 'token-1',
							name: 'Laptop',
							status: 'active',
							expires_at: '2026-10-01T00:00:00Z'
						}
					]
				}
			});
		}
		mutations.push({ method: request.method(), path, body: request.postDataJSON() });
		return route.fulfill({ json: { ok: true } });
	});

	await page.goto('/account');
	await page.getByLabel('Current password').fill('old-password');
	await page.getByLabel('New password').fill('new-password-long');
	await page.getByRole('button', { name: 'Change password' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/account/password',
			body: { current_password: 'old-password', new_password: 'new-password-long' }
		});

	await page.getByLabel('Locale').selectOption('zh-CN');
	await page.getByRole('button', { name: 'Save locale' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/account/locale',
			body: { locale: 'zh-CN' }
		});

	await page.getByRole('button', { name: '撤销令牌' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'DELETE',
			path: '/api/v1/account/api-tokens/token-1',
			body: null
		});

	await page.getByRole('button', { name: '撤销会话' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'DELETE',
			path: '/api/v1/account/sessions/session-2',
			body: null
		});
});

test('administrators can respond to compromised user accounts', async ({ page }) => {
	await mockSession(page, 'administrator');
	const mutations: Array<{ method: string; path: string; body: unknown }> = [];
	await page.route('**/api/v1/admin/users**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (request.method() === 'GET' && path === '/api/v1/admin/users') {
			return route.fulfill({
				json: {
					users: [
						{
							id: 'user-2',
							username: 'curator',
							role: 'member',
							active: true,
							created_at: '2026-01-01T00:00:00Z'
						}
					],
					total: 1,
					page: 1,
					per_page: 20,
					invitations: []
				}
			});
		}
		mutations.push({ method: request.method(), path, body: request.postDataJSON() });
		return route.fulfill({ json: { ok: true } });
	});

	await page.goto('/admin/users');
	await page.getByLabel('Role for curator').selectOption('administrator');
	await page.getByRole('button', { name: 'Save role' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/admin/users/user-2/role',
			body: { role: 'administrator' }
		});

	await page.getByRole('button', { name: 'Disable user' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/admin/users/user-2/status',
			body: { active: false }
		});

	await page.getByLabel('New password for curator').fill('replacement-password');
	await page.getByRole('button', { name: 'Reset password' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/admin/users/user-2/password',
			body: { password: 'replacement-password' }
		});

	await page.getByRole('button', { name: 'Revoke sessions' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'DELETE',
			path: '/api/v1/admin/users/user-2/sessions',
			body: null
		});
});

test('library renders canonical rich titles and exposes later pages', async ({ page }) => {
	await mockSession(page);
	const requestedPages: number[] = [];
	const requestedQueries: Array<{ query: string | null; q: string | null }> = [];
	await page.route('**/api/v1/items*', (route) => {
		const searchParameters = new URL(route.request().url()).searchParams;
		const requestedPage = Number(searchParameters.get('page') ?? '1');
		requestedPages.push(requestedPage);
		requestedQueries.push({ query: searchParameters.get('query'), q: searchParameters.get('q') });
		return route.fulfill({
			json: {
				items: [
					{
						id: `item-${requestedPage}`,
						title_html: requestedPage === 1 ? '<i>Visible</i> $x^2$ Item' : 'Second page Item',
						authors: null,
						publication_date: null,
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 26,
				page: requestedPage,
				per_page: 25
			}
		});
	});

	await page.goto('/library');
	await expect(page.locator('strong i', { hasText: 'Visible' })).toBeVisible();
	await expect(page.locator('strong math msup')).toBeVisible();
	await expect(page.getByText('$x^2$', { exact: false })).toHaveCount(0);
	await page.getByPlaceholder('Search title, author, Tag, or full text').fill('quantum fields');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page).toHaveURL(/\/library\?q=quantum\+fields$/);
	await expect.poll(() => requestedQueries).toContainEqual({ query: 'quantum fields', q: null });
	await page.getByRole('button', { name: 'Next page' }).click();
	await expect.poll(() => requestedPages).toContain(2);
	await expect.poll(() => requestedQueries.at(-1)).toEqual({ query: 'quantum fields', q: null });
	await expect(page.getByText('Second page Item')).toBeVisible();
});

test('discovery renders the flat results response contract', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/discovery/providers', (route) =>
		route.fulfill({ json: [{ id: 'crossref', name: 'Crossref' }] })
	);
	await page.route('**/api/v1/discovery/search', (route) =>
		route.fulfill({
			json: {
				provider: 'crossref',
				results: [
					{
						provider: 'crossref',
						identifier_provider: 'doi',
						identifier: '10.1000/result',
						title: 'Discovered paper',
						authors: 'A. Researcher',
						publication_date: '2026',
						imported: false
					}
				],
				total: 1,
				page: 1,
				per_page: 20
			}
		})
	);

	await page.goto('/discovery');
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('paper');
	await page.getByRole('button', { name: 'Search Discovery' }).click();

	await expect(page.getByText('Discovered paper')).toBeVisible();
	await expect(page.getByText('doi:10.1000/result')).toBeVisible();
});

test('desktop sidebar collapse persists across navigation reloads', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await mockSession(page);
	await page.route('**/api/v1/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 1 } })
	);

	await page.goto('/');
	await page.getByRole('button', { name: 'Collapse sidebar' }).click();
	await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible();
	await expect(page.getByRole('link', { name: 'Library', exact: true })).toHaveAttribute(
		'title',
		'Library'
	);
	await page.reload();
	await expect(page.getByRole('button', { name: 'Expand sidebar' })).toBeVisible();
});

test('discovery query builder stages a selected Candidate Record for Import', async ({ page }) => {
	await mockSession(page);
	let searchBody: Record<string, unknown> | null = null;
	await page.route('**/api/v1/discovery/providers', (route) =>
		route.fulfill({ json: [{ id: 'openalex', name: 'OpenAlex' }] })
	);
	await page.route('**/api/v1/discovery/search', async (route) => {
		searchBody = route.request().postDataJSON();
		return route.fulfill({
			json: {
				provider: 'openalex',
				results: [
					{
						provider: 'openalex',
						identifier_provider: 'openalex',
						identifier: 'W123',
						title: 'Candidate',
						imported: false
					}
				],
				total: 1,
				page: 1,
				per_page: 20
			}
		});
	});
	await page.route('**/api/v1/imports/identifier', (route) =>
		route.fulfill({ json: { id: 'batch-discovery', status: 'ready', records: [], errors: [] } })
	);
	await page.route('**/api/v1/imports/batch-discovery', (route) =>
		route.fulfill({
			json: {
				id: 'batch-discovery',
				status: 'ready',
				workflow_id: null,
				records: [{ title: 'Candidate' }],
				errors: []
			}
		})
	);

	await page.goto('/discovery');
	await page.getByRole('button', { name: 'Add condition' }).click();
	await page.getByPlaceholder('Title, author, DOI, or topic').fill('systems');
	await page.getByPlaceholder('Another condition').fill('review');
	await page.getByLabel('From year').fill('2020');
	await page.getByRole('button', { name: 'Search Discovery' }).click();
	await expect.poll(() => searchBody).toMatchObject({ year_from: 2020 });
	await expect.poll(() => (searchBody?.clauses as unknown[])?.length).toBe(2);
	await page.getByRole('button', { name: 'Review and import' }).click();
	await expect(page).toHaveURL(/\/import\?batch=batch-discovery$/);
	await expect(page.getByText('Candidate')).toBeVisible();
});

test('Import preview paginates restored batches', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/imports/batch-many', (route) =>
		route.fulfill({
			json: {
				id: 'batch-many',
				status: 'ready',
				workflow_id: null,
				records: Array.from({ length: 21 }, (_, index) => ({ title: `Record ${index + 1}` })),
				errors: []
			}
		})
	);

	await page.goto('/import?batch=batch-many');
	await expect(page.getByText('Record 1', { exact: true })).toBeVisible();
	await expect(page.getByText('Record 21', { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Next' }).click();
	await expect(page.getByText('Record 21', { exact: true })).toBeVisible();
});

test('manual Item creation submits complete structured metadata', async ({ page }) => {
	await mockSession(page);
	let creation: Record<string, unknown> | null = null;
	await page.route(/\/api\/v1\/items$/, (route) => {
		if (route.request().method() === 'POST') {
			creation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'item-created', version: 1 } });
		}
		return route.fulfill({ status: 404, json: { detail: 'not found' } });
	});

	await page.goto('/import');
	await page.getByRole('button', { name: 'Open metadata editor' }).click();
	await page.getByLabel('Title', { exact: true }).fill('Structured record');
	await page.getByLabel('Publication title').fill('Journal of Testing');
	await page.getByLabel('Keywords').fill('systems; reproducibility');
	await page
		.getByRole('heading', { name: 'Authors' })
		.locator('..')
		.getByRole('button', { name: 'Add contributor' })
		.click();
	await page.getByLabel('First name').fill('Ada');
	await page.getByLabel('Last name or organization').fill('Lovelace');
	await page.getByLabel('Corresponding').check();
	await page.getByRole('button', { name: 'Add identifier' }).click();
	await page.getByLabel('Provider').fill('openalex');
	await page.getByLabel('Identifier').fill('W123');
	await page.getByRole('button', { name: 'Add custom field' }).click();
	await page.getByLabel('Field name').fill('reviewed');
	await page.getByLabel('JSON or text value').fill('true');
	await page.getByRole('button', { name: 'Add custom field' }).click();
	await page.getByLabel('Field name').nth(1).fill('address');
	await page.getByLabel('JSON or text value').nth(1).fill('123 Main St');
	await page.getByRole('button', { name: 'Create Item' }).click();

	await expect
		.poll(() => creation)
		.toMatchObject({
			title: 'Structured record',
			publication_title: 'Journal of Testing',
			keywords: ['systems', 'reproducibility'],
			authors: [{ first_name: 'Ada', last_name: 'Lovelace', is_corresponding: true }],
			identifiers: [{ provider: 'openalex', value: 'W123' }],
			custom_fields: [
				{ name: 'reviewed', value: true },
				{ name: 'address', value: '123 Main St' }
			]
		});
});

test('Item metadata editor preserves structured contributors and custom fields', async ({
	page
}) => {
	await mockSession(page);
	let update: Record<string, unknown> | null = null;
	await page.route('**/api/v1/items/item-1/workspace', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Editable', version: 4 },
				permissions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: [],
				latest_revision: null
			}
		})
	);
	await page.route('**/api/v1/items/item-1', (route) => {
		if (route.request().method() === 'PUT') {
			update = route.request().postDataJSON();
			return route.fulfill({ json: { id: 'item-1', version: 5 } });
		}
		return route.fulfill({
			json: {
				id: 'item-1',
				title_html: 'Editable',
				version: 4,
				metadata: {
					title: 'Editable',
					keywords: [],
					urls: [],
					authors: [],
					editors: [],
					identifiers: [],
					custom_fields: []
				},
				abstract_html: null
			}
		});
	});

	await page.goto('/item/item-1/metadata');
	await page
		.getByRole('heading', { name: 'Authors' })
		.locator('..')
		.getByRole('button', { name: 'Add contributor' })
		.click();
	await page.getByLabel('First name').fill('Grace');
	await page.getByLabel('Last name or organization').fill('Hopper');
	await page.getByRole('button', { name: 'Add custom field' }).click();
	await page.getByLabel('Field name').fill('score');
	await page.getByLabel('JSON or text value').fill('5');
	await page.getByRole('button', { name: 'Save metadata' }).click();

	await expect
		.poll(() => update)
		.toMatchObject({
			expected_version: 4,
			metadata: {
				authors: [{ first_name: 'Grace', last_name: 'Hopper', is_corresponding: false }],
				custom_fields: [{ name: 'score', value: 5 }]
			}
		});
});

test('Item organization toggles the Tag matrix and waits for recommendations', async ({ page }) => {
	await mockSession(page);
	const mutations: Array<{ method: string; path: string; body: unknown }> = [];
	let workflowReads = 0;
	await page.route('**/api/v1/items/item-1/workspace', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Organize', version: 1 },
				permissions: { edit: true, delete: true },
				counts: { revisions: 1, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: [],
				latest_revision: { id: 'revision-1', original_name: 'paper.pdf' }
			}
		})
	);
	await page.route('**/api/v1/items/item-1/organize', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Organize', version: 1 },
				permissions: { edit: true },
				tags: [],
				projects: [],
				tag_matrix: {
					groups: [{ letter: 'M', tags: [{ id: 'tag-1', name: 'Methods' }], names: ['Methods'] }],
					assigned_ids: [],
					recommended_ids: ['tag-1'],
					suggested_names: ['Replication'],
					suggested_single_words: [],
					suggested_phrases: [],
					recommendation_state: 'ready',
					recommendation_error: null
				}
			}
		})
	);
	await page.route('**/api/v1/items/item-1/tags', (route) => {
		mutations.push({
			method: route.request().method(),
			path: new URL(route.request().url()).pathname,
			body: route.request().postDataJSON()
		});
		return route.fulfill({ json: { ok: true } });
	});
	await page.route('**/api/v1/items/item-1/tag-recommendations', (route) =>
		route.fulfill({ status: 202, json: { id: 'workflow-tags' } })
	);
	await page.route('**/api/v1/workflows/workflow-tags', (route) => {
		workflowReads += 1;
		return route.fulfill({
			json: { id: 'workflow-tags', state: workflowReads > 1 ? 'succeeded' : 'running', error: null }
		});
	});

	await page.goto('/item/item-1/organize');
	await page.getByRole('button', { name: 'Methods ★' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/items/item-1/tags',
			body: { add_tag_ids: ['tag-1'], remove_tag_ids: [], new_names: [] }
		});
	await page.getByRole('button', { name: 'Refresh' }).click();
	await expect.poll(() => workflowReads).toBeGreaterThan(1);
});

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
	await page.getByLabel('Name').fill('Renamed research');
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
	page.once('dialog', async (dialog) => {
		expect(dialog.type()).toBe('prompt');
		expect(dialog.message()).toContain('Research');
		await dialog.accept('Research');
	});
	await page.getByRole('button', { name: 'Delete Project' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'DELETE',
			path: '/api/v1/projects/project-1',
			body: { confirmation: 'Research' }
		});
});

test('Tools exposes Tag maintenance and Citation Style installation', async ({ page }) => {
	await mockSession(page);
	let styleCreation: Record<string, unknown> | null = null;
	await page.route('**/api/v1/duplicates*', (route) => route.fulfill({ json: { groups: [] } }));
	await page.route('**/api/v1/tags', (route) =>
		route.fulfill({ json: [{ id: 'tag-1', name: 'Methods', accessible_item_count: 3 }] })
	);
	await page.route('**/api/v1/citation-styles*', (route) => {
		if (route.request().method() === 'POST') {
			styleCreation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'style-1' } });
		}
		return route.fulfill({ json: { styles: [] } });
	});

	await page.goto('/tools');
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await expect(page.locator('strong').filter({ hasText: 'Methods' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Rename' })).toBeVisible();
	await page.getByRole('tab', { name: 'Citation Styles' }).click();
	await page.getByLabel('Style name').fill('House style');
	await page.getByLabel('CSL XML').fill('<style version="1.0"></style>');
	await page.getByRole('button', { name: 'Install Citation Style' }).click();
	await expect
		.poll(() => styleCreation)
		.toEqual({
			name: 'House style',
			csl: '<style version="1.0"></style>'
		});
});

test('saved export preferences flow into Library bibliography requests', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/account', (route) =>
		route.fulfill({
			json: {
				user: { id: 'user-1', username: 'reader', role: 'member' },
				sessions: [],
				api_tokens: []
			}
		})
	);
	await page.route('**/api/v1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [{ key: 'apa', name: 'APA' }] } })
	);
	await page.route('**/api/v1/citation-key-preview*', (route) =>
		route.fulfill({ json: { key: 'Reader2026' } })
	);

	await page.goto('/account');
	await page.getByLabel('Default citation format').selectOption('bibtex');
	await page.getByLabel('Include additional identifiers').check();
	await expect
		.poll(() =>
			page.evaluate(
				() =>
					JSON.parse(localStorage.getItem('quirebase:export-preferences:v1:account:user-1')!)
						.citation
			)
		)
		.toMatchObject({ format: 'bibtex', includeIdentifiers: true });

	let exportBody: Record<string, unknown> | null = null;
	await page.route('**/api/v1/items*', (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'item-1',
						title_html: 'Exportable',
						authors: 'A. Author',
						publication_date: '2026',
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 1,
				page: 1,
				per_page: 25
			}
		})
	);
	await page.route('**/api/v1/tags', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/projects', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/items/bibliography', (route) => {
		exportBody = route.request().postDataJSON();
		return route.fulfill({
			body: '@article{Reader2026}',
			headers: { 'Content-Disposition': 'attachment; filename="items.bib"' }
		});
	});

	await page.goto('/library');
	await page.getByLabel('Select A. Author').check();
	await page.getByLabel('Bulk action').selectOption('bibliography');
	await page.getByRole('button', { name: 'Apply' }).click();
	await expect
		.poll(() => exportBody)
		.toMatchObject({
			file_format: 'bibtex',
			include_identifiers: true
		});
});

test('only validated Citation Key formulas replace the saved preference', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/account', (route) =>
		route.fulfill({
			json: {
				user: { id: 'user-1', username: 'reader', role: 'member' },
				sessions: [],
				api_tokens: []
			}
		})
	);
	await page.route('**/api/v1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [{ key: 'apa', name: 'APA' }] } })
	);
	let previewedFormula = '';
	await page.route('**/api/v1/citation-key-preview*', (route) => {
		previewedFormula = new URL(route.request().url()).searchParams.get('formula') ?? '';
		return previewedFormula === 'broken('
			? route.fulfill({ status: 422, json: { detail: 'invalid Citation Key formula' } })
			: route.fulfill({ json: { key: 'Reader2026' } });
	});

	await page.goto('/account');
	const formula = page.getByLabel('Citation Key formula');
	await expect(formula).toHaveValue(defaultCitationKeyFormula);
	await formula.fill('broken(');
	await expect.poll(() => previewedFormula).toBe('broken(');
	await expect
		.poll(() =>
			page.evaluate(
				() =>
					JSON.parse(localStorage.getItem('quirebase:export-preferences:v1:account:user-1')!)
						.citation.citationKeyFormula
			)
		)
		.toBe(defaultCitationKeyFormula);

	await formula.fill('auth + year');
	await expect.poll(() => previewedFormula).toBe('auth + year');
	await expect
		.poll(() =>
			page.evaluate(
				() =>
					JSON.parse(localStorage.getItem('quirebase:export-preferences:v1:account:user-1')!)
						.citation.citationKeyFormula
			)
		)
		.toBe('auth + year');
});

test('Item actions export citations and synchronize upstream metadata', async ({ page }) => {
	await mockSession(page);
	const workspace = {
		item: {
			id: 'item-1',
			title_html: 'Actionable',
			authors: 'A. Author',
			publication_date: '2026',
			publication_title: 'Journal',
			doi: '10.1000/test',
			version: 3
		},
		permissions: { edit: true, delete: true },
		counts: { revisions: 1, attachments: 0, annotations: 0, discussion: 0 },
		tags: [],
		owner: { id: 'user-1', username: 'reader' },
		identifiers: [{ provider: 'openalex', value: 'W123' }],
		latest_revision: {
			id: 'revision-1',
			original_name: 'paper.pdf',
			size: 100,
			page_count: 1,
			processing_state: 'ready'
		}
	};
	await page.route('**/api/v1/items/item-1/workspace', (route) =>
		route.fulfill({ json: workspace })
	);
	await page.route('**/api/v1/items/item-1', (route) =>
		route.fulfill({
			json: {
				...workspace.item,
				metadata: {
					title: 'Actionable',
					keywords: [],
					urls: [],
					authors: [],
					editors: [],
					identifiers: [],
					custom_fields: []
				},
				abstract_html: '<i>Summary</i>'
			}
		})
	);
	let exportQuery = '';
	await page.route('**/api/v1/items/item-1/bibliography?*', (route) => {
		exportQuery = new URL(route.request().url()).search;
		return route.fulfill({
			body: 'citation',
			headers: { 'Content-Disposition': 'attachment; filename="item.bib"' }
		});
	});
	let syncBody: Record<string, unknown> | null = null;
	await page.route('**/api/v1/items/item-1/metadata/sync', (route) => {
		syncBody = route.request().postDataJSON();
		return route.fulfill({ json: { ok: true } });
	});

	await page.goto('/item/item-1');
	await expect(page.locator('i', { hasText: 'Summary' })).toBeVisible();
	await page.getByRole('button', { name: 'Export' }).click();
	await page.getByLabel('Format').selectOption('bibtex');
	await page.getByRole('button', { name: 'Download file' }).click();
	await expect.poll(() => exportQuery).toContain('file_format=bibtex');
	await page.getByRole('button', { name: 'Metadata sources' }).click();
	await page.getByRole('button', { name: 'Autoupdate' }).first().click();
	await expect
		.poll(() => syncBody)
		.toEqual({
			expected_version: 3,
			provider: 'doi',
			uid: '10.1000/test'
		});
});

test('administration filters and paginates server-side collections', async ({ page }) => {
	await mockSession(page, 'administrator');
	const requests: string[] = [];
	await page.route('**/api/v1/admin/items*', (route) => {
		requests.push(route.request().url());
		const pageNumber = Number(new URL(route.request().url()).searchParams.get('page') ?? '1');
		return route.fulfill({
			json: {
				items: [],
				total: 40,
				page: pageNumber,
				per_page: 20,
				storage: { total_disk_bytes: 0 }
			}
		});
	});

	await page.goto('/admin/items');
	await page.getByLabel('PDF availability').selectOption('true');
	await page.getByRole('button', { name: 'Apply filters' }).click();
	await expect
		.poll(() => requests.some((url) => new URL(url).searchParams.get('has_pdf') === 'true'))
		.toBe(true);
	await page.getByRole('button', { name: 'Next' }).click();
	await expect
		.poll(() => requests.some((url) => new URL(url).searchParams.get('page') === '2'))
		.toBe(true);
});

test('administration resets section-specific filters during navigation', async ({ page }) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/users*', (route) =>
		route.fulfill({
			json: { users: [], total: 0, page: 1, per_page: 20, invitations: [] }
		})
	);
	let projectRequest = '';
	await page.route('**/api/v1/admin/projects*', (route) => {
		projectRequest = route.request().url();
		return route.fulfill({ json: { projects: [], total: 0, page: 1, per_page: 20 } });
	});

	await page.goto('/admin/users');
	await page.getByLabel('Role').selectOption('member');
	await page.getByRole('button', { name: 'Apply filters' }).click();
	await page
		.getByRole('navigation', { name: 'Administration sections' })
		.getByRole('link', { name: 'Projects' })
		.click();

	await expect.poll(() => projectRequest).not.toBe('');
	expect(new URL(projectRequest).searchParams.get('state')).toBeNull();
	expect(new URL(projectRequest).searchParams.get('visibility')).toBeNull();
	expect(new URL(projectRequest).searchParams.get('page')).toBeNull();
});

test('admin workflow rows render their state contract', async ({ page }) => {
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/workflows', (route) =>
		route.fulfill({
			json: { workflows: [{ id: 'workflow-1', name: 'backup', state: 'succeeded' }] }
		})
	);

	await page.goto('/admin/workflows');

	await expect(page.locator('section').getByText('Succeeded', { exact: true })).toBeVisible();

	await page.route('**/api/v1/admin/maintenance', (route) =>
		route.fulfill({
			json: {
				storage: { items_count: 1, total_disk_bytes: 100 },
				workflows: [{ id: 'workflow-2', name: 'reindex', state: 'running' }]
			}
		})
	);
	await page.goto('/admin/maintenance');
	await expect(page.getByText('Running', { exact: true })).toBeVisible();
});

test('session locale activates navigation without an unrelated rerender', async ({ page }) => {
	await mockSession(page, 'member', 'zh-CN');
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

test('desktop PDF inspector persists annotation notes and replies', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await mockSession(page);
	const mutations: Array<{ method: string; path: string; body: unknown }> = [];
	const annotation = {
		id: 'annotation-1',
		revision_id: 'revision-1',
		page_index: 0,
		kind: 'highlight',
		scope: 'private',
		project_id: null,
		body: 'Original note',
		selected_text: 'Evidence',
		payload: {
			type: 'highlight',
			rect: { x: 20, y: 30, width: 80, height: 12 },
			segment_rects: [{ x: 20, y: 30, width: 80, height: 12 }],
			style: {
				stroke_color: '#f59e0b',
				fill_color: '#fde68a',
				text_color: null,
				opacity: 0.7,
				stroke_width: 1,
				dash_pattern: []
			}
		},
		version: 1,
		author_display_name: 'reader',
		editable: true,
		created_at: '2026-09-16T00:00:00Z',
		updated_at: '2026-09-16T00:00:00Z',
		replies: [
			{
				id: 'reply-1',
				annotation_id: 'annotation-1',
				body: 'Existing reply',
				version: 1,
				author_display_name: 'reader',
				editable: true,
				created_at: '2026-09-16T00:00:00Z',
				updated_at: '2026-09-16T00:00:00Z'
			}
		]
	};
	await page.route('**/api/v1/items/item-1/revisions/revision-1/viewer', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Reader item', version: 1 },
				editable: true,
				annotation_author: 'reader',
				revision: {
					id: 'revision-1',
					original_name: 'paper.pdf',
					page_count: 1,
					processing_state: 'ready',
					page_geometry: [[0, 0, 300, 400]],
					content_url: '/api/v1/items/item-1/revisions/revision-1/content'
				},
				projects: []
			}
		})
	);
	await page.route('**/api/v1/items/item-1/annotations**', (route) => {
		const request = route.request();
		if (request.method() === 'GET') return route.fulfill({ json: [annotation] });
		mutations.push({
			method: request.method(),
			path: new URL(request.url()).pathname,
			body: request.postDataJSON()
		});
		if (request.method() === 'PATCH' && request.url().includes('/replies/')) {
			return route.fulfill({
				json: { ...annotation.replies[0], body: 'Edited reply', version: 2 }
			});
		}
		if (request.method() === 'POST' && request.url().endsWith('/replies')) {
			return route.fulfill({
				json: { ...annotation.replies[0], id: 'reply-2', body: 'New reply' }
			});
		}
		if (request.method() === 'PATCH') {
			return route.fulfill({ json: { ...annotation, body: 'Updated note', version: 2 } });
		}
		return route.fulfill({ json: { ok: true } });
	});
	await page.route('**/api/v1/items/item-1/revisions/revision-1/content', (route) =>
		route.fulfill({ contentType: 'application/pdf', body: minimalPdf() })
	);

	await page.goto('/item/item-1/pdf/revision-1');
	await page.getByRole('button', { name: 'Annotations', exact: true }).click();
	const inspector = page.getByRole('dialog', { name: 'Annotation inspector' });
	await inspector.locator('textarea').first().fill('Updated note');
	await inspector.getByRole('button', { name: 'Save note' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PATCH',
			path: '/api/v1/items/item-1/annotations/annotation-1',
			body: expect.objectContaining({ version: 1, body: 'Updated note' })
		});
	await inspector.getByPlaceholder('Write a reply').fill('New reply');
	await inspector.getByRole('button', { name: 'Reply', exact: true }).click();
	await expect
		.poll(() =>
			mutations.some((entry) => entry.method === 'POST' && entry.path.endsWith('/replies'))
		)
		.toBe(true);
	await inspector.locator('textarea').nth(1).fill('Edited reply');
	await inspector.getByRole('button', { name: 'Save reply' }).click();
	await expect
		.poll(() =>
			mutations.some((entry) => entry.method === 'PATCH' && entry.path.endsWith('/reply-1'))
		)
		.toBe(true);
	await inspector.getByRole('button', { name: 'Delete reply' }).click();
	await expect
		.poll(() =>
			mutations.some((entry) => entry.method === 'DELETE' && entry.path.endsWith('/reply-1'))
		)
		.toBe(true);
	page.once('dialog', (dialog) => dialog.accept());
	await inspector.getByRole('button', { name: 'Delete Annotation' }).click();
	await expect
		.poll(() =>
			mutations.some(
				(entry) => entry.method === 'DELETE' && entry.path.endsWith('/annotations/annotation-1')
			)
		)
		.toBe(true);
});

test('mobile PDF annotation control opens the inspector', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await mockSession(page);
	const pageErrors: string[] = [];
	page.on('pageerror', (error) => pageErrors.push(error.message));
	await page.route('**/api/v1/items/item-1/revisions/revision-1/viewer', (route) =>
		route.fulfill({
			json: {
				item: {
					id: 'item-1',
					title_html: 'Reader item',
					authors: null,
					publication_date: null,
					publication_title: null,
					doi: null,
					version: 1
				},
				editable: true,
				annotation_author: 'reader',
				revision: {
					id: 'revision-1',
					original_name: 'paper.pdf',
					page_count: 1,
					processing_state: 'ready',
					page_geometry: [[0, 0, 300, 400]],
					content_url: '/api/v1/items/item-1/revisions/revision-1/content'
				},
				projects: []
			}
		})
	);
	await page.route('**/api/v1/items/item-1/annotations?*', (route) => route.fulfill({ json: [] }));
	await page.route('**/api/v1/items/item-1/revisions/revision-1/content', (route) =>
		route.fulfill({ contentType: 'application/pdf', body: minimalPdf() })
	);

	await page.goto('/item/item-1/pdf/revision-1');
	await expect(page.getByLabel('PDF reader controls')).toBeVisible();
	expect(pageErrors).toEqual([]);
	await expect(page.getByLabel('Annotation color')).toBeVisible();
	await expect(page.getByText('Opacity', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Highlight' }).click();
	await page.getByLabel('Annotation color').fill('#22c55e');
	await page.getByRole('button', { name: 'Annotations Open inspector' }).click();

	await expect(page.getByRole('dialog', { name: 'Annotation inspector' })).toBeVisible();
});
