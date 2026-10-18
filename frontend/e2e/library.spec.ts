import { tagPage, directoryPage } from './helpers';
import { expect, test } from '@playwright/test';
import { chooseSearchOption, mockSession } from './helpers';

test('a Project filter outside the first directory page resolves directly and survives search', async ({
	page
}) => {
	await mockSession(page);
	const projects = Array.from({ length: 26 }, (_, index) => ({
		id: `project-${index + 1}`,
		name: `Project ${index + 1}`,
		item_count: 0,
		state: 'active',
		participation: 'workspace',
		is_participating: true,
		allowed_participation_changes: [],
		authorization: { allowed: [] }
	}));
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage(projects, route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-26', (route) =>
		route.fulfill({ json: { ...projects[25], active_participants: [] } })
	);
	const itemFilters: Array<string | null> = [];
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		itemFilters.push(new URL(route.request().url()).searchParams.get('project'));
		return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } });
	});

	await page.goto('/workspace/workspace-1/library?project=project-26');
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await expect(page.getByRole('combobox', { name: 'Project', exact: true })).toHaveValue(
		'Project 26'
	);
	await page.getByRole('combobox', { name: 'Project', exact: true }).click();
	await expect(page.getByRole('option', { name: 'Project 26', exact: true })).toHaveCount(1);
	await page.getByRole('combobox', { name: 'Project', exact: true }).press('Escape');
	await page.getByRole('button', { name: 'Load more Projects' }).click();
	await page.getByRole('combobox', { name: 'Project', exact: true }).click();
	await expect(page.getByRole('option', { name: 'Project 26', exact: true })).toHaveCount(1);
	await page.getByRole('combobox', { name: 'Project', exact: true }).press('Escape');
	await page.getByPlaceholder('Search title, author, Tag, or full text').fill('retained filter');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page).toHaveURL(/project=project-26/);
	await expect.poll(() => itemFilters.at(-1)).toBe('project-26');
});

test('library renders canonical rich titles and exposes later pages', async ({ page }) => {
	await mockSession(page);
	const requestedPages: number[] = [];
	const requestedQueries: Array<{ query: string | null; q: string | null }> = [];
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items*', (route) => {
		const searchParameters = new URL(route.request().url()).searchParams;
		const requestedPage = Number(searchParameters.get('offset') ?? '0') / 25 + 1;
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
				offset: (requestedPage - 1) * 25,
				limit: 25
			}
		});
	});

	await page.goto('/workspace/workspace-1/library');
	await expect(page.locator('strong i', { hasText: 'Visible' })).toBeVisible();
	await expect(page.locator('strong math msup')).toBeVisible();
	await expect(page.getByText('$x^2$', { exact: false })).toHaveCount(0);
	await page.getByPlaceholder('Search title, author, Tag, or full text').fill('quantum fields');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/library\?q=quantum\+fields$/);
	await expect.poll(() => requestedQueries).toContainEqual({ query: 'quantum fields', q: null });
	await page.getByRole('button', { name: 'Next page' }).click();
	await expect.poll(() => requestedPages).toContain(2);
	await expect.poll(() => requestedQueries.at(-1)).toEqual({ query: 'quantum fields', q: null });
	await expect(page.getByText('Second page Item')).toBeVisible();
});

