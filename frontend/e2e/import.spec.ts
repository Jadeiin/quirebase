import { expect, test, type Page } from '@playwright/test';
import type { components } from '../src/lib/api/schema.js';
import {
	chooseSearchOption,
	directoryPage,
	mockSession,
	openLibraryAction,
	tagPage,
	workspaceView
} from './helpers';

const importPath = '/workspace/workspace-1/import';
const importHistoryPath = `${importPath}/history`;
const libraryPath = '/workspace/workspace-1/library';
const batchId = '10000000-0000-4000-8000-000000000001';
const importedIds = [
	'20000000-0000-4000-8000-000000000001',
	'20000000-0000-4000-8000-000000000002'
];
const importButtonName = /^Import \d+ records?$/;
type ImportBatch = components['schemas']['ImportBatchPreview'];

function importBatch(overrides: Partial<ImportBatch> = {}): ImportBatch {
	return {
		id: batchId,
		file_format: 'metadata',
		status: 'ready',
		workflow_id: null,
		created_at: '2026-10-21T00:00:00Z',
		committed_item_ids: [],
		records:
			overrides.status === 'committed'
				? []
				: importedIds.map((id, index) => ({
						metadata: {
							id: `urn:uuid:${id}`,
							type: 'JournalArticle',
							title: `Imported reference ${index + 1}`,
							date_published: '2026',
							container: { type: 'Journal', title: 'Import Journal' }
						}
					})),
		errors: [],
		...overrides
	};
}

