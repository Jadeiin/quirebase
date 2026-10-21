import { expect, test } from '@playwright/test';
import { directoryPage, mockSession } from './helpers';

const workflow = {
	id: 'workflow-detail-1',
	name: 'documents.extract_text',
	state: 'succeeded',
	raw_status: 'SUCCESS',
	created_at: '2026-10-01T10:00:00Z',
	updated_at: '2026-10-01T10:01:00Z'
};

for (const section of ['overview', 'settings'] as const) {
	test(`${section} cannot redisplay denied content after a transient retry failure`, async ({
		page
	}) => {
		await mockSession(page, 'administrator');
		await page.clock.setFixedTime(new Date('2026-10-21T01:00:00Z'));
		const payload =
			section === 'overview'
				? {
						user_count: 2,
						pending_invitation_count: 0,
						failed_workflow_count: 0,
						storage: { items_count: 1 },
						recent_events: {
							items: [
								{
									id: 'private-event',
									action: 'Private audit event',
									target_type: 'user',
									created_at: '2026-10-21T00:00:00Z'
								}
							],
							total: 1,
							limit: 20,
							offset: 0
						}
					}
				: {
						registration_policy: 'invitation_only',
						workspace_creation_policy: 'admins_only',
						metadata_contact_email: '',
						ncbi_api_key: 'private-api-key',
						openalex_api_key: '',
						nasa_ads_token: '',
						ieee_api_key: '',
						session_days: 30,
						max_pdf_bytes: 1000000,
						max_attachment_bytes: 1000000,
						export_ttl_hours: 24,
						database_url: 'sqlite:///private.db',
						data_dir: '/private/data'
					};
		let status = 200;
		await page.route(`**/api/v1/admin/${section}*`, (route) =>
			route.fulfill({
				status,
				json:
					status === 200
						? payload
						: { code: status === 403 ? 'permission_denied' : 'internal_error', message: 'Denied' }
			})
		);
		await page.goto(section === 'overview' ? '/admin' : '/admin/settings');
		const content =
			section === 'overview'
				? page.getByText('Private audit event', { exact: true })
				: page.getByLabel('NCBI API key', { exact: true });
		await expect(content).toBeVisible();
		status = 403;
		await page.clock.setFixedTime(new Date('2026-10-21T01:00:31Z'));
		await page.evaluate(() => window.dispatchEvent(new Event('visibilitychange')));
		await expect(page.getByText('Unable to load administration.', { exact: true })).toBeVisible();
		await expect(content).toHaveCount(0);
		status = 503;
		const failed = page.waitForResponse(
			(response) => response.url().includes(`/admin/${section}`) && response.status() === 503
		);
		await page.getByRole('button', { name: 'Retry', exact: true }).click();
		await failed;
		await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeEnabled();
		await expect(page.getByText('Unable to load administration.', { exact: true })).toBeVisible();
		await expect(content).toHaveCount(0);
	});
}

test('audit details expand by keyboard and wrap long evidence on narrow screens', async ({
	page
}) => {
	await page.setViewportSize({ width: 390, height: 900 });
	await mockSession(page, 'administrator');
	const longValue = 'unbroken-audit-evidence-'.repeat(60);
	const event = {
		id: 'audit-event-1',
		action: 'workspace.update',
		target_type: 'workspace',
		target_id: longValue,
		actor_id: 'actor-1',
		workspace_id: 'workspace-1',
		result: 'allowed',
		source: 'web',
		detail: { evidence: longValue },
		created_at: '2026-10-01T10:00:00Z'
	};
	await page.route('**/api/v1/admin/audit?*', (route) =>
		route.fulfill({ json: directoryPage([event], route) })
	);
	await page.goto('/admin/audit');
	const row = page.getByRole('rowgroup', { name: 'workspace.update · audit-event-1', exact: true });
	await expect(row.getByRole('button', { name: 'Details', exact: true })).toHaveAttribute(
		'aria-expanded',
		'false'
	);
	await expect(row.locator('pre')).toHaveCount(0);
	await row.getByRole('button', { name: 'Details', exact: true }).focus();
	await page.keyboard.press('Enter');
	await expect(row.getByRole('button', { name: 'Details', exact: true })).toHaveAttribute(
		'aria-expanded',
		'true'
	);
	await expect(row.locator('pre')).toContainText(longValue);
	await expect(row.getByText('Actor ID', { exact: true })).toBeVisible();
	await expect
		.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
		.toBe(true);
	await row.getByRole('button', { name: 'Details', exact: true }).press('Enter');
	await expect(row.locator('pre')).toHaveCount(0);
});

