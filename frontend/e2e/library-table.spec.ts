import { openLibraryAction } from './helpers';
import AxeBuilder from '@axe-core/playwright';
import { readFile } from 'node:fs/promises';
import { expect, test, type Page } from '@playwright/test';
import { directoryPage, mockSession, tagPage } from './helpers';
import type { components } from '../src/lib/api/schema.js';

const items: components['schemas']['ItemSearchView'][] = Array.from(
	{ length: 100 },
	(_, index) => ({
		id: `item-${index + 1}`,
		title_html: index === 0 ? '<i>文献与公式</i> $x^2$ Research' : `Research Item ${index + 1}`,
		authors:
			index === 2
				? []
				: [
						{ full_name: `Author ${index + 1}`, last_name: `Author ${index + 1}`, first_name: null }
					],
		publication_date: ['2026', '2026-10', '2026-10-19', null][index % 4],
		publication_title: index === 2 ? null : 'Journal of Research',
		doi: index === 0 ? '10.1234/research' : null,
		version: 1
	})
);

function overview(id: string) {
	return {
		id,
		version: 1,
		citation_key: null,
		metadata: {
			id: `urn:${id}`,
			type: 'JournalArticle',
			title: `Preview ${id}`,
			description: `<b>Abstract ${id}</b> $x^2$`,
			date_published: '2026-10'
		},
		authorization: { allowed: ['item.update'] },
		copy_targets: [],
		counts: { revisions: 2, attachments: 1, annotations: 0, discussion: 0 },
		tags: [{ id: 'tag-1', name: 'Methods' }],
		latest_revision_id: 'revision-1',
		thumbnail: null
	};
}

async function mockLibrary(page: Page, rows = items) {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/*/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/workspaces/*/projects?*', (route) =>
		route.fulfill({ json: directoryPage([], route) })
	);
	const reads: URL[] = [];
	await page.route('**/api/v1/workspaces/*/items?*', (route) => {
		const url = new URL(route.request().url());
		reads.push(url);
		const limit = Number(url.searchParams.get('limit'));
		const offset = Number(url.searchParams.get('offset'));
		return route.fulfill({
			json: { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset }
		});
	});
	const previews: string[] = [];
	await page.route('**/api/v1/workspaces/*/items/*/overview', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-2)!;
		previews.push(id);
		return route.fulfill({ json: overview(id) });
	});
	return { reads, previews };
}

for (const view of ['table', 'list'] as const) {
	test(`${view} pointer and keyboard ranges share an anchor and can shrink`, async ({ page }) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		await mockLibrary(page);
		await page.goto('/workspace/workspace-1/library');
		const row = (number: number) => page.locator(`[data-library-item-select="item-${number}"]`);
		const selected = () =>
			page
				.locator('[data-library-item-select]:checked')
				.evaluateAll((elements) =>
					elements.map((element) => (element as HTMLInputElement).dataset.libraryItemSelect)
				);
		await row(2).click();
		await row(6).click({ modifiers: ['Shift'] });
		await expect.poll(selected).toEqual(['item-2', 'item-3', 'item-4', 'item-5', 'item-6']);
		await row(4).click({ modifiers: ['Shift'] });
		await expect.poll(selected).toEqual(['item-2', 'item-3', 'item-4']);
		await row(4).press('Shift+ArrowDown');
		await expect.poll(selected).toEqual(['item-2', 'item-3', 'item-4', 'item-5']);
		await row(1).click({ modifiers: ['Shift'] });
		await expect.poll(selected).toEqual(['item-1', 'item-2']);
		await row(1).press('Shift+ArrowDown');
		await expect.poll(selected).toEqual(['item-2']);
		await row(8).click();
		await row(10).click({ modifiers: ['Shift'] });
		await expect.poll(selected).toEqual(['item-8', 'item-9', 'item-10']);
	});

	test(`${view} clearing and changing the listing reset pointer ranges and preserve control focus`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		await mockLibrary(page);
		await page.goto('/workspace/workspace-1/library');
		const row = (number: number) => page.locator(`[data-library-item-select="item-${number}"]`);
		await row(2).click();
		await row(5).click({ modifiers: ['Shift'] });
		await page.getByRole('button', { name: 'Clear selection', exact: true }).click();
		await expect(page.locator('#library-results')).toBeFocused();
		await row(4).click({ modifiers: ['Shift'] });
		await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(1);
		const sort = page.getByRole('combobox', { name: 'Sort By', exact: true });
		await sort.selectOption('title');
		await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(0);
		await row(6).click({ modifiers: ['Shift'] });
		await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(1);
		await sort.selectOption('updated');
		await row(7).click({ modifiers: ['Shift'] });
		await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(1);
		await page.getByRole('button', { name: 'Next page', exact: true }).click();
		await row(28).click({ modifiers: ['Shift'] });
		await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(1);
		await page.getByRole('button', { name: 'Previous page', exact: true }).click();
		await row(3).click({ modifiers: ['Shift'] });
		await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(1);
		const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
		await search.fill('another query');
		await search.press('Enter');
		await expect(page).toHaveURL(/q=another\+query/);
		await row(9).click({ modifiers: ['Shift'] });
		await expect(page.locator('[data-library-item-select]:checked')).toHaveCount(1);
	});
}