async function mockImportedLibrary(page: Page) {
	const rows: components['schemas']['ItemSearchView'][] = [
		...importedIds.map((id, index) => ({
			id,
			title_html: `Imported reference ${index + 1}`,
			authors: [],
			publication_date: '2026',
			publication_title: 'Import Journal',
			doi: null,
			version: 1
		})),
		{
			id: '20000000-0000-4000-8000-000000000003',
			title_html: 'Earlier Library reference',
			authors: [],
			publication_date: '2025',
			publication_title: 'Earlier Journal',
			doi: null,
			version: 1
		}
	];
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([{ id: 'tag-import', name: 'Imported reading' }], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	const reads: URL[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const url = new URL(route.request().url());
		reads.push(url);
		const parameters = url.searchParams;
		const filtered = rows.filter(
			(row) =>
				(!parameters.has('import_batch') || importedIds.includes(row.id)) &&
				(!parameters.has('year') || row.publication_date === parameters.get('year')) &&
				(!parameters.has('publication_title') ||
					row.publication_title === parameters.get('publication_title'))
		);
		return route.fulfill({ json: directoryPage(filtered, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/*/overview', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		const row = rows.find((item) => item.id === id)!;
		return route.fulfill({
			json: {
				id,
				version: 1,
				citation_key: null,
				metadata: {
					id: `urn:uuid:${id}`,
					type: 'JournalArticle',
					title: row.title_html,
					date_published: row.publication_date,
					container: { type: 'Journal', title: row.publication_title }
				},
				authorization: { allowed: ['item.update'] },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: [],
				latest_revision_id: null,
				thumbnail: null,
				copy_targets: []
			}
		});
	});
	const mutations: unknown[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		mutations.push(route.request().postDataJSON());
		return route.fulfill({ json: { ok: true } });
	});
	return { reads, mutations };
}

// Exercise client navigation without adding a product-only route-switching control.
async function navigateToBatch(page: Page, id: string) {
	await page.evaluate((href) => {
		const link = document.createElement('a');
		link.id = 'test-import-batch-navigation';
		link.href = href;
		link.textContent = 'Open another Import Batch';
		document.querySelector('main')!.append(link);
	}, `${importPath}?batch=${id}`);
	await page.locator('#test-import-batch-navigation').click();
	await page.evaluate(() => document.getElementById('test-import-batch-navigation')?.remove());
}

test('identifier Import uses configured provider choices', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/discovery/providers', (route) =>
		route.fulfill({
			json: { search: [], lookup: [{ id: 'datacite', name: 'DataCite' }], max_search_clauses: 5 }
		})
	);
	await page.goto('/workspace/workspace-1/import');
	const source = page.getByRole('combobox', { name: 'Data source' });
	await expect(source.locator('option')).toHaveText(['Auto detect', 'DataCite']);
	await expect(source).toBeEnabled();
});

test('Import methods use separate keyboard accessible tabs and preserve drafts', async ({
	page
}) => {
	await mockSession(page);
	await page.goto('/workspace/workspace-1/import');
	const tabs = page.getByRole('tablist', { name: 'Import methods' });
	await expect(tabs.getByRole('tab')).toHaveText([
		'Identifiers',
		'Bibliography',
		'PDFs',
		'Manual creation'
	]);
	await expect(page.getByRole('tabpanel', { name: 'Identifiers', exact: true })).toBeVisible();
	await expect(page.getByRole('tab', { name: 'Identifiers', exact: true })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await page
		.getByRole('textbox', { name: 'Identifiers', exact: true })
		.fill('10.1000/first\nISBN:0674016394');
	await page.getByRole('tab', { name: 'Identifiers', exact: true }).focus();
	await page.keyboard.press('ArrowRight');
	await expect(page.getByRole('tab', { name: 'Bibliography', exact: true })).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await expect(page.getByRole('heading', { name: 'Look up identifiers' })).not.toBeVisible();
	await page
		.getByRole('textbox', { name: 'Or paste bibliography data' })
		.fill('@article{x,title={Draft}}');
	await page.getByRole('tab', { name: 'PDFs', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Stage PDFs' })).toBeVisible();
	await page.getByRole('tab', { name: 'Identifiers', exact: true }).click();
	await expect(page.getByRole('textbox', { name: 'Identifiers', exact: true })).toHaveValue(
		'10.1000/first\nISBN:0674016394'
	);
	await page.getByRole('tab', { name: 'Bibliography', exact: true }).click();
	await expect(page.getByRole('textbox', { name: 'Or paste bibliography data' })).toHaveValue(
		'@article{x,title={Draft}}'
	);
});

test('manual Import mounts the schema editor on first activation and retains its draft', async ({
	page
}) => {
	await mockSession(page);
	let schemaRequests = 0;
	page.on('request', (request) => {
		if (request.url().endsWith('/metadata/schema')) schemaRequests += 1;
	});
	await page.goto('/workspace/workspace-1/import');
	await expect(page.getByRole('button', { name: /^PDF files / })).not.toBeVisible();
	await expect(page.getByRole('combobox', { name: 'Data source' })).toBeEnabled();
	expect(schemaRequests).toBe(0);
	await page.getByRole('tab', { name: 'PDFs', exact: true }).click();
	await expect(page.getByRole('button', { name: /^PDF files / })).toBeVisible();
	expect(schemaRequests).toBe(0);
	await page.getByRole('tab', { name: 'Manual creation', exact: true }).click();
	const title = page.getByLabel('Title', { exact: true });
	await title.fill('Manual draft');
	expect(schemaRequests).toBe(1);
	await page.getByRole('tab', { name: 'Identifiers', exact: true }).click();
	await page.getByRole('tab', { name: 'Manual creation', exact: true }).click();
	await expect(title).toHaveValue('Manual draft');
	expect(schemaRequests).toBe(1);
});

test('identifier Import sends one batch and displays partial failures', async ({ page }) => {
	await mockSession(page);
	let body: unknown;
	const preview = {
		id: 'batch-identifiers',
		file_format: 'metadata',
		status: 'ready',
		workflow_id: null,
		records: [{ metadata: { id: 'urn:uuid:test', type: 'Book', title: 'Imported book' } }],
		errors: [
			{
				row: 2,
				identifier: 'invalid',
				severity: 'error',
				code: 'invalid_identifier',
				message: 'Unrecognized identifier'
			}
		]
	};
	await page.route('**/api/v1/workspaces/workspace-1/imports/identifiers', (route) => {
		body = route.request().postDataJSON();
		return route.fulfill({ status: 201, json: preview });
	});
	await page.route('**/api/v1/workspaces/workspace-1/imports/batch-identifiers', (route) =>
		route.fulfill({ json: route.request().method() === 'DELETE' ? { ok: true } : preview })
	);
	await page.goto('/workspace/workspace-1/import');
	await page
		.getByRole('textbox', { name: 'Identifiers', exact: true })
		.fill(' ISBN:0674016394 \n\ninvalid');
	await page.getByRole('button', { name: 'Preview metadata' }).click();
	await expect
		.poll(() => body)
		.toEqual({ identifiers: ['ISBN:0674016394', 'invalid'], provider: 'auto' });
	await expect(page.getByText('Imported book', { exact: true })).toBeVisible();
	await expect(page.getByText('Unrecognized identifier', { exact: true })).toBeVisible();
	await expect(page.getByText('invalid', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: importButtonName })).toBeEnabled();
	await expect(page.getByRole('button', { name: 'Preview metadata' })).toHaveCount(0);
	await expect(page).toHaveURL(/\?batch=batch-identifiers$/);
	await page.reload();
	await expect(page.getByText('Imported book', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Discard', exact: true }).click();
	await expect(page).toHaveURL(/\/import$/);
	await expect(page.getByRole('heading', { name: 'Import preview' })).toHaveCount(0);
	await page.getByRole('textbox', { name: 'Identifiers', exact: true }).fill('42');
	await expect(page.getByRole('button', { name: 'Preview metadata' })).toBeEnabled();
});

test('bibliography Import submits pasted content with automatic format detection', async ({
	page
}) => {
	await mockSession(page);
	let body = '';
	await page.route('**/api/v1/workspaces/workspace-1/imports/bibliography', (route) => {
		body = route.request().postData() ?? '';
		return route.fulfill({
			status: 201,
			json: {
				id: 'batch-bibliography',
				file_format: 'bibtex',
				status: 'ready',
				workflow_id: null,
				records: [],
				errors: [{ severity: 'error', message: 'Invalid record' }]
			}
		});
	});
	await page.goto('/workspace/workspace-1/import');
	await page.getByRole('tab', { name: 'Bibliography', exact: true }).click();
	await page
		.getByRole('textbox', { name: 'Or paste bibliography data' })
		.fill('@article{x,title={Pasted record}}');
	await page.getByRole('button', { name: 'Preview bibliography' }).click();
	await expect.poll(() => body).toContain('@article{x,title={Pasted record}}');
	expect(body).toContain('name="file_format"\r\n\r\nauto');
	await expect(page.getByRole('button', { name: importButtonName })).toBeDisabled();
});

for (const source of ['bibliography', 'pdfs'] as const) {
	test(`${source} Import retires file selections when returning from a preview`, async ({
		page
	}) => {
		await mockSession(page);
		const bibliography = source === 'bibliography';
		const sourceName = bibliography ? 'Bibliography' : 'PDFs';
		const submitName = bibliography ? 'Preview bibliography' : 'Stage PDFs';
		const filename = bibliography ? 'previous.bib' : 'previous.pdf';
		const draft = '@article{draft,title={Unsaved bibliography draft}}';
		const newContent = '@article{new,title={New pasted bibliography}}';
		const nextId = '10000000-0000-4000-8000-000000000002';
		const previews = [batchId, nextId].map((id) =>
			importBatch({ id, file_format: bibliography ? 'bibtex' : 'pdf' })
		);
		const uploadBodies: string[] = [];
		await page.route(`**/api/v1/workspaces/workspace-1/imports/${source}`, (route) => {
			uploadBodies.push(route.request().postData() ?? '');
			return route.fulfill({
				status: bibliography ? 201 : 202,
				json: previews[uploadBodies.length - 1]
			});
		});
		for (const preview of previews) {
			await page.route(`**/api/v1/workspaces/workspace-1/imports/${preview.id}`, (route) =>
				route.fulfill({ json: preview })
			);
		}
		await page.goto(importPath);
		await page.getByRole('tab', { name: sourceName, exact: true }).click();
		if (bibliography) {
			await page.getByRole('textbox', { name: 'Or paste bibliography data' }).fill(draft);
		}
		const input = page.locator(`input[name="${source}"]`);
		await input.setInputFiles({
			name: filename,
			mimeType: bibliography ? 'text/plain' : 'application/pdf',
			buffer: Buffer.from(bibliography ? '@article{old,title={Previous file}}' : '%PDF-1.4 old')
		});
		await expect(page.getByText(filename, { exact: true })).toBeVisible();
		await page.getByRole('tab', { name: 'Identifiers', exact: true }).click();
		await page.getByRole('tab', { name: sourceName, exact: true }).click();
		await expect(page.getByText(filename, { exact: true })).toBeVisible();
		await page.getByRole('button', { name: submitName, exact: true }).click();
		await expect(page).toHaveURL(`${importPath}?batch=${batchId}`);
		await expect(page.getByText('Imported reference 1', { exact: true })).toBeVisible();
		expect(uploadBodies[0]).toContain(filename);
		await page.getByRole('button', { name: 'New import', exact: true }).click();
		await expect(page).toHaveURL(importPath);
		await expect(page.getByText(filename, { exact: true })).toHaveCount(0);
		await expect(input).toHaveJSProperty('value', '');
		if (bibliography) {
			const pasted = page.getByRole('textbox', { name: 'Or paste bibliography data' });
			await expect(pasted).toBeVisible();
			await expect(pasted).toHaveValue(draft);
			await pasted.fill(newContent);
		} else {
			await expect(page.getByRole('button', { name: submitName, exact: true })).toBeDisabled();
			await input.setInputFiles({
				name: 'new.pdf',
				mimeType: 'application/pdf',
				buffer: Buffer.from('%PDF-1.4 new')
			});
		}
		await page.getByRole('button', { name: submitName, exact: true }).click();
		await expect(page).toHaveURL(`${importPath}?batch=${nextId}`);
		expect(uploadBodies).toHaveLength(2);
		expect(uploadBodies[1]).not.toContain(filename);
		expect(uploadBodies[1]).toContain(bibliography ? newContent : 'new.pdf');
	});
}

test('pending PDF imports refresh until they can be committed', async ({ page }) => {
	await mockSession(page);
	let previewRequests = 0;
	await page.route('**/api/v1/workspaces/workspace-1/imports/pdfs', (route) =>
		route.fulfill({
			status: 202,
			json: { id: 'batch-1', status: 'pending', workflow_id: 'workflow-1', records: [], errors: [] }
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/imports/batch-1', (route) => {
		previewRequests += 1;
		return route.fulfill({
			json: {
				id: 'batch-1',
				status: previewRequests > 1 ? 'ready' : 'pending',
				workflow_id: 'workflow-1',
				records:
					previewRequests > 1
						? [
								{
									metadata: {
										id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
										type: 'Other',
										title: 'Imported PDF',
										contributors: [
											{
												type: 'Person',
												person: {
													name: 'Ada Lovelace',
													family_name: 'Lovelace',
													given_name: 'Ada'
												},
												roles: ['Author']
											},
											{
												type: 'Organization',
												organization: { name: 'World Health Organization' },
												roles: ['Author']
											}
										]
									},
									source: { original_name: 'paper.pdf', size: 9 }
								}
							]
						: [],
				errors: []
			}
		});
	});
	let workflowReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/workflows/workflow-1', (route) => {
		workflowReads += 1;
		return route.fulfill({
			json: {
				id: 'workflow-1',
				state: workflowReads > 1 ? 'succeeded' : 'running',
				error: null
			}
		});
	});

	await page.goto('/workspace/workspace-1/import');
	await page.getByRole('tab', { name: 'PDFs', exact: true }).click();
	await page.locator('input[name="pdfs"]').setInputFiles({
		name: 'paper.pdf',
		mimeType: 'application/pdf',
		buffer: Buffer.from('%PDF-1.4\n')
	});
	await page.getByRole('button', { name: 'Stage PDFs' }).click();

	await expect.poll(() => previewRequests, { timeout: 5_000 }).toBeGreaterThan(1);
	await expect(page.getByRole('button', { name: importButtonName })).toBeEnabled();
	await expect(page.getByText('Imported PDF')).toBeVisible();
	await expect(page.getByText('Ada Lovelace; World Health Organization')).toBeVisible();
	await expect(
		page
			.locator('section')
			.filter({ has: page.getByRole('heading', { name: /Import preview/ }) })
			.getByText('paper.pdf', { exact: true })
	).toBeVisible();
});

test('shared pending Import previews poll the batch without actor-only workflow access', async ({
	page
}) => {
	await mockSession(page);
	let previewRequests = 0;
	let workflowRequests = 0;
	await page.route('**/api/v1/workspaces/workspace-1/imports/batch-shared', (route) => {
		previewRequests += 1;
		return route.fulfill({
			json: {
				id: 'batch-shared',
				file_format: 'pdf',
				status: previewRequests > 1 ? 'ready' : 'pending',
				workflow_id: null,
				records:
					previewRequests > 1
						? [
								{
									metadata: {
										id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
										type: 'Other',
										title: 'Shared imported PDF'
									}
								}
							]
						: [],
				errors: []
			}
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/workflows/*', (route) => {
		workflowRequests += 1;
		return route.fulfill({ status: 404, json: { code: 'resource_not_found' } });
	});

	await page.goto('/workspace/workspace-1/import?batch=batch-shared');

	await expect.poll(() => previewRequests, { timeout: 5_000 }).toBeGreaterThan(1);
	await expect(page.getByRole('button', { name: importButtonName })).toBeEnabled();
	await expect(page.getByText('Shared imported PDF')).toBeVisible();
	expect(workflowRequests).toBe(0);
});

for (const owned of [false, true]) {
	test(`${owned ? 'owned' : 'shared'} pending Import previews resume after a temporary refresh failure`, async ({
		page
	}) => {
		await mockSession(page);
		let reads = 0;
		const writes: string[] = [];
		await page.route('**/api/v1/workspaces/workspace-1/imports/batch-recover**', (route) => {
			if (route.request().method() !== 'GET') {
				writes.push(route.request().method());
				return route.fulfill({ status: 500, json: { code: 'internal_error' } });
			}
			reads++;
			if (reads === 2) return route.fulfill({ status: 500, json: { code: 'internal_error' } });
			return route.fulfill({
				json: {
					id: 'batch-recover',
					file_format: 'pdf',
					status: reads >= 4 ? 'ready' : 'pending',
					workflow_id: owned ? 'workflow-recover' : null,
					records:
						reads >= 4
							? [
									{
										metadata: {
											id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
											type: 'Other',
											title: 'Recovered imported PDF'
										}
									}
								]
							: [],
					errors: []
				}
			});
		});
		await page.route('**/api/v1/workspaces/workspace-1/workflows/workflow-recover', (route) =>
			route.fulfill({ json: { id: 'workflow-recover', state: 'succeeded', error: null } })
		);
		await page.goto('/workspace/workspace-1/import?batch=batch-recover');
		await expect(page.getByRole('heading', { name: /Import preview/ })).toBeVisible();
		await expect(page.getByRole('main').getByRole('alert')).toBeVisible();
		await expect(page.getByRole('button', { name: importButtonName })).toBeDisabled();
		await page.getByRole('button', { name: 'Retry', exact: true }).click();
		await expect(page.getByRole('button', { name: importButtonName })).toBeEnabled();
		await expect(page.getByText('Recovered imported PDF', { exact: true })).toBeVisible();
		await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
		await expect(page).toHaveURL(/batch=batch-recover/);
		expect(writes).toEqual([]);
	});
}

test('PDF import accumulates and deduplicates repeated file selections', async ({ page }) => {
	await mockSession(page);
	let uploadBody = '';
	await page.route('**/api/v1/workspaces/workspace-1/imports/pdfs', (route) => {
		uploadBody = route.request().postData() ?? '';
		return route.fulfill({
			status: 202,
			json: { id: 'batch-files', status: 'ready', workflow_id: null, records: [], errors: [] }
		});
	});
	await page.goto('/workspace/workspace-1/import');
	await page.getByRole('tab', { name: 'PDFs', exact: true }).click();
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

test('Import preview paginates restored batches', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/imports/batch-many', (route) =>
		route.fulfill({
			json: {
				id: 'batch-many',
				status: 'ready',
				workflow_id: null,
				records: Array.from({ length: 21 }, (_, index) => ({
					metadata: {
						id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
						type: 'Other',
						title: `Record ${index + 1}`
					}
				})),
				errors: []
			}
		})
	);

	await page.goto('/workspace/workspace-1/import?batch=batch-many');
	await expect(page.getByText('Record 1', { exact: true })).toBeVisible();
	await expect(page.getByText('Record 21', { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Next page' }).click();
	await expect(page.getByText('Record 21', { exact: true })).toBeVisible();
});

test('committing an Import opens its Library scope for preview, filtering and bulk organization', async ({
	page
}) => {
	await page.setViewportSize({ width: 1440, height: 1000 });
	await mockSession(page);
	const { reads, mutations } = await mockImportedLibrary(page);
	let batch = importBatch();
	let commits = 0;
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) =>
		route.fulfill({ json: batch })
	);
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}/commit`, (route) => {
		commits += 1;
		batch = importBatch({ status: 'committed', committed_item_ids: importedIds });
		return route.fulfill({ json: batch });
	});
	await page.goto(`${importPath}?batch=${batchId}`);
	await page.getByRole('button', { name: 'Import 2 records', exact: true }).click();
	await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	await expect(page.getByText('Earlier Library reference', { exact: true })).toHaveCount(0);
	const scope = page.getByRole('group', { name: 'Applied filters', exact: true });
	await expect(scope.getByRole('link', { name: 'Import Batch', exact: true })).toHaveAttribute(
		'href',
		`${importPath}?batch=${batchId}`
	);
	await page.getByRole('button', { name: 'Preview Item 1', exact: true }).click();
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await expect(preview.getByRole('heading', { name: 'Imported reference 1' })).toBeVisible();
	await preview.getByRole('link', { name: 'Import Journal', exact: true }).click();
	await expect(page).toHaveURL(/publication_title=Import\+Journal/);
	await expect.poll(() => reads.at(-1)?.searchParams.get('import_batch')).toBe(batchId);
	await page.getByRole('combobox', { name: 'Sort By', exact: true }).selectOption('title');
	await expect(page).toHaveURL(/sort=title/);
	const details = preview.getByRole('link', { name: 'Open full details', exact: true });
	const destination = new URL((await details.getAttribute('href'))!, page.url());
	const returnTo = destination.searchParams.get('return_to')!;
	const returnUrl = new URL(`/${returnTo}`, page.url());
	expect(returnUrl.searchParams.get('import_batch')).toBe(batchId);
	expect(returnUrl.searchParams.get('publication_title')).toBe('Import Journal');
	expect(returnUrl.searchParams.get('sort')).toBe('title');
	expect(returnUrl.searchParams.get('preview')).toBe(importedIds[0]);
	await details.click();
	await expect(page.getByRole('heading', { level: 1, name: 'Imported reference 1' })).toBeVisible();
	await page.getByRole('main').getByRole('link', { name: 'Library', exact: true }).click();
	await expect(page).toHaveURL(returnUrl.href);
	await page.getByRole('button', { name: 'Close preview', exact: true }).click();
	await page.getByLabel('Select this page', { exact: true }).check();
	await openLibraryAction(page, 'add_tag');
	await chooseSearchOption(page, 'Select Tag', 'Imported reading');
	await page
		.getByRole('dialog', { name: 'Add Tag', exact: true })
		.getByRole('button', { name: 'Add Tag', exact: true })
		.click();
	await expect(page.getByText('Bulk action completed', { exact: true })).toBeVisible();
	expect(mutations).toEqual([
		{ action: 'add_tag', item_ids: importedIds, tag_name: 'Imported reading' }
	]);
	expect(commits).toBe(1);
	expect(reads.every((url) => url.searchParams.get('import_batch') === batchId)).toBe(true);
	await scope.getByRole('link', { name: 'Import Batch', exact: true }).click();
	await expect(page.getByText('Imported 2 records', { exact: true })).toBeVisible();
	await expect(
		page.getByRole('link', { name: 'View imported Items', exact: true })
	).toHaveAttribute('href', `${libraryPath}?import_batch=${batchId}`);
});

test('a lost Import commit response recovers the committed batch without replaying its POST', async ({
	page
}) => {
	await mockSession(page);
	await mockImportedLibrary(page);
	let committed = false;
	let commits = 0;
	let recoveryReads = 0;
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) => {
		if (committed) recoveryReads += 1;
		return route.fulfill({
			json: importBatch(committed ? { status: 'committed', committed_item_ids: importedIds } : {})
		});
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}/commit`, (route) => {
		commits += 1;
		committed = true;
		return route.abort('failed');
	});
	await page.goto(`${importPath}?batch=${batchId}`);
	await page.getByRole('button', { name: 'Import 2 records', exact: true }).click();
	await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	expect(commits).toBe(1);
	expect(recoveryReads).toBeGreaterThan(0);
	await page.goto(`${importPath}?batch=${batchId}`);
	await page.reload();
	await expect(page.getByText('Imported 2 records', { exact: true })).toBeVisible();
	await expect(page.getByRole('button', { name: importButtonName })).toHaveCount(0);
	await page.getByRole('link', { name: 'View imported Items', exact: true }).click();
	await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
	expect(commits).toBe(1);
});

test('an uncertain Import commit checks status before making any further write', async ({
	page
}) => {
	await mockSession(page);
	await mockImportedLibrary(page);
	let committed = false;
	let readable = true;
	let commits = 0;
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) =>
		readable
			? route.fulfill({
					json: importBatch(
						committed ? { status: 'committed', committed_item_ids: importedIds } : {}
					)
				})
			: route.fulfill({ status: 503, json: { code: 'unavailable' } })
	);
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}/commit`, (route) => {
		commits += 1;
		committed = true;
		readable = false;
		return route.abort('failed');
	});
	await page.goto(`${importPath}?batch=${batchId}`);
	await page.getByRole('button', { name: 'Import 2 records', exact: true }).click();
	const check = page.getByRole('button', { name: 'Check import status', exact: true });
	await expect(check).toBeEnabled();
	await expect(page.getByRole('button', { name: importButtonName })).toBeDisabled();
	readable = true;
	await check.click();
	await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
	expect(commits).toBe(1);
});

test('Import status recovery can replace an unavailable preview after a lost commit response', async ({
	page
}) => {
	await mockSession(page);
	await mockImportedLibrary(page);
	let commits = 0;
	let recoveryReads = 0;
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) => {
		if (commits === 0) return route.fulfill({ json: importBatch() });
		recoveryReads += 1;
		return recoveryReads === 1
			? route.fulfill({ status: 403, json: { code: 'permission_denied' } })
			: route.fulfill({
					json: importBatch({ status: 'committed', committed_item_ids: importedIds })
				});
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}/commit`, (route) => {
		commits += 1;
		return route.abort('failed');
	});
	await page.goto(`${importPath}?batch=${batchId}`);
	await page.getByRole('button', { name: 'Import 2 records', exact: true }).click();
	const check = page.getByRole('button', { name: 'Check import status', exact: true });
	await expect(check).toBeEnabled();
	await expect(page).toHaveURL(`${importPath}?batch=${batchId}`);
	await expect(page.getByRole('heading', { name: 'Import preview' })).toHaveCount(0);
	await expect(page.getByRole('button', { name: importButtonName })).toHaveCount(0);
	expect(recoveryReads).toBe(1);
	await check.click();
	await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	expect(recoveryReads).toBe(2);
	expect(commits).toBe(1);
});