test('Library page selection toggles and icon pagination reaches every boundary', async ({
	page
}) => {
	await mockSession(page);
	const requestedPages: number[] = [];
	await page.route('**/api/v1/account', (route) =>
		route.fulfill({
			json: {
				user: { id: 'user-1', username: 'reader', role: 'member' },
				sessions: [],
				api_tokens: []
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const currentPage =
			Number(new URL(route.request().url()).searchParams.get('offset') ?? '0') / 25 + 1;
		requestedPages.push(currentPage);
		return route.fulfill({
			json: {
				items: [1, 2].map((number) => ({
					id: `item-${currentPage}-${number}`,
					title_html: `Page ${currentPage} Item ${number}`,
					authors: 'A. Reader',
					publication_date: '2026',
					publication_title: null,
					doi: null,
					version: 1
				})),
				total: 75,
				offset: (currentPage - 1) * 25,
				limit: 25
			}
		});
	});

	await page.goto('/workspace/workspace-1/library');
	const pageSelection = page.getByLabel('Select this page');
	const itemSelections = page.locator('article input[type="checkbox"]');
	await pageSelection.check();
	await expect(page.locator('article input[type="checkbox"]:checked')).toHaveCount(2);
	await pageSelection.uncheck();
	await expect(page.locator('article input[type="checkbox"]:checked')).toHaveCount(0);
	await expect(itemSelections).toHaveCount(2);

	await page.getByRole('button', { name: 'Last page' }).click();
	await expect.poll(() => requestedPages.at(-1)).toBe(3);
	await page.getByRole('button', { name: 'Previous page' }).click();
	await expect.poll(() => requestedPages.at(-1)).toBe(2);
	await page.getByRole('button', { name: 'First page' }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/library$/);
	await expect(page.getByText('Page 1 Item 1')).toBeVisible();
	await page.getByRole('button', { name: 'Next page' }).click();
	await expect(page).toHaveURL(/page=2/);
	await expect(page.getByText('Page 2 Item 1')).toBeVisible();
});

for (const nextPage of [false, true]) {
	test(`bulk completion preserves a newer selection on ${nextPage ? 'another' : 'the same'} Library page`, async ({
		page
	}) => {
		await mockSession(page);
		const items = Array.from({ length: 26 }, (_, i) => ({
			id: `item-${i}`,
			title_html: `Library Item ${i}`,
			authors: null,
			publication_date: null,
			publication_title: null,
			doi: null,
			version: 1
		}));
		await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
			route.fulfill({ json: directoryPage(items, route) })
		);
		await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
			route.fulfill({ json: directoryPage([], route) })
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
		const started = Promise.withResolvers<void>();
		const release = Promise.withResolvers<void>();
		const submitted: Array<{ item_ids: string[] }> = [];
		await page.route('**/api/v1/workspaces/workspace-1/items/bulk', async (route) => {
			submitted.push(route.request().postDataJSON());
			started.resolve();
			await release.promise;
			return route.fulfill({ json: { ok: true } });
		});
		await page.goto('/workspace/workspace-1/library');
		await page.locator('article input[type=checkbox]').first().check();
		await page.getByRole('combobox', { name: 'Bulk action', exact: true }).selectOption('add_tag');
		await chooseSearchOption(page, 'Select Tag', 'Methods');
		await page.getByRole('button', { name: 'Apply', exact: true }).click();
		await started.promise;
		try {
			if (nextPage) {
				await page.getByRole('button', { name: 'Next page', exact: true }).click();
				await expect(page.getByText('Library Item 25', { exact: true })).toBeVisible();
			} else {
				await page.getByRole('button', { name: 'Clear selection', exact: true }).click();
			}
			const newerSelection = page.locator('article input[type=checkbox]').first();
			await newerSelection.check();
			release.resolve();
			await expect(page.getByText('Bulk action completed', { exact: true })).toBeVisible();
			await expect(newerSelection).toBeChecked();
			await page.getByRole('button', { name: 'Apply', exact: true }).click();
			await expect(newerSelection).not.toBeChecked();
			expect(submitted.map((body) => body.item_ids)).toEqual([
				['item-0'],
				[nextPage ? 'item-25' : 'item-0']
			]);
		} finally {
			release.resolve();
		}
	});
}

test('Library history navigation restores filter drafts and clears selection', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const query = new URL(route.request().url()).searchParams.get('query') ?? 'all';
		return route.fulfill({
			json: {
				items: [
					{
						id: `item-${query}`,
						title_html: `Result for ${query}`,
						authors: 'A. Reader',
						publication_date: '2026',
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 1,
				limit: 25,
				offset: 0
			}
		});
	});

	await page.goto('/workspace/workspace-1/library');
	const search = page.getByPlaceholder('Search title, author, Tag, or full text');
	await search.fill('foo');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/library\?q=foo/);
	await expect(page.getByText('Result for foo')).toBeVisible();

	await search.fill('bar');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/library\?q=bar/);
	await expect(page.getByText('Result for bar')).toBeVisible();
	await page.locator('article input[type="checkbox"]').check();
	await expect(page.getByText('1 selected')).toBeVisible();

	await page.goBack();
	await expect(page).toHaveURL(/\/workspace\/workspace-1\/library\?q=foo/);
	await expect(page.getByText('Result for foo')).toBeVisible();
	await expect(search).toHaveValue('foo');
	await expect(page.getByText('1 selected')).toHaveCount(0);
});

