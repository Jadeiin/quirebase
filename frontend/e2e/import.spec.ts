import { expect, test } from '@playwright/test';
import { mockSession } from './helpers';

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
				records: previewRequests > 1 ? [{ title: 'Imported PDF' }] : [],
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
	await page.route('**/api/v1/workspaces/workspace-1/imports/pdfs', (route) => {
		uploadBody = route.request().postData() ?? '';
		return route.fulfill({
			status: 202,
			json: { id: 'batch-files', status: 'ready', workflow_id: null, records: [], errors: [] }
		});
	});
	await page.goto('/workspace/workspace-1/import');
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
				records: Array.from({ length: 21 }, (_, index) => ({ title: `Record ${index + 1}` })),
				errors: []
			}
		})
	);

	await page.goto('/workspace/workspace-1/import?batch=batch-many');
	await expect(page.getByText('Record 1', { exact: true })).toBeVisible();
	await expect(page.getByText('Record 21', { exact: true })).toHaveCount(0);
	await page.getByRole('button', { name: 'Next' }).click();
	await expect(page.getByText('Record 21', { exact: true })).toBeVisible();
});
