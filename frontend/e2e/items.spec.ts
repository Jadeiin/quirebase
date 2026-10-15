import { chooseSearchOption } from './helpers';
import { directoryPage } from './helpers';
import { expect, test } from '@playwright/test';
import { minimalPdf, mockSession, workspaceView } from './helpers';

const editableItemAuthorization = {
	allowed: [
		'item.update',
		'item.delete',
		'workspace.export',
		'file.manage',
		'file.delete',
		'tag.use',
		'tag.create',
		'project_item.manage'
	]
};

test('DOI source selector uses configured lookup capabilities', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: {
				search: [],
				lookup: [
					{ id: 'commonmeta', name: 'Commonmeta hosted', identifier_namespaces: ['doi'] },
					{ id: 'crossref', name: 'Crossref', identifier_namespaces: ['doi'] },
					{ id: 'pubmed', name: 'PubMed', identifier_namespaces: ['pmid'] }
				],
				max_search_clauses: 5
			}
		})
	);
	const metadata = {
		id: 'https://doi.org/10.1000/primary',
		type: 'JournalArticle',
		title: 'Configured DOI sources'
	};
	await page.route('**/api/v1/workspaces/workspace-1/items/doi-provider/overview', (route) =>
		route.fulfill({
			json: {
				item: {
					id: 'doi-provider',
					title_html: metadata.title,
					doi: '10.1000/primary',
					version: 1
				},
				metadata,
				citation_key: null,
				authorization: editableItemAuthorization,
				copy_targets: [],
				tags: [],
				latest_revision: null,
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
			}
		})
	);
	let syncBody: Record<string, unknown> | null = null;
	await page.route('**/api/v1/workspaces/workspace-1/items/doi-provider/metadata/sync', (route) => {
		syncBody = route.request().postDataJSON();
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/item/doi-provider');
	await page.getByRole('button', { name: 'Record tools', exact: true }).click();
	const dialog = page.getByRole('dialog');
	const selector = dialog.getByRole('combobox', { name: 'Provider', exact: true });
	await expect(selector.locator('option')).toHaveText([
		'Auto detect',
		'Commonmeta hosted',
		'Crossref'
	]);
	await selector.selectOption('commonmeta');
	await dialog.getByRole('button', { name: 'Autoupdate', exact: true }).click();
	await expect
		.poll(() => syncBody)
		.toEqual({ expected_version: 1, provider: 'commonmeta', uid: '10.1000/primary' });
});

for (const primarySpelling of [
	'10.1000/primary',
	'10.1000/PRIMARY',
	'HTTPS://DX.DOI.ORG/10.1000/PRIMARY',
	'https://doi.org/10.1000/pr%69mary'
]) {
	test(`Metadata sources hides the primary DOI ${primarySpelling} and keeps secondary DOIs selectable`, async ({
		page
	}) => {
		await mockSession(page);
		const metadata = {
			id: 'https://doi.org/10.1000/primary',
			type: 'JournalArticle',
			title: 'Multiple DOIs',
			identifiers: [
				{ identifier_type: 'DOI', identifier: primarySpelling },
				{ identifier_type: 'DOI', identifier: '10.1000/secondary' },
				{ identifier_type: 'DOI', identifier: '10.1000/secondary' }
			]
		};
		await page.route('**/api/v1/workspaces/workspace-1/items/doi-sources/overview', (route) =>
			route.fulfill({
				json: {
					item: {
						id: 'doi-sources',
						title_html: metadata.title,
						doi: '10.1000/primary',
						version: 1
					},
					metadata,
					citation_key: null,
					authorization: editableItemAuthorization,
					copy_targets: [],
					tags: [],
					latest_revision: null,
					counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
				}
			})
		);
		await page.route('**/api/v1/workspaces/workspace-1/items/doi-sources', (route) =>
			route.fulfill({
				json: { id: 'doi-sources', title_html: metadata.title, version: 1, metadata }
			})
		);
		let syncBody: Record<string, unknown> | null = null;
		await page.route(
			'**/api/v1/workspaces/workspace-1/items/doi-sources/metadata/sync',
			(route) => {
				syncBody = route.request().postDataJSON();
				return route.fulfill({ json: { ok: true } });
			}
		);
		await page.goto('/workspace/workspace-1/item/doi-sources');
		await page.getByRole('button', { name: 'Record tools', exact: true }).click();
		const dialog = page.getByRole('dialog');
		await expect(dialog.getByText('10.1000/primary', { exact: true })).toHaveCount(1);
		if (primarySpelling !== '10.1000/primary') {
			await expect(dialog.getByText(primarySpelling, { exact: true })).toHaveCount(0);
		}
		await expect(dialog.getByRole('button', { name: 'Autoupdate', exact: true })).toHaveCount(2);
		const secondary = dialog.getByText('10.1000/secondary', { exact: true });
		await expect(secondary).toHaveCount(1);
		await secondary
			.locator('..')
			.locator('..')
			.getByRole('button', { name: 'Autoupdate', exact: true })
			.click();
		await expect
			.poll(() => syncBody)
			.toEqual({ expected_version: 1, provider: 'crossref', uid: '10.1000/secondary' });
	});
}

for (const manual of [false, true]) {
	for (const targetHasFiles of [false, true]) {
		test(`cached Item navigation resets PDF URL and search with manual=${manual}, target files=${targetHasFiles}`, async ({
			page
		}) => {
			await mockSession(page);
			const urlFor = (id: string) => `https://papers.example/${id}.pdf`;
			for (const id of ['pdf-source', 'pdf-target']) {
				const metadata = {
					id: `https://doi.org/10.1000/${id}`,
					type: 'JournalArticle',
					title: id,
					...(id === 'pdf-source' || targetHasFiles
						? { files: [{ url: urlFor(id) }, { url: urlFor(`${id}-other`) }] }
						: {})
				};
				await page.route(`**/api/v1/workspaces/workspace-1/items/${id}/overview`, (route) =>
					route.fulfill({
						json: {
							item: { id, title_html: id, version: 1 },
							metadata,
							citation_key: null,
							authorization: editableItemAuthorization,
							copy_targets: [],
							tags: [],
							latest_revision: null,
							counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
						}
					})
				);
				await page.route(`**/api/v1/workspaces/workspace-1/items/${id}`, (route) =>
					route.fulfill({ json: { id, title_html: id, version: 1, metadata } })
				);
				await page.route(`**/api/v1/workspaces/workspace-1/items/${id}/documents`, (route) =>
					route.fulfill({ json: { item_id: id, files: [] } })
				);
			}
			const requests: Record<string, unknown>[] = [];
			await page.route(
				'**/api/v1/workspaces/workspace-1/items/pdf-target/revisions/remote',
				(route) => {
					requests.push(route.request().postDataJSON());
					return route.fulfill({ status: 202, json: { id: 'pdf-import-workflow' } });
				}
			);
			await page.route('**/api/v1/workspaces/workspace-1/workflows/pdf-import-workflow', (route) =>
				route.fulfill({ json: { id: 'pdf-import-workflow', state: 'succeeded', error: null } })
			);
			async function navigate(id: string) {
				await expect(page.getByRole('combobox', { name: 'PDF URL' })).toBeVisible();
				await page.evaluate((itemId) => {
					document.querySelector('[data-testid="cached-files-link"]')?.remove();
					const link = document.createElement('a');
					link.href = `/workspace/workspace-1/item/${itemId}/files`;
					link.dataset.testid = 'cached-files-link';
					link.textContent = 'Switch cached Item';
					document.querySelector('main')!.append(link);
				}, id);
				await page.getByTestId('cached-files-link').click();
				await expect(page).toHaveURL(new RegExp(`/item/${id}/files$`));
				await expect(page.getByRole('combobox', { name: 'PDF URL' })).toBeVisible();
			}
			await page.goto('/workspace/workspace-1/item/pdf-source/files');
			await navigate('pdf-target');
			await navigate('pdf-source');
			if (manual)
				await page.getByRole('combobox', { name: 'PDF URL' }).fill(urlFor('manual-source'));
			else await chooseSearchOption(page, 'PDF URL', urlFor('pdf-source-other'));
			await navigate('pdf-target');
			const expected = targetHasFiles ? urlFor('pdf-target') : '';
			await expect(page.locator('input[name="url"]').first()).toHaveValue(expected);
			await expect(page.getByRole('combobox', { name: 'PDF URL' })).toHaveValue(expected);
			if (targetHasFiles) {
				await page.getByRole('button', { name: 'Download and add PDF', exact: true }).click();
				await expect.poll(() => requests[0]).toEqual({ source: expected });
			} else expect(requests).toHaveLength(0);
		});
	}
}