for (const { view, fontSize } of (['table', 'list'] as const).flatMap((view) =>
	[16, 18, 20].map((fontSize) => ({ view, fontSize }))
)) {
	test(`${view} at ${fontSize}px folds whole author names, keeps the last credit when it fits and opens the existing preview`, async ({
		page
	}) => {
		await page.setViewportSize({ width: view === 'table' ? 1280 : 390, height: 900 });
		const names = [
			['A', 'B', 'C', 'D'],
			['Morgan Anderson', 'Taylor Johnson', 'Jordan Williams', 'Kimon P. Valavanis'],
			Array.from({ length: 60 }, (_, index) => `Contributor ${String(index + 1).padStart(2, '0')}`),
			['محمد الخوارزمي', 'أحمد زويل', 'אברהם לוי', 'שרה כהן'],
			['Only Author'],
			['E', 'F'],
			['First Author', 'Last Author with a very long credited name '.repeat(2)],
			['Single Author with a long but readable credited name']
		];
		const rows = items.slice(0, names.length).map((item, index) => ({
			...item,
			authors: names[index].map((name) => ({
				full_name: name,
				last_name: name,
				first_name: null
			}))
		}));
		await mockLibrary(page, rows);
		await page.route('**/api/v1/workspaces/*/items/item-3/overview', (route) => {
			const details = overview('item-3');
			return route.fulfill({
				json: {
					...details,
					metadata: {
						...details.metadata,
						contributors: names[2].map((name) => ({
							type: 'Person',
							roles: ['Author'],
							person: { family_name: name }
						}))
					}
				}
			});
		});
		await page.goto('/workspace/workspace-1/library?q=research&sort=title&direction=desc');
		await page.addStyleTag({ content: `html { font-size: ${fontSize}px; }` });
		await page
			.getByRole('radio', { name: view === 'table' ? 'Table' : 'List', exact: true })
			.press('Space');
		const row = (id: string) =>
			view === 'table'
				? page.locator(`tr[data-library-item="${id}"]`)
				: page.locator(`article[data-library-item="${id}"]`);
		const short = row('item-1');
		const medium = row('item-2');
		const crowded = row('item-3');
		const firstMediumAuthor = medium.getByRole('link', {
			name: 'View Items by Morgan Anderson',
			exact: true
		});
		const lastMediumAuthor = medium.getByRole('link', {
			name: 'View Items by Kimon P. Valavanis',
			exact: true
		});
		const ellipsis = (id: string) =>
			row(id).getByRole('button', { name: 'Show all authors', exact: true });
		const sizeAuthors = async (size: 'wide' | 'narrow') => {
			if (view === 'list') {
				await page.setViewportSize({ width: size === 'wide' ? 2400 : 390, height: 900 });
				return;
			}
			const resize = page.getByRole('button', { name: 'Resize Authors column', exact: true });
			if (size === 'narrow') await resize.dispatchEvent('keydown', { key: 'Home' });
			else
				for (let index = 0; index < 40; index++)
					await resize.dispatchEvent('keydown', { key: 'ArrowRight' });
		};
		const assertWholeVisibleNames = async () => {
			for (const [index, authorNames] of names.entries()) {
				const line = row(`item-${index + 1}`).getByTitle(authorNames.join('; '), { exact: true });
				await expect
					.poll(() =>
						line.evaluate((element, expectedNames) => {
							const bounds = element.getBoundingClientRect();
							const credits = Array.from(
								element.querySelectorAll<HTMLElement>('[data-author-index]')
							);
							if (credits.some((credit) => !credit.hidden) && credits[0].hidden) return false;
							let omitted = false;
							for (const credit of credits.slice(0, -1)) {
								if (credit.hidden) omitted = true;
								else if (omitted) return false;
							}
							if (
								Boolean(element.querySelector('button')) !== credits.some((credit) => credit.hidden)
							)
								return false;
							return credits.every((credit) => {
								if (credit.hidden) return credit.getClientRects().length === 0;
								const link = credit.querySelector('a')!;
								const box = credit.getBoundingClientRect();
								return (
									link.textContent === expectedNames[Number(credit.dataset.authorIndex)] &&
									box.left >= bounds.left - 1 &&
									box.right <= bounds.right + 1 &&
									box.height <= bounds.height + 1
								);
							});
						}, authorNames)
					)
					.toBe(true);
			}
		};

		// A narrow line may show only the omission marker; no particular name has to fit.
		await expect(ellipsis('item-2')).toBeVisible();
		await expect(ellipsis('item-3')).toHaveText('…');
		await assertWholeVisibleNames();

		// Leave ample room before asserting which complete names are displayed.
		await ellipsis('item-2').focus();
		await sizeAuthors('wide');
		await expect(short.getByRole('link', { name: /^View Items by / })).toHaveCount(4);
		await expect(ellipsis('item-1')).toHaveCount(0);
		await expect(medium.getByRole('link', { name: /^View Items by / })).toHaveCount(4);
		await expect(ellipsis('item-2')).toHaveCount(0);
		await expect(firstMediumAuthor).toBeFocused();
		await expect(row('item-5').getByRole('link', { name: /^View Items by / })).toHaveCount(1);
		await expect(ellipsis('item-5')).toHaveCount(0);
		await expect(row('item-6').getByRole('link', { name: /^View Items by / })).toHaveCount(2);
		await expect(ellipsis('item-6')).toHaveCount(0);
		await expect(row('item-8').getByRole('link', { name: /^View Items by / })).toHaveCount(1);
		await expect(ellipsis('item-8')).toHaveCount(0);

		// RTL names keep the author order, with visible names still available as filter links.
		const rtlAuthors = row('item-4').getByRole('link', { name: /^View Items by / });
		await expect(rtlAuthors).toHaveCount(4);
		const authorPositions = await rtlAuthors.evaluateAll((links) =>
			links.map((link) => link.getBoundingClientRect().left)
		);
		expect(authorPositions).toEqual([...authorPositions].sort((a, b) => a - b));

		await assertWholeVisibleNames();

		// A focused name that no longer fits transfers focus to the omission marker.
		await lastMediumAuthor.focus();
		await sizeAuthors('narrow');
		await expect(ellipsis('item-2')).toBeVisible();
		await expect(lastMediumAuthor).toBeHidden();
		await expect(ellipsis('item-2')).toBeFocused();
		await assertWholeVisibleNames();

		// Give both complete end credits room before checking their keyboard order.
		await sizeAuthors('wide');
		await expect(
			crowded.getByRole('link', { name: 'View Items by Contributor 01', exact: true })
		).toBeVisible();
		const lastAuthor = crowded.getByRole('link', {
			name: 'View Items by Contributor 60',
			exact: true
		});
		await expect(lastAuthor).toBeVisible();
		await assertWholeVisibleNames();
		const visibleAuthors = crowded.getByRole('link', { name: /^View Items by / });
		expect(await visibleAuthors.count()).toBeGreaterThan(1);
		expect(await visibleAuthors.count()).toBeLessThan(60);
		await visibleAuthors.nth((await visibleAuthors.count()) - 2).focus();
		await page.keyboard.press('Tab');
		await expect(ellipsis('item-3')).toBeFocused();
		await page.keyboard.press('Tab');
		await expect(lastAuthor).toBeFocused();
		await page.keyboard.press('Shift+Tab');
		await page.keyboard.press('Enter');
		const preview = page.getByRole('complementary', { name: 'Item preview' });
		await expect(preview.getByRole('link', { name: /^Contributor / })).toHaveCount(60);
		await expect(preview.getByRole('link', { name: 'Contributor 60', exact: true })).toBeVisible();
		let parameters = new URL(page.url()).searchParams;
		expect(parameters.get('preview')).toBe('item-3');
		expect(parameters.get('q')).toBe('research');
		expect(parameters.get('sort')).toBe('title');
		expect(parameters.get('direction')).toBe('desc');
		await preview.getByRole('button', { name: 'Close preview', exact: true }).click();
		await expect(preview).toHaveCount(0);
		await expect(ellipsis('item-3')).toBeFocused();
		// Widening the results can remove the preview's original overflow trigger.
		await sizeAuthors('narrow');
		await ellipsis('item-2').click();
		await expect(preview).toBeVisible();
		await sizeAuthors('wide');
		await expect(ellipsis('item-2')).toHaveCount(0);
		await preview.getByRole('button', { name: 'Close preview', exact: true }).click();
		await expect(page.locator('#library-results')).toBeFocused();
		await short.getByRole('link', { name: 'View Items by D', exact: true }).click();
		await expect.poll(() => new URL(page.url()).searchParams.get('author_last_name')).toBe('D');
		parameters = new URL(page.url()).searchParams;
		expect(parameters.get('author_first_name')).toBe('');
		expect(parameters.get('q')).toBe('research');
		expect(parameters.get('sort')).toBe('title');
		expect(parameters.get('direction')).toBe('desc');
	});
}

test('bulk toolbar explains requirements, keeps failed targets and restores focus after retry', async ({
	page
}) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await mockLibrary(page);
	let attempts = 0;
	await page.route('**/api/v1/workspaces/*/items/bulk', (route) => {
		attempts++;
		return route.fulfill(
			attempts === 1
				? { status: 500, json: { code: 'internal_error', message: 'Try again later' } }
				: { json: { ok: true } }
		);
	});
	await page.goto('/workspace/workspace-1/library');
	const row = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
	await row.check();
	const toolbar = page.getByRole('region', { name: 'Bulk actions', exact: true });
	await expect(toolbar).toContainText('Current page only');
	const bounds = (await toolbar.boundingBox())!;
	expect(bounds.x).toBeGreaterThanOrEqual(0);
	expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
	await openLibraryAction(page, 'add_project');
	let dialog = page.getByRole('dialog', { name: 'Add to Project', exact: true });
	await expect(dialog.getByRole('button', { name: 'Add to Project', exact: true })).toBeDisabled();
	await expect(
		dialog.getByRole('button', { name: 'Add to Project', exact: true })
	).toHaveAccessibleDescription('Choose a Project.');
	await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
	await openLibraryAction(page, 'add_tag');
	dialog = page.getByRole('dialog', { name: 'Add Tag', exact: true });
	const apply = dialog.getByRole('button', { name: 'Add Tag', exact: true });
	await expect(apply).toHaveAccessibleDescription('Choose or enter a Tag.');
	await dialog.getByRole('combobox', { name: 'Select Tag', exact: true }).fill('Methods');
	await dialog.getByText('Add Tag', { exact: true }).first().click();
	await expect(apply).toBeEnabled();
	await page.screenshot({ path: '/tmp/quirebase-library-bulk-mobile.png' });
	await apply.click();
	await expect(page.getByRole('alert')).toContainText('Something went wrong. Try again.');
	// The modal correctly hides the Library from the accessibility tree.
	await expect(page.locator('[data-library-item-select="item-1"]')).toBeChecked();
	const retry = dialog.getByRole('button', { name: 'Retry', exact: true });
	await expect(retry).toBeEnabled();
	await retry.click();
	await expect(page.getByText('Bulk action completed', { exact: true })).toBeVisible();
	await expect(row).not.toBeChecked();
	await expect(page.locator('#library-results')).toBeFocused();
	expect(attempts).toBe(2);
});