test('adding a Library Item invalidates a previously opened Project', async ({ page }) => {
	await mockSession(page);
	let added = false;
	let projectReads = 0;
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects/project-1', (route) => {
		projectReads += 1;
		return route.fulfill({
			json: {
				id: 'project-1',
				name: 'Research',
				description: 'Reading list',
				authorization: {
					allowed: [
						'project.update',
						'project.archive',
						'project_item.manage',
						'project_participation.manage',
						'project.delete'
					]
				},
				item_count: added ? 1 : 0,
				state: 'active',
				participation: 'workspace',
				is_participating: true,
				allowed_participation_changes: ['workspace', 'open', 'managed'],
				active_participants: [{ user_id: 'user-1', username: 'reader' }]
			}
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({
			json: directoryPage(
				[
					{
						id: 'project-1',
						name: 'Research',
						authorization: {
							allowed: [
								'project.update',
								'project.archive',
								'project_item.manage',
								'project_participation.manage',
								'project.delete'
							]
						},
						is_participating: true,
						item_count: added ? 1 : 0,
						state: 'active',
						participation: 'workspace',
						allowed_participation_changes: ['workspace', 'open', 'managed'],
						description: 'Reading list'
					}
				],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({
			json: {
				items: [
					{
						id: 'item-1',
						title_html: 'Newly added Item',
						authors: 'A. Reader',
						publication_date: '2026',
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				total: 1,
				limit: 25,
				offset: 0
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/bulk', (route) => {
		added = true;
		return route.fulfill({ json: { ok: true } });
	});

	await page.goto('/workspace/workspace-1/projects/project-1');
	await expect.poll(() => projectReads).toBe(1);
	await page.getByRole('link', { name: 'Library', exact: true }).first().click();
	await page.getByLabel('Select this page').check();
	await page.getByLabel('Bulk action').selectOption('add_project');
	await chooseSearchOption(page, 'Select Project', 'Research');
	await page.getByRole('button', { name: 'Apply' }).click();
	await expect(page.getByText('Bulk action completed')).toBeVisible();
	await page.getByRole('link', { name: 'Projects', exact: true }).first().click();
	await page.getByRole('link').filter({ hasText: 'Research' }).click();
	await expect.poll(() => projectReads).toBeGreaterThan(1);
	await expect(page.getByText('Newly added Item')).toBeVisible();
});

for (const workspaceId of ['workspace-1', 'workspace-2']) {
	test(`saved export preferences flow into Library and Item bibliography requests in ${workspaceId}`, async ({
		page
	}) => {
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
		await page.route('**/api/v1/workspaces/workspace-1/citation-styles*', (route) =>
			route.fulfill({
				json: {
					styles: [
						{ key: 'apa', name: 'APA' },
						{ key: 'custom-style-1', name: 'Custom style' }
					]
				}
			})
		);
		await page.route('**/api/v1/account/citation-key-preview*', (route) =>
			route.fulfill({ json: { key: 'Reader2026' } })
		);

		await page.goto('/account');
		await chooseSearchOption(page, 'Workspace for citation style', 'Research');
		await page
			.getByLabel('Default CSL style')
			.getByRole('option', { name: 'Custom style', exact: true })
			.click();
		await page.getByLabel('Default citation format').selectOption('bibtex');
		await page.getByLabel('Include abstract').uncheck();
		await page
			.getByRole('combobox', { name: 'BibTeX character representation' })
			.selectOption('latex');
		await page.getByRole('checkbox', { name: 'Preserve BibTeX title case' }).check();
		await page.getByRole('combobox', { name: 'Output sorting' }).selectOption('author');
		await page.getByRole('combobox', { name: 'DOI policy' }).selectOption('omit');
		await page.getByRole('combobox', { name: 'URL policy' }).selectOption('omit_when_doi');
		await page.getByRole('textbox', { name: 'Excluded fields' }).fill('abstract, publisher');
		await expect
			.poll(() =>
				page.evaluate(
					() =>
						JSON.parse(localStorage.getItem('quirebase:export-preferences:v1:account:user-1')!)
							.citation
				)
			)
			.toMatchObject({
				format: 'bibtex',
				includeAbstract: false,
				encoding: 'latex',
				preserveCase: true,
				doiPolicy: 'omit',
				urlPolicy: 'omit_when_doi',
				excludedFields: 'abstract, publisher',
				sortBy: 'author'
			});
		await page.reload();
		await page.getByRole('tab', { name: 'BibTeX', exact: true }).click();
		await expect(
			page.getByRole('combobox', { name: 'BibTeX character representation' })
		).toHaveValue('latex');
		await expect(page.getByRole('checkbox', { name: 'Preserve BibTeX title case' })).toBeChecked();

		let exportBody: Record<string, unknown> | null = null;
		await page.route(`**/api/v1/workspaces/${workspaceId}/items*`, (route) =>
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
					limit: 25,
					offset: 0
				}
			})
		);
		await page.route(`**/api/v1/workspaces/${workspaceId}/tags?*`, (route) =>
			route.fulfill({ json: tagPage([], route) })
		);
		await page.route(`**/api/v1/workspaces/${workspaceId}/projects?view=all*`, (route) =>
			route.fulfill({ json: directoryPage([], route) })
		);
		await page.route(`**/api/v1/workspaces/${workspaceId}/items/bibliography`, (route) => {
			exportBody = route.request().postDataJSON();
			return route.fulfill({
				body: '@article{Reader2026}',
				headers: { 'Content-Disposition': 'attachment; filename="items.bib"' }
			});
		});

		await page.goto(`/workspace/${workspaceId}/library`);
		await page.getByLabel('Select A. Author').check();
		await page.getByLabel('Bulk action').selectOption('bibliography');
		await page.getByRole('button', { name: 'Apply' }).click();
		await expect
			.poll(() => exportBody)
			.toMatchObject({
				file_format: 'bibtex',
				style: workspaceId === 'workspace-1' ? 'custom-style-1' : 'apa',
				include_abstract: false,
				encoding: 'latex',
				preserve_case: true,
				doi_policy: 'omit',
				url_policy: 'omit_when_doi',
				sort_by: 'author',
				excluded_fields: ['abstract', 'publisher']
			});

		await page.route(`**/api/v1/workspaces/${workspaceId}/items/item-1/overview`, (route) =>
			route.fulfill({
				json: {
					metadata: {
						id: 'urn:uuid:00000000-0000-4000-8000-000000000001',
						type: 'Other',
						title: 'Exportable'
					},
					citation_key: null,
					id: 'item-1',
					version: 1,
					latest_revision_id: null,
					authorization: { allowed: ['workspace.export'] },
					counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
					tags: [],
					copy_targets: []
				}
			})
		);
		let itemParameters: URLSearchParams | null = null;
		await page.route(`**/api/v1/workspaces/${workspaceId}/items/item-1/bibliography?*`, (route) => {
			itemParameters = new URL(route.request().url()).searchParams;
			return route.fulfill({
				body: '@article{Reader2026}',
				headers: { 'Content-Disposition': 'attachment; filename="item.bib"' }
			});
		});
		await page.goto(`/workspace/${workspaceId}/item/item-1`);
		await page.getByRole('button', { name: 'Export', exact: true }).click();
		await page.getByRole('button', { name: 'Download file' }).click();
		await expect
			.poll(() => itemParameters?.get('style'))
			.toBe(workspaceId === 'workspace-1' ? 'custom-style-1' : 'apa');
		expect(Object.fromEntries(itemParameters!)).toMatchObject({
			encoding: 'latex',
			preserve_case: 'true',
			doi_policy: 'omit',
			url_policy: 'omit_when_doi',
			sort_by: 'author'
		});
		expect(itemParameters!.getAll('excluded_fields')).toEqual(['abstract', 'publisher']);
	});
}

test('library filters do not overflow narrow viewports', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 720 });
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items*', (route) =>
		route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
	);

	await page.goto('/workspace/workspace-1/library');
	await expect(page.getByPlaceholder('Search title, author, Tag, or full text')).toBeVisible();
	const { scrollWidth, innerWidth } = await page.evaluate(() => ({
		scrollWidth: document.documentElement.scrollWidth,
		innerWidth: window.innerWidth
	}));
	expect(scrollWidth).toBeLessThanOrEqual(innerWidth);
});

test('Library sort and file filters persist in navigation and use typed API filters', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	const requests: Array<{ sort: string | null; files: string | null }> = [];
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const params = new URL(route.request().url()).searchParams;
		requests.push({ sort: params.get('sort'), files: params.get('has_files') });
		return route.fulfill({ json: directoryPage([], route) });
	});
	await page.goto('/workspace/workspace-1/library');
	await page.getByRole('combobox', { name: 'Sort By', exact: true }).selectOption('title');
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await page.getByRole('combobox', { name: 'Files', exact: true }).selectOption('false');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect.poll(() => requests.at(-1)).toEqual({ sort: 'title', files: 'false' });
	await expect(page).toHaveURL(/sort=title&has_files=false/);
	await page.reload();
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await expect(page.getByRole('combobox', { name: 'Sort By', exact: true })).toHaveValue('title');
	await expect(page.getByRole('combobox', { name: 'Files', exact: true })).toHaveValue('false');
});

