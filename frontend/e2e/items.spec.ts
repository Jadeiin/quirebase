import { expect, test } from '@playwright/test';
import { minimalPdf, mockSession } from './helpers';

test('item detail URL selects and loads the metadata section', async ({ page }) => {
	await mockSession(page);
	let metadataRequests = 0;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: '<i>Visible</i> Item', version: 1 },
				latest_revision: null,
				allowed_actions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1', (route) => {
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

	await page.goto('/workspace/workspace-1/item/item-1/metadata');

	await expect.poll(() => metadataRequests).toBe(1);
	await expect(page.getByRole('link', { name: 'Metadata' })).toHaveAttribute(
		'aria-current',
		'page'
	);
	await expect(page.getByRole('heading', { name: 'Metadata' })).toBeVisible();
});

test('Item overview renders without the deprecated Item Owner projection', async ({ page }) => {
	await mockSession(page);
	const pageErrors: string[] = [];
	page.on('pageerror', (error) => pageErrors.push(error.message));
	await page.route('**/api/v1/workspaces/workspace-1/items/item-overview/overview', (route) =>
		route.fulfill({
			json: {
				item: {
					id: 'item-overview',
					title_html: 'Workspace-scoped Item',
					authors: 'A. Researcher',
					publication_date: '2026',
					publication_title: 'Research Journal',
					doi: null,
					version: 1
				},
				allowed_actions: { edit: false, delete: false },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				identifiers: [],
				latest_revision: null,
				thumbnail: null
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-overview', (route) =>
		route.fulfill({
			json: {
				id: 'item-overview',
				title_html: 'Workspace-scoped Item',
				authors: 'A. Researcher',
				publication_date: '2026',
				publication_title: 'Research Journal',
				doi: null,
				version: 1,
				metadata: {
					title: 'Workspace-scoped Item',
					keywords: [],
					urls: [],
					authors: [],
					editors: [],
					identifiers: [],
					custom_fields: [],
					reference_type: null,
					volume: null,
					issue: null,
					pages: null,
					journal_abbreviation: null,
					publisher: null,
					place_published: null,
					affiliation: null,
					bibtex_key: null
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
		})
	);

	await page.goto('/workspace/workspace-1/item/item-overview');

	await expect(page.getByRole('heading', { name: 'Publication details' })).toBeVisible();
	const record = page
		.locator('section')
		.filter({ has: page.getByRole('heading', { name: 'Record' }) });
	await expect(record.getByText('Permissions', { exact: true })).toBeVisible();
	await expect(record.getByText('Read only', { exact: true })).toBeVisible();
	await expect(record.getByText('Citation key', { exact: true })).toBeVisible();
	await expect(pageErrors).toEqual([]);
});

test('read-only Item metadata does not expose mutation controls', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-readonly/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-readonly', title_html: 'Read-only Item', version: 1 },
				latest_revision: null,
				allowed_actions: { edit: false, delete: false },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-2', username: 'owner' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-readonly', (route) =>
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

	await page.goto('/workspace/workspace-1/item/item-readonly/metadata');

	await expect(page.getByText('Ada Reader')).toBeVisible();
	await expect(page.getByText('Shared abstract')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Save metadata' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Record tools' })).toHaveCount(0);
});

test('cross-Workspace copy only offers destinations where the User can create Items', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces', (route) =>
		route.fulfill({
			json: [
				{
					id: 'workspace-1',
					name: 'Source',
					effective_capabilities: ['workspace.read']
				},
				{
					id: 'workspace-2',
					name: 'Eligible destination',
					effective_capabilities: ['workspace.read', 'items.create']
				},
				{
					id: 'workspace-3',
					name: 'Read-only destination',
					effective_capabilities: ['workspace.read']
				}
			]
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-copy/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-copy', title_html: 'Copy source', version: 1 },
				latest_revision: null,
				allowed_actions: { edit: false, delete: false },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-copy', (route) =>
		route.fulfill({
			json: {
				id: 'item-copy',
				title_html: 'Copy source',
				version: 1,
				metadata: {
					title: 'Copy source',
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
	let copyBody: unknown;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-copy/copy', (route) => {
		copyBody = route.request().postDataJSON();
		return route.fulfill({
			json: {
				source_workspace_id: 'workspace-1',
				source_item_id: 'item-copy',
				target_workspace_id: 'workspace-2',
				target_item_id: 'item-copy-result'
			}
		});
	});

	await page.goto('/workspace/workspace-1/item/item-copy');
	await page.getByRole('button', { name: 'Copy to Workspace' }).click();
	const destination = page.getByLabel('Target Workspace');
	await expect(destination.locator('option')).toHaveText([
		'Choose a Workspace',
		'Eligible destination'
	]);
	await destination.selectOption('workspace-2');
	await page.getByRole('button', { name: 'Create copy' }).click();
	await expect.poll(() => copyBody).toEqual({ target_workspace_id: 'workspace-2' });
	await expect(page.getByRole('link', { name: 'Open copy' })).toHaveAttribute(
		'href',
		'/workspace/workspace-2/item/item-copy-result'
	);
});

test('Item annotation review spans every PDF revision', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-annotations/overview', (route) =>
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
				allowed_actions: { edit: false, delete: false },
				counts: { revisions: 2, attachments: 0, annotations: 2, discussion: 0 },
				tags: [],
				owner: { id: 'user-2', username: 'owner' },
				identifiers: []
			}
		})
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-annotations/annotations/review*',
		(route) => {
			const revisionId = new URL(route.request().url()).searchParams.get('revision_id');
			const annotations = ['revision-new', 'revision-old'].flatMap((currentRevision) => [
				{
					id: `annotation-${currentRevision}`,
					revision_id: currentRevision,
					revision_name: currentRevision === 'revision-new' ? 'new.pdf' : 'old.pdf',
					page_index: 0,
					kind: 'note',
					body: currentRevision === 'revision-new' ? 'New revision note' : 'Old revision note',
					selected_text: null,
					author_display_name: 'reader',
					allowed_actions: [],
					replies: []
				},
				{
					id: `shared-${currentRevision}`,
					revision_id: currentRevision,
					revision_name: currentRevision === 'revision-new' ? 'new.pdf' : 'old.pdf',
					page_index: 0,
					kind: 'note',
					body: 'Shared project note',
					selected_text: null,
					author_display_name: 'collaborator',
					allowed_actions: [],
					replies: []
				}
			]);
			const visible = revisionId
				? annotations.filter((annotation) => annotation.revision_id === revisionId)
				: annotations;
			return route.fulfill({
				json: {
					revisions: [
						{ id: 'revision-new', original_name: 'new.pdf' },
						{ id: 'revision-old', original_name: 'old.pdf' }
					],
					annotations: visible,
					total: visible.length,
					page: 1,
					per_page: 50
				}
			});
		}
	);

	await page.goto('/workspace/workspace-1/item/item-annotations/annotations');

	await expect(page.getByText('New revision note')).toBeVisible();
	await expect(page.getByText('Old revision note')).toBeVisible();
	await expect(page.getByText('New revision note')).toHaveCount(1);
	await expect(page.getByText('Shared project note')).toHaveCount(2);
	await page.getByLabel('PDF revision').selectOption('revision-old');
	await expect(page.getByText('New revision note')).toHaveCount(0);
	await expect(page.getByText('Old revision note')).toBeVisible();
	await expect(page.getByText('Shared project note')).toHaveCount(1);
});