test('bulk progress keeps the search interactive and preserves its focus on completion', async ({
	page
}) => {
	await mockLibrary(page);
	const release = Promise.withResolvers<void>();
	let submitted = false;
	await page.route('**/api/v1/workspaces/*/items/bulk', async (route) => {
		submitted = true;
		await release.promise;
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/library');
	await page.locator('[data-library-item-select="item-1"]').check();
	const toolbar = page.getByRole('region', { name: 'Bulk actions', exact: true });
	await openLibraryAction(page, 'add_tag');
	await page
		.getByRole('dialog')
		.getByRole('combobox', { name: 'Select Tag', exact: true })
		.fill('Methods');
	await page.getByRole('dialog').getByText('Add Tag', { exact: true }).first().click();
	await page.getByRole('dialog').getByRole('button', { name: 'Add Tag', exact: true }).click();
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	try {
		await expect.poll(() => submitted).toBe(true);
		await page
			.getByRole('dialog')
			.getByRole('button', { name: 'Continue in Library', exact: true })
			.click();
		await expect(toolbar).toHaveAttribute('aria-busy', 'true');
		await expect(toolbar).toContainText('Applying action…');
		await expect(toolbar.getByRole('button', { name: 'Clear selection' })).toBeEnabled();
		await expect(toolbar.getByRole('button', { name: 'Add Tag', exact: true })).toBeDisabled();
		await search.fill('unfinished search');
	} finally {
		release.resolve();
	}
	await expect(toolbar).toHaveCount(0);
	await expect(search).toBeFocused();
	await expect(search).toHaveValue('unfinished search');
	await expect(page).not.toHaveURL(/q=/);
});

test('bulk delete returns focus to More actions on cancellation and results after deletion', async ({
	page
}) => {
	const rows = items.slice(0, 3);
	await mockLibrary(page, rows);
	await page.route('**/api/v1/workspaces/*/items/bulk', (route) => {
		rows.splice(0, 1);
		return route.fulfill({ json: { ok: true } });
	});
	await page.goto('/workspace/workspace-1/library');
	await page.locator('[data-library-item-select="item-1"]').check();
	await openLibraryAction(page, 'delete_items');
	const apply = page
		.getByRole('region', { name: 'Bulk actions', exact: true })
		.getByRole('button', { name: 'More actions', exact: true });
	const dialog = page.getByRole('dialog');
	await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
	await expect(apply).toBeFocused();
	await openLibraryAction(page, 'delete_items');
	await dialog.getByRole('button', { name: 'Permanently delete', exact: true }).click();
	await expect(dialog).toHaveCount(0);
	await expect(page.locator('[data-library-item-select="item-1"]')).toHaveCount(0);
	await expect(page.getByRole('region', { name: 'Bulk actions', exact: true })).toHaveCount(0);
	await expect(page.locator('#library-results')).toBeFocused();
});

for (const view of ['table', 'list'] as const) {
	test(`${view} row shortcuts browse, select and preview without changing search drafts`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		const { reads } = await mockLibrary(page);
		await page.goto('/workspace/workspace-1/library?q=committed');
		const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
		await search.fill('unsubmitted draft');
		const count = reads.length;
		const region = page.getByRole('region', { name: 'Library Items', exact: true });
		const first = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
		const second = page.getByRole('checkbox', { name: 'Select Author 2', exact: true });
		await region.press('ArrowDown');
		await expect(first).toBeFocused();
		await expect(first).not.toBeChecked();
		await first.press('j');
		await expect(second).toBeFocused();
		await expect(second).not.toBeChecked();
		await second.press('x');
		await expect(second).toBeChecked();
		await second.press('k');
		await expect(first).toBeFocused();
		await first.press('x');
		await expect(first).toBeChecked();
		await expect(second).toBeChecked();
		await first.press('Shift+X');
		await expect(first).toBeChecked();
		await expect(second).not.toBeChecked();
		await first.press('i');
		const preview = page.getByRole('complementary', { name: 'Item preview' });
		await expect(preview.getByRole('heading', { name: 'Item preview', exact: true })).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(preview).toHaveCount(0);
		await expect(first).toBeFocused();
		await first.press('Enter');
		await expect(preview.getByRole('heading', { name: 'Item preview', exact: true })).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(first).toBeFocused();
		await first.press('End');
		const last = page.getByRole('checkbox', { name: 'Select Author 25', exact: true });
		await expect(last).toBeFocused();
		await last.press('ArrowDown');
		await expect(last).toBeFocused();
		await expect(page).not.toHaveURL(/page=/);
		await last.press('Home');
		await expect(first).toBeFocused();
		expect(
			await first.evaluate((control) => {
				const bounds = control.getBoundingClientRect();
				return (
					document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2) ===
					control
				);
			})
		).toBe(true);
		await expect(search).toHaveValue('unsubmitted draft');
		await expect(first).toBeChecked();
		expect(reads).toHaveLength(count);
		await page.screenshot({ path: `/tmp/quirebase-library-row-focus-${view}.png` });
		await page.getByRole('link', { name: 'Research Item 2', exact: true }).press('Enter');
		await expect(page).toHaveURL(/\/item\/item-2\?/);
		expect(new URL(page.url()).searchParams.get('return_to')).toBe(
			'workspace/workspace-1/library?q=committed#library-item-item-2'
		);
	});

	test(`${view} range selection grows, shrinks and resets after clearing or toggling`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		await mockLibrary(page);
		await page.goto('/workspace/workspace-1/library');
		const first = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
		const second = page.getByRole('checkbox', { name: 'Select Author 2', exact: true });
		const third = page.getByRole('checkbox', { name: 'Select', exact: true });
		await first.press('Shift+ArrowDown');
		await expect(second).toBeFocused();
		await expect(first).toBeChecked();
		await expect(second).toBeChecked();
		await second.press('Shift+ArrowDown');
		await expect(third).toBeFocused();
		await expect(third).toBeChecked();
		await third.press('Shift+ArrowUp');
		await expect(second).toBeFocused();
		await expect(third).not.toBeChecked();
		await second.press('Shift+ArrowUp');
		await expect(first).toBeFocused();
		await expect(first).toBeChecked();
		await expect(second).not.toBeChecked();
		await first.press('ArrowDown');
		await second.press('Shift+ArrowDown');
		await expect(first).not.toBeChecked();
		await expect(second).toBeChecked();
		await expect(third).toBeChecked();
		await third.press('Escape');
		await expect(second).not.toBeChecked();
		await expect(third).not.toBeChecked();
		await third.press('Shift+ArrowUp');
		await expect(second).toBeFocused();
		await expect(second).toBeChecked();
		await expect(third).toBeChecked();
		await second.press('x');
		await second.press('Shift+ArrowUp');
		await expect(first).toBeChecked();
		await expect(second).toBeChecked();
		await expect(third).not.toBeChecked();
		await first.press('Shift+X');
		await page.keyboard.down('x');
		await expect(first).not.toBeChecked();
		await page.keyboard.down('x');
		await expect(first).not.toBeChecked();
		await page.keyboard.up('x');
		await page.keyboard.down('j');
		await page.keyboard.down('j');
		await page.keyboard.up('j');
		await expect(third).toBeFocused();
	});

	test(`${view} keyboard search and help preserve drafts, focus and selection`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		const { reads } = await mockLibrary(page);
		await page.goto('/workspace/workspace-1/library?q=committed');
		const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
		const row = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
		await row.check();
		const count = reads.length;
		await row.press('/');
		await expect(search).toBeFocused();
		await expect(search).toHaveValue('committed');
		await search.fill('draft');
		await search.press('/');
		await search.press('?');
		await expect(search).toHaveValue('draft/?');
		await expect(page.getByRole('dialog')).toHaveCount(0);
		await row.focus();
		await row.press('?');
		const help = page.getByRole('dialog', { name: 'Keyboard shortcuts', exact: true });
		await expect(help).toBeVisible();
		await page.keyboard.press('/');
		await expect(help.getByRole('button', { name: 'Close', exact: true })).toBeFocused();
		const accessibility = await new AxeBuilder({ page })
			.include('[role="dialog"]')
			.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
			.analyze();
		expect(
			accessibility.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
		).toEqual([]);
		await page.screenshot({ path: `/tmp/quirebase-library-shortcuts-${view}.png` });
		await page.keyboard.press('Escape');
		await expect(help).toHaveCount(0);
		await expect(row).toBeFocused();
		await expect(row).toBeChecked();
		await expect(search).toHaveValue('draft/?');
		expect(reads).toHaveLength(count);
		await expect(page).toHaveURL(/q=committed$/);
	});

	test(`${view} Escape dismisses one layer at a time and restores result focus`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		await mockLibrary(page);
		await page.goto('/workspace/workspace-1/library');
		const row = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
		await row.check();
		const trigger = page.getByRole('button', { name: 'Preview Item 1', exact: true });
		await trigger.click();
		const preview = page.getByRole('complementary', { name: 'Item preview' });
		await expect(preview.getByRole('heading', { name: 'Item preview', exact: true })).toBeFocused();
		await page.getByRole('button', { name: 'Keyboard shortcuts', exact: true }).click();
		await expect(
			page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true })
		).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(page.getByRole('dialog')).toHaveCount(0);
		await expect(preview).toBeVisible();
		await expect(row).toBeChecked();
		const display = page.getByRole('button', { name: 'Display options', exact: true });
		await display.click();
		await expect(page.getByRole('combobox', { name: 'Density', exact: true })).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(page.getByRole('dialog')).toHaveCount(0);
		await expect(display).toBeFocused();
		await expect(preview).toBeVisible();
		await expect(row).toBeChecked();
		await page.keyboard.press('Escape');
		await expect(preview).toHaveCount(0);
		await expect(trigger).toBeFocused();
		await expect(row).toBeChecked();
		const apply = page
			.getByRole('region', { name: 'Bulk actions', exact: true })
			.getByRole('button', { name: 'More actions', exact: true });
		await openLibraryAction(page, 'delete_items');
		await expect(
			page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true })
		).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(page.getByRole('dialog')).toHaveCount(0);
		await expect(row).toBeChecked();
		await expect(apply).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(row).not.toBeChecked();
		await expect(page.locator('#library-results')).toBeFocused();
	});
}

test('single-key shortcuts can be disabled, persist per user and remain reachable by button', async ({
	page
}) => {
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	const button = page.getByRole('button', { name: 'Keyboard shortcuts', exact: true });
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	const row = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
	const enabled = page.getByRole('checkbox', {
		name: 'Enable letter and symbol shortcuts',
		exact: true
	});
	const glyph = button.locator('svg');
	await expect(glyph).toBeVisible();
	await expect.poll(() => glyph.evaluate((icon) => icon.childElementCount)).toBeGreaterThan(0);
	await button.click();
	await enabled.uncheck();
	await page.keyboard.press('Escape');
	await expect(search).not.toHaveAttribute('aria-keyshortcuts');
	await page.reload();
	await row.check();
	await row.press('/');
	await row.press('?');
	for (const key of ['j', 'k', 'x', 'Shift+X', 'i']) await row.press(key);
	await expect(row).toBeFocused();
	await expect(row).toBeChecked();
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await row.press('ArrowDown');
	await expect(page.getByRole('checkbox', { name: 'Select Author 2', exact: true })).toBeFocused();
	await row.press('Escape');
	await expect(row).not.toBeChecked();
	await button.click();
	await expect(enabled).not.toBeChecked();
	await enabled.check();
	await page.keyboard.press('Escape');
	await row.press('/');
	await expect(search).toBeFocused();
	await button.click();
	await enabled.uncheck();
	await page.keyboard.press('Escape');
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: {
				authenticated: true,
				user: { id: 'user-2', username: 'another', role: 'member' }
			}
		})
	);
	await page.reload();
	await row.press('/');
	await expect(search).toBeFocused();
});

