import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

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
	await expect(page.getByRole('tabpanel')).toHaveCount(1);
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
	await expect(page.getByRole('button', { name: 'PDF files', exact: true })).not.toBeVisible();
	await expect(page.getByRole('combobox', { name: 'Data source' })).toBeEnabled();
	expect(schemaRequests).toBe(0);
	await page.getByRole('tab', { name: 'PDFs', exact: true }).click();
	await expect(page.getByRole('button', { name: 'PDF files', exact: true })).toBeVisible();
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
	await expect(page.getByRole('button', { name: 'Commit', exact: true })).toBeEnabled();
	await expect(page.getByRole('button', { name: 'Preview metadata' })).toBeDisabled();
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
	await expect(page.getByRole('button', { name: 'Commit', exact: true })).toBeDisabled();
});

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
	await expect(page.getByRole('button', { name: 'Commit' })).toBeEnabled();
	await expect(page.getByText('Imported PDF')).toBeVisible();
	await expect(page.getByText('Ada Lovelace; World Health Organization')).toBeVisible();
	await expect(page.getByText('paper.pdf', { exact: true })).toBeVisible();
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
	await expect(page.getByRole('button', { name: 'Commit' })).toBeEnabled();
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
		await expect(page.getByRole('button', { name: 'Commit', exact: true })).toBeDisabled();
		await page.getByRole('button', { name: 'Retry', exact: true }).click();
		await expect(page.getByRole('button', { name: 'Commit', exact: true })).toBeEnabled();
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