test('Item annotation review surfaces aggregate lookup failures', async ({ page }) => {
	await mockSession(page);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-annotations-error/overview',
		(route) =>
			route.fulfill({
				json: {
					item: { id: 'item-annotations-error', title_html: 'Annotated Item', version: 1 },
					latest_revision: {
						id: 'revision-new',
						original_name: 'new.pdf',
						size: 200,
						page_count: 2,
						processing_state: 'ready'
					},
					allowed_actions: { edit: false, delete: false },
					counts: { revisions: 1, attachments: 0, annotations: 1, discussion: 0 },
					tags: [],
					owner: { id: 'user-2', username: 'owner' },
					identifiers: []
				}
			})
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-annotations-error/annotations/review*',
		(route) =>
			route.fulfill({
				status: 502,
				json: {
					code: 'upstream_service_error',
					message: 'annotation projection failed'
				}
			})
	);

	await page.goto('/workspace/workspace-1/item/item-annotations-error/annotations');

	await expect(page.getByText('Unable to load annotations.')).toBeVisible();
	await expect(page.getByText('New revision note')).toHaveCount(0);
});

test('Annotation moderation refreshes a stale version and requires an explicit retry', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-moderation/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-moderation', title_html: 'Moderation Item', version: 1 },
				latest_revision: {
					id: 'revision-1',
					original_name: 'paper.pdf',
					size: 100,
					page_count: 1,
					processing_state: 'ready'
				},
				allowed_actions: { edit: false, delete: false },
				counts: { revisions: 1, attachments: 0, annotations: 1, discussion: 0 },
				tags: [],
				owner: { id: 'user-2', username: 'owner' },
				identifiers: []
			}
		})
	);
	let reviewReads = 0;
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-moderation/annotations/review*',
		(route) => {
			reviewReads += 1;
			const latest = reviewReads > 1;
			return route.fulfill({
				json: {
					revisions: [{ id: 'revision-1', original_name: 'paper.pdf', size: 100, page_count: 1 }],
					annotations: [
						{
							id: 'annotation-1',
							revision_id: 'revision-1',
							revision_name: 'paper.pdf',
							page_index: 0,
							kind: 'note',
							version: latest ? 2 : 1,
							body: latest ? 'Updated by another moderator' : 'Original moderation target',
							selected_text: null,
							author_display_name: 'author',
							allowed_actions: ['hide'],
							replies: []
						}
					],
					total: 1,
					page: 1,
					per_page: 50
				}
			});
		}
	);
	const moderationBodies: unknown[] = [];
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-moderation/annotations/annotation-1/moderation',
		(route) => {
			moderationBodies.push(route.request().postDataJSON());
			if (moderationBodies.length === 1)
				return route.fulfill({
					status: 409,
					json: { code: 'version_conflict', message: 'annotation version is stale' }
				});
			return route.fulfill({ json: { id: 'annotation-1', version: 3 } });
		}
	);

	await page.goto('/workspace/workspace-1/item/item-moderation/annotations');
	await expect(page.getByText('Original moderation target')).toBeVisible();
	await page.getByRole('button', { name: 'hide', exact: true }).click();
	await expect(page.getByText('Updated by another moderator')).toBeVisible();
	await expect(
		page.getByText(/Latest state refreshed; review it and explicitly retry/)
	).toBeVisible();
	await expect.poll(() => moderationBodies).toEqual([{ action: 'hide', version: 1 }]);

	await page.getByRole('button', { name: 'hide', exact: true }).click();
	await expect
		.poll(() => moderationBodies)
		.toEqual([
			{ action: 'hide', version: 1 },
			{ action: 'hide', version: 2 }
		]);
});