for (const [primary, namespace, value, provider, identifierType, secondary] of [
	[
		'https://openalex.org/W123',
		'openalex',
		'W123',
		'openalex',
		'OpenAlex',
		'https://openalex.org/W123'
	],
	['https://pubmed.ncbi.nlm.nih.gov/42/', 'pmid', '42', 'pubmed', 'PMID', '42'],
	['https://arxiv.org/abs/2401.00001', 'arxiv', '2401.00001', 'arxiv', 'arXiv', '2401.00001']
]) {
	for (const alsoSecondary of [false, true]) {
		test(`primary ${namespace} offers one sync action with secondary=${alsoSecondary}`, async ({
			page
		}) => {
			await mockSession(page);
			const metadata = {
				id: primary,
				type: 'Preprint',
				title: 'Primary source',
				...(alsoSecondary
					? {
							identifiers: [
								{ identifier_type: identifierType, identifier: secondary },
								{ identifier_type: identifierType, identifier: secondary }
							]
						}
					: {})
			};
			await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
				route.fulfill({
					json: {
						search: [],
						lookup: [{ id: provider, name: provider, identifier_namespaces: [namespace] }],
						max_search_clauses: 5
					}
				})
			);
			await page.route('**/api/v1/workspaces/workspace-1/items/primary-source/overview', (route) =>
				route.fulfill({
					json: {
						item: { id: 'primary-source', title_html: metadata.title, version: 1 },
						metadata,
						primary_lookup_identifier: alsoSecondary ? null : { provider: namespace, value },
						citation_key: null,
						authorization: editableItemAuthorization,
						copy_targets: [],
						tags: [],
						latest_revision: null,
						counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
					}
				})
			);
			await page.route('**/api/v1/workspaces/workspace-1/items/primary-source', (route) =>
				route.fulfill({
					json: { id: 'primary-source', title_html: metadata.title, version: 1, metadata }
				})
			);
			let syncBody: Record<string, unknown> | null = null;
			await page.route(
				'**/api/v1/workspaces/workspace-1/items/primary-source/metadata/sync',
				(route) => {
					syncBody = route.request().postDataJSON();
					return route.fulfill({ json: { ok: true } });
				}
			);
			await page.goto('/workspace/workspace-1/item/primary-source');
			await page.getByRole('button', { name: 'Record tools', exact: true }).click();
			const action = page
				.getByRole('dialog')
				.getByRole('button', { name: 'Autoupdate', exact: true });
			await expect(action).toHaveCount(1);
			await action.click();
			await expect
				.poll(() => syncBody)
				.toEqual({ expected_version: 1, provider, uid: alsoSecondary ? secondary : value });
		});
	}
}

for (const repeated of [false, true]) {
	test(`metadata sources expose supported lookups with repeated identifiers=${repeated}`, async ({
		page
	}) => {
		await mockSession(page);
		const pageErrors: string[] = [];
		page.on('pageerror', (error) => pageErrors.push(error.message));
		const identifiers = [
			{ identifier_type: 'PMID', identifier: '42' },
			...(repeated
				? [
						{ identifier_type: 'PMID', identifier: '42' },
						{ identifier_type: 'Other', scheme: 'pmid', identifier: '42' }
					]
				: []),
			{ identifier_type: 'Handle', identifier: '12345/record' },
			{ identifier_type: 'URL', identifier: 'https://example.org/record' },
			{ identifier_type: 'Other', scheme: 'Local registry', identifier: 'local-123' },
			{ identifier_type: 'PMCID', identifier: 'PMC42' },
			{ identifier_type: 'ISBN', identifier: '9780131103627' },
			{ identifier_type: 'Bibcode', identifier: '2025ApJ...123..456A' }
		];
		const metadata = {
			id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
			type: 'Dataset',
			title: 'Identifier actions',
			identifiers
		};
		await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
			route.fulfill({
				json: {
					search: [],
					lookup: [
						{ id: 'pubmed', name: 'PubMed', identifier_namespaces: ['pmid'] },
						{ id: 'openlibrary', name: 'Open Library', identifier_namespaces: ['isbn'] }
					],
					max_search_clauses: 5
				}
			})
		);
		await page.route(
			'**/api/v1/workspaces/workspace-1/items/identifier-actions/overview',
			(route) =>
				route.fulfill({
					json: {
						item: { id: 'identifier-actions', title_html: metadata.title, version: 1 },
						metadata,
						citation_key: null,
						authorization: editableItemAuthorization,
						copy_targets: [],
						tags: [],
						latest_revision: null,
						counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
					}
				})
		);
		await page.route('**/api/v1/workspaces/workspace-1/items/identifier-actions', (route) =>
			route.fulfill({
				json: { id: 'identifier-actions', title_html: metadata.title, version: 1, metadata }
			})
		);
		let syncBody: Record<string, unknown> | null = null;
		await page.route(
			'**/api/v1/workspaces/workspace-1/items/identifier-actions/metadata/sync',
			(route) => {
				syncBody = route.request().postDataJSON();
				return route.fulfill({ json: { ok: true } });
			}
		);
		await page.goto('/workspace/workspace-1/item/identifier-actions');
		await page.getByRole('button', { name: 'Record tools', exact: true }).click();
		const dialog = page.getByRole('dialog');
		await expect(dialog.getByText('42', { exact: true })).toHaveCount(1);
		for (const value of [
			'12345/record',
			'https://example.org/record',
			'local-123',
			'PMC42',
			'2025ApJ...123..456A'
		]) {
			const row = dialog.getByText(value, { exact: true }).locator('..').locator('..');
			await expect(row).toBeVisible();
			await expect(row.getByRole('button', { name: 'Autoupdate', exact: true })).toHaveCount(0);
		}
		await expect(dialog.getByRole('button', { name: 'Autoupdate', exact: true })).toHaveCount(2);
		await dialog
			.getByText('42', { exact: true })
			.locator('..')
			.locator('..')
			.getByRole('button', { name: 'Autoupdate', exact: true })
			.click();
		await expect
			.poll(() => syncBody)
			.toEqual({ expected_version: 1, provider: 'pubmed', uid: '42' });
		await expect(pageErrors).toEqual([]);
	});
}

