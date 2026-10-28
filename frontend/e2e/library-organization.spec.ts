import { expect, test, type Page } from '@playwright/test';
import type { components } from '../src/lib/api/schema.js';
import {
	chooseSearchOption,
	directoryPage,
	mockSession,
	openLibraryAction,
	projectPage,
	tagPage
} from './helpers';

const libraryPath = '/workspace/workspace-1/library';
const importPath = '/workspace/workspace-1/import';
const batchId = '10000000-0000-4000-8000-000000000001';

function optionName(name: string, kind: string) {
	return `${name} ${kind}`;
}

async function mockOrganization(
	page: Page,
	{ count = 30, importedCount = count }: { count?: number; importedCount?: number } = {}
) {
	await mockSession(page);
	const items: components['schemas']['ItemSearchView'][] = Array.from(
		{ length: count },
		(_, index) => ({
			id: `item-${index + 1}`,
			title_html: `Reading Item ${String(index + 1).padStart(2, '0')}`,
			authors: [{ last_name: 'Smith', first_name: 'Ada', full_name: 'Ada Smith' }],
			publication_date: '2026',
			publication_title: 'Reading Journal',
			doi: null,
			version: 1
		})
	);
	const importedIds = items.slice(0, importedCount).map(({ id }) => id);
	const assignments = new Map(items.map(({ id }) => [id, { files: false, tag: '', project: '' }]));
	const itemReads: URL[] = [];
	const tagReads: URL[] = [];
	const projectDetailReads: string[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const url = new URL(route.request().url());
		itemReads.push(url);
		const parameters = url.searchParams;
		const filtered = items.filter(({ id }) => {
			const assigned = assignments.get(id)!;
			return (
				(!parameters.has('import_batch') || importedIds.includes(id)) &&
				(!parameters.has('has_files') ||
					assigned.files === (parameters.get('has_files') === 'true')) &&
				(!parameters.has('has_tags') ||
					Boolean(assigned.tag) === (parameters.get('has_tags') === 'true')) &&
				(!parameters.has('has_projects') ||
					Boolean(assigned.project) === (parameters.get('has_projects') === 'true')) &&
				(!parameters.has('tag') || assigned.tag === parameters.get('tag')) &&
				(!parameters.has('project') || assigned.project === parameters.get('project'))
			);
		});
		return route.fulfill({ json: directoryPage(filtered, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) => {
		tagReads.push(new URL(route.request().url()));
		return route.fulfill({
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
		});
	});
	const project = {
		id: 'project-1',
		name: 'Reading Project',
		description: '',
		item_count: 0,
		state: 'active',
		participation: 'workspace',
		is_participating: true,
		allowed_participation_changes: [],
		authorization: { allowed: ['project_item.manage'] },
		active_participants: []
	};
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: projectPage([project], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/*', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-1)!;
		projectDetailReads.push(id);
		return id === project.id
			? route.fulfill({ json: project })
			: route.fulfill({ status: 404, json: { detail: 'Unknown Project' } });
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/*/overview', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		return route.fulfill({
			json: {
				id,
				version: 1,
				citation_key: null,
				metadata: {
					id: `urn:${id}`,
					type: 'JournalArticle',
					title: `Preview ${id}`
				},
				authorization: { allowed: ['item.update'] },
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				tags: assignments.get(id)?.tag ? [{ id: assignments.get(id)!.tag, name: 'Methods' }] : [],
				latest_revision_id: null,
				thumbnail: null,
				copy_targets: []
			}
		});
	});
	const batch: components['schemas']['ImportBatchPreview'] = {
		id: batchId,
		file_format: 'metadata',
		status: 'committed',
		workflow_id: null,
		can_retry: false,
		created_at: '2026-10-21T00:00:00Z',
		committed_item_ids: importedIds,
		records: [],
		errors: []
	};
	await page.route(`**/api/v1/workspaces/workspace-1/imports/${batchId}`, (route) =>
		route.fulfill({ json: batch })
	);
	const mutations: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		const body = route.request().postDataJSON();
		mutations.push(body);
		for (const id of body.item_ids as string[]) {
			const assigned = assignments.get(id)!;
			if (body.action === 'add_tag') assigned.tag = 'tag-1';
			if (body.action === 'add_project') assigned.project = body.project_id;
		}
		return route.fulfill({ json: { ok: true } });
	});
	return { itemReads, mutations, importedIds, tagReads, projectDetailReads, assignments };
}