test('Library shortcuts respect editing, IME, modifiers and consumed events', async ({ page }) => {
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library?preview=item-1');
	const preview = page.getByRole('complementary', { name: 'Item preview' });
	await expect(preview.getByRole('heading', { name: 'Item preview', exact: true })).toBeFocused();
	const row = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
	await row.check();
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	await search.fill('unsubmitted draft');
	await search.press('Escape');
	await expect(search).toBeFocused();
	await expect(search).toHaveValue('unsubmitted draft');
	await expect(preview).toBeVisible();
	await expect(row).toBeChecked();
	await row.focus();
	for (const properties of [
		{ key: '/', isComposing: true },
		{ key: '?', keyCode: 229 },
		{ key: '/', ctrlKey: true },
		{ key: '?', metaKey: true },
		{ key: '/', altKey: true },
		{ key: 'Escape', repeat: true },
		{ key: 'Escape', isComposing: true },
		{ key: 'j', isComposing: true },
		{ key: 'x', keyCode: 229 },
		{ key: 'x', ctrlKey: true }
	]) {
		await row.dispatchEvent('keydown', properties);
		await expect(row).toBeFocused();
		await expect(preview).toBeVisible();
		await expect(row).toBeChecked();
		await expect(page.getByRole('dialog')).toHaveCount(0);
	}
	for (const key of ['x', 'Escape']) {
		await row.evaluate((element) => {
			element.addEventListener('keydown', (event) => event.preventDefault(), { once: true });
		});
		await row.press(key);
		await expect(preview).toBeVisible();
		await expect(row).toBeChecked();
	}
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	const project = page.getByRole('combobox', { name: 'Project', exact: true });
	await project.click();
	await project.press('Escape');
	await expect(preview).toBeVisible();
	await expect(row).toBeChecked();
	await page.getByRole('button', { name: 'Choose date for Year', exact: true }).click();
	await page.keyboard.press('Escape');
	await expect(preview).toBeVisible();
	await expect(row).toBeChecked();
});

for (const [platform, modifier] of [
	['MacIntel', 'Meta'],
	['Win32', 'Control']
] as const) {
	test(`${platform} select-all stays in Library results and help shows the platform binding`, async ({
		page
	}) => {
		await page.addInitScript((platform) => {
			Object.defineProperty(navigator, 'platform', { get: () => platform });
			Object.defineProperty(navigator, 'userAgent', { get: () => platform });
		}, platform);
		await mockLibrary(page);
		await page.goto('/workspace/workspace-1/library');
		const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
		await search.fill('typing a draft');
		// Navigator overrides exercise app mappings; native text editing still uses the host OS.
		await search.press(`${process.platform === 'darwin' ? 'Meta' : 'Control'}+a`);
		expect(
			await search.evaluate((input: HTMLInputElement) => [input.selectionStart, input.selectionEnd])
		).toEqual([0, 14]);
		await expect(page.getByRole('checkbox', { name: 'Select this page' })).not.toBeChecked();
		const first = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
		await first.press(`${modifier}+a`);
		await expect(page.getByRole('checkbox', { name: 'Select this page' })).toBeChecked();
		await expect(page.getByRole('region', { name: 'Bulk actions', exact: true })).toContainText(
			'25 selected'
		);
		await first.press('?');
		const help = page.getByRole('dialog', { name: 'Keyboard shortcuts', exact: true });
		await expect(
			help.locator('kbd').filter({ hasText: modifier === 'Meta' ? /^⌘ A$/ : /^Ctrl\+A$/ })
		).toHaveText(modifier === 'Meta' ? '⌘ A' : 'Ctrl+A');
		await expect(help.getByRole('button', { name: 'Close', exact: true })).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(first).toBeFocused();
		for (const key of ['j', 'x', 'ArrowDown']) {
			const untouched = await page.locator('body').evaluate((element, key) => {
				const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
				element.dispatchEvent(event);
				return !event.defaultPrevented;
			}, key);
			expect(untouched).toBe(true);
		}
		await expect(first).toBeFocused();
		await expect(first).toBeChecked();
	});
}

test('holding Escape never dismisses the next Library layer', async ({ page }) => {
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	const row = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
	await row.check();
	const trigger = page.getByRole('button', { name: 'Preview Item 1', exact: true });
	await trigger.click();
	const preview = page.getByRole('complementary', { name: 'Item preview' });
	await expect(preview.getByRole('heading', { name: 'Item preview', exact: true })).toBeFocused();
	await page.keyboard.press('?');
	const help = page.getByRole('dialog', { name: 'Keyboard shortcuts', exact: true });
	await expect(help.getByRole('button', { name: 'Close', exact: true })).toBeFocused();
	await page.keyboard.down('Escape');
	await expect(help).toHaveCount(0);
	await page.keyboard.down('Escape');
	await expect(preview).toBeVisible();
	await expect(row).toBeChecked();
	await page.keyboard.up('Escape');
	await page.keyboard.down('Escape');
	await expect(preview).toHaveCount(0);
	await expect(trigger).toBeFocused();
	await page.keyboard.down('Escape');
	await expect(row).toBeChecked();
	await page.keyboard.up('Escape');
	await page.keyboard.press('Escape');
	await expect(row).not.toBeChecked();
});

test('Library shortcuts recover when a key release happens outside the page', async ({ page }) => {
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	const row = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	// Model a press whose keyup never reaches this page, e.g. when switching windows.
	await row.dispatchEvent('keydown', { key: '/', code: 'Slash' });
	await expect(search).toBeFocused();
	await row.press('/');
	await expect(search).toBeFocused();
});

test('Library hotkeys release their bindings on navigation and work again on return', async ({
	page
}) => {
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	const row = page.getByRole('checkbox', { name: 'Select Author 1', exact: true });
	await row.press('/');
	await expect(page.getByRole('textbox', { name: 'Library Search', exact: true })).toBeFocused();
	await page
		.getByRole('navigation', { name: 'Main navigation', exact: true })
		.getByRole('link', { name: 'Projects', exact: true })
		.click();
	await expect(
		page.getByRole('heading', { name: 'Projects', level: 1, exact: true })
	).toBeVisible();
	for (const key of ['/', '?', 'Escape', 'j', 'x', 'ArrowDown']) {
		const untouched = await page.locator('body').evaluate((element, key) => {
			const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
			element.dispatchEvent(event);
			element.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true }));
			return !event.defaultPrevented;
		}, key);
		expect(untouched).toBe(true);
	}
	await page.goBack();
	await row.press('j');
	const next = page.getByRole('checkbox', { name: 'Select Author 2', exact: true });
	await expect(next).toBeFocused();
	await next.press('k');
	await expect(row).toBeFocused();
	await row.press('/');
	await expect(page.getByRole('textbox', { name: 'Library Search', exact: true })).toBeFocused();
	await row.press('?');
	const help = page.getByRole('dialog', { name: 'Keyboard shortcuts', exact: true });
	await expect(help.getByRole('button', { name: 'Close', exact: true })).toBeFocused();
	await page.keyboard.press('Escape');
	await expect(help).toHaveCount(0);
	await expect(row).toBeFocused();
});

