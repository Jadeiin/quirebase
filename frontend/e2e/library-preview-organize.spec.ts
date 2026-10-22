import { expect, test, type Page } from '@playwright/test';
import type { components } from '../src/lib/api/schema.js';
import { directoryPage, mockSession, tagPage } from './helpers';

type Tag = components['schemas']['ItemTagView'];
type TagSet = components['schemas']['TagSetRequest'];

async function mockPreviewLibrary(
	page: Page,
	options: {
		readOnly?: boolean;
		failRemoveProject?: boolean;
		failTagWrite?: boolean;
		beforeTagWrite?: () => Promise<void>;
		itemCount?: number;
		filterByTags?: boolean;
		longLabels?: boolean;
	} = {}
) {
	await mockSession(page);
	const tags: Tag[] = [
		{
			id: 'tag-reviewed',
			name: options.longLabels ? 'ReviewedWithoutAnySpaces'.repeat(12) : 'Reviewed'
		},
		{ id: 'tag-methods', name: 'Methods' }
	];
	const itemCount = options.itemCount ?? 3;
	const assignments: Record<string, { tags: string[]; projects: string[] }> = Object.fromEntries(
		Array.from({ length: itemCount }, (_, index) => [
			`item-${index + 1}`,
			{
				tags: options.filterByTags || index === 0 ? ['tag-reviewed'] : [],
				projects: options.longLabels ? ['project-1'] : []
			}
		])
	);
	const writes: { itemId: string; body: TagSet }[] = [];
	let organizeReads = 0;
	let removeAttempts = 0;
	const allowed: components['schemas']['WorkspaceAuthorizationView']['allowed'] = options.readOnly
		? []
		: ['item.update', 'tag.use', 'tag.create', 'project_item.manage'];
	await page.route('**/api/v1/workspaces/*/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/*/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/*/items?*', (route) => {
		const url = new URL(route.request().url());
		const limit = Number(url.searchParams.get('limit'));
		const offset = Number(url.searchParams.get('offset'));
		const rows = Array.from({ length: itemCount }, (_, index) => ({
			id: `item-${index + 1}`,
			title_html: `Reference ${index + 1}`,
			authors: [],
			publication_date: '2026-10',
			publication_title: 'Journal of Research',
			doi: null,
			version: 1
		})).filter(
			(row) =>
				!options.filterByTags ||
				!url.searchParams.get('tag') ||
				assignments[row.id].tags.includes(url.searchParams.get('tag')!)
		);
		return route.fulfill({
			json: {
				items: rows.slice(offset, offset + limit),
				total: rows.length,
				limit,
				offset
			}
		});
	});
	await page.route('**/api/v1/workspaces/*/items/*/overview', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		return route.fulfill({
			json: {
				id,
				version: 1,
				citation_key: null,
				metadata: {
					id: `https://doi.org/10.1234/${id}`,
					type: 'JournalArticle',
					title: `Preview ${id}`,
					description: '<b>A useful abstract</b>',
					date_published: '2026-10',
					container: { title: 'Journal of Research' },
					contributors: [
						{
							type: 'Person',
							roles: ['Author'],
							person: { given_name: 'Ada', family_name: 'Lovelace' }
						}
					]
				},
				authorization: { allowed },
				counts: { revisions: 1, attachments: 0, annotations: 0, discussion: 0 },
				tags: tags.filter((tag) => assignments[id].tags.includes(tag.id)),
				latest_revision_id: 'revision-1',
				thumbnail: null,
				copy_targets: []
			}
		});
	});
	await page.route('**/api/v1/workspaces/*/items/*/organize', (route) => {
		organizeReads++;
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		return route.fulfill({
			json: {
				authorization: { allowed },
				projects: [
					{
						id: 'project-1',
						name: options.longLabels
							? 'EvidenceReviewWithoutAnySpaces'.repeat(12)
							: 'Evidence review',
						assigned: assignments[id].projects.includes('project-1'),
						participation: 'workspace',
						is_participating: true
					}
				],
				tag_matrix: {
					groups: [{ letter: 'M', tags }],
					assigned_ids: assignments[id].tags,
					recommended_ids: [],
					suggested_names: [],
					recommendation_state: 'ready',
					recommendation_error: null
				}
			}
		});
	});
	await page.route('**/api/v1/workspaces/*/items/*/tags', async (route) => {
		const itemId = new URL(route.request().url()).pathname.split('/').at(-2)!;
		const body = route.request().postDataJSON() as TagSet;
		writes.push({ itemId, body });
		await options.beforeTagWrite?.();
		if (options.failTagWrite && writes.length === 1) {
			return route.fulfill({ status: 500, json: { code: 'internal_error', message: 'Try later' } });
		}
		const current = assignments[itemId];
		for (const name of body.new_names ?? []) {
			const tag = { id: `tag-created-${tags.length}`, name };
			tags.push(tag);
			current.tags.push(tag.id);
		}
		current.tags = [...new Set([...current.tags, ...(body.add_tag_ids ?? [])])].filter(
			(id) => !(body.remove_tag_ids ?? []).includes(id)
		);
		return route.fulfill({ json: { ok: true } });
	});
	await page.route('**/api/v1/workspaces/*/projects/*/items/*', (route) => {
		const itemId = new URL(route.request().url()).pathname.split('/').at(-1)!;
		if (route.request().method() === 'DELETE') {
			removeAttempts++;
			if (options.failRemoveProject && removeAttempts === 1)
				return route.fulfill({
					status: 500,
					json: { code: 'internal_error', message: 'Try later' }
				});
			assignments[itemId].projects = [];
		} else assignments[itemId].projects = ['project-1'];
		return route.fulfill({ json: { ok: true } });
	});
	return {
		writes,
		assignments,
		organizeReads: () => organizeReads,
		removeAttempts: () => removeAttempts
	};
}