async function chooseAll(page: Page, label: 'Tag' | 'Project') {
	await page.getByRole('button', { name: `Show options for ${label}`, exact: true }).click();
	await page
		.getByRole('listbox', { name: label, exact: true })
		.getByRole('option', {
			name:
				label === 'Tag'
					? optionName('All Tags', 'Condition')
					: optionName('All Projects', 'Condition'),
			exact: true
		})
		.click();
	await page
		.getByRole('combobox', { name: label, exact: true })
		.evaluate(
			() =>
				new Promise<void>((resolve) =>
					requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
				)
		);
}

async function expectParameters(page: Page, expected: Record<string, string>) {
	await expect.poll(() => Object.fromEntries(new URL(page.url()).searchParams)).toEqual(expected);
}

test('organization criteria stay inside Filters and submit together while preserving the reading scope', async ({
	page
}) => {
	const { itemReads, tagReads, projectDetailReads } = await mockOrganization(page);
	const scope = {
		q: 'reading',
		import_batch: batchId,
		sort: 'title',
		direction: 'desc',
		authors: JSON.stringify([{ last_name: 'Smith', first_name: 'Ada' }]),
		keyword_exact: 'graph theory',
		reference_type: 'JournalArticle',
		page_size: '10',
		preview: 'item-21'
	};
	await page.goto(`${libraryPath}?${new URLSearchParams({ ...scope, page: '3' })}`);
	await expect(page.locator('#library-preview')).toContainText('Preview item-21');
	await expect(page.getByRole('combobox', { name: 'Tag', exact: true })).not.toBeVisible();
	await expect(page.getByRole('combobox', { name: 'Project', exact: true })).not.toBeVisible();
	await expect(page.getByRole('combobox', { name: 'Files', exact: true })).not.toBeVisible();
	await expect(page.getByRole('group', { name: 'Organize Items', exact: true })).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Untagged', exact: true })).toHaveCount(0);
	await page.locator('[data-library-item-select="item-21"]').check();
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const readCount = itemReads.length;
	await page.getByRole('combobox', { name: 'Files', exact: true }).selectOption('false');
	await chooseSearchOption(page, 'Tag', 'Untagged', optionName('Untagged', 'Condition'));
	await chooseSearchOption(
		page,
		'Project',
		'Without Projects',
		optionName('Without Projects', 'Condition')
	);
	await expectParameters(page, { ...scope, page: '3' });
	expect(itemReads).toHaveLength(readCount);
	expect(tagReads.every((url) => !url.searchParams.has('tag_id'))).toBe(true);
	expect(projectDetailReads).toEqual([]);
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expectParameters(page, {
		...scope,
		has_files: 'false',
		has_tags: 'false',
		has_projects: 'false'
	});
	await expect(page.getByRole('region', { name: 'Bulk actions', exact: true })).toHaveCount(0);
	await expect(page.locator('#library-preview')).toContainText('Preview item-21');
	await expect.poll(() => itemReads.at(-1)?.searchParams.get('has_projects')).toBe('false');
	expect(itemReads.at(-1)?.searchParams.get('has_tags')).toBe('false');
	expect(itemReads.at(-1)?.searchParams.get('has_files')).toBe('false');
	expect(itemReads.at(-1)?.searchParams.get('import_batch')).toBe(batchId);
	expect(itemReads.at(-1)?.searchParams.get('offset')).toBe('0');
	const applied = page.getByRole('group', { name: 'Applied filters', exact: true });
	await applied
		.getByRole('button', { name: 'Remove filter Tag status: Untagged', exact: true })
		.click();
	await expectParameters(page, { ...scope, has_files: 'false', has_projects: 'false' });
	await expect(page.getByRole('combobox', { name: 'Tag', exact: true })).toHaveValue('');
	await expect(page.getByRole('combobox', { name: 'Tag', exact: true })).toHaveAttribute(
		'placeholder',
		'All Tags'
	);
	await applied
		.getByRole('button', {
			name: 'Remove filter Project assignment: Without Projects',
			exact: true
		})
		.click();
	await applied
		.getByRole('button', { name: 'Remove filter Files: Without files', exact: true })
		.click();
	await expectParameters(page, scope);
});