for (const view of ['table', 'list'] as const) {
	test(`${view} sorting shares URL state, resets paging and preserves filters and preview`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		const { reads } = await mockLibrary(page);
		await page.goto(
			'/workspace/workspace-1/library?q=research&sort=created&direction=asc&author_last_name=Smith&author_first_name=&page=2&page_size=10&preview=item-99'
		);
		const sort = page.getByRole('combobox', { name: 'Sort By', exact: true });
		const direction = page.locator('#library-sort-direction');
		await expect(sort).toHaveValue('created');
		await expect(direction).toHaveAccessibleName(
			'Sort order: Oldest first. Switch to Newest first.'
		);
		await page.getByRole('checkbox', { name: 'Select this page' }).check();
		await sort.selectOption('published');
		await expect.poll(() => reads.at(-1)?.searchParams.get('sort')).toBe('published');
		let parameters = new URL(page.url()).searchParams;
		expect(parameters.has('page')).toBe(false);
		expect(parameters.has('direction')).toBe(false);
		for (const [key, value] of Object.entries({
			q: 'research',
			author_last_name: 'Smith',
			author_first_name: '',
			page_size: '10',
			preview: 'item-99'
		}))
			expect(parameters.get(key)).toBe(value);
		expect(reads.at(-1)?.searchParams.get('offset')).toBe('0');
		expect(reads.at(-1)?.searchParams.get('direction')).toBe('desc');
		await expect(page.getByRole('checkbox', { name: 'Select this page' })).not.toBeChecked();
		await direction.click();
		await expect.poll(() => reads.at(-1)?.searchParams.get('direction')).toBe('asc');
		await page.reload();
		await expect(sort).toHaveValue('published');
		await expect(direction).toHaveAccessibleName(
			'Sort order: Oldest first. Switch to Newest first.'
		);
		await expect(page.getByRole('complementary', { name: 'Item preview' })).toBeVisible();
		if (view === 'table') {
			const date = page.getByRole('button', { name: 'Sort by publication date', exact: true });
			const heading = page.getByRole('columnheader').filter({ has: date });
			await expect(heading).toHaveAttribute('aria-sort', 'ascending');
			await date.focus();
			await date.press('Enter');
			await expect(heading).toHaveAttribute('aria-sort', 'descending');
			await expect(sort).toHaveValue('published');
			await expect(direction).toHaveAccessibleName(
				'Sort order: Newest first. Switch to Oldest first.'
			);
		}
		await sort.selectOption('title');
		await expect(sort).toHaveValue('title');
		await expect(direction).toHaveAccessibleName('Sort order: A–Z. Switch to Z–A.');
		if (view === 'table')
			await page.getByRole('button', { name: 'Sort by title', exact: true }).click();
		else await direction.click();
		await expect.poll(() => reads.at(-1)?.searchParams.get('direction')).toBe('desc');
		parameters = new URL(page.url()).searchParams;
		expect(parameters.get('sort')).toBe('title');
		expect(parameters.get('direction')).toBe('desc');
		await page.goBack();
		await expect(sort).toHaveValue('title');
		await expect(direction).toHaveAccessibleName('Sort order: A–Z. Switch to Z–A.');
		await sort.selectOption('publication');
		await expect.poll(() => reads.at(-1)?.searchParams.get('sort')).toBe('publication');
		await expect(sort).toHaveValue('publication');
		if (view === 'table')
			await page.getByRole('button', { name: 'Sort by publication', exact: true }).click();
		else await direction.click();
		await expect.poll(() => reads.at(-1)?.searchParams.get('direction')).toBe('desc');
		await expect(sort).toHaveValue('publication');
		await expect(direction).toHaveAccessibleName('Sort order: Z–A. Switch to A–Z.');
		if (view === 'table') {
			const publication = page.getByRole('button', { name: 'Sort by publication', exact: true });
			await expect(publication).toBeFocused();
			await expect(publication).toBeInViewport();
		}
		await page.reload();
		await expect(sort).toHaveValue('publication');
		await expect(direction).toHaveAccessibleName('Sort order: Z–A. Switch to A–Z.');
		await sort.selectOption('author');
		await expect.poll(() => reads.at(-1)?.searchParams.get('sort')).toBe('author');
		await expect(sort).toHaveValue('author');
		await expect(direction).toHaveAccessibleName('Sort order: A–Z. Switch to Z–A.');
		if (view === 'table') {
			const author = page.getByRole('button', {
				name: 'Sort by authors',
				exact: true
			});
			await expect(page.getByRole('columnheader').filter({ has: author })).toHaveAttribute(
				'aria-sort',
				'ascending'
			);
			await author.focus();
			await author.press('Enter');
			await expect(author).toBeFocused();
		} else await direction.click();
		await expect.poll(() => reads.at(-1)?.searchParams.get('direction')).toBe('desc');
		await page.reload();
		await expect(sort).toHaveValue('author');
		await expect(direction).toHaveAccessibleName('Sort order: Z–A. Switch to A–Z.');
	});

	test(`${view} metadata links refine submitted results, preserve preview and support undo`, async ({
		page
	}) => {
		if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
		const rows = items.map((item) => ({
			...item,
			authors: [
				{ full_name: 'Jane Smith', last_name: 'Smith', first_name: 'Jane' },
				{ full_name: 'Council; & 一', last_name: 'Council; & 一', first_name: null }
			],
			publication_title: 'Journal; & 特刊 50%_+',
			publication_date: '2026-10-19'
		}));
		const { reads, previews } = await mockLibrary(page, rows);
		const initial = new URLSearchParams({
			q: 'committed',
			author: 'old text',
			author_last_name: 'Old',
			author_first_name: 'Name',
			year: '2025',
			publication_title: 'Old journal',
			keyword_exact: 'Graph & ML',
			reference_type: 'JournalArticle',
			has_files: 'false',
			sort: 'title',
			page: '2',
			page_size: '10',
			preview: 'item-99'
		});
		await page.goto(`/workspace/workspace-1/library?${initial}`);
		await expect(page.getByRole('complementary', { name: 'Item preview' })).toBeVisible();
		if (view === 'table') {
			// Both complete names must fit before exercising their filter links.
			const resize = page.getByRole('button', { name: 'Resize Authors column', exact: true });
			for (let index = 0; index < 4; index++) await resize.press('ArrowRight');
		}
		const row = () =>
			view === 'table'
				? page.getByRole('table', { name: 'Library Items' }).locator('tbody tr').first()
				: page.locator('#library-results article').first();
		await row().getByRole('checkbox').check();
		await page.getByPlaceholder('Search title, author, Tag, or full text').fill('unsaved draft');
		const author = row().getByRole('link', { name: 'View Items by Jane Smith', exact: true });
		await author.focus();
		await author.press('Enter');
		await expect.poll(() => new URL(page.url()).searchParams.get('author_last_name')).toBe('Smith');
		let parameters = new URL(page.url()).searchParams;
		expect(parameters.get('author_first_name')).toBe('Jane');
		expect(parameters.has('author')).toBe(false);
		expect(parameters.has('page')).toBe(false);
		for (const key of [
			'q',
			'year',
			'publication_title',
			'keyword_exact',
			'reference_type',
			'has_files',
			'sort',
			'page_size',
			'preview'
		])
			expect(parameters.get(key)).toBe(initial.get(key));
		await expect(row().getByRole('checkbox')).not.toBeChecked();
		await expect.poll(() => reads.at(-1)?.searchParams.get('author_last_name')).toBe('Smith');
		expect(reads.at(-1)?.searchParams.get('offset')).toBe('0');
		expect(reads.at(-1)?.searchParams.get('query')).toBe('committed');
		await expect(
			page.getByRole('button', { name: 'Remove filter Author: Jane Smith', exact: true })
		).toBeVisible();

		await row().getByRole('link', { name: 'View Items by Council; & 一', exact: true }).click();
		await expect
			.poll(() => new URL(page.url()).searchParams.get('author_last_name'))
			.toBe('Council; & 一');
		expect(new URL(page.url()).searchParams.get('author_first_name')).toBe('');
		const date = row().getByRole('link', { name: 'View Items published in 2026', exact: true });
		await expect(date).toHaveText('2026');
		await expect(row()).toContainText('2026-10-19');
		await date.click();
		await expect.poll(() => new URL(page.url()).searchParams.get('year')).toBe('2026');
		const beforePublication = page.url();
		await row()
			.getByRole('link', { name: 'View Items in Journal; & 特刊 50%_+', exact: true })
			.click();
		await expect
			.poll(() => new URL(page.url()).searchParams.get('publication_title'))
			.toBe(rows[0].publication_title);
		await page.goBack();
		await expect(page).toHaveURL(beforePublication);
		parameters = new URL(page.url()).searchParams;
		expect(parameters.get('publication_title')).toBe('Old journal');
		expect(parameters.get('year')).toBe('2026');
		expect(parameters.get('author_last_name')).toBe('Council; & 一');
		expect(parameters.get('preview')).toBe('item-99');
		expect(previews).toEqual(['item-99']);
		await expect(row().locator('a a')).toHaveCount(0);
		const details = new URL(
			(await row().getByRole('link').first().getAttribute('href'))!,
			page.url()
		);
		expect(details.pathname).toBe('/workspace/workspace-1/item/item-1');
		const returnTo = new URL(details.searchParams.get('return_to')!, page.url());
		expect(returnTo.searchParams.get('preview')).toBe('item-99');
		expect(returnTo.searchParams.get('author_last_name')).toBe('Council; & 一');
		expect(returnTo.searchParams.get('year')).toBe('2026');
		expect(returnTo.hash).toBe('#library-item-item-1');
	});
}

test('sorting remains available with empty results', async ({ page }) => {
	await mockLibrary(page, []);
	await page.goto('/workspace/workspace-1/library');
	await expect(page.getByText('No Items found.', { exact: true })).toBeVisible();
	const sort = page.getByRole('combobox', { name: 'Sort By', exact: true });
	await sort.selectOption('published');
	await page
		.getByRole('button', { name: 'Sort order: Newest first. Switch to Oldest first.' })
		.click();
	await expect(page).toHaveURL(/sort=published&direction=asc/);
});

for (const view of ['table', 'list'] as const) {
	for (const status of [403, 404, 500]) {
		test(`${view} Project list handles cached rows after HTTP ${status}`, async ({ page }) => {
			if (view === 'list') await page.setViewportSize({ width: 390, height: 844 });
			await mockLibrary(page);
			await page.route('**/api/v1/workspaces/*/projects/project-1', (route) =>
				route.fulfill({
					json: { id: 'project-1', name: 'Managed Project', authorization: { allowed: [] } }
				})
			);
			let responseStatus = 200;
			await page.route('**/api/v1/workspaces/*/items?*', (route) =>
				responseStatus === 200
					? route.fallback()
					: route.fulfill({
							status: responseStatus,
							json: {
								code:
									responseStatus === 404
										? 'not_found'
										: responseStatus === 403
											? 'permission_denied'
											: 'internal_error',
								message: 'Read failed'
							}
						})
			);
			await page.goto('/workspace/workspace-1/library?project=project-1');
			const item = page.getByRole('link', { name: 'Research Item 2', exact: true });
			const selection = page.getByRole('checkbox', { name: 'Select Author 2', exact: true });
			await expect(item).toBeVisible();
			await selection.check();
			await page.clock.install();
			responseStatus = status;
			await page.clock.fastForward(31_000);
			await page.evaluate(() => {
				for (const visibilityState of ['hidden', 'visible']) {
					Object.defineProperty(document, 'visibilityState', {
						configurable: true,
						value: visibilityState
					});
					window.dispatchEvent(new Event('visibilitychange'));
				}
			});
			const alert = page.locator('#library-results').getByRole('alert');
			const retry = alert.getByRole('button', { name: 'Retry', exact: true });
			await expect(alert).toContainText(
				status === 500
					? 'Unable to refresh the Library. Showing the last loaded results.'
					: 'Unable to load the Library.'
			);
			await expect(retry).toBeEnabled();
			if (status === 500) {
				await expect(item).toBeVisible();
				await expect(selection).toBeChecked();
			} else {
				await expect(item).toHaveCount(0);
				await expect(page.getByRole('region', { name: 'Bulk actions', exact: true })).toHaveCount(
					0
				);
				await expect(page.getByRole('navigation', { name: 'Library pages' })).toContainText(
					'Showing 0–0 of 0'
				);
				responseStatus = 500;
				const failedRetry = page.waitForResponse(
					(response) => response.url().includes('/items?') && response.status() === 500
				);
				await retry.click();
				await failedRetry;
				await expect(retry).toBeEnabled();
				await expect(alert).toContainText('Unable to load the Library.');
				await expect(item).toHaveCount(0);
			}
			responseStatus = 200;
			await retry.click();
			await expect(item).toBeVisible();
			await expect(alert).toHaveCount(0);
			if (status === 500) await expect(selection).toBeChecked();
			else await expect(selection).not.toBeChecked();
		});
	}
}