test('Library year calendar keeps numeric year filters and searchable selectors support keyboard selection', async ({
	page
}) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) =>
		route.fulfill({
			json: tagPage(
				[
					{ id: 'tag-1', name: 'Methods' },
					{ id: 'tag-2', name: 'Results' }
				],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	const filters: Array<{ year: string | null; tag: string | null }> = [];
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const params = new URL(route.request().url()).searchParams;
		filters.push({ year: params.get('year'), tag: params.get('tag') });
		return route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } });
	});
	await page.goto('/workspace/workspace-1/library');
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const year = page.getByRole('textbox', { name: 'Year', exact: true });
	await year.fill('2024');
	await page.getByRole('button', { name: 'Choose date for Year', exact: true }).click();
	await page
		.getByRole('application', { name: 'Calendar for Year', exact: true })
		.getByRole('button', { name: '2023', exact: true })
		.click();
	const tag = page.getByRole('combobox', { name: 'Tag', exact: true });
	await tag.fill('Meth');
	await expect(page.getByRole('option', { name: 'Methods', exact: true })).toBeVisible();
	await tag.press('ArrowDown');
	await tag.press('Enter');
	await expect(tag).toHaveValue('Methods');
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect.poll(() => filters.at(-1)).toEqual({ year: '2023', tag: 'tag-1' });
	await page.getByRole('button', { name: 'Clear filters' }).click();
	await expect(year).toHaveValue('');
	await expect(tag).toHaveValue('');
});