test('a preview Tag refinement replaces Tagged and removing it restores the full reading scope', async ({
	page
}) => {
	const { assignments, itemReads } = await mockOrganization(page, { count: 3, importedCount: 2 });
	assignments.get('item-1')!.tag = 'tag-1';
	const scope = {
		q: 'reading',
		import_batch: batchId,
		sort: 'title',
		direction: 'desc',
		has_files: 'false',
		page_size: '10',
		preview: 'item-1'
	};
	await page.goto(`${libraryPath}?${new URLSearchParams({ ...scope, has_tags: 'true' })}`);
	await expect(page.locator('[data-library-item-select]')).toHaveCount(1);
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await preview.getByRole('link', { name: 'Methods', exact: true }).click();
	await expectParameters(page, { ...scope, tag: 'tag-1' });
	await expect(preview).toContainText('Preview item-1');
	const applied = page.getByRole('group', { name: 'Applied filters', exact: true });
	const tag = applied.getByRole('button', { name: 'Remove filter Tag: Methods', exact: true });
	await expect(tag).toBeVisible();
	await expect(
		applied.getByRole('button', { name: 'Remove filter Tag status: Tagged', exact: true })
	).toHaveCount(0);
	await expect.poll(() => itemReads.at(-1)?.searchParams.get('tag')).toBe('tag-1');
	expect(itemReads.at(-1)?.searchParams.has('has_tags')).toBe(false);
	await tag.click();
	await expectParameters(page, scope);
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	await expect(page.locator('[data-library-item-select="item-2"]')).toBeVisible();
	await expect(preview).toContainText('Preview item-1');
	await expect(
		applied.getByRole('button', { name: 'Remove filter Tag status: Tagged', exact: true })
	).toHaveCount(0);
});