for (const surface of ['Library', 'Project'] as const) {
	for (const status of [403, 404]) {
		test(`purged Project pages and sort orders stay unavailable offline in ${surface} after HTTP ${status}`, async ({
			page,
			context
		}) => {
			const { reads } = await mockLibrary(page);
			await page.route('**/api/v1/workspaces/*/projects/project-1', (route) =>
				route.fulfill({
					json: {
						id: 'project-1',
						name: 'Managed Project',
						description: '',
						state: 'active',
						participation: 'managed',
						item_count: items.length,
						is_participating: true,
						allowed_participation_changes: [],
						authorization: { allowed: [] },
						active_participants: []
					}
				})
			);
			await page.route('**/api/v1/workspaces/*/projects/project-1/discussions', (route) =>
				route.fulfill({ json: [] })
			);
			let denied = false;
			await page.route('**/api/v1/workspaces/*/items?*', (route) =>
				denied
					? route.fulfill({
							status,
							json: { code: status === 404 ? 'not_found' : 'permission_denied', message: 'Denied' }
						})
					: route.fallback()
			);
			await page.goto(
				surface === 'Library'
					? '/workspace/workspace-1/library?project=project-1'
					: '/workspace/workspace-1/projects/project-1'
			);
			const item = page.getByRole('link', {
				name: 'Research Item 2',
				exact: true
			});
			await expect(item).toBeVisible();
			const sort = page.getByRole('combobox', { name: 'Sort By', exact: true });
			await sort.selectOption('title');
			await expect.poll(() => reads.at(-1)?.searchParams.get('sort')).toBe('title');
			await expect(item).toBeVisible();
			await page.getByRole('button', { name: 'Next page', exact: true }).click();
			await expect(
				page.getByRole('link', {
					name: 'Research Item 26',
					exact: true
				})
			).toBeVisible();
			denied = true;
			await sort.selectOption(surface === 'Library' ? 'published' : 'created');
			const results =
				surface === 'Library'
					? page.locator('#library-results')
					: page.getByRole('region', { name: 'Items', exact: true });
			const alert = results.getByRole('alert');
			const failure =
				surface === 'Library' ? 'Unable to load the Library.' : 'Unable to load Items.';
			await expect(alert).toContainText(failure);
			await context.setOffline(true);
			await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(false);
			const readCount = reads.length;
			for (const expected of [
				{ sort: 'title', page: '2' },
				{ sort: 'title', page: null },
				{ sort: null, page: null }
			]) {
				await page.goBack();
				await expect.poll(() => new URL(page.url()).searchParams.get('sort')).toBe(expected.sort);
				await expect(sort).toHaveValue(expected.sort ?? 'updated');
				await expect(alert).toContainText(failure);
				await expect(alert.getByRole('button', { name: 'Retry', exact: true })).toBeEnabled();
				await expect(results.getByText('No Items found.', { exact: true })).toHaveCount(0);
				await expect(results.getByText('No Items in this Project.', { exact: true })).toHaveCount(
					0
				);
				await expect(results.getByRole('link', { name: /^Research Item/ })).toHaveCount(0);
				await expect(page.getByRole('checkbox', { name: /^Select Author/ })).toHaveCount(0);
				expect(new URL(page.url()).searchParams.get('page')).toBe(expected.page);
				expect(reads).toHaveLength(readCount);
			}
			denied = false;
			await context.setOffline(false);
			await expect(item).toBeVisible();
			await expect(alert).toHaveCount(0);
		});
	}
}

test('keyboard sorting restores header focus after a slow response without taking focus from another control', async ({
	page
}) => {
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	const title = page.getByRole('button', { name: 'Sort by title', exact: true });
	await expect(title).toBeVisible();
	let release = () => {};
	let arrived = () => {};
	let pending = new Promise<void>((resolve) => {
		release = resolve;
	});
	let requested = new Promise<void>((resolve) => {
		arrived = resolve;
	});
	await page.route('**/api/v1/workspaces/*/items?*', async (route) => {
		arrived();
		await pending;
		await route.fallback();
	});
	await title.focus();
	await title.press('Enter');
	await requested;
	await expect(page.getByRole('status').filter({ hasText: 'Loading Library…' })).toBeVisible();
	release();
	await expect(page.getByRole('columnheader').filter({ has: title })).toHaveAttribute(
		'aria-sort',
		'ascending'
	);
	await expect(title).toBeFocused();

	pending = new Promise<void>((resolve) => {
		release = resolve;
	});
	requested = new Promise<void>((resolve) => {
		arrived = resolve;
	});
	await title.press('Enter');
	await requested;
	const search = page.getByPlaceholder('Search title, author, Tag, or full text');
	await search.focus();
	release();
	await expect(page.getByRole('columnheader').filter({ has: title })).toHaveAttribute(
		'aria-sort',
		'descending'
	);
	await expect(search).toBeFocused();
});

test('table keeps native links, partial dates and independent keyboard selection', async ({
	page
}) => {
	const { previews } = await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	const table = page.getByRole('table', { name: 'Library Items' });
	await expect(table).toBeVisible();
	await expect(table.locator('strong i')).toHaveText('文献与公式');
	await expect(table.locator('strong math msup')).toBeVisible();
	await expect(
		table
			.locator('td')
			.filter({ hasText: /^2026-10$/ })
			.first()
	).toBeVisible();
	const first = table.getByRole('checkbox', { name: 'Select Author 1', exact: true });
	await first.focus();
	await first.press('Space');
	await expect(first).toBeChecked();
	await expect(first).toBeFocused();
	await expect(page.getByLabel('Select this page')).toHaveJSProperty('indeterminate', true);
	const title = table.getByRole('link').first();
	await title.focus();
	await expect(first).toBeChecked();
	await expect(title).toHaveAttribute(
		'href',
		`/workspace/workspace-1/item/item-1?${new URLSearchParams({
			return_to: 'workspace/workspace-1/library#library-item-item-1'
		})}`
	);
	await page.getByLabel('Select this page').check();
	await expect(table.getByRole('checkbox').filter({ visible: true })).toHaveCount(25);
	await expect(table.locator('input:checked')).toHaveCount(25);
	await page.getByLabel('Select this page').uncheck();
	await expect(table.locator('input:checked')).toHaveCount(0);
	expect(previews).toEqual([]);
});

test('preview preserves drafts and selection, shares its URL and restores trigger focus', async ({
	page
}) => {
	const { reads, previews } = await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library?q=committed&page=2');
	const search = page.getByPlaceholder('Search title, author, Tag, or full text');
	await search.fill('unsubmitted draft');
	const row = page.getByRole('checkbox', { name: 'Select Author 26', exact: true });
	await row.check();
	const count = reads.length;
	const trigger = page.getByRole('button', { name: 'Preview Item 1', exact: true });
	await trigger.click();
	const preview = page.getByRole('complementary', { name: 'Item preview' });
	await expect(
		preview.getByRole('heading', { name: 'Preview item-26', exact: true })
	).toBeVisible();
	await expect(preview.getByRole('heading', { name: 'Item preview', exact: true })).toBeFocused();
	await expect(search).toHaveValue('unsubmitted draft');
	await expect(row).toBeChecked();
	await expect(page).toHaveURL(/q=committed&page=2&preview=item-26$/);
	expect(reads).toHaveLength(count);
	expect(previews).toEqual(['item-26']);
	const context = new URLSearchParams({
		return_to:
			'workspace/workspace-1/library?q=committed&page=2&preview=item-26#library-item-item-26'
	});
	await expect(preview.getByRole('link', { name: 'Open full details' })).toHaveAttribute(
		'href',
		`/workspace/workspace-1/item/item-26?${context}`
	);
	await expect(preview.getByRole('link', { name: 'Read PDF' })).toHaveAttribute(
		'href',
		`/workspace/workspace-1/item/item-26/pdf/revision-1?${context}`
	);
	await preview.getByRole('button', { name: 'Close preview' }).click();
	await expect(preview).toHaveCount(0);
	await expect(trigger).toBeFocused();
	await expect(row).toBeChecked();
	await expect(search).toHaveValue('unsubmitted draft');
	await page.goBack();
	await expect(preview).toBeVisible();
	await page.reload();
	await expect(preview.getByRole('heading', { name: 'Preview item-26' })).toBeVisible();
	await preview.getByRole('heading', { name: 'Item preview', exact: true }).press('Escape');
	await expect(preview).toHaveCount(0);
	await expect(page.locator('#library-results')).toBeFocused();
});