test('a lost commit response reconciles its captured batch after navigation without redirecting the new batch', async ({
	page
}) => {
	await mockSession(page);
	const otherId = '10000000-0000-4000-8000-000000000002';
	const release = Promise.withResolvers<void>();
	const recovered = Promise.withResolvers<void>();
	let committed = false;
	let commits = 0;
	let recoveryReads = 0;
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, async (route) => {
		if (committed) recoveryReads += 1;
		await route.fulfill({
			json: importBatch(committed ? { status: 'committed', committed_item_ids: importedIds } : {})
		});
		if (committed) recovered.resolve();
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}/commit`, async (route) => {
		commits += 1;
		await release.promise;
		committed = true;
		await route.abort('failed');
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${otherId}`, (route) =>
		route.fulfill({
			json: importBatch({
				id: otherId,
				records: [
					{
						metadata: {
							id: 'urn:uuid:20000000-0000-4000-8000-000000000004',
							type: 'Book',
							title: 'Another batch in progress'
						}
					}
				]
			})
		})
	);
	try {
		await page.goto(`${importPath}?batch=${batchId}`);
		await page.getByRole('button', { name: 'Import 2 records', exact: true }).click();
		await expect.poll(() => commits).toBe(1);
		await navigateToBatch(page, otherId);
		await expect(page.getByText('Another batch in progress', { exact: true })).toBeVisible();
		release.resolve();
		await expect.poll(() => recoveryReads).toBe(1);
		await recovered.promise;
		await page.evaluate(
			() =>
				new Promise<void>((resolve) =>
					requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
				)
		);
		await expect(page).toHaveURL(`${importPath}?batch=${otherId}`);
		await expect(page.getByText('Another batch in progress', { exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Import 1 record', exact: true })).toBeEnabled();
		await page.goBack();
		await expect(page).toHaveURL(`${importPath}?batch=${batchId}`);
		await expect(page.getByText('Imported 2 records', { exact: true })).toBeVisible();
		expect(commits).toBe(1);
	} finally {
		release.resolve();
	}
});

test('a late Import creation response cannot replace a committed receipt opened through history', async ({
	page
}) => {
	await mockSession(page);
	await mockImportedLibrary(page);
	const release = Promise.withResolvers<void>();
	const responded = Promise.withResolvers<void>();
	const readyBatch = importBatch();
	let batch = readyBatch;
	let creations = 0;
	let commits = 0;
	let previewReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/imports/identifiers', async (route) => {
		creations += 1;
		await release.promise;
		await route.fulfill({ status: 201, json: readyBatch });
		responded.resolve();
	});
	await page.route('**/api/v1/workspaces/workspace-1/imports?*', (route) => {
		const completed = new URL(route.request().url()).searchParams.get('view') === 'completed';
		return route.fulfill({
			json: directoryPage(
				creations > 0 && completed === (batch.status === 'committed')
					? [
							{
								id: batchId,
								file_format: batch.file_format,
								status: batch.status,
								created_at: batch.created_at,
								record_count: 2,
								diagnostic_count: 0
							}
						]
					: [],
				route
			)
		});
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) => {
		previewReads += 1;
		return route.fulfill({ json: batch });
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}/commit`, (route) => {
		commits += 1;
		batch = importBatch({ status: 'committed', committed_item_ids: importedIds });
		return route.fulfill({ json: batch });
	});
	try {
		await page.goto(importPath);
		await page.getByRole('textbox', { name: 'Identifiers', exact: true }).fill('ISBN:0674016394');
		await page.getByRole('button', { name: 'Preview metadata', exact: true }).click();
		await expect.poll(() => creations).toBe(1);
		await page.getByRole('link', { name: 'Import history', exact: true }).click();
		await expect(page).toHaveURL(importHistoryPath);
		await page
			.locator(`[data-import-batch="${batchId}"]`)
			.getByRole('link', { name: 'Open import', exact: true })
			.click();
		await expect(page.getByText('Imported reference 1', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Import 2 records', exact: true }).click();
		await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
		await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
		expect(commits).toBe(1);
		release.resolve();
		await responded.promise;
		await page.evaluate(
			() =>
				new Promise<void>((resolve) =>
					requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
				)
		);
		await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
		await navigateToBatch(page, batchId);
		await expect(page).toHaveURL(`${importPath}?batch=${batchId}`);
		await expect(page.getByText('Imported 2 records', { exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: importButtonName })).toHaveCount(0);
		await expect(page.getByText('Imported reference 1', { exact: true })).toHaveCount(0);
		await expect(page.getByText('Imported reference 2', { exact: true })).toHaveCount(0);
		await expect(
			page.getByRole('link', { name: 'View imported Items', exact: true })
		).toHaveAttribute('href', `${libraryPath}?import_batch=${batchId}`);
		// A fresh read must not conceal the late response overwriting the warm committed cache.
		expect(previewReads).toBe(1);
		expect(creations).toBe(1);
		expect(commits).toBe(1);
	} finally {
		release.resolve();
	}
});

for (const command of ['commit', 'retry'] as const) {
	test(`a late Import ${command} response cannot restore a batch deleted from history`, async ({
		page
	}) => {
		await mockSession(page);
		const release = Promise.withResolvers<void>();
		const responded = Promise.withResolvers<void>();
		let batch = importBatch(command === 'retry' ? { status: 'failed', records: [] } : {});
		let removed = false;
		let commands = 0;
		let deletes = 0;
		let previewReads = 0;
		await page.route('**/api/v1/workspaces/workspace-1/imports?*', (route) =>
			route.fulfill({
				json: directoryPage(
					removed
						? []
						: [
								{
									id: batchId,
									file_format: batch.file_format,
									status: batch.status,
									created_at: batch.created_at,
									record_count: 2,
									diagnostic_count: 0
								}
							],
					route
				)
			})
		);
		await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) => {
			if (route.request().method() === 'DELETE') {
				deletes += 1;
				removed = true;
				return route.fulfill({ status: 204 });
			}
			previewReads += 1;
			return removed
				? route.fulfill({
						status: 404,
						json: { code: 'import_batch_unavailable', message: 'Import Batch not found' }
					})
				: route.fulfill({ json: batch });
		});
		await page.route(
			`**/api/v1/workspaces/workspace-1/imports/${batchId}/${command}`,
			async (route) => {
				commands += 1;
				batch = importBatch(
					command === 'commit'
						? { status: 'committed', committed_item_ids: importedIds }
						: { status: 'pending', records: [] }
				);
				await release.promise;
				await route.fulfill({ status: command === 'commit' ? 200 : 202, json: batch });
				responded.resolve();
			}
		);
		const historyQuery = command === 'commit' ? '&view=completed' : '';
		const historyUrl = `${importHistoryPath}${command === 'commit' ? '?view=completed' : ''}`;
		try {
			await page.goto(`${importPath}?batch=${batchId}&from=history${historyQuery}`);
			await page
				.getByRole('button', {
					name: command === 'commit' ? 'Import 2 records' : 'Retry',
					exact: true
				})
				.click();
			await expect.poll(() => commands).toBe(1);
			await page.getByRole('button', { name: 'Back to import history', exact: true }).click();
			await expect(page).toHaveURL(historyUrl);
			const row = page.locator(`[data-import-batch="${batchId}"]`);
			await row
				.getByRole('button', {
					name: command === 'commit' ? 'Delete import record' : 'Discard',
					exact: true
				})
				.click();
			await expect(row).toHaveCount(0);
			expect(deletes).toBe(1);
			release.resolve();
			await responded.promise;
			await page.evaluate(
				() =>
					new Promise<void>((resolve) =>
						requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
					)
			);
			await expect(page).toHaveURL(historyUrl);
			expect(previewReads).toBe(1);
			await navigateToBatch(page, batchId);
			await expect(page).toHaveURL(`${importPath}?batch=${batchId}`);
			await page.evaluate(
				() =>
					new Promise<void>((resolve) =>
						requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
					)
			);
			// Check before the pending-batch polling interval could conceal a restored cache.
			expect(previewReads).toBe(2);
			await expect(page.getByRole('main').getByRole('alert')).toContainText(
				'The requested resource was not found.'
			);
			await expect(page.getByRole('heading', { name: 'Import preview' })).toHaveCount(0);
			await expect(page.getByText('Imported 2 records', { exact: true })).toHaveCount(0);
			await expect(page.getByText('Preparing uploaded PDFs…', { exact: true })).toHaveCount(0);
			expect(commands).toBe(1);
		} finally {
			release.resolve();
		}
	});
}

test('a late Import commit response preserves lost receipt deletion recovery', async ({ page }) => {
	await mockSession(page);
	const releaseCommit = Promise.withResolvers<void>();
	const commitResponded = Promise.withResolvers<void>();
	const recoveryStarted = Promise.withResolvers<void>();
	const releaseRecovery = Promise.withResolvers<void>();
	const recoveryResponded = Promise.withResolvers<void>();
	const refreshStarted = Promise.withResolvers<void>();
	const releaseRefreshes = Promise.withResolvers<void>();
	const historyUrl = `${importHistoryPath}?view=completed`;
	let batch = importBatch();
	let removed = false;
	let commits = 0;
	let deletes = 0;
	let previewReads = 0;
	let directoryReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/imports?*', async (route) => {
		directoryReads += 1;
		if (directoryReads > 1) {
			refreshStarted.resolve();
			await releaseRefreshes.promise;
		}
		await route.fulfill({
			json: directoryPage(
				removed
					? []
					: [
							{
								id: batchId,
								file_format: batch.file_format,
								status: batch.status,
								created_at: batch.created_at,
								record_count: 2,
								diagnostic_count: 0
							}
						],
				route
			)
		});
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, async (route) => {
		if (route.request().method() === 'DELETE') {
			deletes += 1;
			removed = true;
			await route.abort('failed');
			return;
		}
		previewReads += 1;
		if (!removed) {
			await route.fulfill({ json: batch });
			return;
		}
		if (previewReads === 2) {
			recoveryStarted.resolve();
			await releaseRecovery.promise;
		}
		await route.fulfill({
			status: 404,
			json: { code: 'import_batch_unavailable', message: 'Import Batch not found' }
		});
		if (previewReads === 2) recoveryResponded.resolve();
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}/commit`, async (route) => {
		commits += 1;
		batch = importBatch({ status: 'committed', committed_item_ids: importedIds });
		await releaseCommit.promise;
		await route.fulfill({ json: batch });
		commitResponded.resolve();
	});
	try {
		await page.goto(`${importPath}?batch=${batchId}&from=history&view=completed`);
		await page.getByRole('button', { name: 'Import 2 records', exact: true }).click();
		await expect.poll(() => commits).toBe(1);
		await page.getByRole('button', { name: 'Back to import history', exact: true }).click();
		await expect(page).toHaveURL(historyUrl);
		const row = page.locator(`[data-import-batch="${batchId}"]`);
		const remove = row.getByRole('button', { name: 'Delete import record', exact: true });
		await remove.click();
		await recoveryStarted.promise;
		expect(deletes).toBe(1);
		expect(previewReads).toBe(2);
		releaseCommit.resolve();
		await commitResponded.promise;
		// The refresh proves the command response ran; hold it so an empty list cannot hide a failure.
		await refreshStarted.promise;
		await page.evaluate(
			() =>
				new Promise<void>((resolve) =>
					requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
				)
		);
		await expect(page).toHaveURL(historyUrl);
		await expect(remove).toBeDisabled();
		await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
		releaseRecovery.resolve();
		await recoveryResponded.promise;
		releaseRefreshes.resolve();
		await expect(row).toHaveCount(0);
		await expect(page.getByRole('main').getByRole('alert')).toHaveCount(0);
		expect(previewReads).toBe(2);
		await navigateToBatch(page, batchId);
		await expect(page.getByRole('main').getByRole('alert')).toContainText(
			'The requested resource was not found.'
		);
		expect(previewReads).toBe(3);
		await expect(page.getByRole('heading', { name: 'Import preview' })).toHaveCount(0);
		await expect(page.getByText('Imported 2 records', { exact: true })).toHaveCount(0);
		expect(commits).toBe(1);
		expect(deletes).toBe(1);
	} finally {
		releaseCommit.resolve();
		releaseRecovery.resolve();
		releaseRefreshes.resolve();
	}
});