test('Search commits all filter drafts, paging preserves newer edits, and history restores submitted values', async ({
	page
}) => {
	const { itemReads } = await mockOrganization(page);
	await page.goto(`${libraryPath}?q=reading&page=2&page_size=10`);
	await expect(page.locator('[data-library-item-select="item-11"]')).toBeVisible();
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	const contributor = page.getByRole('textbox', { name: 'Contributor', exact: true });
	const keyword = page.getByRole('textbox', { name: 'Keyword', exact: true });
	await search.fill('organized');
	await contributor.fill('Ada Smith');
	await keyword.fill('review');
	await chooseSearchOption(page, 'Tag', 'Untagged', optionName('Untagged', 'Condition'));
	await expectParameters(page, { q: 'reading', page: '2', page_size: '10' });
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	const committed = {
		q: 'organized',
		author: 'Ada Smith',
		keyword: 'review',
		has_tags: 'false',
		page_size: '10'
	};
	await expectParameters(page, committed);
	await expect(page.locator('[data-library-item-select="item-1"]')).toBeVisible();
	const readCount = itemReads.length;
	await search.fill('newer search');
	await contributor.fill('newer contributor');
	await keyword.fill('newer keyword');
	await chooseSearchOption(page, 'Tag', 'Tagged', optionName('Tagged', 'Condition'));
	await chooseSearchOption(
		page,
		'Project',
		'Without Projects',
		optionName('Without Projects', 'Condition')
	);
	await page.getByRole('combobox', { name: 'Files', exact: true }).selectOption('false');
	await expectParameters(page, committed);
	expect(itemReads).toHaveLength(readCount);
	await page.getByRole('button', { name: 'Next page', exact: true }).click();
	await expectParameters(page, { ...committed, page: '2' });
	await expect(search).toHaveValue('newer search');
	await expect(contributor).toHaveValue('newer contributor');
	await expect(keyword).toHaveValue('newer keyword');
	await expect(page.getByRole('combobox', { name: 'Tag', exact: true })).toHaveValue('Tagged');
	await expect(page.getByRole('combobox', { name: 'Project', exact: true })).toHaveValue(
		'Without Projects'
	);
	await expect(page.getByRole('combobox', { name: 'Files', exact: true })).toHaveValue('false');
	await page.goBack();
	await expectParameters(page, committed);
	await expect(search).toHaveValue('organized');
	await expect(contributor).toHaveValue('Ada Smith');
	await expect(keyword).toHaveValue('review');
	await expect(page.getByRole('combobox', { name: 'Tag', exact: true })).toHaveValue('Untagged');
	await expect(page.getByRole('combobox', { name: 'Project', exact: true })).toHaveValue('');
	await expect(page.getByRole('combobox', { name: 'Files', exact: true })).toHaveValue('');
	await page.goBack();
	await expectParameters(page, { q: 'reading', page: '2', page_size: '10' });
	await expect(search).toHaveValue('reading');
	await expect(contributor).toHaveValue('');
	await expect(keyword).toHaveValue('');
	await expect(page.getByRole('combobox', { name: 'Tag', exact: true })).toHaveValue('');
});

test('specific, absence, presence and All choices replace each other without leaking preset identifiers', async ({
	page
}) => {
	const { itemReads, tagReads, projectDetailReads } = await mockOrganization(page);
	const absent = { has_files: 'false', has_tags: 'false', has_projects: 'false' };
	await page.goto(`${libraryPath}?${new URLSearchParams(absent)}`);
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await expect(page.getByRole('combobox', { name: 'Tag', exact: true })).toHaveValue('Untagged');
	await expect(page.getByRole('combobox', { name: 'Project', exact: true })).toHaveValue(
		'Without Projects'
	);
	await chooseSearchOption(page, 'Tag', 'Methods', optionName('Methods', 'Tag'));
	await chooseSearchOption(
		page,
		'Project',
		'Reading Project',
		optionName('Reading Project', 'Project')
	);
	await expectParameters(page, absent);
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expectParameters(page, { tag: 'tag-1', project: 'project-1', has_files: 'false' });
	await chooseSearchOption(page, 'Tag', 'Untagged', optionName('Untagged', 'Condition'));
	await chooseSearchOption(
		page,
		'Project',
		'Without Projects',
		optionName('Without Projects', 'Condition')
	);
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expectParameters(page, absent);
	await chooseSearchOption(page, 'Tag', 'Tagged', optionName('Tagged', 'Condition'));
	await chooseSearchOption(
		page,
		'Project',
		'With Projects',
		optionName('With Projects', 'Condition')
	);
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expectParameters(page, { has_files: 'false', has_tags: 'true', has_projects: 'true' });
	await chooseAll(page, 'Tag');
	await chooseAll(page, 'Project');
	await page.getByRole('combobox', { name: 'Files', exact: true }).selectOption('');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expectParameters(page, {});
	for (const url of itemReads) {
		expect([null, 'tag-1']).toContain(url.searchParams.get('tag'));
		expect([null, 'project-1']).toContain(url.searchParams.get('project'));
	}
	for (const url of tagReads) expect([null, 'tag-1']).toContain(url.searchParams.get('tag_id'));
	expect(projectDetailReads.every((id) => id === 'project-1')).toBe(true);
});