for (const withFiles of [false, true]) {
	test(`overview includes the Work landing URL with files=${withFiles}`, async ({ page }) => {
		await mockSession(page);
		const url = 'https://pubmed.ncbi.nlm.nih.gov/42/';
		const metadata = {
			id: 'https://doi.org/10.1000/landing',
			type: 'JournalArticle',
			title: 'Landing page Item',
			url,
			...(withFiles ? { files: [{ url }, { url: 'https://example.org/article.pdf' }] } : {})
		};
		await page.route('**/api/v1/workspaces/workspace-1/items/landing/overview', (route) =>
			route.fulfill({
				json: {
					item: { id: 'landing', title_html: metadata.title, version: 1 },
					metadata,
					citation_key: null,
					authorization: { allowed: [] },
					copy_targets: [],
					tags: [],
					latest_revision: null,
					counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
				}
			})
		);
		await page.route('**/api/v1/workspaces/workspace-1/items/landing', (route) =>
			route.fulfill({ json: { id: 'landing', title_html: metadata.title, version: 1, metadata } })
		);
		await page.goto('/workspace/workspace-1/item/landing');
		const panel = page
			.locator('section')
			.filter({ has: page.getByRole('heading', { name: 'External links', exact: true }) });
		await expect(panel.locator(`a[href="${url}"]`)).toHaveCount(1);
		await expect(panel.getByText('No external links.')).toHaveCount(0);
		if (withFiles)
			await expect(panel.locator('a[href="https://example.org/article.pdf"]')).toHaveCount(1);
	});
}

test('item detail URL selects and loads the metadata section', async ({ page }) => {
	await mockSession(page);
	let metadataRequests = 0;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: '<i>Visible</i> Item'
				},
				citation_key: null,
				item: { id: 'item-1', title_html: '<i>Visible</i> Item', version: 1 },
				latest_revision: null,
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
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
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: '<i>Visible</i> Item'
				},
				abstract_html: null
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
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Workspace-scoped Item',
					date_published: '2026',
					container: { title: 'Research Journal' }
				},
				citation_key: null,
				item: {
					id: 'item-overview',
					title_html: 'Workspace-scoped Item',
					authors: 'A. Researcher',
					publication_date: '2026',
					publication_title: 'Research Journal',
					doi: null,
					version: 1
				},
				authorization: { allowed: [] },
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],

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
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Workspace-scoped Item'
				},
				abstract_html: null
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
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Read-only Item'
				},
				citation_key: null,
				item: { id: 'item-readonly', title_html: 'Read-only Item', version: 1 },
				latest_revision: null,
				authorization: { allowed: [] },
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
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
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Read-only Item',
					description: 'Shared abstract',
					subjects: [{ subject: 'shared' }],
					contributors: [
						{
							type: 'Person',
							person: {
								name: 'Ada Reader',
								family_name: 'Reader',
								given_name: 'Ada'
							},
							roles: ['Author']
						}
					],
					identifiers: [
						{ identifier_type: 'DOI', identifier: '10.1000/shared' },
						{ identifier_type: 'OpenAlex', identifier: 'https://openalex.org/W1230000000' }
					]
				},
				abstract_html: 'Shared abstract'
			}
		})
	);

	await page.goto('/workspace/workspace-1/item/item-readonly/metadata');

	await expect(page.getByText('Ada Reader')).toBeVisible();
	await expect(page.getByText('Shared abstract')).toBeVisible();
	await expect(page.getByText('10.1000/shared')).toBeVisible();
	await expect(
		page.getByText('openalex: https://openalex.org/W1230000000', { exact: true })
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Save metadata' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Record tools' })).toHaveCount(0);
});