test('Item file uploads wait for durable processing before refreshing', async ({ page }) => {
	await mockSession(page);
	let documentReads = 0;
	let workflowReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Files Item' },
				latest_revision: null,
				allowed_actions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/documents', (route) => {
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
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1', (route) =>
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
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/revisions', (route) =>
		route.fulfill({ status: 202, json: { id: 'workflow-1' } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/workflows/workflow-1', (route) => {
		workflowReads += 1;
		return route.fulfill({
			json: { id: 'workflow-1', state: workflowReads > 1 ? 'succeeded' : 'running', error: null }
		});
	});

	await page.goto('/workspace/workspace-1/item/item-1/files');
	await page.locator('input[name="pdf"]').setInputFiles({
		name: 'paper.pdf',
		mimeType: 'application/pdf',
		buffer: minimalPdf()
	});
	await page.getByRole('button', { name: 'Upload PDF' }).click();
	await expect.poll(() => workflowReads).toBeGreaterThan(1);
	await expect(page.getByText('paper.pdf')).toBeVisible();
	await expect(page.getByText('Document processing completed')).toBeVisible();
	await expect(page.getByRole('button', { name: /Background tasks/ })).toBeVisible();
});

test('Item file uploads settle with an error toast when status polling fails', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Files Item' },
				latest_revision: null,
				allowed_actions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/documents', (route) =>
		route.fulfill({ json: { item_id: 'item-1', files: [] } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1', (route) =>
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
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/revisions', (route) =>
		route.fulfill({ status: 202, json: { id: 'workflow-1' } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/workflows/workflow-1', (route) =>
		route.fulfill({ status: 404, json: { code: 'not_found', message: 'missing' } })
	);

	await page.goto('/workspace/workspace-1/item/item-1/files');
	await page.locator('input[name="pdf"]').setInputFiles({
		name: 'paper.pdf',
		mimeType: 'application/pdf',
		buffer: minimalPdf()
	});
	await page.getByRole('button', { name: 'Upload PDF' }).click();
	await expect(page.getByText('The requested resource was not found.').first()).toBeVisible({
		timeout: 20000
	});
	await expect(page.getByRole('button', { name: 'Upload PDF' })).toBeEnabled();
});

test('Item Files acquires URL imports through the same-origin API', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-remote/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-remote', title_html: 'Remote PDF Item', version: 1 },
				latest_revision: null,
				allowed_actions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: []
			}
		})
	);
	let documentReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-remote/documents', (route) => {
		documentReads += 1;
		return route.fulfill({ json: { item_id: 'item-remote', files: [] } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-remote', (route) =>
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
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-remote/revisions/remote',
		(route) => {
			revisionImport = route.request().postDataJSON();
			return route.fulfill({ status: 202, json: { id: 'workflow-remote' } });
		}
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-remote/attachments/remote',
		(route) => {
			attachmentImport = route.request().postDataJSON();
			return route.fulfill({ status: 202, json: { id: 'workflow-attachment' } });
		}
	);
	await page.route('**/api/v1/workspaces/workspace-1/workflows/workflow-remote', (route) =>
		route.fulfill({ json: { id: 'workflow-remote', state: 'succeeded', error: null } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/workflows/workflow-attachment', (route) =>
		route.fulfill({ json: { id: 'workflow-attachment', state: 'succeeded', error: null } })
	);

	await page.goto('/workspace/workspace-1/item/item-remote/files');
	await expect(page.locator('input[name="url"]').first()).toHaveValue(
		'https://papers.example/article.pdf'
	);
	await page.getByRole('button', { name: 'Download and add PDF' }).click();
	await expect
		.poll(() => revisionImport)
		.toEqual({
			source: 'https://papers.example/article.pdf'
		});
	await expect.poll(() => documentReads).toBeGreaterThan(1);

	const attachmentUrl = page.locator('input[name="url"]').nth(1);
	await attachmentUrl.fill('https://papers.example/supplement.zip');
	await page.getByRole('button', { name: 'Download and add attachment' }).click();
	await expect
		.poll(() => attachmentImport)
		.toEqual({
			source: 'https://papers.example/supplement.zip',
			graphical_abstract: false
		});
	await expect(attachmentUrl).toHaveValue('');
	await expect.poll(() => documentReads).toBeGreaterThan(2);

	await attachmentUrl.fill('https://papers.example/figure.png');
	const graphicalAbstract = page.getByLabel('Use as Graphical Abstract').nth(1);
	await graphicalAbstract.check();
	await page.getByRole('button', { name: 'Download and add attachment' }).click();
	await expect
		.poll(() => attachmentImport)
		.toEqual({
			source: 'https://papers.example/figure.png',
			graphical_abstract: true
		});
	await expect(attachmentUrl).toHaveValue('');
	await expect(graphicalAbstract).not.toBeChecked();

	expect(browserRemoteRequests).toBe(0);
});

test('manual Item creation submits complete structured metadata', async ({ page }) => {
	await mockSession(page);
	let creation: Record<string, unknown> | null = null;
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/items$/, (route) => {
		if (route.request().method() === 'POST') {
			creation = route.request().postDataJSON();
			return route.fulfill({ status: 201, json: { id: 'item-created', version: 1 } });
		}
		return route.fulfill({ status: 404, json: { detail: 'not found' } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-created/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-created', title_html: 'Structured record', version: 1 },
				allowed_actions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				identifiers: [],
				latest_revision: null
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-created', (route) =>
		route.fulfill({
			json: {
				id: 'item-created',
				title_html: 'Structured record',
				authors: 'Ada Lovelace',
				publication_date: '2026',
				publication_title: 'Journal of Testing',
				doi: null,
				version: 1,
				metadata: {
					title: 'Structured record',
					keywords: ['systems', 'reproducibility'],
					urls: [],
					authors: [{ first_name: 'Ada', last_name: 'Lovelace', is_corresponding: true }],
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
		})
	);

	await page.goto('/workspace/workspace-1/import');
	await page.getByRole('button', { name: 'Open metadata editor' }).click();
	await page.getByLabel('Title', { exact: true }).fill('Structured record');
	await page.getByLabel('Publication title').fill('Journal of Testing');
	await page.getByLabel('Keywords').fill('systems; reproducibility');
	await page
		.locator('header', { has: page.getByRole('heading', { name: 'Authors' }) })
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
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Editable', version: 4 },
				allowed_actions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: [],
				latest_revision: null
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1', (route) => {
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

	await page.goto('/workspace/workspace-1/item/item-1/metadata');
	await page
		.locator('header', { has: page.getByRole('heading', { name: 'Authors' }) })
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

test('Metadata synchronization refreshes the editor draft and Overview details', async ({
	page
}) => {
	await mockSession(page);
	let version = 1;
	let synchronized = false;
	let synchronization: { provider?: string; uid?: string } | null = null;
	const metadata = () => ({
		title: synchronized ? 'Synchronized title' : 'Old title',
		abstract: synchronized ? 'Synchronized abstract' : 'Old abstract',
		keywords: [],
		urls: [],
		authors: [],
		editors: [],
		identifiers: [],
		custom_fields: []
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: metadata().title, version, doi: '10.1000/sync' },
				allowed_actions: { edit: true, delete: true },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: [{ provider: 'doi', value: '10.1000/sync' }],
				latest_revision: null
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/metadata/sync', (route) => {
		synchronization = route.request().postDataJSON();
		synchronized = true;
		version += 1;
		return route.fulfill({ json: { ok: true } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1', (route) =>
		route.fulfill({
			json: {
				id: 'item-1',
				title_html: metadata().title,
				version,
				metadata: metadata(),
				abstract_html: metadata().abstract
			}
		})
	);

	await page.goto('/workspace/workspace-1/item/item-1');
	await expect(page.getByText('Old abstract')).toBeVisible();
	await page.getByRole('link', { name: 'Edit metadata' }).click();
	await expect(page).toHaveURL(/\/metadata$/);
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Old title');

	await page.getByRole('button', { name: 'Record tools' }).click();
	await page.getByLabel('Provider').selectOption('datacite');
	await page.getByRole('button', { name: 'Autoupdate' }).click();
	await expect
		.poll(() => synchronization)
		.toMatchObject({ provider: 'datacite', uid: '10.1000/sync' });
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Synchronized title');
	await page
		.getByRole('dialog', { name: 'Item actions' })
		.getByRole('button', { name: 'Close' })
		.click();

	await page.getByRole('link', { name: 'Overview' }).click();
	await expect(page.getByText('Synchronized abstract')).toBeVisible();
});

test('Item organization toggles the Tag matrix and waits for recommendations', async ({ page }) => {
	await mockSession(page);
	const mutations: Array<{ method: string; path: string; body: unknown }> = [];
	let workflowReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Organize', version: 1 },
				allowed_actions: { edit: true, delete: true },
				counts: { revisions: 1, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				owner: { id: 'user-1', username: 'reader' },
				identifiers: [],
				latest_revision: { id: 'revision-1', original_name: 'paper.pdf' }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/organize', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Organize', version: 1 },
				allowed_actions: { edit: true },
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
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/tags', (route) => {
		mutations.push({
			method: route.request().method(),
			path: new URL(route.request().url()).pathname,
			body: route.request().postDataJSON()
		});
		return route.fulfill({ json: { ok: true } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/tag-recommendations', (route) =>
		route.fulfill({ status: 202, json: { id: 'workflow-tags' } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/workflows/workflow-tags', (route) => {
		workflowReads += 1;
		return route.fulfill({
			json: { id: 'workflow-tags', state: workflowReads > 1 ? 'succeeded' : 'running', error: null }
		});
	});

	await page.goto('/workspace/workspace-1/item/item-1/organize');
	await page.getByRole('button', { name: 'Methods ★' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/workspaces/workspace-1/items/item-1/tags',
			body: { add_tag_ids: ['tag-1'], remove_tag_ids: [], new_names: [] }
		});
	await page.getByRole('button', { name: 'Refresh' }).click();
	await expect.poll(() => workflowReads).toBeGreaterThan(1);
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
		allowed_actions: { edit: true, delete: true },
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
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({ json: workspace })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1', (route) =>
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
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/bibliography?*', (route) => {
		exportQuery = new URL(route.request().url()).search;
		return route.fulfill({
			body: 'citation',
			headers: { 'Content-Disposition': 'attachment; filename="item.bib"' }
		});
	});
	let syncBody: Record<string, unknown> | null = null;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/metadata/sync', (route) => {
		syncBody = route.request().postDataJSON();
		return route.fulfill({ json: { ok: true } });
	});

	await page.goto('/workspace/workspace-1/item/item-1');
	await expect(page.locator('i', { hasText: 'Summary' })).toBeVisible();
	await page.getByRole('button', { name: 'Export' }).click();
	await page.getByLabel('Format').selectOption('bibtex');
	await page.getByRole('button', { name: 'Download file' }).click();
	await expect.poll(() => exportQuery).toContain('file_format=bibtex');
	await page.getByRole('button', { name: 'Metadata sources' }).click();
	await page.getByLabel('Provider').selectOption('openalex');
	await page.getByRole('button', { name: 'Autoupdate' }).first().click();
	await expect
		.poll(() => syncBody)
		.toEqual({
			expected_version: 3,
			provider: 'openalex',
			uid: '10.1000/test'
		});
});