test('saved organization views reopen all absence filters and their Import scope after a reload', async ({
	page
}) => {
	await mockOrganization(page);
	const saved = {
		q: 'reading',
		import_batch: batchId,
		sort: 'title',
		has_files: 'false',
		has_tags: 'false',
		has_projects: 'false',
		page_size: '10'
	};
	await page.goto(
		`${libraryPath}?${new URLSearchParams({ ...saved, page: '2', preview: 'item-11' })}`
	);
	await page.getByRole('textbox', { name: 'Library Search', exact: true }).fill('unsaved draft');
	await page.getByRole('button', { name: 'Saved views', exact: true }).click();
	let dialog = page.getByRole('dialog', { name: 'Saved views', exact: true });
	await dialog.getByRole('textbox', { name: 'View name', exact: true }).fill('Import cleanup');
	await dialog.getByRole('button', { name: 'Save current view', exact: true }).click();
	if (!(await dialog.isVisible())) {
		await page.getByRole('button', { name: 'Saved views', exact: true }).click();
	}
	let view = dialog.getByRole('link', { name: 'Import cleanup', exact: true });
	await expect(view).toBeVisible();
	expect(
		Object.fromEntries(new URL((await view.getAttribute('href'))!, page.url()).searchParams)
	).toEqual(saved);
	await page.keyboard.press('Escape');
	await page.goto(libraryPath);
	await page.reload();
	await page.getByRole('button', { name: 'Saved views', exact: true }).click();
	dialog = page.getByRole('dialog', { name: 'Saved views', exact: true });
	view = dialog.getByRole('link', { name: 'Import cleanup', exact: true });
	await view.click();
	await expectParameters(page, saved);
	await expect(page.getByRole('textbox', { name: 'Library Search', exact: true })).toHaveValue(
		'reading'
	);
	await expect(page.locator('[data-library-item-select="item-1"]')).toBeVisible();
	await expect(page.locator('#library-preview')).toHaveCount(0);
	await expect(page.getByRole('combobox', { name: 'Tag', exact: true })).not.toBeVisible();
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await expect(page.getByRole('combobox', { name: 'Tag', exact: true })).toHaveValue('Untagged');
	await expect(page.getByRole('combobox', { name: 'Project', exact: true })).toHaveValue(
		'Without Projects'
	);
	await expect(page.getByRole('combobox', { name: 'Files', exact: true })).toHaveValue('false');
});

test('a committed Import Batch leads to a cleanup view where bulk Tag and Project assignments remove matching rows', async ({
	page
}) => {
	const { itemReads, mutations, importedIds } = await mockOrganization(page, {
		count: 3,
		importedCount: 2
	});
	await page.goto(`${importPath}?batch=${batchId}`);
	await page.getByRole('link', { name: 'View imported Items', exact: true }).click();
	await expectParameters(page, { import_batch: batchId });
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await chooseSearchOption(page, 'Tag', 'Untagged', optionName('Untagged', 'Condition'));
	await chooseSearchOption(
		page,
		'Project',
		'Without Projects',
		optionName('Without Projects', 'Condition')
	);
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await page.getByLabel('Select this page', { exact: true }).check();
	await openLibraryAction(page, 'add_tag');
	await chooseSearchOption(page, 'Select Tag', 'Methods');
	await page
		.getByRole('dialog', { name: 'Add Tag', exact: true })
		.getByRole('button', { name: 'Add Tag', exact: true })
		.click();
	await expect(page.getByText('No Items found.', { exact: true })).toBeVisible();
	await expect(page.getByRole('region', { name: 'Bulk actions', exact: true })).toHaveCount(0);
	await page
		.getByRole('button', { name: 'Remove filter Tag status: Untagged', exact: true })
		.click();
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(0);
	await page.getByLabel('Select this page', { exact: true }).check();
	await openLibraryAction(page, 'add_project');
	await chooseSearchOption(page, 'Select Project', 'Reading Project');
	await page
		.getByRole('dialog', { name: 'Add to Project', exact: true })
		.getByRole('button', { name: 'Add to Project', exact: true })
		.click();
	await expect(page.getByText('No Items found.', { exact: true })).toBeVisible();
	await expect(page.getByRole('region', { name: 'Bulk actions', exact: true })).toHaveCount(0);
	await page
		.getByRole('button', {
			name: 'Remove filter Project assignment: Without Projects',
			exact: true
		})
		.click();
	await expectParameters(page, { import_batch: batchId });
	await expect(page.locator('[data-library-item-select]')).toHaveCount(2);
	await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(0);
	expect(mutations).toEqual([
		{ action: 'add_tag', item_ids: importedIds, tag_name: 'Methods' },
		{ action: 'add_project', item_ids: importedIds, project_id: 'project-1' }
	]);
	expect(itemReads.every((url) => url.searchParams.get('import_batch') === batchId)).toBe(true);
	await page.getByRole('link', { name: 'Import Batch', exact: true }).click();
	await expect(page.getByText('Imported 2 records', { exact: true })).toBeVisible();
});