test('preview shows bibliographic context, copies DOI and opens organization only on request', async ({
	page
}) => {
	const state = await mockPreviewLibrary(page);
	await page.addInitScript(() =>
		Object.defineProperty(navigator, 'clipboard', {
			value: {
				writeText: async (value: string) => {
					(window as unknown as { copiedDoi: string }).copiedDoi = value;
				}
			}
		})
	);
	await page.goto('/workspace/workspace-1/library?sort=title&preview=item-1');
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await expect(preview).toContainText('Ada Lovelace');
	await expect(preview).toContainText('Journal of Research · 2026-10');
	await expect(preview.getByRole('link', { name: 'Read PDF', exact: true })).toHaveAttribute(
		'href',
		/item\/item-1\/pdf\/revision-1\?return_to=/
	);
	await preview.getByRole('button', { name: 'Copy DOI', exact: true }).click();
	await expect
		.poll(() => page.evaluate(() => (window as unknown as { copiedDoi: string }).copiedDoi))
		.toBe('10.1234/item-1');
	await expect(preview.getByRole('status')).toContainText('Copied to clipboard');
	expect(state.organizeReads()).toBe(0);
	await preview.getByRole('button', { name: 'Organize this Item', exact: true }).click();
	await expect(
		preview.getByRole('combobox', { name: 'Add a Tag to this Item', exact: true })
	).toBeVisible();
	expect(state.organizeReads()).toBe(1);
});

test('preview edits only its Item while keeping bulk selection and local failed Project confirmation', async ({
	page
}) => {
	const state = await mockPreviewLibrary(page, { failRemoveProject: true });
	await page.goto('/workspace/workspace-1/library');
	const selected = page.locator('[data-library-item-select="item-3"]');
	await selected.check();
	await page.getByRole('button', { name: 'Preview Item 1', exact: true }).click();
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await preview.getByRole('button', { name: 'Organize this Item', exact: true }).click();
	const tagInput = preview.getByRole('combobox', { name: 'Add a Tag to this Item', exact: true });
	await tagInput.fill('Methods');
	await page.getByRole('option', { name: 'Methods', exact: true }).click();
	await preview.getByRole('button', { name: 'Add tag', exact: true }).click();
	await expect(preview.getByRole('button', { name: 'Remove Methods', exact: true })).toBeVisible();
	await expect(tagInput).toHaveValue('');
	await preview.getByRole('button', { name: 'Remove Reviewed', exact: true }).click();
	await expect(preview.getByRole('button', { name: 'Remove Reviewed', exact: true })).toHaveCount(
		0
	);
	await tagInput.fill('Reproducibility');
	await page.keyboard.press('Escape');
	await preview.getByRole('button', { name: 'Add tag', exact: true }).click();
	await expect(
		preview.getByRole('button', { name: 'Remove Reproducibility', exact: true })
	).toBeVisible();
	await expect(selected).toBeChecked();
	expect(state.writes.map((write) => write.itemId)).toEqual(['item-1', 'item-1', 'item-1']);
	expect(state.assignments['item-3'].tags).toEqual([]);
	await preview.getByRole('combobox', { name: 'Add to a Project', exact: true }).click();
	await page.getByRole('option', { name: 'Evidence review', exact: true }).click();
	await preview.getByRole('button', { name: 'Add', exact: true }).click();
	const remove = preview.getByRole('button', { name: 'Remove from Evidence review', exact: true });
	await expect(remove).toBeVisible();
	await remove.click();
	const dialog = page.getByRole('dialog', { name: 'Remove Item from Project?', exact: true });
	await expect(dialog).toContainText(
		'permanently deletes all of its Project Annotations and Replies'
	);
	await dialog.getByRole('button', { name: 'Remove from Project', exact: true }).click();
	await expect(dialog.getByRole('alert')).toContainText('Something went wrong. Try again.');
	await dialog.getByRole('button', { name: 'Remove from Project', exact: true }).click();
	await expect(dialog).toHaveCount(0);
	await expect(remove).toHaveCount(0);
	await expect(
		preview.getByRole('heading', { name: 'Organize this Item', exact: true })
	).toBeFocused();
	expect(state.removeAttempts()).toBe(2);
	await expect(selected).toBeChecked();
});