test('same-page Import batch navigation and Back ignore a slow older preview response', async ({
	page
}) => {
	await mockSession(page);
	const otherId = '10000000-0000-4000-8000-000000000002';
	const release = Promise.withResolvers<void>();
	let reads = 0;
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, async (route) => {
		reads += 1;
		if (reads === 1) await release.promise;
		return route.fulfill({ json: importBatch() });
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${otherId}`, (route) =>
		route.fulfill({
			json: importBatch({
				id: otherId,
				records: [
					{
						metadata: {
							id: 'urn:uuid:20000000-0000-4000-8000-000000000004',
							type: 'Book',
							title: 'Current batch reference'
						}
					}
				]
			})
		})
	);
	try {
		await page.goto(`${importPath}?batch=${batchId}`);
		await expect.poll(() => reads).toBe(1);
		await navigateToBatch(page, otherId);
		await expect(page.getByText('Current batch reference', { exact: true })).toBeVisible();
		release.resolve();
		await page.evaluate(
			() =>
				new Promise<void>((resolve) =>
					requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
				)
		);
		await expect(page).toHaveURL(`${importPath}?batch=${otherId}`);
		await expect(page.getByText('Imported reference 1', { exact: true })).toHaveCount(0);
		await page.goBack();
		await expect(page).toHaveURL(`${importPath}?batch=${batchId}`);
		await expect(page.getByText('Imported reference 1', { exact: true })).toBeVisible();
		await expect(page.getByText('Current batch reference', { exact: true })).toHaveCount(0);
	} finally {
		release.resolve();
	}
});

test('failed PDF processing retries its staged batch and commits the ready result', async ({
	page
}) => {
	await mockSession(page);
	await mockImportedLibrary(page);
	let batch = importBatch({
		file_format: 'pdf',
		status: 'failed',
		records: [],
		errors: [{ severity: 'error', message: 'PDF metadata service temporarily unavailable' }]
	});
	const writes: string[] = [];
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) =>
		route.fulfill({ json: batch })
	);
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}/retry`, (route) => {
		writes.push('retry');
		const pending = importBatch({ file_format: 'pdf', status: 'pending', records: [] });
		batch = importBatch({
			file_format: 'pdf',
			records: importBatch().records.map((record) => ({
				...record,
				source: { original_name: 'staged-paper.pdf', size: 9 }
			}))
		});
		return route.fulfill({ status: 202, json: pending });
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}/commit`, (route) => {
		writes.push('commit');
		batch = importBatch({
			file_format: 'pdf',
			status: 'committed',
			committed_item_ids: importedIds
		});
		return route.fulfill({ json: batch });
	});
	await page.goto(`${importPath}?batch=${batchId}`);
	await expect(page.getByText('PDF metadata service temporarily unavailable')).toBeVisible();
	await expect(page.getByRole('button', { name: importButtonName })).toBeDisabled();
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByText('staged-paper.pdf', { exact: true })).toHaveCount(2);
	await page.getByRole('button', { name: 'Import 2 records', exact: true }).click();
	await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	expect(writes).toEqual(['retry', 'commit']);
});

test('pending PDF processing survives leaving and reload with a Workflow link to its batch', async ({
	page
}) => {
	await mockSession(page);
	await mockImportedLibrary(page);
	const workflowId = '30000000-0000-4000-8000-000000000001';
	let ready = false;
	let uploads = 0;
	let workflowReads = 0;
	const batch = () =>
		importBatch({
			file_format: 'pdf',
			status: ready ? 'ready' : 'pending',
			workflow_id: workflowId,
			records: ready ? importBatch().records : []
		});
	await page.route('**/api/v1/workspaces/workspace-1/imports/pdfs', (route) => {
		uploads += 1;
		return route.fulfill({ status: 202, json: batch() });
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) =>
		route.fulfill({ json: batch() })
	);
	await page.route(`**/api/v1/workspaces/workspace-1/workflows/${workflowId}`, (route) => {
		workflowReads += 1;
		return route.fulfill({
			json: { id: workflowId, state: ready ? 'succeeded' : 'running', error: null }
		});
	});
	await page.goto(importPath);
	await page.getByRole('tab', { name: 'PDFs', exact: true }).click();
	await page.locator('input[name="pdfs"]').setInputFiles({
		name: 'background-paper.pdf',
		mimeType: 'application/pdf',
		buffer: Buffer.from('%PDF-1.4\n')
	});
	await page.getByRole('button', { name: 'Stage PDFs', exact: true }).click();
	await expect(
		page.getByRole('button', { name: 'Background tasks (1)', exact: true })
	).toBeVisible();
	await page
		.getByRole('navigation', { name: 'Main navigation', exact: true })
		.getByRole('link', { name: 'Library', exact: true })
		.click();
	await expect(page).toHaveURL(libraryPath);
	await page.reload();
	await page.getByRole('button', { name: 'Background tasks (1)', exact: true }).click();
	const openBatch = page.getByRole('link', { name: 'View import', exact: true });
	await expect(openBatch).toHaveAttribute('href', `${importPath}?batch=${batchId}`);
	ready = true;
	await openBatch.click();
	await expect(page).toHaveURL(`${importPath}?batch=${batchId}`);
	await expect(page.getByRole('button', { name: 'Import 2 records', exact: true })).toBeEnabled();
	await page.getByRole('button', { name: 'Background tasks (1)', exact: true }).click();
	await expect(page.getByText('succeeded', { exact: true })).toBeVisible();
	await page.keyboard.press('Escape');
	await page
		.getByRole('navigation', { name: 'Main navigation', exact: true })
		.getByRole('link', { name: 'Library', exact: true })
		.click();
	const terminalReads = workflowReads;
	await page.reload();
	await page.getByRole('button', { name: 'Background tasks (1)', exact: true }).click();
	await expect(openBatch).toHaveAttribute('href', `${importPath}?batch=${batchId}`);
	await expect(page.getByText('succeeded', { exact: true })).toBeVisible();
	expect(workflowReads).toBe(terminalReads);
	expect(uploads).toBe(1);
});

test('Chinese Import preview fits a 375px dark screen and keeps its primary action usable', async ({
	page
}) => {
	await page.setViewportSize({ width: 375, height: 812 });
	await mockSession(page);
	await mockImportedLibrary(page);
	await page.addInitScript(() => {
		localStorage.setItem('quirebase:locale', 'zh-CN');
		localStorage.setItem('quirebase:theme', 'dark');
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) =>
		route.fulfill({
			json: importBatch({
				errors: [
					{
						severity: 'warning',
						row: 2,
						identifier: '10.1234/a-long-imported-source-identifier-without-whitespace',
						message: '该记录的出版日期尚不完整，请在导入后检查并补充。'
					}
				]
			})
		})
	);
	let commits = 0;
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}/commit`, (route) => {
		commits += 1;
		return route.fulfill({
			json: importBatch({ status: 'committed', committed_item_ids: importedIds })
		});
	});
	await page.goto(`${importPath}?batch=${batchId}`);
	await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	const apply = page.getByRole('button', { name: /导入.*2.*条/ });
	await expect(apply).toBeEnabled();
	await apply.scrollIntoViewIfNeeded();
	const bounds = (await apply.boundingBox())!;
	expect(bounds.x).toBeGreaterThanOrEqual(0);
	expect(bounds.x + bounds.width).toBeLessThanOrEqual(375);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
		true
	);
	await page.screenshot({
		path: '/private/tmp/quirebase-import-preview-375-zh-dark.png',
		fullPage: true
	});
	await apply.click();
	await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
	expect(commits).toBe(1);
});