const selectorCopies = [
	{
		locale: 'en-US',
		filters: 'Filters',
		search: 'Search',
		tag: 'Tag',
		tags: 'Tags',
		project: 'Project',
		projects: 'Projects',
		conditions: 'Filter conditions',
		conditionKind: 'Condition',
		untagged: 'Untagged',
		unassigned: 'Without Projects',
		allTags: 'All Tags',
		allProjects: 'All Projects',
		condition: (name: string) => `Condition: ${name}`,
		tagName: (name: string) => `Tag: ${name}`,
		projectName: (name: string) => `Project: ${name}`,
		showOptions: (name: string) => `Show options for ${name}`,
		removeTagStatus: 'Remove filter Tag status: Untagged',
		removeTag: 'Remove filter Tag: Untagged',
		removeProjectStatus: 'Remove filter Project assignment: Without Projects'
	},
	{
		locale: 'zh-CN',
		filters: '筛选',
		search: '搜索',
		tag: '标签',
		tags: '标签',
		project: '项目',
		projects: '项目',
		conditions: '筛选条件',
		conditionKind: '条件',
		untagged: '未加标签',
		unassigned: '未归入项目',
		allTags: '全部标签',
		allProjects: '全部项目',
		condition: (name: string) => `条件：${name}`,
		tagName: (name: string) => `标签：${name}`,
		projectName: (name: string) => `项目：${name}`,
		showOptions: (name: string) => `显示${name}选项`,
		removeTagStatus: '移除筛选条件 标签状态: 未加标签',
		removeTag: '移除筛选条件 标签: 未加标签',
		removeProjectStatus: '移除筛选条件 项目归属: 未归入项目'
	}
];

type SelectorCopy = (typeof selectorCopies)[number];