test('cross-Workspace copy uses the server-provided eligible destinations', async ({ page }) => {
	await mockSession(page);
	await page.route(/\/api\/v1\/workspaces(?:\?.*)?$/, (route) =>
		route.fulfill({
			json: directoryPage(
				[
					{
						id: 'workspace-1',
						name: 'Source',
						authorization: { allowed: ['workspace.read'] }
					},
					{
						id: 'workspace-2',
						name: 'Eligible destination',
						authorization: { allowed: ['workspace.read', 'item.create'] }
					},
					{
						id: 'workspace-3',
						name: 'Read-only destination',
						authorization: { allowed: ['workspace.read'] }
					}
				],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-copy/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Copy source'
				},
				citation_key: null,
				item: { id: 'item-copy', title_html: 'Copy source', version: 1 },
				latest_revision: null,
				authorization: { allowed: ['workspace.export'] },
				copy_targets: [
					{
						id: 'workspace-2',
						name: 'Eligible destination'
					}
				],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
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
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Copy source'
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
	const destination = page.getByRole('combobox', { name: 'Target Workspace', exact: true });
	await destination.click();
	await expect(page.getByRole('option')).toHaveCount(2);
	await expect(page.getByRole('option', { name: 'Choose a Workspace', exact: true })).toBeVisible();
	await expect(
		page.getByRole('option', { name: 'Eligible destination', exact: true })
	).toBeVisible();
	await chooseSearchOption(page, 'Target Workspace', 'Eligible destination');
	await page.getByRole('button', { name: 'Create copy' }).click();
	await expect.poll(() => copyBody).toEqual({ target_workspace_id: 'workspace-2' });
	await expect(page.getByRole('link', { name: 'Open copy' })).toHaveAttribute(
		'href',
		'/workspace/workspace-2/item/item-copy-result'
	);
});

test('cross-Workspace copy refreshes the target Workspace dashboard and Library', async ({
	page
}) => {
	await mockSession(page);
	const sourceItem = {
		id: 'item-copy',
		title_html: 'Copy source',
		authors: null,
		publication_date: null,
		publication_title: null,
		doi: null,
		version: 1
	};
	const copiedItem = { ...sourceItem, id: 'item-copy-result' };
	let copied = false;
	await page.route('**/api/v1/workspaces/workspace-2/dashboard', (route) =>
		route.fulfill({
			json: {
				new_items: copied ? [copiedItem] : [],
				recent_items: [],
				projects: [],
				project_count: 0,
				session_count: 0
			}
		})
	);
	await page.route(/\/api\/v1\/workspaces\/workspace-2\/items(\?|$)/, (route) => {
		const items = copied ? [copiedItem] : [];
		return route.fulfill({ json: { items, total: items.length, limit: 25, offset: 0 } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-copy/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Copy source'
				},
				citation_key: null,
				item: sourceItem,
				latest_revision: null,
				authorization: { allowed: ['workspace.export'] },
				copy_targets: [{ id: 'workspace-2', name: 'Archive' }],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-copy', (route) =>
		route.fulfill({
			json: {
				...sourceItem,
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Copy source'
				},
				abstract_html: null
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-copy/copy', (route) => {
		copied = true;
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
	// Warm the target Workspace projections so the copy has to invalidate cached views.
	await page.getByRole('button', { name: 'Workspace', exact: true }).click();
	await page.getByRole('menuitem', { name: /Archive/ }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-2$/);
	await page.getByRole('link', { name: 'Library', exact: true }).first().click();
	await expect(page).toHaveURL(/\/workspace\/workspace-2\/library$/);
	await page.goBack();
	await expect(page).toHaveURL(/\/workspace\/workspace-2$/);
	await page.goBack();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/item\/item-copy$/);

	await page.getByRole('button', { name: 'Copy to Workspace' }).click();
	await chooseSearchOption(page, 'Target Workspace', 'Archive');
	await page.getByRole('button', { name: 'Create copy' }).click();
	await expect(page.getByRole('link', { name: 'Open copy' })).toBeVisible();
	await page.keyboard.press('Escape');

	await page.getByRole('button', { name: 'Workspace', exact: true }).click();
	await page.getByRole('menuitem', { name: /Archive/ }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-2$/);
	await expect(page.getByText('Copy source')).toBeVisible();
	await page.getByRole('link', { name: 'Library', exact: true }).first().click();
	await expect(page).toHaveURL(/\/workspace\/workspace-2\/library$/);
	await expect(page.getByText('Copy source')).toBeVisible();
});

test('creating a Workspace refreshes cached Item copy destinations', async ({ page }) => {
	await mockSession(page);
	const sourceItem = {
		id: 'item-copy',
		title_html: 'Copy source',
		authors: null,
		publication_date: null,
		publication_title: null,
		doi: null,
		version: 1
	};
	let workspaceCreated = false;
	await page.route('**/api/v1/workspaces/creation-availability', (route) =>
		route.fulfill({ json: { allowed: true, owner_username_required: false } })
	);
	await page.route(/\/api\/v1\/workspaces(?:\?.*)?$/, (route) => {
		if (route.request().method() === 'POST') {
			workspaceCreated = true;
			return route.fulfill({ status: 201, json: { id: 'workspace-new' } });
		}
		return route.fulfill({
			json: directoryPage(
				[
					workspaceView('workspace-1', 'Research'),
					workspaceView('workspace-2', 'Archive'),
					...(workspaceCreated ? [workspaceView('workspace-new', 'New Workspace')] : [])
				],
				route
			)
		});
	});
	await page.route('**/api/v1/workspaces/workspace-new', (route) =>
		route.fulfill({ json: workspaceView('workspace-new', 'New Workspace') })
	);
	await page.route('**/api/v1/workspaces/workspace-new/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-copy/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Copy source'
				},
				citation_key: null,
				item: sourceItem,
				latest_revision: null,
				authorization: { allowed: ['workspace.export'] },
				copy_targets: workspaceCreated
					? [
							{ id: 'workspace-2', name: 'Archive' },
							{ id: 'workspace-new', name: 'New Workspace' }
						]
					: [{ id: 'workspace-2', name: 'Archive' }],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-copy', (route) =>
		route.fulfill({
			json: {
				...sourceItem,
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Copy source'
				},
				abstract_html: null
			}
		})
	);

	await page.goto('/workspace/workspace-1/item/item-copy');
	await page.getByRole('button', { name: 'Copy to Workspace' }).click();
	await page.getByRole('combobox', { name: 'Target Workspace', exact: true }).click();
	await expect(page.getByRole('option')).toHaveCount(2);
	await page.keyboard.press('Escape');
	await page.keyboard.press('Escape');

	await page.getByRole('button', { name: 'Workspace', exact: true }).click();
	await page.getByRole('menuitem', { name: 'Manage workspaces' }).click();
	await page.getByLabel('Workspace name').fill('New Workspace');
	await page.getByRole('button', { name: 'Create workspace' }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-new$/);
	await page.goBack();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/item\/item-copy$/);

	await page.getByRole('button', { name: 'Copy to Workspace' }).click();
	await page.getByRole('combobox', { name: 'Target Workspace', exact: true }).click();
	await expect(page.getByRole('option', { name: 'New Workspace', exact: true })).toBeVisible();
});

test('Item annotation review spans every PDF revision', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-annotations/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Annotated Item'
				},
				citation_key: null,
				item: { id: 'item-annotations', title_html: 'Annotated Item', version: 1 },
				latest_revision: {
					id: 'revision-new',
					original_name: 'new.pdf',
					size: 200,
					page_count: 2,
					processing_state: 'ready'
				},
				authorization: { allowed: ['workspace.export'] },
				copy_targets: [],
				counts: { revisions: 2, attachments: 0, annotations: 2, discussion: 0 },
				tags: []
			}
		})
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-annotations/annotations*',
		(route) => {
			const query = new URL(route.request().url()).searchParams;
			const revisionId = query.get('revision_id');
			const annotations = ['revision-new', 'revision-old'].flatMap((currentRevision) => [
				{
					id: `annotation-${currentRevision}`,
					scope: 'private',
					project_id: null,
					project_name: null,
					revision_id: currentRevision,
					revision_name: currentRevision === 'revision-new' ? 'new.pdf' : 'old.pdf',
					page_index: 0,
					kind: 'note',
					body: currentRevision === 'revision-new' ? 'New revision note' : 'Old revision note',
					selected_text: null,
					author_display_name: 'reader',
					authorization: { allowed: [] },
					replies: []
				},
				{
					id: `shared-${currentRevision}`,
					scope: 'project',
					project_id: 'project-1',
					project_name: 'Shared',
					revision_id: currentRevision,
					revision_name: currentRevision === 'revision-new' ? 'new.pdf' : 'old.pdf',
					page_index: 0,
					kind: 'note',
					body: 'Shared project note',
					selected_text: null,
					author_display_name: 'collaborator',
					authorization: { allowed: [] },
					replies: []
				}
			]);
			const visible = annotations
				.filter((annotation) => !revisionId || annotation.revision_id === revisionId)
				.filter((annotation) => !query.get('scope') || annotation.scope === query.get('scope'));
			return route.fulfill({
				json: {
					revisions: [
						{ id: 'revision-new', original_name: 'new.pdf' },
						{ id: 'revision-old', original_name: 'old.pdf' }
					],
					projects: [{ id: 'project-1', name: 'Shared' }],
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
	await expect(page.getByRole('link', { name: 'Open PDF' }).last()).toHaveAttribute(
		'href',
		'/workspace/workspace-1/item/item-annotations/pdf/revision-old?project_id=project-1'
	);
	await page
		.getByRole('combobox', { name: 'Annotation source', exact: true })
		.selectOption('private');
	await expect(page.getByText('Shared project note')).toHaveCount(0);
	await expect(page.getByText('Old revision note')).toBeVisible();
	await page
		.getByRole('combobox', { name: 'Annotation source', exact: true })
		.selectOption('project-1');
	await expect(page.getByText('Old revision note')).toHaveCount(0);
	await expect(page.getByText('Shared project note')).toHaveCount(1);
	await expect(page.getByRole('link', { name: 'Open annotation workspace' })).toHaveAttribute(
		'href',
		'/workspace/workspace-1/item/item-annotations/pdf/revision-old?project_id=project-1'
	);
});

test('Item annotation review surfaces aggregate lookup failures', async ({ page }) => {
	await mockSession(page);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-annotations-error/overview',
		(route) =>
			route.fulfill({
				json: {
					metadata: {
						id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
						type: 'Other',
						title: 'Annotated Item'
					},
					citation_key: null,
					item: { id: 'item-annotations-error', title_html: 'Annotated Item', version: 1 },
					latest_revision: {
						id: 'revision-new',
						original_name: 'new.pdf',
						size: 200,
						page_count: 2,
						processing_state: 'ready'
					},
					authorization: { allowed: ['workspace.export'] },
					copy_targets: [],
					counts: { revisions: 1, attachments: 0, annotations: 1, discussion: 0 },
					tags: []
				}
			})
	);
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-annotations-error/annotations*',
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
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Moderation Item'
				},
				citation_key: null,
				item: { id: 'item-moderation', title_html: 'Moderation Item', version: 1 },
				latest_revision: {
					id: 'revision-1',
					original_name: 'paper.pdf',
					size: 100,
					page_count: 1,
					processing_state: 'ready'
				},
				authorization: { allowed: ['workspace.export'] },
				copy_targets: [],
				counts: { revisions: 1, attachments: 0, annotations: 1, discussion: 0 },
				tags: []
			}
		})
	);
	let reviewReads = 0;
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-moderation/annotations*',
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
							mine: false,
							authorization: {
								allowed: ['project_annotation.hide', 'project_annotation.delete']
							},
							replies: []
						},
						{
							id: 'own-annotation',
							revision_id: 'revision-1',
							revision_name: 'paper.pdf',
							page_index: 0,
							kind: 'note',
							version: 1,
							body: 'My own annotation',
							selected_text: null,
							author_display_name: 'reader',
							mine: true,
							authorization: {
								allowed: ['project_annotation.update', 'project_annotation.delete']
							},
							replies: []
						}
					],
					total: 2,
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
	await expect(
		page.getByText('My own annotation').locator('..').getByLabel('Moderator actions')
	).toHaveCount(0);
	await page.getByRole('button', { name: 'Hide', exact: true }).click();
	await expect(page.getByText('Updated by another moderator')).toBeVisible();
	await expect(
		page.getByText(/Latest state refreshed; review it and explicitly retry/)
	).toBeVisible();
	await expect.poll(() => moderationBodies).toEqual([{ action: 'hide', version: 1 }]);

	await page.getByRole('button', { name: 'Hide', exact: true }).click();
	await expect
		.poll(() => moderationBodies)
		.toEqual([
			{ action: 'hide', version: 1 },
			{ action: 'hide', version: 2 }
		]);

	await page.getByRole('button', { name: 'Delete', exact: true }).click();
	await page.getByRole('dialog').getByRole('button', { name: 'Delete', exact: true }).click();
	await expect
		.poll(() => moderationBodies)
		.toEqual([
			{ action: 'hide', version: 1 },
			{ action: 'hide', version: 2 },
			{ action: 'delete', version: 2 }
		]);
});

