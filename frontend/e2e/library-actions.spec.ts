import { expect, test, type Page } from '@playwright/test';
import {
	chooseSearchOption,
	directoryPage,
	mockSession,
	openLibraryAction,
	projectPage,
	tagPage
} from './helpers';

const rows = Array.from({ length: 28 }, (_, index) => ({
	id: `item-${index + 1}`,
	title_html: `Action Item ${index + 1}`,
	authors: [
		{ full_name: `Author ${index + 1}`, last_name: `Author ${index + 1}`, first_name: null }
	],
	publication_date: '2026',
	publication_title: 'Journal of Actions',
	doi: null,
	version: 1
}));

async function mockLibrary(page: Page) {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({ json: directoryPage(rows, route) })
	);
	const project = {
		id: 'project-1',
		name: 'Reading',
		state: 'active',
		participation: 'workspace',
		is_participating: true,
		item_count: 0,
		authorization: { allowed: ['project_item.manage'] }
	};
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: projectPage([project], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) =>
		route.fulfill({ json: { ...project, active_participants: [] } })
	);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({
			json: tagPage(
				[
					{
						id: 'tag-1',
						name: 'Methods',
						accessible_item_count: 0,
						authorization: { allowed: ['tag.use'] }
					}
				],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/*/overview', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		return route.fulfill({
			json: {
				id,
				version: 1,
				citation_key: null,
				metadata: { id: `urn:${id}`, type: 'JournalArticle', title: `Preview ${id}` },
				authorization: { allowed: ['item.update'] },
				copy_targets: [],
				tags: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				latest_revision_id: null,
				thumbnail: null
			}
		});
	});
	const bibliography: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/bibliography', (route) => {
		const body = route.request().postDataJSON();
		bibliography.push(body);
		return route.fulfill({
			body: `References: ${body.item_ids.join(', ')}`,
			contentType: 'text/plain',
			headers: { 'Content-Disposition': 'attachment; filename="references.txt"' }
		});
	});
	return { bibliography };
}

async function installClipboard(page: Page, rejected = false) {
	await page.addInitScript((rejected) => {
		const state = { rejected, writes: [] as string[] };
		Object.defineProperty(window, '__libraryClipboard', { value: state });
		Object.defineProperty(navigator, 'clipboard', {
			configurable: true,
			value: {
				writeText: async (text: string) => {
					if (state.rejected) throw new DOMException('Clipboard blocked', 'NotAllowedError');
					state.writes.push(text);
				}
			}
		});
	}, rejected);
}

async function clipboardWrites(page: Page) {
	return page.evaluate(
		() =>
			(window as typeof window & { __libraryClipboard: { writes: string[] } }).__libraryClipboard
				.writes
	);
}

test('Add to Project loads options only when opened, searches beyond the first page and verifies the selected target', async ({
	page
}) => {
	await mockLibrary(page);
	const projects = Array.from({ length: 60 }, (_, index) => ({
		id: `project-${index + 1}`,
		name: `Project ${String(index + 1).padStart(2, '0')}`,
		state: 'active',
		participation: 'workspace',
		is_participating: true,
		item_count: 0,
		authorization: { allowed: index === 0 ? [] : ['project_item.manage'] }
	}));
	const reads: Array<{ search: string; offset: number }> = [];
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) => {
		const params = new URL(route.request().url()).searchParams;
		reads.push({ search: params.get('search') ?? '', offset: Number(params.get('offset') ?? 0) });
		return route.fulfill({ json: projectPage(projects, route) });
	});
	const detailStarted = Promise.withResolvers<void>();
	const releaseDetail = Promise.withResolvers<void>();
	let detailReads = 0;
	let detailAvailable = false;
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-60', async (route) => {
		detailReads++;
		if (!detailAvailable) {
			detailStarted.resolve();
			await releaseDetail.promise;
			return route.fulfill({
				status: 503,
				json: { code: 'internal_error', message: 'Temporary Project lookup failure' }
			});
		}
		return route.fulfill({ json: { ...projects[59], active_participants: [] } });
	});
	const submitted: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		submitted.push(route.request().postDataJSON());
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/library');
	await page.locator('[data-library-item-select="item-1"]').check();
	await openLibraryAction(page, 'add_project');
	const dialog = page.getByRole('dialog', { name: 'Add to Project', exact: true });
	await expect(dialog).toBeVisible();
	expect(reads).toEqual([]);
	const submit = dialog.getByRole('button', { name: 'Add to Project', exact: true });
	await expect(submit).toBeDisabled();
	await dialog
		.getByRole('button', { name: 'Show options for Select Project', exact: true })
		.click();
	await expect(dialog.getByRole('option', { name: 'Project 25', exact: true })).toBeVisible();
	await expect(dialog.getByRole('option', { name: 'Project 26', exact: true })).toHaveCount(0);
	await expect(dialog.getByRole('option', { name: 'Project 01', exact: true })).toHaveCount(0);
	expect(reads).toEqual([{ search: '', offset: 0 }]);
	try {
		await chooseSearchOption(page, 'Select Project', 'Project 60');
		await detailStarted.promise;
		await expect(submit).toBeDisabled();
		expect(reads).toContainEqual({ search: 'Project 60', offset: 0 });
		expect(submitted).toEqual([]);
	} finally {
		releaseDetail.resolve();
	}
	await expect(dialog.getByRole('alert')).toBeVisible();
	await expect(submit).toBeDisabled();
	const failedDetailReads = detailReads;
	await page.context().setOffline(true);
	try {
		await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
		await dialog.getByRole('button', { name: 'Retry', exact: true }).click();
		await expect(submit).toBeDisabled();
		await expect(dialog.getByRole('alert')).toBeVisible();
		expect(detailReads).toBe(failedDetailReads);
		detailAvailable = true;
	} finally {
		await page.context().setOffline(false);
	}
	await expect(submit).toBeEnabled();
	await submit.click();
	await expect(dialog).toHaveCount(0);
	expect(submitted).toEqual([
		{ action: 'add_project', item_ids: ['item-1'], project_id: 'project-60' }
	]);
});

for (const view of ['table', 'list'] as const) {
	test(`${view} row actions target the current Item and preserve a different selection`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		await installClipboard(page);
		const { bibliography } = await mockLibrary(page);
		await page.goto('/workspace/workspace-1/library');
		const selected = page.locator('[data-library-item-select="item-2"]');
		await selected.check();
		const trigger = page.locator('#library-results [data-library-item-actions="item-1"]');
		await trigger.click();
		await page.getByRole('menuitem', { name: 'Copy citation', exact: true }).click();
		const dialog = page.getByRole('dialog', { name: 'Copy citation', exact: true });
		await expect(dialog).toContainText('Current Item');
		await dialog.getByRole('button', { name: 'Copy to clipboard', exact: true }).click();
		await expect.poll(() => clipboardWrites(page)).toEqual(['References: item-1']);
		expect(bibliography).toMatchObject([{ item_ids: ['item-1'] }]);
		await expect(selected).toBeChecked();
		if (await dialog.isVisible())
			await dialog.getByRole('button', { name: 'Close', exact: true }).click();
		await expect(trigger).toBeFocused();
	});

	test(`${view} row menu mutation and cancel return focus without clearing other selected Items`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		await mockLibrary(page);
		const submitted: Record<string, unknown>[] = [];
		await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
			submitted.push(route.request().postDataJSON());
			return route.fulfill({ json: { ok: true } });
		});
		await page.goto('/workspace/workspace-1/library');
		const selected = page.locator('[data-library-item-select="item-2"]');
		await selected.check();
		const trigger = page.locator('#library-results [data-library-item-actions="item-1"]');
		await trigger.click();
		await page.getByRole('menuitem', { name: 'Permanently delete', exact: true }).click();
		const deletion = page.getByRole('dialog', {
			name: 'Permanently delete this Item?',
			exact: true
		});
		await expect(deletion).toContainText('Current Item');
		await expect(deletion.getByRole('button', { name: 'Cancel', exact: true })).toBeFocused();
		await deletion.getByRole('button', { name: 'Cancel', exact: true }).click();
		await expect(trigger).toBeFocused();
		await trigger.click();
		await page.getByRole('menuitem', { name: 'Add Tag', exact: true }).click();
		const dialog = page.getByRole('dialog', { name: 'Add Tag', exact: true });
		await expect(dialog).toContainText('Current Item');
		await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
		await expect(trigger).toBeFocused();
		await trigger.click();
		await page.getByRole('menuitem', { name: 'Add Tag', exact: true }).click();
		await chooseSearchOption(page, 'Select Tag', 'Methods');
		await dialog.getByRole('button', { name: 'Add Tag', exact: true }).click();
		await expect(dialog).toHaveCount(0);
		await expect(selected).toBeChecked();
		expect(submitted).toMatchObject([
			{ action: 'add_tag', item_ids: ['item-1'], tag_name: 'Methods' }
		]);
	});
}

test('selected citation copy follows result order and saved format options', async ({ page }) => {
	await installClipboard(page);
	await page.addInitScript(() => {
		localStorage.setItem(
			'quirebase:export-preferences:v1:account:user-1',
			JSON.stringify({
				schemaVersion: 1,
				citation: {
					format: 'bibtex',
					includeAbstract: false,
					preserveCase: true,
					encoding: 'latex',
					doiPolicy: 'omit',
					urlPolicy: 'omit_when_doi',
					excludedFields: 'abstract, publisher',
					sortBy: 'input'
				},
				document: {}
			})
		);
		localStorage.setItem(
			'quirebase:export-preferences:v1:account:user-1:workspace:workspace-1:citation-style',
			'custom-style'
		);
	});
	const { bibliography } = await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	await page.locator('[data-library-item-select="item-3"]').check();
	await page.locator('[data-library-item-select="item-1"]').check();
	const toolbar = page.getByRole('region', { name: 'Bulk actions', exact: true });
	const trigger = toolbar.getByRole('button', { name: 'Copy citation', exact: true });
	await trigger.click();
	const dialog = page.getByRole('dialog', { name: 'Copy citation', exact: true });
	await expect(dialog).toContainText('2 selected');
	await expect(dialog.getByRole('combobox', { name: 'Format', exact: true })).toHaveValue('bibtex');
	await dialog.getByRole('button', { name: 'Copy to clipboard', exact: true }).click();
	await expect.poll(() => clipboardWrites(page)).toEqual(['References: item-1, item-3']);
	expect(bibliography).toMatchObject([
		{
			item_ids: ['item-1', 'item-3'],
			file_format: 'bibtex',
			style: 'custom-style',
			include_abstract: false,
			preserve_case: true,
			encoding: 'latex',
			doi_policy: 'omit',
			url_policy: 'omit_when_doi',
			excluded_fields: ['abstract', 'publisher'],
			sort_by: 'input'
		}
	]);
	await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(2);
	if (await dialog.isVisible())
		await dialog.getByRole('button', { name: 'Close', exact: true }).click();
	await expect(trigger).toBeFocused();
});

test('clipboard rejection preserves generated text for manual copy and retry without another request', async ({
	page
}) => {
	await installClipboard(page, true);
	const { bibliography } = await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	await page.locator('[data-library-item-select="item-1"]').check();
	await openLibraryAction(page, 'copy');
	const dialog = page.getByRole('dialog', { name: 'Copy citation', exact: true });
	const copy = dialog.getByRole('button', { name: 'Copy to clipboard', exact: true });
	await copy.click();
	const text = dialog.getByRole('textbox', { name: 'Citation text', exact: true });
	await expect(text).toHaveValue('References: item-1');
	await expect(text).toHaveAttribute('readonly', '');
	await expect(dialog.getByRole('alert')).toBeVisible();
	await page.evaluate(() => {
		(
			window as typeof window & { __libraryClipboard: { rejected: boolean } }
		).__libraryClipboard.rejected = false;
	});
	await copy.click();
	await expect.poll(() => clipboardWrites(page)).toEqual(['References: item-1']);
	expect(bibliography).toHaveLength(1);
	await expect(page.locator('[data-library-item-select="item-1"]')).toBeChecked();
});

test('export downloads the selected bibliography and keeps selection for subsequent actions', async ({
	page
}) => {
	const { bibliography } = await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	await page.locator('[data-library-item-select="item-2"]').check();
	await openLibraryAction(page, 'bibliography');
	const dialog = page.getByRole('dialog', { name: 'Export bibliography', exact: true });
	await dialog.getByRole('combobox', { name: 'Format', exact: true }).selectOption('ris');
	const downloaded = page.waitForEvent('download');
	await dialog.getByRole('button', { name: 'Download file', exact: true }).click();
	await downloaded;
	expect(bibliography).toMatchObject([{ item_ids: ['item-2'], file_format: 'ris' }]);
	await expect(page.locator('[data-library-item-select="item-2"]')).toBeChecked();
});

test('preview and selected-row shortcuts copy the target of their focused context', async ({
	page
}) => {
	await installClipboard(page);
	const { bibliography } = await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library?preview=item-1');
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await expect(preview).toContainText('Preview item-1');
	await page.locator('[data-library-item-select="item-2"]').check();
	await preview.locator('[data-library-item-actions="item-1"]').click();
	await page.getByRole('menuitem', { name: 'Copy citation', exact: true }).click();
	let dialog = page.getByRole('dialog', { name: 'Copy citation', exact: true });
	await expect(dialog).toContainText('Current Item');
	await dialog.getByRole('button', { name: 'Copy to clipboard', exact: true }).click();
	await expect.poll(() => clipboardWrites(page)).toEqual(['References: item-1']);
	if (await dialog.isVisible())
		await dialog.getByRole('button', { name: 'Close', exact: true }).click();
	await preview.getByRole('heading', { name: 'Item preview', exact: true }).focus();
	await page.keyboard.press('ControlOrMeta+Shift+C');
	dialog = page.getByRole('dialog', { name: 'Copy citation', exact: true });
	await expect(dialog).toContainText('Current Item');
	await dialog.getByRole('button', { name: 'Copy to clipboard', exact: true }).click();
	await expect
		.poll(() => clipboardWrites(page))
		.toEqual(['References: item-1', 'References: item-1']);
	await page.locator('[data-library-item-select="item-2"]').focus();
	await page.keyboard.press('ControlOrMeta+Shift+C');
	await expect(dialog).toContainText('1 selected');
	await dialog.getByRole('button', { name: 'Copy to clipboard', exact: true }).click();
	await expect
		.poll(() => clipboardWrites(page))
		.toEqual(['References: item-1', 'References: item-1', 'References: item-2']);
	expect(bibliography.map((body) => body.item_ids)).toEqual([['item-1'], ['item-1'], ['item-2']]);
});

test('row action shortcut restores focus and ignores text entry and open dialogs', async ({
	page
}) => {
	await installClipboard(page);
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	const row = page.locator('[data-library-item-select="item-1"]');
	await row.press('Shift+F10');
	await expect(page.getByRole('menuitem', { name: 'Copy citation', exact: true })).toBeVisible();
	const menu = page.getByRole('menu');
	// Skeleton transfers menu focus on an animation frame after opening.
	await expect(menu).toBeFocused();
	await page.keyboard.press('Escape');
	await expect(menu).toHaveCount(0);
	const trigger = page.locator('#library-results [data-library-item-actions="item-1"]');
	await expect(trigger).toBeFocused();
	await page.locator('[data-library-item-select="item-2"]').check();
	await trigger.press('ControlOrMeta+Shift+C');
	const dialog = page.getByRole('dialog', { name: 'Copy citation', exact: true });
	await expect(dialog).toContainText('Current Item');
	await dialog.getByRole('button', { name: 'Cancel', exact: true }).focus();
	await page.keyboard.press('ControlOrMeta+Shift+C');
	await expect(page.getByRole('dialog')).toHaveCount(1);
	await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	await search.fill('draft query');
	await search.press('ControlOrMeta+Shift+C');
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await expect(search).toBeFocused();
	await expect(search).toHaveValue('draft query');
});

test('citation retry keeps captured Items and options after listing navigation', async ({
	page
}) => {
	await installClipboard(page);
	await mockLibrary(page);
	const release = Promise.withResolvers<void>();
	const requests: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/bibliography', async (route) => {
		const body = route.request().postDataJSON();
		requests.push(body);
		if (requests.length === 1) {
			await release.promise;
			return route.fulfill({
				status: 500,
				json: { code: 'internal_error', message: 'Temporary failure' }
			});
		}
		return route.fulfill({ body: 'Retried citation', contentType: 'text/plain' });
	});
	await page.goto('/workspace/workspace-1/library');
	await page.getByRole('button', { name: 'Next page', exact: true }).click();
	await page.locator('[data-library-item-select="item-26"]').check();
	await openLibraryAction(page, 'copy');
	const dialog = page.getByRole('dialog', { name: 'Copy citation', exact: true });
	await dialog.getByRole('combobox', { name: 'Format', exact: true }).selectOption('bibtex');
	await dialog.getByRole('button', { name: 'Copy to clipboard', exact: true }).click();
	try {
		await expect.poll(() => requests.length).toBe(1);
		await page.goBack();
		await expect(page).toHaveURL(/\/library$/);
		await expect(dialog).toHaveCount(0);
		await page.locator('[data-library-item-select="item-1"]').check();
	} finally {
		release.resolve();
	}
	await page.getByRole('button', { name: 'Review action', exact: true }).click();
	await expect(dialog.getByRole('alert')).toBeVisible();
	await expect(dialog.getByRole('combobox', { name: 'Format', exact: true })).toHaveValue('bibtex');
	await expect(dialog.getByRole('combobox', { name: 'Format', exact: true })).toBeDisabled();
	await dialog.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect.poll(() => clipboardWrites(page)).toEqual(['Retried citation']);
	expect(requests).toHaveLength(2);
	expect(requests[1]).toEqual(requests[0]);
	expect(requests[1]).toMatchObject({ item_ids: ['item-26'], file_format: 'bibtex' });
	await expect(page.locator('[data-library-item-select="item-1"]')).toBeChecked();
	await expect(page).toHaveURL(/\/library$/);
});

test('document download uses saved annotation and supplement preferences and preserves selection', async ({
	page
}) => {
	await page.addInitScript(() => {
		localStorage.setItem(
			'quirebase:export-preferences:v1:account:user-1',
			JSON.stringify({
				schemaVersion: 1,
				citation: {},
				document: { includeAnnotations: true, includeSupplements: true }
			})
		);
	});
	await mockLibrary(page);
	const downloads: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/documents/archive', (route) => {
		downloads.push(route.request().postDataJSON());
		return route.fulfill({
			body: 'zip-fixture',
			contentType: 'application/zip',
			headers: { 'Content-Disposition': 'attachment; filename="documents.zip"' }
		});
	});
	await page.goto('/workspace/workspace-1/library');
	await page.locator('[data-library-item-select="item-1"]').check();
	await openLibraryAction(page, 'documents');
	const dialog = page.getByRole('dialog', { name: 'Download documents', exact: true });
	await expect(
		dialog.getByRole('checkbox', { name: 'Include Annotations', exact: true })
	).toBeChecked();
	await expect(
		dialog.getByRole('checkbox', { name: 'Include supplementary files', exact: true })
	).toBeChecked();
	const downloaded = page.waitForEvent('download');
	await dialog.getByRole('button', { name: 'Download file', exact: true }).click();
	await downloaded;
	expect(downloads).toMatchObject([
		{ item_ids: ['item-1'], include_annotations: true, include_supplements: true }
	]);
	await expect(page.locator('[data-library-item-select="item-1"]')).toBeChecked();
});