test('Import history paginates both views and deleting a completed receipt preserves Library Items', async ({
	page
}) => {
	await mockSession(page);
	await mockImportedLibrary(page);
	type BatchSummary = components['schemas']['ImportBatchSummary'];
	const summaries = (completed: boolean): BatchSummary[] =>
		Array.from({ length: 21 }, (_, index) => ({
			id:
				completed && index === 0 ? batchId : `${completed ? 'completed' : 'pending'}-${index + 1}`,
			file_format: `${completed ? 'Completed' : 'Pending'} source ${index + 1}`,
			status: completed ? 'committed' : 'ready',
			created_at: '2026-10-21T00:00:00Z',
			record_count: 2,
			diagnostic_count: 0
		}));
	let receiptDeleted = false;
	let receiptDeletes = 0;
	const directoryReads: URL[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/imports?*', (route) => {
		const url = new URL(route.request().url());
		directoryReads.push(url);
		const rows = summaries(url.searchParams.get('view') === 'completed').filter(
			(row) => !receiptDeleted || row.id !== batchId
		);
		return route.fulfill({ json: directoryPage(rows, route) });
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) => {
		if (route.request().method() === 'DELETE') {
			receiptDeletes += 1;
			receiptDeleted = true;
			return route.fulfill({ status: 204 });
		}
		return receiptDeleted
			? route.fulfill({
					status: 404,
					json: { code: 'import_batch_unavailable', message: 'Import Batch not found' }
				})
			: route.fulfill({
					json: importBatch({ status: 'committed', committed_item_ids: importedIds })
				});
	});
	await page.goto(importPath);
	await expect(page.getByRole('tablist', { name: 'Import methods', exact: true })).toBeVisible();
	expect(directoryReads).toHaveLength(0);
	await page.getByRole('link', { name: 'Import history', exact: true }).click();
	await expect(page).toHaveURL(importHistoryPath);
	const pages = page.getByRole('navigation', { name: 'Import pages', exact: true });
	const pendingFirst = page.locator('a[href$="batch=pending-1"]');
	const pendingLast = page.locator('a[href$="batch=pending-21"]');
	await expect(pendingFirst).toBeVisible();
	await expect(pendingLast).toHaveCount(0);
	await pages.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(pendingLast).toBeVisible();
	await expect(pendingFirst).toHaveCount(0);
	await expect(pages).toContainText('Page 2 of 2');
	await page.getByRole('tab', { name: 'Completed imports', exact: true }).click();
	const openReceipt = page.locator(`a[href$="batch=${batchId}"]`);
	await expect(openReceipt).toBeVisible();
	await expect(pages).toContainText('Page 1 of 2');
	await pages.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(page.locator('a[href$="batch=completed-21"]')).toBeVisible();
	await pages.getByRole('button', { name: 'Previous page', exact: true }).click();
	await openReceipt.click();
	await expect(page.getByText('Imported 2 records', { exact: true })).toBeVisible();
	await page.getByRole('link', { name: 'View imported Items', exact: true }).click();
	await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	await page.getByRole('link', { name: 'Import Batch', exact: true }).click();
	await expect(page.getByRole('tablist', { name: 'Import methods', exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'New import', exact: true }).click();
	await page.getByRole('link', { name: 'Import history', exact: true }).click();
	await page.getByRole('tab', { name: 'Completed imports', exact: true }).click();
	await page
		.locator(`[data-import-batch="${batchId}"]`)
		.getByRole('button', { name: 'Delete import record', exact: true })
		.click();
	await expect(page).toHaveURL(`${importHistoryPath}?view=completed`);
	await expect(page.getByText('Completed source 2 · 2 records', { exact: true })).toBeVisible();
	await expect(openReceipt).toHaveCount(0);
	await page
		.getByRole('navigation', { name: 'Main navigation', exact: true })
		.getByRole('link', { name: 'Library', exact: true })
		.click();
	await expect(page.locator('[data-library-item-select]')).toHaveCount(3);
	await expect(page.getByText('Imported reference 1', { exact: true })).toBeVisible();
	await expect(page.getByText('Imported reference 2', { exact: true })).toBeVisible();
	await page.goto(`${importPath}?batch=${batchId}`);
	await expect(page.getByRole('main').getByRole('alert')).toContainText(
		'The requested resource was not found.'
	);
	await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeEnabled();
	await expect(page.getByText('Imported 2 records', { exact: true })).toHaveCount(0);
	expect(receiptDeletes).toBe(1);
	for (const view of ['pending', 'completed']) {
		expect(
			directoryReads.some(
				(url) => url.searchParams.get('view') === view && url.searchParams.get('offset') === '20'
			)
		).toBe(true);
	}
});