test('Item file uploads keep the accepted file after dismissing or rejecting a chooser', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Files Item'
				},
				citation_key: null,
				item: { id: 'item-1', title_html: 'Files Item' },
				latest_revision: null,
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
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
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Files Item'
				},
				abstract_html: null
			}
		})
	);
	let uploadBody = '';
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/revisions', (route) => {
		uploadBody = route.request().postData() ?? '';
		return route.fulfill({ status: 202, json: { id: 'workflow-1' } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/workflows/workflow-1', (route) =>
		route.fulfill({ json: { id: 'workflow-1', state: 'succeeded', error: null } })
	);

	await page.goto('/workspace/workspace-1/item/item-1/files');
	const input = page.locator('input[name="pdf"]');
	await input.setInputFiles({
		name: 'cancel-probe.pdf',
		mimeType: 'application/pdf',
		buffer: minimalPdf()
	});

	// Opening the chooser again and dismissing it must not drop the accepted file:
	// the picker clears the hidden input so re-selecting the same file still fires
	// `input`, then restores the accepted files before the dialog opens.
	await Promise.all([
		page.waitForEvent('filechooser'),
		page.getByRole('button', { name: 'PDF file', exact: true }).click()
	]);
	expect(await input.evaluate((element: HTMLInputElement) => element.files?.length ?? 0)).toBe(1);
	expect(await input.evaluate((element: HTMLInputElement) => element.files?.[0]?.name ?? '')).toBe(
		'cancel-probe.pdf'
	);

	// An unsupported selection is rejected and reported, and the hidden input must
	// keep matching the accepted file instead of submitting the rejected one.
	for (let attempt = 0; attempt < 2; attempt += 1) {
		await input.setInputFiles({
			name: 'notes.txt',
			mimeType: 'text/plain',
			buffer: Buffer.from('not a pdf')
		});
		await expect(page.getByText('cancel-probe.pdf', { exact: true })).toBeVisible();
		expect(
			await input.evaluate((element: HTMLInputElement) => element.files?.[0]?.name ?? '')
		).toBe('cancel-probe.pdf');
	}
	await page.getByRole('button', { name: 'Remove cancel-probe.pdf', exact: true }).click();
	expect(await input.evaluate((element: HTMLInputElement) => element.files?.length ?? 0)).toBe(0);
	await expect(page.getByRole('button', { name: 'Upload PDF' })).toBeDisabled();
	await input.setInputFiles({
		name: 'cancel-probe.pdf',
		mimeType: 'application/pdf',
		buffer: minimalPdf()
	});

	await page.getByRole('button', { name: 'Upload PDF' }).click();
	await expect.poll(() => uploadBody).toContain('cancel-probe.pdf');
	expect(uploadBody).not.toContain('notes.txt');
});

test('Item file uploads wait for durable processing before refreshing', async ({ page }) => {
	await mockSession(page);
	let documentReads = 0;
	let workflowReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Files Item'
				},
				citation_key: null,
				item: { id: 'item-1', title_html: 'Files Item' },
				latest_revision: null,
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
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
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Files Item'
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
	await expect(page.locator('input[name="pdf"]')).toBeDisabled();
	await expect(page.locator('input[name="attachment"]')).toBeDisabled();
	await expect.poll(() => workflowReads).toBeGreaterThan(1);
	await expect(page.getByText('paper.pdf')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(1);
	await expect(page.getByText('Document processing completed')).toBeVisible();
	await expect(page.getByRole('button', { name: /Background tasks/ })).toBeVisible();
	await expect(page.locator('input[name="pdf"]')).toBeEnabled();
	await expect(page.locator('input[name="attachment"]')).toBeEnabled();
	await expect(page.getByRole('button', { name: 'Upload PDF' })).toBeDisabled();
});

test('Item file uploads settle with an error toast when status polling fails', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Files Item'
				},
				citation_key: null,
				item: { id: 'item-1', title_html: 'Files Item' },
				latest_revision: null,
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
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
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Files Item'
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
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Remote PDF Item',
					files: [
						{ url: 'https://papers.example/article.pdf', mime_type: 'application/pdf' },
						{ url: 'https://papers.example/article.pdf', mime_type: 'application/pdf' },
						{ url: 'https://papers.example/revised.pdf', mime_type: 'application/pdf' },
						{ url: 'https://papers.example/supplement.zip', mime_type: 'application/zip' }
					]
				},
				citation_key: null,
				item: { id: 'item-remote', title_html: 'Remote PDF Item', version: 1 },
				latest_revision: null,
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
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
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Remote PDF Item',
					files: [
						{ url: 'https://papers.example/article.pdf', mime_type: 'application/pdf' },
						{ url: 'https://papers.example/article.pdf', mime_type: 'application/pdf' },
						{ url: 'https://papers.example/revised.pdf', mime_type: 'application/pdf' },
						{ url: 'https://papers.example/supplement.zip', mime_type: 'application/zip' }
					]
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
	await chooseSearchOption(page, 'PDF URL', 'https://papers.example/revised.pdf');
	await expect(page.getByRole('option')).toHaveCount(0);
	await page.getByRole('button', { name: 'Download and add PDF' }).click();
	await expect
		.poll(() => revisionImport)
		.toEqual({
			source: 'https://papers.example/revised.pdf'
		});
	await expect.poll(() => documentReads).toBeGreaterThan(1);

	await expect(page.getByRole('combobox', { name: 'PDF URL' })).toHaveValue('');
	await page.getByRole('combobox', { name: 'PDF URL' }).fill('https://papers.example/custom.pdf');
	await page.getByRole('button', { name: 'Download and add PDF' }).click();
	await expect.poll(() => revisionImport).toEqual({ source: 'https://papers.example/custom.pdf' });

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