test('workflow details load on demand and retain transient data until authoritative denial', async ({
	page
}) => {
	await page.setViewportSize({ width: 390, height: 900 });
	await mockSession(page, 'administrator');
	await page.route('**/api/v1/admin/workflows?*', (route) =>
		route.fulfill({ json: directoryPage([workflow], route) })
	);
	let requests = 0;
	let status = 500;
	const longOutput = 'workflow-output-'.repeat(60);
	await page.route('**/api/v1/admin/workflows/workflow-detail-1', (route) => {
		requests += 1;
		return route.fulfill({
			status,
			json:
				status === 200
					? { ...workflow, output: { evidence: longOutput }, executor_id: 'executor-1' }
					: {
							code: status === 403 ? 'permission_denied' : 'internal_error',
							message: 'Unavailable'
						}
		});
	});
	await page.goto('/admin/workflows');
	const row = page.getByRole('rowgroup', { name: workflow.name, exact: true });
	await expect(row.getByRole('button', { name: 'Details', exact: true })).toBeVisible();
	expect(requests).toBe(0);
	await row.getByRole('button', { name: 'Details', exact: true }).click();
	await expect(row.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
	await expect(row.locator('pre')).toHaveCount(0);
	status = 200;
	await row.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(row.locator('pre')).toContainText(longOutput);
	await expect
		.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
		.toBe(true);
	status = 500;
	await row.getByRole('button', { name: 'Refresh details', exact: true }).click();
	await expect(row.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
	await expect(row.locator('pre')).toContainText(longOutput);
	status = 403;
	await row.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByText('Unable to load administration.', { exact: true })).toBeVisible();
	await expect(row).toHaveCount(0);
	await expect(page.getByText('executor-1', { exact: true })).toHaveCount(0);
});

for (const deniedRead of ['list', 'detail'] as const) {
	test(`workflow ${deniedRead} denial purges warmed details and offline list variants`, async ({
		page,
		context
	}) => {
		await mockSession(page, 'administrator');
		const other = { ...workflow, id: 'workflow-detail-2', name: 'documents.export_annotations' };
		let denied = false;
		await page.route('**/api/v1/admin/workflows?*', (route) =>
			denied && deniedRead === 'list'
				? route.fulfill({ status: 403, json: { code: 'permission_denied', message: 'Denied' } })
				: route.fulfill({ json: directoryPage([workflow, other], route) })
		);
		await page.route('**/api/v1/admin/workflows/workflow-detail-*', (route) => {
			const item = route.request().url().endsWith(other.id) ? other : workflow;
			return denied && deniedRead === 'detail'
				? route.fulfill({ status: 403, json: { code: 'permission_denied', message: 'Denied' } })
				: route.fulfill({ json: { ...item, output: `Private output for ${item.id}` } });
		});
		await page.goto('/admin/workflows');
		await page
			.getByRole('button', {
				name: 'Sort order: Newest first. Switch to Oldest first.',
				exact: true
			})
			.click();
		await expect(page).toHaveURL(/direction=asc/);
		await page
			.getByRole('button', {
				name: 'Sort order: Oldest first. Switch to Newest first.',
				exact: true
			})
			.click();
		await expect(page).not.toHaveURL(/direction=asc/);
		for (const item of [workflow, other]) {
			const row = page.getByRole('rowgroup', { name: item.name, exact: true });
			await row.getByRole('button', { name: 'Details', exact: true }).click();
			await expect(row.locator('pre')).toHaveText(`Private output for ${item.id}`);
		}
		denied = true;
		if (deniedRead === 'list') {
			await page.getByRole('button', { name: 'Refresh', exact: true }).click();
		} else {
			await page.getByRole('button', { name: 'Refresh details', exact: true }).click();
		}
		await expect(page.getByText('Unable to load administration.', { exact: true })).toBeVisible();
		await expect(page.locator('[data-workflow-details]')).toHaveCount(0);
		await context.setOffline(true);
		try {
			await page
				.getByRole('button', {
					name: 'Sort order: Newest first. Switch to Oldest first.',
					exact: true
				})
				.click();
			await expect(page).toHaveURL(/direction=asc/);
			await expect(page.getByText('Unable to load administration.', { exact: true })).toBeVisible();
			await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
			await expect(page.getByText(/Private output for/)).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Details', exact: true })).toHaveCount(0);
			await expect(page.getByText('No workflows.', { exact: true })).toHaveCount(0);
		} finally {
			await context.setOffline(false);
		}
	});
}

test('workflow filters send an exact name and server creation order', async ({ page }) => {
	await mockSession(page, 'administrator');
	const requests: URLSearchParams[] = [];
	await page.route('**/api/v1/admin/workflows?*', (route) => {
		requests.push(new URL(route.request().url()).searchParams);
		return route.fulfill({ json: directoryPage([workflow], route) });
	});
	await page.goto('/admin/workflows');
	await page.getByLabel('Workflow name (exact)', { exact: true }).fill(workflow.name);
	await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
	await expect.poll(() => requests.at(-1)?.get('name')).toBe(workflow.name);
	await expect(page).toHaveURL(/name=documents.extract_text/);
	await page
		.getByRole('button', { name: 'Sort order: Newest first. Switch to Oldest first.', exact: true })
		.click();
	await expect.poll(() => requests.at(-1)?.get('direction')).toBe('asc');
	expect(requests.at(-1)?.get('name')).toBe(workflow.name);
	await page
		.getByRole('button', { name: 'Sort order: Oldest first. Switch to Newest first.', exact: true })
		.click();
	await expect.poll(() => requests.at(-1)?.get('direction')).toBe('desc');
});

test('audit creation order and refinements are sent to the server', async ({ page }) => {
	await mockSession(page, 'administrator');
	const requests: URLSearchParams[] = [];
	await page.route('**/api/v1/admin/audit?*', (route) => {
		requests.push(new URL(route.request().url()).searchParams);
		return route.fulfill({ json: directoryPage([], route) });
	});
	await page.goto('/admin/audit');
	await page.getByLabel('Action', { exact: true }).fill('workspace.update');
	await page.getByLabel('Target type', { exact: true }).fill('workspace');
	await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
	await expect.poll(() => requests.at(-1)?.get('action')).toBe('workspace.update');
	await page
		.getByRole('button', { name: 'Sort order: Newest first. Switch to Oldest first.', exact: true })
		.click();
	await expect.poll(() => requests.at(-1)?.get('direction')).toBe('asc');
	expect(requests.at(-1)?.get('target_type')).toBe('workspace');
	expect(requests.at(-1)?.get('action')).toBe('workspace.update');
});

const maintenanceStorage = {
	items_count: 12,
	total_disk_bytes: 1048576,
	database_allocated_bytes: 2097152,
	workflow_history_count: 3,
	workflow_checkpoint_count: 5,
	datasource_checkpoint_count: 8,
	integrity_checked_at: '2026-10-01T10:02:00Z',
	integrity_status: 'succeeded',
	integrity_error_count: 1,
	integrity_errors: ['A stored object needs inspection.']
};

for (const width of [1280, 390]) {
	test(
		'maintenance keeps metrics and execution without a duplicate workflow list at ' + width + 'px',
		async ({ page }) => {
			await page.setViewportSize({ width, height: 900 });
			await mockSession(page, 'administrator');
			let workflowLists = 0;
			await page.route('**/api/v1/admin/workflows?*', (route) => {
				workflowLists += 1;
				return route.fulfill({ json: directoryPage([], route) });
			});
			await page.route('**/api/v1/admin/maintenance', (route) =>
				route.fulfill({ json: maintenanceStorage })
			);
			await page.goto('/admin/maintenance');
			await expect(page.getByText('Database allocation', { exact: true })).toBeVisible();
			await expect(page.getByText('Workflow history', { exact: true })).toBeVisible();
			await expect(
				page.getByRole('button', { name: 'Check stored objects', exact: true })
			).toBeEnabled();
			await page.getByText('Integrity error samples', { exact: true }).click();
			await expect(
				page.getByText('A stored object needs inspection.', { exact: true })
			).toBeVisible();
			await expect(
				page.getByRole('heading', { name: 'Recent operations', exact: true })
			).toHaveCount(0);
			await expect(page.getByRole('table')).toHaveCount(0);
			await expect(page.getByRole('button', { name: 'Details', exact: true })).toHaveCount(0);
			await expect
				.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
				.toBe(true);
			expect(workflowLists).toBe(0);
		}
	);
}

test('maintenance execution stays in the background center and refreshes metrics after completion', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let workflowLists = 0;
	let metricReads = 0;
	let started = 0;
	let completed = false;
	const release = Promise.withResolvers<void>();
	await page.route('**/api/v1/admin/workflows?*', (route) => {
		workflowLists += 1;
		return route.fulfill({ json: directoryPage([], route) });
	});
	await page.route('**/api/v1/admin/maintenance', (route) => {
		metricReads += 1;
		return route.fulfill({
			json: { ...maintenanceStorage, workflow_history_count: completed ? 4 : 3 }
		});
	});
	await page.route('**/api/v1/admin/maintenance/check_objects', (route) => {
		started += 1;
		return route.fulfill({ status: 202, json: { id: 'maintenance-job-1', state: 'pending' } });
	});
	await page.route('**/api/v1/admin/workflows/maintenance-job-1', async (route) => {
		await release.promise;
		completed = true;
		return route.fulfill({
			json: { ...workflow, id: 'maintenance-job-1', name: 'operations.check_objects' }
		});
	});
	await page.goto('/admin/maintenance');
	const run = page.getByRole('button', { name: 'Check stored objects', exact: true });
	await run.click();
	try {
		await expect(run).toBeDisabled();
		await expect(page.getByText('Maintenance operation started', { exact: true })).toBeVisible();
		await page.getByRole('button', { name: 'Background tasks (1)', exact: true }).click();
		await expect(
			page.getByText('Maintenance: Check stored objects', { exact: true })
		).toBeVisible();
		release.resolve();
		await expect(
			page.getByText('Maintenance operation completed', { exact: true }).first()
		).toBeVisible();
		await expect(run).toBeEnabled();
		await expect.poll(() => metricReads).toBeGreaterThan(1);
		await expect(
			page
				.locator('dt')
				.filter({ hasText: /^Workflow history$/ })
				.locator('+ dd')
		).toHaveText('4');
		expect(started).toBe(1);
		expect(workflowLists).toBe(0);
	} finally {
		release.resolve();
	}
});

test('maintenance metrics recover from a failed read without rendering empty workflow history', async ({
	page
}) => {
	await mockSession(page, 'administrator');
	let status = 500;
	await page.route('**/api/v1/admin/maintenance', (route) =>
		route.fulfill({
			status,
			json: status === 200 ? maintenanceStorage : { code: 'internal_error', message: 'Unavailable' }
		})
	);
	await page.goto('/admin/maintenance');
	await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
	await expect(page.getByText('Database allocation', { exact: true })).toHaveCount(0);
	await expect(page.getByText('No maintenance workflows.', { exact: true })).toHaveCount(0);
	status = 200;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByText('Database allocation', { exact: true })).toBeVisible();
	await expect(
		page.getByRole('button', { name: 'Check stored objects', exact: true })
	).toBeEnabled();
	await expect(page.getByRole('table')).toHaveCount(0);
});