test('Library loads Tag options on demand, searches server pages and resolves a selected Tag outside the first page', async ({
	page
}) => {
	await mockSession(page);
	const tags = Array.from({ length: 60 }, (_, index) => ({
		id: `tag-${index + 1}`,
		name: `Tag ${String(index + 1).padStart(2, '0')}`
	}));
	const reads: Array<{ offset: number; search: string | null; tag: string | null; limit: number }> =
		[];
	await page.route('**/api/v1/workspaces/workspace-1/tags?*', (route) => {
		const query = new URL(route.request().url()).searchParams;
		reads.push({
			offset: Number(query.get('offset') ?? 0),
			limit: Number(query.get('limit')),
			search: query.get('search'),
			tag: query.get('tag_id')
		});
		return route.fulfill({ json: tagPage(tags, route) });
	});
	await page.route('**/api/v1/workspaces/workspace-1/projects?view=all*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
		route.fulfill({ json: { items: [], total: 0, limit: 25, offset: 0 } })
	);
	await page.goto('/workspace/workspace-1/library');
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	expect(reads).toEqual([]);
	await page.getByRole('button', { name: 'Show options for Tag', exact: true }).click();
	await expect(page.getByRole('option', { name: 'Tag 25', exact: true })).toBeVisible();
	await expect(page.getByRole('option', { name: 'Tag 26', exact: true })).toHaveCount(0);
	expect(reads).toEqual([{ offset: 0, limit: 25, search: null, tag: null }]);
	await page.getByRole('button', { name: 'Load more Tags', exact: true }).click();
	await expect(page.getByRole('option', { name: 'Tag 50', exact: true })).toBeVisible();
	expect(reads[1].offset).toBe(25);
	const loadMore = page.getByRole('button', { name: 'Load more Tags', exact: true });
	await loadMore.focus();
	await loadMore.press('Enter');
	await expect(page.getByRole('option', { name: 'Tag 60', exact: true })).toBeVisible();
	expect(reads[2].offset).toBe(50);
	await chooseSearchOption(page, 'Tag', 'Tag 60');
	await expect
		.poll(() => reads.some((read) => read.search === 'Tag 60' && read.offset === 0))
		.toBe(true);
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page).toHaveURL(/tag=tag-60/);
	await page.reload();
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await expect(page.getByRole('combobox', { name: 'Tag', exact: true })).toHaveValue('Tag 60');
	await expect
		.poll(() => reads.some((read) => read.tag === 'tag-60' && read.limit === 1))
		.toBe(true);
});