async function mockNamedSelectors(page: Page, copy: SelectorCopy) {
	if (copy.locale === 'zh-CN') await page.setViewportSize({ width: 390, height: 844 });
	await mockOrganization(page, { count: 0 });
	await page.addInitScript(
		(locale) => localStorage.setItem('quirebase:locale', locale),
		copy.locale
	);
	const tags = [
		{ id: 'tag-condition', name: copy.untagged },
		{ id: 'tag-all', name: copy.allTags },
		{ id: 'tag-condition-name', name: copy.condition(copy.untagged) },
		{ id: 'tag-typed-name', name: copy.tagName(copy.untagged) },
		{ id: 'tag-2025', name: `${copy.tagName(copy.untagged)}-2025` },
		{ id: 'tag-2026', name: `${copy.tagName(copy.untagged)}-2026` }
	];
	const projects = [
		{ id: 'project-condition', name: copy.unassigned },
		{ id: 'project-all', name: copy.allProjects },
		{ id: 'project-condition-name', name: copy.condition(copy.unassigned) },
		{ id: 'project-typed-name', name: copy.projectName(copy.unassigned) },
		{ id: 'project-2025', name: `${copy.projectName(copy.unassigned)}-2025` },
		{ id: 'project-2026', name: `${copy.projectName(copy.unassigned)}-2026` }
	].map((project) => ({
		...project,
		description: '',
		item_count: 0,
		state: 'active',
		participation: 'workspace',
		is_participating: true,
		allowed_participation_changes: [],
		authorization: { allowed: ['project_item.manage'] },
		active_participants: []
	}));
	const tagReads: URL[] = [];
	const projectReads: URL[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) => {
		tagReads.push(new URL(route.request().url()));
		return route.fulfill({ json: tagPage(tags, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) => {
		projectReads.push(new URL(route.request().url()));
		return route.fulfill({ json: projectPage(projects, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects/*', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-1);
		return route.fulfill({ json: projects.find((project) => project.id === id) });
	});
	await page.goto(libraryPath);
	await expect(page.locator('html')).toHaveAttribute('lang', copy.locale);
	await page.getByRole('button', { name: copy.filters, exact: true }).click();
	const tag = page.getByRole('combobox', { name: copy.tag, exact: true });
	const project = page.getByRole('combobox', { name: copy.project, exact: true });
	return {
		tag,
		project,
		pickers: [
			{
				field: tag,
				label: copy.tag,
				parameter: 'tag',
				base: copy.untagged,
				typedName: copy.tagName,
				reads: tagReads
			},
			{
				field: project,
				label: copy.project,
				parameter: 'project',
				base: copy.unassigned,
				typedName: copy.projectName,
				reads: projectReads
			}
		]
	};
}

for (const copy of selectorCopies) {
	test(`${copy.locale} separates filter conditions from identically named Tags and Projects`, async ({
		page
	}) => {
		const { tag, project, pickers } = await mockNamedSelectors(page, copy);
		let tagOptions = page.getByRole('listbox', { name: copy.tag, exact: true });
		await tag.fill(copy.untagged);
		await expect(
			tagOptions
				.getByRole('group', { name: copy.conditions, exact: true })
				.getByRole('option', { name: optionName(copy.untagged, copy.conditionKind), exact: true })
		).toBeVisible();
		await expect(
			tagOptions
				.getByRole('group', { name: copy.tags, exact: true })
				.getByRole('option', { name: optionName(copy.untagged, copy.tag), exact: true })
		).toBeVisible();
		await tag.press('ArrowDown');
		await tag.press('Enter');
		await expect(tag).toHaveValue(copy.untagged);
		await expect(tag).toHaveAccessibleDescription(copy.conditionKind);
		await chooseSearchOption(
			page,
			copy.project,
			copy.unassigned,
			optionName(copy.unassigned, copy.conditionKind)
		);
		await expect(project).toHaveValue(copy.unassigned);
		await expect(project).toHaveAccessibleDescription(copy.conditionKind);
		await page.getByRole('button', { name: copy.search, exact: true }).click();
		await expectParameters(page, { has_tags: 'false', has_projects: 'false' });
		await expect(
			page.getByRole('button', { name: copy.removeTagStatus, exact: true })
		).toBeVisible();
		await expect(
			page.getByRole('button', { name: copy.removeProjectStatus, exact: true })
		).toBeVisible();
		await chooseSearchOption(page, copy.tag, copy.untagged, optionName(copy.untagged, copy.tag));
		await chooseSearchOption(
			page,
			copy.project,
			copy.unassigned,
			optionName(copy.unassigned, copy.project)
		);
		await page.getByRole('button', { name: copy.search, exact: true }).click();
		await expectParameters(page, { tag: 'tag-condition', project: 'project-condition' });
		await expect(page.getByRole('button', { name: copy.removeTag, exact: true })).toBeVisible();
		await expect(page.getByRole('button', { name: copy.removeTagStatus, exact: true })).toHaveCount(
			0
		);
		await page.reload();
		await page.getByRole('button', { name: copy.filters, exact: true }).click();
		await expect(tag).toHaveValue(copy.untagged);
		await expect(project).toHaveValue(copy.unassigned);
		await expect(tag).toHaveAccessibleDescription(copy.tag);
		await expect(project).toHaveAccessibleDescription(copy.project);
		for (const picker of pickers) {
			for (const name of [copy.condition(picker.base), picker.typedName(picker.base)]) {
				await chooseSearchOption(page, picker.label, name, optionName(name, picker.label));
				await expect(picker.field).toHaveValue(name);
				await expect(picker.field).toHaveAccessibleDescription(picker.label);
			}
		}
		await page.getByRole('button', { name: copy.search, exact: true }).click();
		await expectParameters(page, { tag: 'tag-typed-name', project: 'project-typed-name' });
		await chooseSearchOption(page, copy.tag, copy.allTags, optionName(copy.allTags, copy.tag));
		await chooseSearchOption(
			page,
			copy.project,
			copy.allProjects,
			optionName(copy.allProjects, copy.project)
		);
		await page.getByRole('button', { name: copy.search, exact: true }).click();
		await expectParameters(page, { tag: 'tag-all', project: 'project-all' });
		await expect(tag).toHaveValue(copy.allTags);
		await expect(project).toHaveValue(copy.allProjects);
		await page.getByRole('button', { name: copy.showOptions(copy.tag), exact: true }).click();
		tagOptions = page.getByRole('listbox', { name: copy.tag, exact: true });
		await expect(
			tagOptions
				.getByRole('group', { name: copy.tags, exact: true })
				.getByRole('option', { name: optionName(copy.allTags, copy.tag), exact: true })
		).toBeVisible();
		await tagOptions
			.getByRole('group', { name: copy.conditions, exact: true })
			.getByRole('option', { name: optionName(copy.allTags, copy.conditionKind), exact: true })
			.click();
		await page.getByRole('button', { name: copy.showOptions(copy.project), exact: true }).click();
		const projectOptions = page.getByRole('listbox', { name: copy.project, exact: true });
		await expect(
			projectOptions
				.getByRole('group', { name: copy.projects, exact: true })
				.getByRole('option', { name: optionName(copy.allProjects, copy.project), exact: true })
		).toBeVisible();
		await projectOptions
			.getByRole('group', { name: copy.conditions, exact: true })
			.getByRole('option', { name: optionName(copy.allProjects, copy.conditionKind), exact: true })
			.click();
		await page.getByRole('button', { name: copy.search, exact: true }).click();
		await expectParameters(page, {});
		await expect(tag).toHaveValue('');
		await expect(tag).toHaveAttribute('placeholder', copy.allTags);
		await expect(project).toHaveValue('');
		await expect(project).toHaveAttribute('placeholder', copy.allProjects);
	});

	test(`${copy.locale} edits selected Tag and Project suffixes using their raw names`, async ({
		page
	}) => {
		const { pickers } = await mockNamedSelectors(page, copy);
		const selected: Record<string, string> = {};
		for (const picker of pickers) {
			const original = `${picker.typedName(picker.base)}-2025`;
			const edited = `${picker.typedName(picker.base)}-2026`;
			await chooseSearchOption(page, picker.label, original, optionName(original, picker.label));
			await expect(picker.field).toHaveValue(original);
			await expect(picker.field).toHaveAccessibleDescription(picker.label);
			// Collapse the selection to its end; macOS End scrolls the document.
			await picker.field.press('ControlOrMeta+A');
			await picker.field.press('ArrowRight');
			await picker.field.press('Backspace');
			await picker.field.press('6');
			await expect(picker.field).toHaveValue(edited);
			await expect(picker.field).toHaveAccessibleDescription('');
			await expect.poll(() => picker.reads.at(-1)?.searchParams.get('search')).toBe(edited);

			await page
				.getByRole('listbox', { name: picker.label, exact: true })
				.getByRole('option', { name: optionName(edited, picker.label), exact: true })
				.click();
			await expect(picker.field).toHaveValue(edited);
			await expect(picker.field).toHaveAccessibleDescription(picker.label);
			await page.getByRole('button', { name: copy.search, exact: true }).click();
			selected[picker.parameter] = `${picker.parameter}-2026`;
			await expectParameters(page, selected);
		}
	});
}