for (const interaction of ['unchanged', 'search', 'selection', 'shared-search'] as const) {
	test(`delayed preview module respects ${interaction} focus`, async ({ page }) => {
		await mockLibrary(page);
		const manifest = JSON.parse(
			await readFile('.svelte-kit/output/client/.vite/manifest.json', 'utf8')
		) as Record<string, { name?: string; file: string }>;
		const entry = Object.values(manifest).find(({ name }) => name === 'LibraryPreview')!;
		let release = () => {};
		let arrived = () => {};
		const pending = new Promise<void>((resolve) => {
			release = resolve;
		});
		const requested = new Promise<void>((resolve) => {
			arrived = resolve;
		});
		await page.route(`**/${entry.file}`, async (route) => {
			arrived();
			await pending;
			await route.continue();
		});
		try {
			await page.goto(
				`/workspace/workspace-1/library${interaction === 'shared-search' ? '?preview=item-1' : ''}`,
				{ waitUntil: 'domcontentloaded' }
			);
			if (interaction !== 'shared-search')
				await page.getByRole('button', { name: 'Preview Item 1', exact: true }).click();
			await requested;
			await expect(
				page.getByRole('status').filter({ hasText: 'Loading Item preview…' })
			).toBeVisible();
			const search = page.getByPlaceholder('Search title, author, Tag, or full text');
			const selection = page.getByRole('checkbox', { name: 'Select this page', exact: true });
			if (interaction === 'search' || interaction === 'shared-search')
				await search.fill('typing during load');
			else if (interaction === 'selection') {
				await selection.focus();
				await selection.press('Space');
			}
			release();
			const preview = page.getByRole('complementary', { name: 'Item preview' });
			await expect(
				preview.getByRole('heading', { name: 'Preview item-1', exact: true })
			).toBeVisible();
			if (interaction === 'search' || interaction === 'shared-search') {
				await expect(search).toBeFocused();
				await search.press('End');
				await search.pressSequentially(' continues');
				await expect(search).toHaveValue('typing during load continues');
			} else if (interaction === 'selection') {
				await expect(selection).toBeFocused();
				await expect(selection).toBeChecked();
			} else
				await expect(
					preview.getByRole('heading', { name: 'Item preview', exact: true })
				).toBeFocused();
		} finally {
			release();
		}
	});
}

test('closing a shared preview returns focus to results through buttons and history', async ({
	page
}) => {
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library?preview=item-1');
	const preview = page.getByRole('complementary', { name: 'Item preview' });
	const heading = preview.getByRole('heading', { name: 'Item preview', exact: true });
	await expect(heading).toBeFocused();
	await preview.getByRole('button', { name: 'Close preview', exact: true }).click();
	await expect(preview).toHaveCount(0);
	await expect(page.locator('#library-results')).toBeFocused();
	await page.goBack();
	await expect(heading).toBeFocused();
	await page.goForward();
	await expect(preview).toHaveCount(0);
	await expect(page.locator('#library-results')).toBeFocused();
});

test('selection clears for server paging and sorting while preview keeps its target', async ({
	page
}) => {
	const { reads } = await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	await page.getByRole('checkbox', { name: 'Select Author 1', exact: true }).check();
	await page.getByRole('button', { name: 'Preview Item 1', exact: true }).click();
	await page.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(
		page.getByRole('checkbox', { name: 'Select Author 26', exact: true })
	).not.toBeChecked();
	await expect(page.getByRole('button', { name: 'Clear selection', exact: true })).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'Preview item-1', exact: true })).toBeVisible();
	await page.getByRole('button', { name: 'Sort by title', exact: true }).click();
	await expect.poll(() => reads.at(-1)?.searchParams.get('sort')).toBe('title');
	expect(reads.at(-1)?.searchParams.get('offset')).toBe('0');
	await expect(
		page
			.getByRole('columnheader')
			.filter({ has: page.getByRole('button', { name: 'Sort by title', exact: true }) })
	).toHaveAttribute('aria-sort', 'ascending');
	await expect(page.getByRole('heading', { name: 'Preview item-1', exact: true })).toBeVisible();
	await page.goBack();
	await expect(page).toHaveURL(/page=2&preview=item-1/);
});

test('display controls persist per user and resize by keyboard and pointer', async ({ page }) => {
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	await page.getByRole('button', { name: 'Display options', exact: true }).click();
	await expect(page.getByRole('combobox', { name: 'Density', exact: true })).toBeFocused();
	await page.getByRole('combobox', { name: 'Density', exact: true }).selectOption('compact');
	await page.keyboard.press('Escape');
	await expect(page.getByRole('button', { name: 'Display options', exact: true })).toBeFocused();
	const resize = page.getByRole('button', { name: 'Resize Title column', exact: true });
	await resize.focus();
	await resize.press('ArrowRight');
	await expect
		.poll(() =>
			page
				.locator('col')
				.nth(1)
				.evaluate((element) => element.getBoundingClientRect().width)
		)
		.toBe(380);
	const box = await resize.boundingBox();
	await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
	await page.mouse.down();
	await page.mouse.move(box!.x + box!.width / 2 + 40, box!.y + box!.height / 2);
	await page.mouse.up();
	await expect
		.poll(() =>
			page
				.locator('col')
				.nth(1)
				.evaluate((element) => element.getBoundingClientRect().width)
		)
		.toBe(420);
	await page.getByRole('button', { name: 'Display options', exact: true }).click();
	await page.getByRole('checkbox', { name: 'Authors', exact: true }).uncheck();
	await page.getByRole('checkbox', { name: 'DOI', exact: true }).check();
	await page.keyboard.press('Escape');
	await expect(
		page.getByRole('button', { name: 'Resize Authors column', exact: true })
	).toHaveCount(0);
	await expect(page.getByRole('cell', { name: '10.1234/research', exact: true })).toBeVisible();
	await page.reload();
	await page.getByRole('button', { name: 'Display options', exact: true }).click();
	await expect(page.getByRole('combobox', { name: 'Density', exact: true })).toHaveValue('compact');
	await page.keyboard.press('Escape');
	await expect(
		page.getByRole('button', { name: 'Resize Authors column', exact: true })
	).toHaveCount(0);
	await expect
		.poll(() =>
			page
				.locator('col')
				.nth(1)
				.evaluate((element) => element.getBoundingClientRect().width)
		)
		.toBe(420);
	await page.getByRole('radio', { name: 'List', exact: true }).press('Space');
	await expect(page.getByRole('table')).toHaveCount(0);
	await page.reload();
	await expect(page.getByRole('radio', { name: 'List', exact: true })).toBeChecked();
	await expect(page.locator('#library-results article')).toHaveCount(25);
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: { authenticated: true, user: { id: 'user-2', username: 'another', role: 'member' } }
		})
	);
	await page.reload();
	await expect(page.getByRole('radio', { name: 'Automatic', exact: true })).toBeChecked();
	await page.getByRole('button', { name: 'Display options', exact: true }).click();
	await expect(page.getByRole('combobox', { name: 'Density', exact: true })).toHaveValue(
		'comfortable'
	);
	await page.keyboard.press('Escape');
	await expect(
		page.getByRole('button', { name: 'Resize Authors column', exact: true })
	).toBeVisible();
});

test('pointer resize limits survive reload at both title column bounds', async ({ page }) => {
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	// Keep column widths above the available space so the browser adds no surplus to the title.
	await page.getByRole('button', { name: 'Display options', exact: true }).click();
	await page.getByRole('checkbox', { name: 'DOI', exact: true }).check();
	await page.keyboard.press('Escape');
	const resize = page.getByRole('button', { name: 'Resize Title column', exact: true });
	const width = () =>
		page
			.locator('col')
			.nth(1)
			.evaluate((element) => element.getBoundingClientRect().width);
	for (const { delta, expected } of [
		{ delta: 500, expected: 800 },
		{ delta: -800, expected: 240 }
	]) {
		await resize.scrollIntoViewIfNeeded();
		const box = (await resize.boundingBox())!;
		await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
		await page.mouse.down();
		await page.mouse.move(box.x + box.width / 2 + delta, box.y + box.height / 2);
		await page.mouse.up();
		await expect.poll(width).toBe(expected);
		await page.reload();
		await expect.poll(width).toBe(expected);
	}
});

test('late preview response never replaces the newly opened Item', async ({ page }) => {
	await mockLibrary(page);
	let release!: () => void;
	let started = false;
	const gate = new Promise<void>((resolve) => {
		release = resolve;
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', async (route) => {
		started = true;
		await gate;
		await route.fulfill({ json: overview('item-1') });
	});
	await page.goto('/workspace/workspace-1/library');
	await page.getByRole('button', { name: 'Preview Item 1', exact: true }).click();
	await expect.poll(() => started).toBe(true);
	await page.getByRole('button', { name: 'Preview Item 2', exact: true }).click();
	await expect(page.getByRole('heading', { name: 'Preview item-2', exact: true })).toBeVisible();
	release();
	await expect(page.getByRole('heading', { name: 'Preview item-1', exact: true })).toHaveCount(0);
});