test('manual Item creation submits the standard Work and separate Citation Key', async ({
	page
}) => {
	await mockSession(page);
	let creation: Record<string, unknown> | null = null;
	const metadata = {
		id: 'https://doi.org/10.1000/created',
		type: 'Book',
		title: 'Structured record',
		date_published: '2024',
		container: { title: 'Collection' },
		subjects: [{ subject: 'systems; theory' }, { subject: 'reproducibility' }],
		contributors: [{ type: 'Person', person: { name: 'Ada Lovelace' }, roles: ['Author'] }],
		identifiers: [
			{ identifier_type: 'OpenAlex', identifier: 'https://openalex.org/W1230000000' },
			{ identifier_type: 'DOI', identifier: '10.1000/second' }
		],
		funding_references: [{ funder_name: 'Foundation' }]
	};
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/items$/, (route) => {
		creation = route.request().postDataJSON();
		return route.fulfill({ status: 201, json: { id: 'item-created', version: 1 } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-created/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-created', title_html: metadata.title, version: 1 },
				metadata,
				citation_key: 'Lovelace2024',
				authorization: editableItemAuthorization,
				copy_targets: [],
				tags: [],
				latest_revision: null,
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-created', (route) =>
		route.fulfill({
			json: {
				id: 'item-created',
				title_html: metadata.title,
				version: 1,
				metadata,
				citation_key: 'Lovelace2024'
			}
		})
	);
	await page.goto('/workspace/workspace-1/import');
	await page.getByRole('tab', { name: 'Manual creation', exact: true }).click();
	await page.getByLabel('Title', { exact: true }).fill(metadata.title);
	await page.getByLabel('Reference type').selectOption('Book');
	const date = page.getByRole('textbox', { name: 'Publication date', exact: true });
	await date.fill('2024');
	await page.getByLabel('Date precision').selectOption('month');
	await expect(date).toHaveValue('');
	await date.fill('2024-02');
	await page.getByLabel('Date precision').selectOption('day');
	await expect(date).toHaveValue('');
	await date.fill('2024-02-29');
	await page.getByLabel('Date precision').selectOption('year');
	await expect(date).toHaveValue('2024');
	await page.getByLabel('Citation key').fill('Lovelace2024');
	await page.getByRole('button', { name: 'Edit standard metadata JSON' }).click();
	await page.getByRole('textbox', { name: 'Metadata', exact: true }).fill(JSON.stringify(metadata));
	await page.getByRole('button', { name: 'Create Item' }).click();
	await expect(page.getByText('Apply JSON changes before saving.')).toBeVisible();
	expect(creation).toBeNull();
	await page.getByRole('button', { name: 'Apply JSON', exact: true }).click();
	await page.getByRole('button', { name: 'Create Item' }).click();
	await expect.poll(() => creation).toEqual({ metadata, citation_key: 'Lovelace2024' });
});

for (const published of ['2024-02', '2024-02-29T12:34:56Z']) {
	test(`Item editing preserves hidden Work facts and ${published}`, async ({ page }) => {
		await mockSession(page);
		let update: Record<string, unknown> | null = null;
		const metadata = {
			id: 'https://doi.org/10.1000/own',
			type: 'ProceedingsArticle',
			title: 'Editable',
			date_published: published,
			contributors: [
				{
					type: 'Person',
					person: { name: 'Grace Hopper', affiliations: [{ name: 'University' }] },
					roles: ['Author']
				},
				{ type: 'Organization', organization: { name: 'Research Council' }, roles: ['Editor'] }
			],
			identifiers: [
				{ identifier_type: 'DOI', identifier: '10.1000/second' },
				{ identifier_type: 'DOI', identifier: '10.1000/third' },
				{ identifier_type: 'OpenAlex', identifier: 'https://openalex.org/W1230000000' }
			],
			container: {
				title: 'Proceedings',
				identifiers: [{ identifier_type: 'ISBN', identifier: '9780131103627' }]
			},
			relations: [{ id: 'https://doi.org/10.1000/related', type: 'IsSupplementTo' }],
			funding_references: [{ funder_name: 'Foundation' }]
		};
		await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
			route.fulfill({
				json: {
					item: { id: 'item-1', title_html: metadata.title, version: 4 },
					metadata,
					citation_key: 'Hopper2024',
					authorization: editableItemAuthorization,
					copy_targets: [],
					tags: [],
					latest_revision: null,
					counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
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
					title_html: metadata.title,
					version: 4,
					metadata,
					citation_key: 'Hopper2024'
				}
			});
		});
		await page.goto('/workspace/workspace-1/item/item-1/metadata');
		await expect(page.getByLabel('Reference type')).toHaveValue(metadata.type);
		await page.getByLabel('Reference type').selectOption('Software');
		await page.getByLabel('Title', { exact: true }).fill('Revised');
		await expect(page.getByRole('textbox', { name: 'Publication date', exact: true })).toHaveValue(
			published
		);
		if (published.includes('T')) await expect(page.getByLabel('Date precision')).toHaveCount(0);
		else await expect(page.getByLabel('Date precision')).toHaveValue('month');
		await page.getByRole('button', { name: 'Save metadata' }).click();
		await expect
			.poll(() => update)
			.toEqual({
				expected_version: 4,
				citation_key: 'Hopper2024',
				metadata: { ...metadata, title: 'Revised', type: 'Software' }
			});
	});
}