test('failed tag assignment keeps its submitted draft and retries the captured Item', async ({
	page
}) => {
	const state = await mockPreviewLibrary(page, { failTagWrite: true });
	await page.goto('/workspace/workspace-1/library?preview=item-1');
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await preview.getByRole('button', { name: 'Organize this Item', exact: true }).click();
	const tagInput = preview.getByRole('combobox', { name: 'Add a Tag to this Item', exact: true });
	await tagInput.fill('Retry tag');
	await page.keyboard.press('Escape');
	await preview.getByRole('button', { name: 'Add tag', exact: true }).click();
	await expect(preview.getByRole('alert')).toContainText('Something went wrong. Try again.');
	await expect(tagInput).toHaveValue('Retry tag');
	await preview.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(
		preview.getByRole('button', { name: 'Remove Retry tag', exact: true })
	).toBeVisible();
	await expect(tagInput).toHaveValue('');
	expect(state.writes).toEqual([
		{ itemId: 'item-1', body: { add_tag_ids: [], remove_tag_ids: [], new_names: ['Retry tag'] } },
		{ itemId: 'item-1', body: { add_tag_ids: [], remove_tag_ids: [], new_names: ['Retry tag'] } }
	]);
});

test('pending organization stays scoped after collapsing or navigating to a different preview', async ({
	page
}) => {
	let release!: () => void;
	const gate = new Promise<void>((resolve) => {
		release = resolve;
	});
	const state = await mockPreviewLibrary(page, { beforeTagWrite: () => gate });
	await page.goto('/workspace/workspace-1/library?preview=item-1');
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	const organizeButton = preview.getByRole('button', { name: 'Organize this Item', exact: true });
	await organizeButton.click();
	const tagInput = preview.getByRole('combobox', { name: 'Add a Tag to this Item', exact: true });
	await tagInput.fill('Pending tag');
	await page.keyboard.press('Escape');
	await preview.getByRole('button', { name: 'Add tag', exact: true }).click();
	await expect.poll(() => state.writes.length).toBe(1);
	await organizeButton.click();
	await organizeButton.click();
	await expect(tagInput).toHaveValue('Pending tag');
	await expect(preview.getByRole('button', { name: 'Add tag', exact: true })).toBeDisabled();
	await preview.getByRole('button', { name: 'Next Item', exact: true }).click();
	await expect(page).toHaveURL(/preview=item-2/);
	await expect(preview).toContainText('Preview item-2');
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	await search.fill('draft stays here');
	release();
	await expect.poll(() => state.assignments['item-1'].tags.length).toBe(2);
	await expect(search).toBeFocused();
	await expect(search).toHaveValue('draft stays here');
	await expect(preview.getByText('Item organization updated', { exact: true })).toHaveCount(0);
	expect(state.assignments['item-2'].tags).toEqual([]);
});

test('preview keyboard navigation leaves editable fields and read-only organization alone', async ({
	page
}) => {
	await mockPreviewLibrary(page, { readOnly: true });
	await page.goto('/workspace/workspace-1/library?preview=item-1');
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	const heading = preview.getByRole('heading', { name: 'Item preview', exact: true });
	await expect(heading).toBeFocused();
	await heading.press('j');
	await expect(page).toHaveURL(/preview=item-2/);
	await preview.getByRole('button', { name: 'Organize this Item', exact: true }).click();
	await expect(preview.getByText('No assigned Projects', { exact: true })).toBeVisible();
	await expect(preview.getByRole('combobox')).toHaveCount(0);
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	await search.fill('j');
	await search.press('ArrowDown');
	await expect(page).toHaveURL(/preview=item-2/);
	await expect(search).toBeFocused();
});

test('narrow preview organization wraps long labels without horizontal overflow', async ({
	page
}) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await mockPreviewLibrary(page, { longLabels: true });
	await page.goto('/workspace/workspace-1/library?preview=item-1');
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await preview.getByRole('button', { name: 'Organize this Item', exact: true }).click();
	await expect(
		preview.getByRole('combobox', { name: 'Add a Tag to this Item', exact: true })
	).toBeVisible();
	expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
	await page.screenshot({ path: '/tmp/quirebase-preview-organize-mobile.png' });
});