test('a lost receipt deletion response reconciles its inactive batch without redirecting the new batch', async ({
	page,
	context
}) => {
	await mockSession(page);
	const { reads } = await mockImportedLibrary(page);
	const otherId = '10000000-0000-4000-8000-000000000002';
	const release = Promise.withResolvers<void>();
	const recovered = Promise.withResolvers<void>();
	let receiptDeleted = false;
	let receiptDeletes = 0;
	let recoveryReads = 0;
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, async (route) => {
		if (route.request().method() === 'DELETE') {
			receiptDeletes += 1;
			await release.promise;
			receiptDeleted = true;
			await route.abort('failed');
			return;
		}
		if (receiptDeleted) {
			recoveryReads += 1;
			await route.fulfill({
				status: 404,
				json: { code: 'import_batch_unavailable', message: 'Import Batch not found' }
			});
			recovered.resolve();
		} else {
			await route.fulfill({
				json: importBatch({ status: 'committed', committed_item_ids: importedIds })
			});
		}
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${otherId}`, (route) =>
		route.fulfill({
			json: importBatch({
				id: otherId,
				records: [
					{
						metadata: {
							id: 'urn:uuid:20000000-0000-4000-8000-000000000004',
							type: 'Book',
							title: 'Another batch in progress'
						}
					}
				]
			})
		})
	);
	try {
		// Warm the Library module and receipt-scoped result cache before deleting.
		await page.goto(`${libraryPath}?import_batch=${batchId}`);
		await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
		await expect(page.getByText('Imported reference 1', { exact: true })).toBeVisible();
		await page.getByRole('link', { name: 'Import Batch', exact: true }).click();
		await expect(page.getByText('Imported 2 records', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Delete import record', exact: true }).click();
		await expect.poll(() => receiptDeletes).toBe(1);
		await navigateToBatch(page, otherId);
		await expect(page.getByText('Another batch in progress', { exact: true })).toBeVisible();
		release.resolve();
		await expect.poll(() => recoveryReads).toBe(1);
		await recovered.promise;
		await page.evaluate(
			() =>
				new Promise<void>((resolve) =>
					requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
				)
		);
		await expect(page).toHaveURL(`${importPath}?batch=${otherId}`);
		await expect(page.getByText('Another batch in progress', { exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Import 1 record', exact: true })).toBeEnabled();

		await context.setOffline(true);
		await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
		const readCount = reads.length;
		// Keep the same QueryClient: a document reload would discard the stale cache itself.
		await page.evaluate((href) => {
			const link = document.createElement('a');
			link.id = 'test-import-receipt-library-navigation';
			link.href = href;
			link.textContent = 'Open receipt Library results';
			document.querySelector('main')!.append(link);
		}, `${libraryPath}?import_batch=${batchId}`);
		await page.locator('#test-import-receipt-library-navigation').click();
		await page.evaluate(() =>
			document.getElementById('test-import-receipt-library-navigation')?.remove()
		);
		await expect(page).toHaveURL(`${libraryPath}?import_batch=${batchId}`);
		const results = page.locator('#library-results');
		const alert = results.getByRole('alert');
		await expect(alert).toContainText('Unable to load the Library.');
		await expect(alert.getByRole('button', { name: 'Retry', exact: true })).toBeEnabled();
		await expect(results.locator('[data-library-item-select]')).toHaveCount(0);
		await expect(results.getByText('Imported reference 1', { exact: true })).toHaveCount(0);
		await expect(results.getByText('Imported reference 2', { exact: true })).toHaveCount(0);
		await expect(results.getByText('No Items found.', { exact: true })).toHaveCount(0);
		expect(reads).toHaveLength(readCount);
		expect(receiptDeletes).toBe(1);
	} finally {
		release.resolve();
		await context.setOffline(false);
	}
});

test('Import directory restores its completed page through batch navigation, reload and history', async ({
	page
}) => {
	await mockSession(page);
	const summaries: components['schemas']['ImportBatchSummary'][] = Array.from(
		{ length: 21 },
		(_, index) => ({
			id: `completed-${index + 1}`,
			file_format: `Completed source ${index + 1}`,
			status: 'committed',
			created_at: '2026-10-21T00:00:00Z',
			record_count: 2,
			diagnostic_count: 0
		})
	);
	const directoryReads: URL[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/imports?*', (route) => {
		const url = new URL(route.request().url());
		directoryReads.push(url);
		return route.fulfill({
			json: directoryPage(url.searchParams.get('view') === 'completed' ? summaries : [], route)
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/imports/completed-21', (route) =>
		route.fulfill({
			json: importBatch({
				id: 'completed-21',
				status: 'committed',
				committed_item_ids: importedIds
			})
		})
	);
	const pages = page.getByRole('navigation', { name: 'Import pages', exact: true });
	async function expectDirectory(number: number, size = 20) {
		await expect(page).toHaveURL(
			(url) =>
				url.searchParams.get('context') === 'saved-position' &&
				url.searchParams.get('view') === 'completed' &&
				Number(url.searchParams.get('page') ?? 1) === number &&
				Number(url.searchParams.get('page_size') ?? 20) === size &&
				!url.searchParams.has('batch')
		);
		await expect(page.getByRole('tab', { name: 'Completed imports', exact: true })).toHaveAttribute(
			'aria-selected',
			'true'
		);
		await expect(pages).toContainText(`Page ${number} of ${Math.ceil(21 / size)}`);
	}
	const lastBatch = page.locator('a[href$="batch=completed-21"]');
	await page.goto(`${importHistoryPath}?context=saved-position`);
	await page.getByRole('tab', { name: 'Completed imports', exact: true }).click();
	await expectDirectory(1);
	await pages.getByRole('button', { name: 'Next page', exact: true }).click();
	await expectDirectory(2);
	await page.reload();
	await expectDirectory(2);
	await expect(lastBatch).toBeVisible();
	await lastBatch.click();
	await expect(page.getByText('Imported 2 records', { exact: true })).toBeVisible();
	await expect(page).toHaveURL(
		(url) =>
			url.searchParams.get('context') === 'saved-position' &&
			url.searchParams.get('view') === 'completed' &&
			url.searchParams.get('page') === '2' &&
			url.searchParams.get('batch') === 'completed-21'
	);
	await page.goBack();
	await expectDirectory(2);
	await page.goBack();
	await expectDirectory(1);
	await page.goForward();
	await expectDirectory(2);
	await lastBatch.click();
	await expect(page).toHaveURL((url) => url.searchParams.get('batch') === 'completed-21');
	await page.reload();
	await expect(page.getByText('Imported 2 records', { exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Back to import history', exact: true }).click();
	await expectDirectory(2);
	await pages.getByRole('combobox', { name: 'Page Size', exact: true }).selectOption('10');
	await expectDirectory(1, 10);
	await page.goBack();
	await expectDirectory(2);
	await page.getByRole('tab', { name: 'Pending imports', exact: true }).click();
	await expect(page).toHaveURL(
		(url) =>
			url.searchParams.get('context') === 'saved-position' &&
			!url.searchParams.has('view') &&
			!url.searchParams.has('page')
	);
	await expect(page.getByText('No pending imports', { exact: true })).toBeVisible();
	await page.goBack();
	await expectDirectory(2);
	expect(
		directoryReads.some(
			(url) =>
				url.searchParams.get('view') === 'completed' &&
				url.searchParams.get('limit') === '20' &&
				url.searchParams.get('offset') === '20'
		)
	).toBe(true);
});

test('Import directory clamps only a successful settled read and replaces the invalid page in history', async ({
	page
}) => {
	await mockSession(page);
	let failInvalidPage = true;
	const summaries: components['schemas']['ImportBatchSummary'][] = Array.from(
		{ length: 21 },
		(_, index) => ({
			id: `completed-${index + 1}`,
			file_format: 'metadata',
			status: 'committed',
			created_at: '2026-10-21T00:00:00Z',
			record_count: 2,
			diagnostic_count: 0
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/imports?*', (route) => {
		const url = new URL(route.request().url());
		if (url.searchParams.get('offset') === '1960' && failInvalidPage)
			return route.fulfill({ status: 503, json: { code: 'unavailable', message: 'Try again' } });
		return route.fulfill({ json: directoryPage(summaries, route) });
	});
	const pages = page.getByRole('navigation', { name: 'Import pages', exact: true });
	await page.goto(`${importHistoryPath}?context=clamp&view=completed`);
	await expect(pages).toContainText('Page 1 of 2');
	await page.goto(`${importHistoryPath}?context=clamp&view=completed&page=99`);
	await expect(page.getByRole('main').getByRole('alert')).toBeVisible();
	await expect(page).toHaveURL(`${importHistoryPath}?context=clamp&view=completed&page=99`);
	failInvalidPage = false;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page).toHaveURL(`${importHistoryPath}?context=clamp&view=completed&page=2`);
	await expect(pages).toContainText('Page 2 of 2');
	await page.goBack();
	await expect(page).toHaveURL(`${importHistoryPath}?context=clamp&view=completed`);
	await expect(pages).toContainText('Page 1 of 2');
});

test('unavailable Workflow history retains its Import destination across reload', async ({
	page
}) => {
	await mockSession(page);
	await mockImportedLibrary(page);
	const workflowId = 'expired-import-workflow';
	await page.addInitScript(
		({ workflowId, batchId }) => {
			if (localStorage.getItem('quirebase:tracked-workflows:user-1')) return;
			localStorage.setItem(
				'quirebase:tracked-workflows:user-1',
				JSON.stringify([
					{
						id: workflowId,
						workspaceId: 'workspace-1',
						target: { kind: 'import_batch', id: batchId },
						label: 'Preparing imported PDFs',
						successMessage: 'Import ready',
						failureMessage: 'Unable to prepare Import',
						startedAt: Date.now()
					}
				])
			);
		},
		{ workflowId, batchId }
	);
	let workflowReads = 0;
	await page.route(`**/api/v1/workspaces/workspace-1/workflows/${workflowId}`, (route) => {
		workflowReads += 1;
		return route.fulfill({
			status: 404,
			json: { code: 'not_found', message: 'Workflow not found' }
		});
	});
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) =>
		route.fulfill({
			json: importBatch({ status: 'committed', committed_item_ids: importedIds })
		})
	);
	await page.goto(libraryPath);
	const background = page.getByRole('button', { name: 'Background tasks (1)', exact: true });
	await background.click();
	const openImport = page.getByRole('link', { name: 'View import', exact: true });
	const unavailable = openImport
		.locator('..')
		.getByText('Workflow history is unavailable. Check the current result.', { exact: true });
	await expect(unavailable).toBeVisible();
	await expect(openImport).toHaveAttribute('href', `${importPath}?batch=${batchId}`);
	await openImport.click();
	await expect(page).toHaveURL(`${importPath}?batch=${batchId}`);
	await expect(page.getByText('Imported 2 records', { exact: true })).toBeVisible();
	await page.getByRole('link', { name: 'View imported Items', exact: true }).click();
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	const readsBeforeReload = workflowReads;
	await page.reload();
	await background.click();
	await expect(unavailable).toBeVisible();
	await expect(openImport).toHaveAttribute('href', `${importPath}?batch=${batchId}`);
	expect(workflowReads).toBe(readsBeforeReload);
});

test('history supports direct discard, retains row failures and corrects the last page after deletion', async ({
	page
}) => {
	await mockSession(page);
	let removed = false;
	let deletes = 0;
	let denyDelete = true;
	const summaries: components['schemas']['ImportBatchSummary'][] = Array.from(
		{ length: 21 },
		(_, index) => ({
			id: `pending-${index + 1}`,
			file_format: `Pending source ${index + 1}`,
			status: 'ready',
			created_at: '2026-10-21T00:00:00Z',
			record_count: 1,
			diagnostic_count: 0
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/imports?*', (route) =>
		route.fulfill({
			json: directoryPage(
				summaries.filter((row) => !removed || row.id !== 'pending-21'),
				route
			)
		})
	);
	const release = Promise.withResolvers<void>();
	await page.route('**/api/v1/workspaces/workspace-1/imports/pending-21', async (route) => {
		if (route.request().method() === 'DELETE') {
			deletes += 1;
			if (denyDelete) {
				await route.fulfill({ status: 503, json: { code: 'unavailable', message: 'Try again' } });
			} else {
				await release.promise;
				removed = true;
				await route.fulfill({ status: 204 });
			}
		} else {
			await route.fulfill({ json: importBatch({ id: 'pending-21' }) });
		}
	});
	try {
		await page.goto(`${importHistoryPath}?page=2`);
		const row = page.locator('[data-import-batch="pending-21"]');
		const discard = row.getByRole('button', { name: 'Discard', exact: true });
		await discard.click();
		await expect(row.getByRole('alert')).toBeVisible();
		await expect(discard).toBeEnabled();
		await expect(page).toHaveURL(`${importHistoryPath}?page=2`);
		denyDelete = false;
		await discard.click();
		await expect(discard).toBeDisabled();
		expect(deletes).toBe(2);
		release.resolve();
		await expect(page).toHaveURL(importHistoryPath);
		await expect(page.getByRole('region', { name: 'Import history', exact: true })).toBeFocused();
		await expect(row).toHaveCount(0);
		await expect(page.getByText('Pending source 1 · 1 record', { exact: true })).toBeVisible();
		await expect(page.getByRole('alert')).toHaveCount(0);
	} finally {
		release.resolve();
	}
});

test('history deletion preserves focus moved to another control while the request is pending', async ({
	page
}) => {
	await mockSession(page);
	let removed = false;
	const release = Promise.withResolvers<void>();
	await page.route('**/api/v1/workspaces/workspace-1/imports?*', (route) =>
		route.fulfill({
			json: directoryPage(
				removed
					? []
					: [
							{
								id: 'pending-focus',
								file_format: 'metadata',
								status: 'ready',
								created_at: '2026-10-21T00:00:00Z',
								record_count: 1,
								diagnostic_count: 0
							}
						],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/imports/pending-focus', async (route) => {
		await release.promise;
		removed = true;
		await route.fulfill({ status: 204 });
	});
	try {
		await page.goto(importHistoryPath);
		const discard = page.getByRole('button', { name: 'Discard', exact: true });
		await discard.click();
		await expect(discard).toBeDisabled();
		const newImport = page.getByRole('link', { name: 'New import', exact: true });
		await newImport.focus();
		release.resolve();
		await expect(discard).toHaveCount(0);
		await expect(newImport).toBeFocused();
		await expect(page.getByText('No pending imports', { exact: true })).toBeVisible();
	} finally {
		release.resolve();
	}
});

test('Chinese read-only Import history opens records without offering creation or deletion', async ({
	page
}) => {
	await page.setViewportSize({ width: 375, height: 812 });
	await mockSession(page);
	await page.addInitScript(() => {
		localStorage.setItem('quirebase:locale', 'zh-CN');
		localStorage.setItem('quirebase:theme', 'dark');
	});
	await page.route('**/api/v1/workspaces/workspace-1', (route) =>
		route.fulfill({
			json: {
				...workspaceView('workspace-1', 'Research'),
				current_role: 'viewer',
				authorization: { allowed: ['workspace.read'] }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/imports?*', (route) =>
		route.fulfill({
			json: directoryPage(
				new URL(route.request().url()).searchParams.get('view') === 'completed'
					? [
							{
								id: batchId,
								file_format: 'commonmeta',
								status: 'committed',
								created_at: '2026-10-21T00:00:00Z',
								record_count: 2,
								diagnostic_count: 0
							}
						]
					: [],
				route
			)
		})
	);
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) =>
		route.fulfill({
			json: importBatch({ status: 'committed', committed_item_ids: importedIds })
		})
	);
	await page.goto(`${importPath}?batch=${batchId}`);
	await page.getByRole('button', { name: '导入历史', exact: true }).click();
	await expect(page).toHaveURL(importHistoryPath);
	await page.getByRole('tab', { name: '已完成的导入', exact: true }).click();
	const open = page.getByRole('link', { name: '打开导入记录', exact: true });
	await expect(open).toBeVisible();
	await expect(page.getByRole('link', { name: '新建导入', exact: true })).toHaveCount(0);
	await expect(page.getByRole('button', { name: '删除导入记录', exact: true })).toHaveCount(0);
	await expect(page.getByRole('button', { name: '丢弃', exact: true })).toHaveCount(0);
	await open.click();
	await expect(page).toHaveURL((url) => url.searchParams.get('batch') === batchId);
	await page.getByRole('button', { name: '返回导入历史', exact: true }).click();
	await expect(open).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
		true
	);
	await page.screenshot({
		path: '/private/tmp/quirebase-import-history-375-zh-dark.png',
		fullPage: true
	});
});