test('Metadata synchronization refreshes the editor draft and Overview details', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: {
				search: [],
				lookup: [{ id: 'datacite', name: 'DataCite', identifier_namespaces: ['doi'] }],
				max_search_clauses: 5
			}
		})
	);
	let version = 1;
	let synchronized = false;
	let synchronization: { provider?: string; uid?: string } | null = null;
	const metadata = () => ({
		id: 'https://doi.org/10.1000/sync',
		type: 'Other',
		title: synchronized ? 'Synchronized title' : 'Old title',
		description: synchronized ? 'Synchronized abstract' : 'Old abstract',
		identifiers: [{ identifier_type: 'DOI', identifier: '10.1000/sync' }]
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: metadata(),
				citation_key: null,
				item: { id: 'item-1', title_html: metadata().title, version, doi: '10.1000/sync' },
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],

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
				abstract_html: metadata().description
			}
		})
	);

	await page.goto('/workspace/workspace-1/item/item-1');
	await expect(page.getByText('Old abstract')).toBeVisible();
	await page.getByRole('link', { name: 'Edit metadata' }).click();
	await expect(page).toHaveURL(/\/metadata$/);
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Old title');

	await page.getByRole('button', { name: 'Record tools' }).click();
	await page
		.getByRole('dialog', { name: 'Item actions' })
		.getByLabel('Provider', { exact: true })
		.selectOption('datacite');
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
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Organize'
				},
				citation_key: null,
				item: { id: 'item-1', title_html: 'Organize', version: 1 },
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 1, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],

				latest_revision: { id: 'revision-1', original_name: 'paper.pdf' }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/organize', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Organize', version: 1 },
				authorization: editableItemAuthorization,
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
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: {
				search: [],
				lookup: [{ id: 'openalex', name: 'OpenAlex', identifier_namespaces: ['openalex', 'doi'] }],
				max_search_clauses: 5
			}
		})
	);
	const workspace = {
		metadata: {
			id: 'https://doi.org/10.1000/test',
			type: 'Other',
			title: 'Actionable',
			description: '<i>Summary</i>',
			date_published: '2026',
			container: { title: 'Journal' },
			identifiers: [{ identifier_type: 'OpenAlex', identifier: 'https://openalex.org/W1230000000' }]
		},
		citation_key: null,
		item: {
			id: 'item-1',
			title_html: 'Actionable',
			authors: 'A. Author',
			publication_date: '2026',
			publication_title: 'Journal',
			doi: '10.1000/test',
			version: 3
		},
		authorization: editableItemAuthorization,
		copy_targets: [],
		counts: { revisions: 1, attachments: 0, annotations: 0, discussion: 0 },
		tags: [],

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
				metadata: workspace.metadata,
				abstract_html: workspace.metadata.description
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
	for (const format of ['csl-json', 'commonmeta']) {
		await page.getByLabel('Format').selectOption(format);
		await page.getByRole('button', { name: 'Download file' }).click();
		await expect.poll(() => exportQuery).toContain(`file_format=${format}`);
	}
	await page.getByRole('tab', { name: 'Metadata sources' }).click();
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

test('publication calendar preserves precision, supports keyboard selection and validates typed dates', async ({
	page
}) => {
	await mockSession(page);
	await page.goto('/workspace/workspace-1/import');
	await page.getByRole('tab', { name: 'Manual creation', exact: true }).click();
	const date = page.getByRole('textbox', { name: 'Publication date', exact: true });
	const precision = page.getByLabel('Date precision');
	const calendar = page.getByRole('application', {
		name: 'Calendar for Publication date',
		exact: true
	});
	const openCalendar = () =>
		page.getByRole('button', { name: 'Choose date for Publication date', exact: true }).click();
	await date.fill('2024');
	await openCalendar();
	await calendar.getByRole('button', { name: '2023', exact: true }).click();
	await expect(date).toHaveValue('2023');
	await expect(calendar).not.toBeVisible();
	await precision.selectOption('month');
	await expect(date).toHaveValue('');
	await date.fill('2024-02');
	await openCalendar();
	await calendar.getByRole('button', { name: /March/ }).click();
	await expect(date).toHaveValue('2024-03');
	await precision.selectOption('day');
	await expect(date).toHaveValue('');
	await date.pressSequentially('2024-02-29');
	await openCalendar();
	const selectedDay = calendar.getByRole('button', { name: /Selected date.*February 29/ });
	await selectedDay.focus();
	await selectedDay.press('ArrowRight');
	await page.locator(':focus').press('Enter');
	await expect(date).toHaveValue('2024-03-01');
	await expect(calendar).not.toBeVisible();
	await date.fill('2023-02-29');
	await date.press('Tab');
	await expect(date).toHaveValue('2023-02-29');
	expect(await date.evaluate((element: HTMLInputElement) => element.checkValidity())).toBe(false);
	await date.fill('');
	await date.press('Tab');
	await expect(date).toHaveValue('');
	expect(await date.evaluate((element: HTMLInputElement) => element.checkValidity())).toBe(true);
});

test('Overview and Files share Work without detail requests and localize publication details', async ({
	page
}) => {
	await mockSession(page);
	const metadata = {
		id: 'https://doi.org/10.1000/overview',
		type: 'JournalArticle',
		title: 'Overview record',
		description: '<i>Overview abstract</i>',
		subjects: [{ subject: 'Graph theory' }],
		files: [{ url: 'https://papers.example/overview.pdf', mime_type: 'application/pdf' }],
		contributors: ['Ada', 'Grace'].map((name) => ({
			type: 'Person',
			person: { name, affiliations: [{ name: 'Research University' }] },
			roles: ['Author']
		})),
		container: {
			type: 'Journal',
			title: 'Research Journal',
			additional_titles: ['Res. J.'],
			first_page: '10',
			last_page: '24',
			publisher: { name: 'Journal host' },
			identifiers: [{ identifier_type: 'ISSN', identifier: '1234-5678' }],
			platform: 'Research platform',
			series: 'Research series',
			location: 'Shanghai',
			url: 'https://journal.example',
			country: 'CN',
			language: 'zh'
		}
	};
	await page.route('**/api/v1/workspaces/workspace-1/items/overview/overview', (route) =>
		route.fulfill({
			json: {
				metadata,
				item: { id: 'overview', title_html: metadata.title, version: 1 },
				citation_key: 'ManualOverviewKey',
				authorization: editableItemAuthorization,
				copy_targets: [],
				tags: [],
				latest_revision: null,
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
			}
		})
	);
	let detailRequests = 0;
	await page.route('**/api/v1/workspaces/workspace-1/items/overview', (route) => {
		detailRequests += 1;
		return route.fulfill({ status: 500, json: { message: 'Unexpected detail request' } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/overview/documents', (route) =>
		route.fulfill({ json: { item_id: 'overview', files: [] } })
	);
	await page.goto('/workspace/workspace-1/item/overview');
	await expect(page.getByText('Research University', { exact: true })).toHaveCount(1);
	await expect(page.getByText('10–24', { exact: true })).toBeVisible();
	await expect(page.getByText('ISSN: 1234-5678', { exact: true })).toBeVisible();
	await expect(page.getByText('Journal host', { exact: true })).toBeVisible();
	await expect(page.getByText('Res. J.', { exact: true })).toBeVisible();
	await expect(page.getByText('Research platform', { exact: true })).toBeVisible();
	await expect(page.getByText('Overview abstract', { exact: true })).toBeVisible();
	await expect(page.getByText('ManualOverviewKey', { exact: true })).toBeVisible();
	await expect(page.getByText('Graph theory', { exact: true })).toBeVisible();
	await page.getByRole('link', { name: 'Files', exact: true }).click();
	await expect(page.getByRole('combobox', { name: 'PDF URL' })).toHaveValue(
		'https://papers.example/overview.pdf'
	);
	await page.getByRole('link', { name: 'Overview', exact: true }).click();
	await expect(page.getByText('ManualOverviewKey', { exact: true })).toBeVisible();
	expect(detailRequests).toBe(0);
	await page.evaluate(() => {
		localStorage.setItem('quirebase:locale', 'zh-CN');
		window.dispatchEvent(
			new StorageEvent('storage', { key: 'quirebase:locale', newValue: 'zh-CN' })
		);
	});
	await expect(page.getByText('期刊论文', { exact: true })).toBeVisible();
	await expect(page.getByText('期刊', { exact: true })).toBeVisible();
});

test('Dashboard read history refreshes after opening an Item', async ({ page }) => {
	await mockSession(page);
	const item = {
		id: 'item-1',
		title_html: 'Read item',
		authors: null,
		publication_date: null,
		publication_title: null,
		doi: null,
		version: 1
	};
	let read = false;
	await page.route('**/api/v1/workspaces/workspace-1/dashboard', (route) =>
		route.fulfill({
			json: {
				new_items: [item],
				recent_items: read ? [{ item, last_read_at: '2026-01-01T00:00:00Z' }] : [],
				projects: [],
				project_count: 0,
				session_count: 0
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) => {
		// Opening an Item section records the read that feeds "Continue reading".
		read = true;
		return route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Read item'
				},
				citation_key: null,
				item,
				latest_revision: null,
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
			}
		});
	});

	await page.goto('/workspace/workspace-1');
	await expect(page.getByText('Open an Item to start your reading history.')).toBeVisible();
	await page.getByRole('link', { name: /Read item/ }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/item\/item-1$/);
	await page.getByRole('link', { name: 'Dashboard', exact: true }).first().click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1$/);
	await expect(page.getByText('Open an Item to start your reading history.')).toHaveCount(0);
});

test('Tools Tag counts refresh after an Item tag assignment', async ({ page }) => {
	await mockSession(page);
	let assigned = false;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Item'
				},
				citation_key: null,
				item: { id: 'item-1', title_html: 'Item', version: 1 },
				latest_revision: null,
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/organize', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Item', version: 1 },
				authorization: editableItemAuthorization,
				tags: assigned ? [{ id: 'tag-1', name: 'Methods' }] : [],
				projects: [],
				tag_matrix: {
					groups: [{ letter: 'M', tags: [{ id: 'tag-1', name: 'Methods' }], names: ['Methods'] }],
					assigned_ids: assigned ? ['tag-1'] : [],
					recommended_ids: [],
					suggested_names: [],
					suggested_single_words: [],
					suggested_phrases: [],
					recommendation_state: 'ready',
					recommendation_error: null
				}
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/tags', (route) => {
		assigned = true;
		return route.fulfill({ json: { ok: true } });
	});
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/tags\?.*/, (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'tag-1',
						name: 'Methods',
						accessible_item_count: assigned ? 1 : 0,
						authorization: { allowed: ['tag.manage'] }
					}
				],
				total: 1,
				limit: 20,
				offset: 0
			}
		})
	);

	await page.goto('/workspace/workspace-1/item/item-1/organize');
	await page.getByRole('link', { name: 'Tools', exact: true }).first().click();
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await expect(page.getByText('0 Items')).toBeVisible();
	await page.goBack();
	await expect(page).toHaveURL(/\/item\/item-1\/organize$/);
	await page.getByRole('button', { name: 'Methods', exact: true }).click();
	await expect.poll(() => assigned).toBe(true);
	await page.getByRole('link', { name: 'Tools', exact: true }).first().click();
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await expect(page.getByText('1 Item')).toBeVisible();
});