test('failed and deleted preview reads are recoverable without displaying old Item content', async ({
	page
}) => {
	await mockLibrary(page);
	let failed = true;
	await page.route('**/api/v1/workspaces/workspace-1/items/item-1/overview', (route) =>
		failed
			? route.fulfill({ status: 404, json: { code: 'resource_not_found', message: 'Not found' } })
			: route.fulfill({ json: overview('item-1') })
	);
	await page.goto('/workspace/workspace-1/library?preview=item-1');
	const preview = page.getByRole('complementary', { name: 'Item preview' });
	await expect(preview.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
	failed = false;
	await preview.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(preview.getByRole('heading', { name: 'Preview item-1', exact: true })).toBeVisible();
	failed = true;
	await preview.getByRole('button', { name: 'Refresh preview', exact: true }).click();
	await expect(preview.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
	await expect(preview.getByRole('heading', { name: 'Preview item-1', exact: true })).toHaveCount(
		0
	);
	await expect(page.getByRole('table')).toBeVisible();
});

for (const theme of ['light', 'dark']) {
	test(`table, column settings and preview have no serious accessibility findings in ${theme} mode`, async ({
		page
	}) => {
		await page.addInitScript((value) => localStorage.setItem('quirebase:theme', value), theme);
		await mockLibrary(page);
		await page.goto('/workspace/workspace-1/library?page_size=100');
		await expect(page.getByRole('table').getByRole('checkbox')).toHaveCount(100);
		await page.getByRole('button', { name: 'Preview Item 1', exact: true }).click();
		await expect(page.getByRole('heading', { name: 'Preview item-1', exact: true })).toBeVisible();
		const check = async () => {
			const result = await new AxeBuilder({ page })
				.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
				.analyze();
			expect(
				result.violations
					.filter((v) => v.impact === 'serious' || v.impact === 'critical')
					.map((v) => ({ id: v.id, targets: v.nodes.map((n) => n.target) }))
			).toEqual([]);
		};
		await check();
		await page.getByRole('button', { name: 'Display options', exact: true }).click();
		await expect(page.getByRole('checkbox', { name: 'DOI', exact: true })).toBeVisible();
		await check();
		await page.keyboard.press('Escape');
		await page.screenshot({ path: `/tmp/quirebase-library-table-${theme}.png`, fullPage: true });
	});
}

test('narrow screens use compact reading links without page overflow', async ({ page }) => {
	await page.setViewportSize({ width: 320, height: 720 });
	const { reads } = await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	await expect(page.getByRole('table')).toHaveCount(0);
	await expect(
		page.locator('#library-results article').first().getByRole('link').first()
	).toHaveAttribute(
		'href',
		`/workspace/workspace-1/item/item-1?${new URLSearchParams({
			return_to: 'workspace/workspace-1/library#library-item-item-1'
		})}`
	);
	await page.getByRole('checkbox', { name: 'Select Author 1', exact: true }).check();
	const trigger = page.getByRole('button', { name: 'Preview Item 1', exact: true });
	await trigger.click();
	const preview = page.getByRole('complementary', { name: 'Item preview' });
	await expect(preview.getByRole('heading', { name: 'Preview item-1', exact: true })).toBeVisible();
	await expect(
		preview.getByRole('heading', { name: 'Item preview', exact: true })
	).toBeInViewport();
	await preview.getByRole('button', { name: 'Close preview', exact: true }).click();
	await expect(trigger).toBeFocused();
	await expect(trigger).toBeInViewport();
	const view = page.getByRole('radiogroup', { name: 'View', exact: true });
	const search = page.getByPlaceholder('Search title, author, Tag, or full text');
	await search.fill('unsubmitted draft');
	const readCount = reads.length;
	await view.getByRole('radio', { name: 'Table', exact: true }).press('Space');
	await expect(page.getByRole('table')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Display options', exact: true })).toBeVisible();
	await expect(page.getByRole('checkbox', { name: 'Select Author 1', exact: true })).toBeChecked();
	await expect
		.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
		.toBe(true);
	await view.getByRole('radio', { name: 'List', exact: true }).press('Space');
	await page.setViewportSize({ width: 1440, height: 900 });
	await expect(page.getByRole('table')).toHaveCount(0);
	await expect(page.getByRole('button', { name: 'Display options', exact: true })).toBeVisible();
	await view.getByRole('radio', { name: 'Automatic', exact: true }).press('Space');
	await expect(page.getByRole('table')).toBeVisible();
	await expect(page.getByRole('checkbox', { name: 'Select Author 1', exact: true })).toBeChecked();
	await page.setViewportSize({ width: 320, height: 720 });
	await expect(page.getByRole('table')).toHaveCount(0);
	await expect(search).toHaveValue('unsubmitted draft');
	expect(reads).toHaveLength(readCount);
});

test('desktop controls share one row and density remains available in both views', async ({
	page
}) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	const controls = page.getByRole('group', { name: 'Library controls', exact: true });
	const sort = controls.getByRole('group', { name: 'Sort', exact: true });
	await expect(sort.getByRole('option')).toHaveText([
		'Date modified',
		'Date added',
		'Publication date',
		'Publication',
		'Author',
		'Title'
	]);
	await expect(sort.getByRole('button')).toHaveAccessibleName(
		'Sort order: Newest first. Switch to Oldest first.'
	);
	const view = controls.getByRole('radiogroup', { name: 'View', exact: true });
	const display = controls.getByRole('button', { name: 'Display options', exact: true });
	const boxes = await Promise.all([sort, view, display].map((control) => control.boundingBox()));
	const centers = boxes.map((box) => box!.y + box!.height / 2);
	expect(Math.max(...centers) - Math.min(...centers)).toBeLessThan(2);
	await view.getByRole('radio', { name: 'List', exact: true }).press('Space');
	await display.click();
	await expect(page.getByRole('combobox', { name: 'Density', exact: true })).toBeFocused();
	await page.getByRole('combobox', { name: 'Density', exact: true }).selectOption('compact');
	await expect(page.getByRole('checkbox', { name: 'Authors', exact: true })).toHaveCount(0);
	await page.keyboard.press('Escape');
	await expect(display).toBeFocused();
	await expect(page.getByRole('combobox', { name: 'Density', exact: true })).toBeHidden();
	await view.getByRole('radio', { name: 'Table', exact: true }).press('Space');
	await display.click();
	await expect(page.getByRole('combobox', { name: 'Density', exact: true })).toBeFocused();
	await expect(page.getByRole('combobox', { name: 'Density', exact: true })).toHaveValue('compact');
	await expect(page.getByRole('checkbox', { name: 'Authors', exact: true })).toBeChecked();
	await page.keyboard.press('Escape');
	await expect(display).toBeFocused();
	await expect(page.getByRole('combobox', { name: 'Density', exact: true })).toBeHidden();
	await page
		.locator('#library-results')
		.screenshot({ path: '/tmp/quirebase-library-controls.png' });
});

for (const control of ['field', 'direction'] as const) {
	test(`sort ${control} keeps keyboard focus after slow sorting`, async ({ page }) => {
		await mockLibrary(page);
		await page.goto('/workspace/workspace-1/library');
		const target = page.locator(`#library-sort-${control}`);
		await expect(target).toBeVisible();
		let release = () => {};
		const pending = new Promise<void>((resolve) => {
			release = resolve;
		});
		await page.route('**/api/v1/workspaces/*/items?*', async (route) => {
			await pending;
			await route.fallback();
		});
		await target.focus();
		if (control === 'field') await target.selectOption('author');
		else await target.press('Enter');
		await expect(page.getByRole('status').filter({ hasText: 'Loading Library…' })).toBeVisible();
		release();
		await expect(page.getByRole('checkbox', { name: 'Select this page' })).toBeVisible();
		await expect(target).toBeFocused();
	});
}

test('icon view segments support pointer and arrow keys and retain the chosen mode', async ({
	page
}) => {
	await mockLibrary(page);
	await page.goto('/workspace/workspace-1/library');
	const view = page.getByRole('radiogroup', { name: 'View', exact: true });
	const automatic = view.getByRole('radio', { name: 'Automatic', exact: true });
	const table = view.getByRole('radio', { name: 'Table', exact: true });
	const list = view.getByRole('radio', { name: 'List', exact: true });
	await expect(automatic).toBeChecked();
	await automatic.focus();
	await automatic.press('ArrowRight');
	await expect(table).toBeChecked();
	await table.press('ArrowRight');
	await expect(list).toBeChecked();
	await expect(page.getByRole('table')).toHaveCount(0);
	await page.reload();
	await expect(list).toBeChecked();
	await view.getByTitle('Table', { exact: true }).click();
	await expect(table).toBeChecked();
	await expect(page.getByRole('table')).toBeVisible();
	await view.getByTitle('List', { exact: true }).click();
	await expect(list).toBeChecked();
	await list.press('ArrowLeft');
	await table.press('ArrowLeft');
	await expect(automatic).toBeChecked();
	await page.setViewportSize({ width: 320, height: 720 });
	await expect(page.getByRole('table')).toHaveCount(0);
	await expect(automatic).toBeChecked();
	await expect
		.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
		.toBe(true);
	await page
		.locator('#library-results')
		.evaluate((element) =>
			window.scrollTo({ top: element.getBoundingClientRect().top + scrollY - 80 })
		);
	await page.screenshot({
		path: '/tmp/quirebase-library-controls-mobile.png',
		animations: 'disabled'
	});
});