test('removing the current Tag keeps a filtered-out preview open and continues with its successor', async ({
	page
}) => {
	await mockPreviewLibrary(page, { filterByTags: true });
	await page.goto('/workspace/workspace-1/library?tag=tag-reviewed&preview=item-2');
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await preview.getByRole('button', { name: 'Organize this Item', exact: true }).click();
	await preview.getByRole('button', { name: 'Remove Reviewed', exact: true }).click();
	await expect(preview).toContainText('Outside current results');
	await expect(page.locator('[data-library-item-select="item-2"]')).toHaveCount(0);
	await expect(preview).toContainText('Preview item-2');
	await preview.getByRole('button', { name: 'Next Item', exact: true }).click();
	await expect(page).toHaveURL(/preview=item-3/);
	await expect(preview).toContainText('Preview item-3');
});

test('removing the only result on the final page preserves preview through the page clamp', async ({
	page
}) => {
	await mockPreviewLibrary(page, { filterByTags: true, itemCount: 11 });
	await page.goto(
		'/workspace/workspace-1/library?tag=tag-reviewed&page_size=10&page=2&preview=item-11'
	);
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await preview.getByRole('button', { name: 'Organize this Item', exact: true }).click();
	await preview.getByRole('button', { name: 'Remove Reviewed', exact: true }).click();
	await expect.poll(() => new URL(page.url()).searchParams.get('page')).toBe(null);
	await expect(preview).toContainText('Preview item-11');
	await expect(preview).toContainText('Outside current results');
	await preview.getByRole('button', { name: 'Previous Item', exact: true }).click();
	await expect(page).toHaveURL(/preview=item-10/);
	await expect(preview).toContainText('Preview item-10');
	await expect(preview).toContainText('Item 10 of 10');
});

test('preview facets refine the submitted Library query while preserving sort and preview', async ({
	page
}) => {
	await mockPreviewLibrary(page);
	await page.goto(
		'/workspace/workspace-1/library?q=methods&year=2026&sort=title&direction=desc&page_size=10&preview=item-1'
	);
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await preview.getByRole('link', { name: 'Reviewed', exact: true }).click();
	await expect.poll(() => new URL(page.url()).searchParams.get('tag')).toBe('tag-reviewed');
	for (const [key, value] of Object.entries({
		q: 'methods',
		year: '2026',
		sort: 'title',
		direction: 'desc',
		page_size: '10',
		preview: 'item-1'
	})) {
		expect(new URL(page.url()).searchParams.get(key)).toBe(value);
	}
	await preview.getByRole('link', { name: 'Ada Lovelace', exact: true }).click();
	await expect
		.poll(() => new URL(page.url()).searchParams.get('author_last_name'))
		.toBe('Lovelace');
	expect(new URL(page.url()).searchParams.get('author_first_name')).toBe('Ada');
	expect(new URL(page.url()).searchParams.get('tag')).toBe('tag-reviewed');
	expect(new URL(page.url()).searchParams.get('preview')).toBe('item-1');
});

for (const status of [403, 404]) {
	test(`an authoritative ${status} organization refresh hides cached associations until recovery`, async ({
		page
	}) => {
		await mockPreviewLibrary(page);
		await page.goto('/workspace/workspace-1/library?preview=item-1');
		const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
		await preview.getByRole('button', { name: 'Organize this Item', exact: true }).click();
		await expect(
			preview.getByRole('button', { name: 'Remove Reviewed', exact: true })
		).toBeVisible();
		let denied = true;
		await page.route('**/api/v1/workspaces/*/items/item-1/organize', (route) =>
			denied
				? route.fulfill({
						status,
						json: {
							code: status === 403 ? 'permission_denied' : 'not_found',
							message: 'Unavailable'
						}
					})
				: route.fallback()
		);
		await preview.getByRole('button', { name: 'Refresh preview', exact: true }).click();
		await expect(preview.getByRole('alert')).toContainText(
			status === 403
				? 'You do not have permission to perform this action.'
				: 'The requested resource was not found.'
		);
		await expect(preview.getByRole('button', { name: 'Remove Reviewed', exact: true })).toHaveCount(
			0
		);
		await expect(preview.getByRole('combobox')).toHaveCount(0);
		await expect(preview.getByText('No tags', { exact: true })).toHaveCount(0);
		await preview.getByRole('button', { name: 'Organize this Item', exact: true }).click();
		await preview.getByRole('button', { name: 'Organize this Item', exact: true }).click();
		await expect(preview.getByRole('button', { name: 'Remove Reviewed', exact: true })).toHaveCount(
			0
		);
		denied = false;
		await preview.getByRole('button', { name: 'Retry', exact: true }).click();
		await expect(
			preview.getByRole('button', { name: 'Remove Reviewed', exact: true })
		).toBeVisible();
	});
}