test('Project item counts refresh after an Item assignment', async ({ page }) => {
	await mockSession(page);
	let assigned = false;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Item'
				},
				citation_key: null,
				item: { id: 'item-1', title_html: 'Item', version: 1 },
				latest_revision: null,
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/organize', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Item', version: 1 },
				authorization: editableItemAuthorization,
				tags: [],
				projects: [
					{
						id: 'project-1',
						name: 'Alpha',
						assigned,
						participation: 'open',
						is_participating: false
					}
				],
				tag_matrix: {
					groups: [],
					assigned_ids: [],
					recommended_ids: [],
					suggested_names: [],
					suggested_single_words: [],
					suggested_phrases: [],
					recommendation_state: 'ready',
					recommendation_error: null
				}
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/items/item-1', (route) => {
		assigned = true;
		return route.fulfill({ json: { ok: true } });
	});
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/projects\?.*/, (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'project-1',
						name: 'Alpha',
						item_count: assigned ? 1 : 0,
						state: 'active',
						participation: 'open',
						is_participating: false,
						description: '',
						allowed_participation_changes: [],
						authorization: { allowed: ['workspace.read'] }
					}
				],
				total: 1,
				limit: 25,
				offset: 0
			}
		})
	);

	await page.goto('/workspace/workspace-1/item/item-1/organize');
	await page.getByRole('link', { name: 'Projects', exact: true }).first().click();
	await expect(page.getByText('0 Items')).toBeVisible();
	await page.goBack();
	await expect(page).toHaveURL(/\/item\/item-1\/organize$/);
	await page.getByText('Other open Projects').click();
	await page.getByRole('button', { name: 'Add', exact: true }).click();
	await expect.poll(() => assigned).toBe(true);
	await page.getByRole('link', { name: 'Projects', exact: true }).first().click();
	await expect(page.getByText('1 Item')).toBeVisible();
});

test('Tag renames refresh Item tag projections', async ({ page }) => {
	await mockSession(page);
	let renamed = false;
	const tagName = () => (renamed ? 'Methods renamed' : 'Methods');
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		route.fulfill({
			json: {
				metadata: {
					id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
					type: 'Other',
					title: 'Item'
				},
				citation_key: null,
				item: { id: 'item-1', title_html: 'Item', version: 1 },
				latest_revision: null,
				authorization: editableItemAuthorization,
				copy_targets: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/organize', (route) =>
		route.fulfill({
			json: {
				item: { id: 'item-1', title_html: 'Item', version: 1 },
				authorization: editableItemAuthorization,
				tags: [{ id: 'tag-1', name: tagName() }],
				projects: [],
				tag_matrix: {
					groups: [{ letter: 'M', tags: [{ id: 'tag-1', name: tagName() }], names: [tagName()] }],
					assigned_ids: ['tag-1'],
					recommended_ids: [],
					suggested_names: [],
					suggested_single_words: [],
					suggested_phrases: [],
					recommendation_state: 'ready',
					recommendation_error: null
				}
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/tags/tag-1', (route) => {
		renamed = true;
		return route.fulfill({ json: { ok: true } });
	});
	await page.route(/\/api\/v1\/workspaces\/workspace-1\/tags\?.*/, (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'tag-1',
						name: tagName(),
						accessible_item_count: 1,
						authorization: { allowed: ['tag.manage'] }
					}
				],
				total: 1,
				limit: 20,
				offset: 0
			}
		})
	);

	await page.goto('/workspace/workspace-1/item/item-1/organize');
	await expect(page.getByRole('button', { name: 'Methods', exact: true })).toBeVisible();
	await page.getByRole('link', { name: 'Tools', exact: true }).first().click();
	await page.getByRole('tab', { name: 'Manage Tags' }).click();
	await page.getByRole('button', { name: 'Rename', exact: true }).click();
	await page.getByLabel('New Tag name').fill('Methods renamed');
	await page.getByRole('dialog').getByRole('button', { name: 'Rename', exact: true }).click();
	await expect(page.getByText('Tag renamed')).toBeVisible();
	await page.goBack();
	await expect(page).toHaveURL(/\/item\/item-1\/organize$/);
	await expect(page.getByRole('button', { name: 'Methods renamed', exact: true })).toBeVisible();
});
