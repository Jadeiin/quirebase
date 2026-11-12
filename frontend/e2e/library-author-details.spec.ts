import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFile } from 'node:fs/promises';
import { directoryPage, mockSession, tagPage } from './helpers';

const contributors = [
	{
		type: 'Person',
		roles: ['Author'],
		person: {
			name: 'Alex Morgan',
			id: 'https://orcid.org/0000-0002-1825-0097',
			affiliations: [
				{ name: 'First Institute', identifier: '03yrm5c26', identifier_type: 'ROR' },
				{ name: 'Laboratory without ID' }
			]
		}
	},
	{
		type: 'Person',
		roles: ['Author'],
		person: { name: 'Alex Morgan', affiliations: [{ name: 'Second Institute' }] }
	},
	{
		type: 'Organization',
		roles: ['Author'],
		organization: { name: 'Research Council', id: 'https://ror.org/02mhbdp94' },
		person: {
			name: 'Inactive',
			affiliations: [
				{ name: 'Inactive institution', identifier: '03yrm5c26', identifier_type: 'ROR' }
			]
		}
	},
	...Array.from({ length: 28 }, (_, index) => ({
		type: 'Person',
		roles: ['Author'],
		person: { name: `Researcher With A Full Name ${index + 4}` }
	})),
	{ type: 'Person', roles: ['Author'], person: { name: 'Last Author' } }
];

async function setup(page: Page, credits = contributors) {
	await mockSession(page);
	for (const resource of ['tags', 'projects'])
		await page.route(`**/api/v1/workspaces/workspace-1/${resource}?*`, (route) =>
			route.fulfill({ json: resource === 'tags' ? tagPage([], route) : directoryPage([], route) })
		);
	const reads: URLSearchParams[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) => {
		const params = new URL(route.request().url()).searchParams;
		reads.push(params);
		return route.fulfill({
			json: {
				items: [
					{
						id: 'source',
						title_html: 'Research identity',
						authors: [{ full_name: 'Alex Morgan', last_name: 'Alex Morgan', first_name: null }],
						publication_date: '2026',
						publication_title: 'Journal',
						doi: null,
						version: 1
					}
				],
				total: 26,
				limit: Number(params.get('limit')),
				offset: Number(params.get('offset'))
			}
		});
	});
	await page.route('**/api/v1/workspaces/workspace-1/items/source/overview', (route) =>
		route.fulfill({
			json: {
				id: 'source',
				version: 1,
				metadata: {
					id: 'urn:test:source',
					type: 'JournalArticle',
					title: 'Research identity',
					contributors: credits
				},
				citation_key: null,
				authorization: { allowed: [] },
				tags: [],
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
				latest_revision_id: null,
				copy_targets: []
			}
		})
	);
	return reads;
}

test('Library author popovers stay above table headers and view controls', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 600 });
	await setup(page, contributors.slice(0, 1));
	await page.goto('/workspace/workspace-1/library?preview=source');
	// Keep an actual overlap even when the default height constraint avoids this collision.
	await page.addStyleTag({
		content: '[data-scope="popover"][data-part="content"] { max-height: 70dvh; }'
	});
	const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
	await preview
		.getByRole('button', { name: 'View details for Alex Morgan', exact: true })
		.first()
		.click();
	const details = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
	await expect(details.getByText('First Institute', { exact: true })).toBeVisible();

	await expect
		.poll(() =>
			details.evaluate((dialog) => {
				const bounds = dialog.getBoundingClientRect();
				const overlaps = (selector: string) => {
					const target = document.querySelector(selector)?.getBoundingClientRect();
					return Boolean(
						target &&
						bounds.left < target.right &&
						bounds.right > target.left &&
						bounds.top < target.bottom &&
						bounds.bottom > target.top
					);
				};
				const covered: string[] = [];
				for (let x = bounds.left + 8; x < bounds.right - 8; x += 8)
					for (let y = bounds.top + 8; y < bounds.bottom - 8; y += 8) {
						const top = document.elementFromPoint(x, y);
						if (top && !dialog.contains(top)) covered.push(top.outerHTML.slice(0, 180));
					}
				return {
					headerOverlap: overlaps('#library-results thead'),
					viewOverlap: overlaps('#library-results [role="radiogroup"]'),
					covered: [...new Set(covered)]
				};
			})
		)
		.toEqual({ headerOverlap: true, viewOverlap: true, covered: [] });
	await details.getByRole('link', { name: 'Filter Library by this ORCID', exact: true }).click();
	await expect
		.poll(() => new URL(page.url()).searchParams.get('author_orcid'))
		.toBe('0000-0002-1825-0097');
	await expect(page.getByRole('radio', { name: 'Automatic', exact: true })).toBeChecked();
});

test('short desktop windows scroll author actions within the viewport', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 600 });
	await setup(page, contributors.slice(0, 1));
	await page.goto('/workspace/workspace-1/library?preview=source');
	await page
		.getByRole('complementary', { name: 'Item preview', exact: true })
		.getByRole('button', { name: 'View details for Alex Morgan', exact: true })
		.click();
	const details = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
	const action = details
		.getByRole('group', { name: 'Library filters', exact: true })
		.getByRole('link', {
			name: 'Filter Library by this name',
			exact: true
		});
	await expect(action).toBeVisible();
	await expect
		.poll(() =>
			details.evaluate((element) => {
				const bounds = element.getBoundingClientRect();
				return bounds.top >= 0 && bounds.bottom <= innerHeight;
			})
		)
		.toBe(true);
	await action.scrollIntoViewIfNeeded();
	expect(await details.evaluate((element) => element.scrollTop > 0)).toBe(true);
	await action.click();
	await expect
		.poll(() => JSON.parse(new URL(page.url()).searchParams.get('authors') ?? 'null'))
		.toEqual([{ last_name: 'Alex Morgan', first_name: '' }]);
	expect(new URL(page.url()).searchParams.has('author_ror')).toBe(false);
});

for (const locale of ['en-US', 'zh-CN']) {
	test(`320px combined name and ROR action stays inside author details (${locale})`, async ({
		page
	}) => {
		await page.setViewportSize({ width: 320, height: 800 });
		await page.addInitScript((locale) => localStorage.setItem('quirebase:locale', locale), locale);
		await setup(page, contributors.slice(0, 1));
		await page.goto('/workspace/workspace-1/item/source');
		await page
			.getByRole('button', {
				name: locale === 'zh-CN' ? '查看 Alex Morgan 的详情' : 'View details for Alex Morgan',
				exact: true
			})
			.click();
		const details = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
		const action = details.getByRole('link', {
			name:
				locale === 'zh-CN'
					? '按此署名和 ROR 筛选库内文献：First Institute'
					: 'Filter Library by this name and ROR: First Institute',
			exact: true
		});
		await expect(action).toBeVisible();
		const bounds = (await details.boundingBox())!;
		const button = (await action.boundingBox())!;
		expect(button.x + button.width).toBeLessThanOrEqual(bounds.x + bounds.width);
		expect(await action.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(
			true
		);
		await action.click();
		await expect.poll(() => new URL(page.url()).searchParams.get('author_ror')).toBe('03yrm5c26');
		expect(JSON.parse(new URL(page.url()).searchParams.get('authors')!)).toEqual([
			{ last_name: 'Alex Morgan', first_name: '' }
		]);
		expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
			true
		);
	});
}

for (const value of ['invalid', '']) {
	test(`invalid ROR (${value || 'empty'}) stays visible and removable`, async ({ page }) => {
		await setup(page);
		await page.route('**/api/v1/workspaces/workspace-1/items?*', (route) =>
			new URL(route.request().url()).searchParams.has('author_ror')
				? route.fulfill({
						status: 422,
						json: { code: 'validation_failed', message: 'invalid author institution ROR' }
					})
				: route.fallback()
		);
		await page.goto(`/workspace/workspace-1/library?${new URLSearchParams({ author_ror: value })}`);
		await expect(
			page.getByText('Invalid ROR filter. Remove it to continue.', { exact: true })
		).toBeVisible();
		await expect(page.getByText('Unable to load the Library.', { exact: true })).toBeVisible();
		await page
			.getByRole('button', {
				name: `Remove filter Author institution (ROR)${value ? `: ${value}` : ''}`,
				exact: true
			})
			.click();
		await expect(page).toHaveURL('/workspace/workspace-1/library');
		await expect(page.getByText('Research identity', { exact: true })).toBeVisible();
	});
}

for (const width of [1440, 390]) {
	test(`${width}px Library author details recover a failed chunk without losing identity filters`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 900 });
		await setup(page);
		const manifest = JSON.parse(
			await readFile('.svelte-kit/output/client/.vite/manifest.json', 'utf8')
		) as Record<string, { name?: string; file: string }>;
		const entry = Object.values(manifest).find(({ name }) => name === 'ItemAuthorDetailsContent')!;
		let attempts = 0;
		await page.route(`**/${entry.file}`, (route) =>
			++attempts === 1
				? route.fulfill({
						status: 503,
						headers: { 'Cache-Control': 'no-store' },
						body: 'Unavailable'
					})
				: route.continue()
		);
		const url =
			'/workspace/workspace-1/library?author_orcid=0000-0002-1825-0097&author_ror=03yrm5c26&preview=source';
		await page.goto(url);
		const trigger = page
			.getByRole('complementary', { name: 'Item preview', exact: true })
			.getByRole('button', { name: 'View details for Alex Morgan', exact: true })
			.first();
		await expect(trigger).toBeVisible();
		expect(attempts).toBe(0);
		await trigger.click();
		const details = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
		await expect(details.getByRole('alert')).toContainText('Unable to load author details.');
		const loaded = page.waitForEvent('load');
		await details.getByRole('button', { name: 'Refresh page', exact: true }).click();
		await loaded;
		await expect(page).toHaveURL(url);
		await trigger.click();
		await expect(details.getByText('First Institute', { exact: true })).toBeVisible();
		await expect(
			details.getByRole('link', {
				name: 'Filter Library by this name and ROR: First Institute',
				exact: true
			})
		).toBeVisible();
		expect(attempts).toBe(2);
	});

	test(`${width}px Library overview shares inline author folding and record-local details`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 900 });
		await setup(page);
		await page.goto('/workspace/workspace-1/library?preview=source');
		const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
		const byline = preview.locator('[data-author-byline]');
		const first = byline
			.getByRole('button', { name: 'View details for Alex Morgan', exact: true })
			.first();
		await expect(preview.getByRole('button', { name: 'Show authors', exact: true })).toBeVisible();
		const rowHeight = await byline.evaluate((element) =>
			Number.parseFloat(getComputedStyle(element).lineHeight)
		);
		expect((await byline.boundingBox())!.height).toBeLessThanOrEqual(
			rowHeight * (width < 768 ? 1 : 3) + 1
		);
		expect(await first.evaluate((element) => getComputedStyle(element).textDecorationLine)).toBe(
			'none'
		);
		await first.click();
		let details = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
		await expect(details.getByText('First Institute', { exact: true })).toBeVisible();
		await expect(details.getByText('Second Institute', { exact: true })).toHaveCount(0);
		await expect(
			details.getByRole('link', {
				name: 'Filter Library by this name and ROR: First Institute',
				exact: true
			})
		).toBeVisible();
		await expect(
			details.getByRole('link', { name: 'Filter Library by this ORCID', exact: true })
		).toBeVisible();
		expect(
			(await new AxeBuilder({ page }).include('[role="dialog"]').analyze()).violations.filter(
				(v) => v.impact === 'serious' || v.impact === 'critical'
			)
		).toEqual([]);
		await page.keyboard.press('Escape');
		await expect(details).toHaveCount(0);
		await expect(preview).toBeVisible();
		await expect(first).toBeFocused();
		await preview.getByRole('button', { name: 'Show authors', exact: true }).click();
		await expect(page.getByRole('dialog')).toHaveCount(0);
		await expect(byline.getByRole('button', { name: /^View details for / })).toHaveCount(
			contributors.length
		);
		await byline
			.getByRole('button', { name: 'View details for Alex Morgan', exact: true })
			.nth(1)
			.click();
		details = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
		await expect(details.getByText('Second Institute', { exact: true })).toBeVisible();
		await expect(details.getByText('First Institute', { exact: true })).toHaveCount(0);
		await expect(
			details.getByRole('link', { name: /Filter Library by this (ROR|ORCID)/ })
		).toHaveCount(0);
		await page.keyboard.press('Escape');
		await byline.getByRole('button', { name: 'View details for Last Author', exact: true }).click();
		details = page.getByRole('dialog', { name: 'Last Author', exact: true });
		await expect(details.getByText('Affiliations on this work', { exact: true })).toHaveCount(0);
		await expect(
			details.getByRole('link', { name: 'Filter Library by this name', exact: true })
		).toBeVisible();
		await page.keyboard.press('Escape');
		await preview.getByRole('button', { name: 'Show fewer authors', exact: true }).click();
		expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
			true
		);
	});

	test(`${width}px multiple institutions keep ROR-only and combined actions separate`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 900 });
		await setup(page, [
			{
				type: 'Person',
				roles: ['Author'],
				person: {
					name: 'Alex Morgan',
					affiliations: [
						{ name: 'First Institute', identifier: '03yrm5c26', identifier_type: 'ROR' },
						{ name: 'Another Institute', identifier: '02mhbdp94', identifier_type: 'ROR' },
						{ name: 'Laboratory without ID' }
					]
				}
			}
		]);
		await page.goto('/workspace/workspace-1/library?preview=source');
		await page
			.getByRole('complementary', { name: 'Item preview', exact: true })
			.getByRole('button', { name: 'View details for Alex Morgan', exact: true })
			.click();
		const details = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
		const footer = details.getByRole('group', { name: 'Library filters', exact: true });
		await expect(footer.getByRole('link', { name: /name and ROR/ })).toHaveCount(0);
		for (const [institution, ror] of [
			['First Institute', '03yrm5c26'],
			['Another Institute', '02mhbdp94']
		]) {
			const standalone = details
				.locator('dl')
				.getByRole('link', { name: institution, exact: true });
			const standaloneParameters = new URL((await standalone.getAttribute('href'))!, page.url())
				.searchParams;
			expect(standaloneParameters.get('author_ror')).toBe(ror);
			expect(standaloneParameters.has('authors')).toBe(false);
			await expect(standalone).toBeVisible();
			const combined = details.locator('dl').getByRole('link', {
				name: `Filter Library by this name and ROR: ${institution}`,
				exact: true
			});
			const combinedParameters = new URL((await combined.getAttribute('href'))!, page.url())
				.searchParams;
			expect(combinedParameters.get('author_ror')).toBe(ror);
			expect(JSON.parse(combinedParameters.get('authors')!)).toEqual([
				{ last_name: 'Alex Morgan', first_name: '' }
			]);
			expect((await standalone.boundingBox())!.y).toBeLessThan((await combined.boundingBox())!.y);
		}
		await details
			.locator('dl')
			.getByRole('link', {
				name: 'Filter Library by this name and ROR: Another Institute',
				exact: true
			})
			.click();
		await expect.poll(() => new URL(page.url()).searchParams.get('author_ror')).toBe('02mhbdp94');
	});

	test(`${width}px Library preview identity actions retain submitted scope and close details`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 900 });
		const reads = await setup(page);
		const initial = new URLSearchParams({
			q: 'committed',
			authors: JSON.stringify([{ last_name: 'Coauthor', first_name: '' }]),
			year: '2026',
			has_files: 'false',
			sort: 'title',
			page: '2',
			page_size: '10',
			preview: 'source'
		});
		await page.goto(`/workspace/workspace-1/library?${initial}`);
		await page.getByPlaceholder('Search title, author, Tag, or full text').fill('unsaved draft');
		const preview = page.getByRole('complementary', { name: 'Item preview', exact: true });
		const first = preview
			.getByRole('button', { name: 'View details for Alex Morgan', exact: true })
			.first();
		await first.click();
		await page
			.getByRole('dialog', { name: 'Alex Morgan', exact: true })
			.getByRole('link', { name: 'Filter Library by this ORCID', exact: true })
			.click();
		await expect
			.poll(() => new URL(page.url()).searchParams.get('author_orcid'))
			.toBe('0000-0002-1825-0097');
		await expect(page.getByRole('dialog')).toHaveCount(0);
		await first.click();
		await page
			.getByRole('dialog', { name: 'Alex Morgan', exact: true })
			.locator('dl')
			.getByRole('link', { name: 'First Institute', exact: true })
			.click();
		await expect.poll(() => new URL(page.url()).searchParams.get('author_ror')).toBe('03yrm5c26');
		expect(JSON.parse(new URL(page.url()).searchParams.get('authors')!)).toEqual([
			{ last_name: 'Coauthor', first_name: '' }
		]);
		await first.click();
		await page
			.getByRole('dialog', { name: 'Alex Morgan', exact: true })
			.locator('dl')
			.getByRole('link', {
				name: 'Filter Library by this name and ROR: First Institute',
				exact: true
			})
			.click();
		await expect.poll(() => new URL(page.url()).searchParams.get('author_ror')).toBe('03yrm5c26');
		await expect(page.getByRole('dialog')).toHaveCount(0);
		await expect.poll(() => reads.at(-1)?.get('author_ror')).toBe('03yrm5c26');
		const parameters = new URL(page.url()).searchParams;
		for (const key of ['q', 'year', 'has_files', 'sort', 'page_size', 'preview'])
			expect(parameters.get(key)).toBe(initial.get(key));
		expect(parameters.has('page')).toBe(false);
		expect(JSON.parse(parameters.get('authors')!)).toEqual([
			{ last_name: 'Coauthor', first_name: '' },
			{ last_name: 'Alex Morgan', first_name: '' }
		]);
		expect(reads.at(-1)?.get('authors')).toBe(parameters.get('authors'));
		expect(reads.at(-1)?.get('author_orcid')).toBe('0000-0002-1825-0097');
		expect(reads.at(-1)?.get('query')).toBe('committed');
		await expect(
			page.getByText('ORCID, ROR and name filters may match different authors on the same Item.', {
				exact: false
			})
		).toBeVisible();
		await page.reload();
		await expect(
			page.getByRole('button', {
				name: 'Remove filter Author institution (ROR): 03yrm5c26',
				exact: true
			})
		).toBeVisible();
		await expect(preview).toBeVisible();
	});

	test(`${width}px Item header offers separate ROR profiles and filters for affiliations and organizations`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 900 });
		await setup(page);
		await page.goto('/workspace/workspace-1/item/source');
		await page
			.getByRole('button', { name: 'View details for Alex Morgan', exact: true })
			.first()
			.click();
		let details = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
		await expect(
			details.getByRole('link', { name: 'ROR: 03yrm5c26', exact: true })
		).toHaveAttribute('href', 'https://ror.org/03yrm5c26');
		await expect(
			details.getByRole('link', { name: 'ROR: 03yrm5c26', exact: true })
		).toHaveAttribute('target', '_blank');
		const footer = details.getByRole('group', { name: 'Library filters', exact: true });
		expect(
			(await footer.getByRole('link').allTextContents())
				.map((label) => label.trim().replace(/\s+/g, ' '))
				.slice(-1)
		).toEqual(['Filter Library by this name']);
		await details.locator('dl').getByRole('link', { name: 'First Institute', exact: true }).click();
		await expect.poll(() => new URL(page.url()).searchParams.get('author_ror')).toBe('03yrm5c26');
		expect(new URL(page.url()).searchParams.has('authors')).toBe(false);
		await page.goBack();
		await page
			.getByRole('button', { name: 'View details for Alex Morgan', exact: true })
			.first()
			.click();
		details = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
		await details
			.locator('dl')
			.getByRole('link', {
				name: 'Filter Library by this name and ROR: First Institute',
				exact: true
			})
			.click();
		await expect.poll(() => new URL(page.url()).searchParams.get('author_ror')).toBe('03yrm5c26');
		expect(JSON.parse(new URL(page.url()).searchParams.get('authors')!)).toEqual([
			{ last_name: 'Alex Morgan', first_name: '' }
		]);
		expect(new URL(page.url()).searchParams.has('author_orcid')).toBe(false);
		await expect(
			page.getByRole('button', { name: 'Remove filter Author: Alex Morgan', exact: true })
		).toBeVisible();
		await expect(
			page.getByText('Name and ROR filters may match different authors on the same Item.', {
				exact: false
			})
		).toBeVisible();
		await page.goBack();
		await page.getByRole('button', { name: 'Show authors', exact: true }).click();
		await page
			.getByRole('button', { name: 'View details for Research Council', exact: true })
			.click();
		details = page.getByRole('dialog', { name: 'Research Council', exact: true });
		await expect(details.getByText('Affiliations on this work', { exact: true })).toHaveCount(0);
		await expect(details.getByText('Inactive institution', { exact: true })).toHaveCount(0);
		await expect(
			details.getByRole('link', { name: 'ror.org/02mhbdp94', exact: true })
		).toHaveAttribute('target', '_blank');
		await details
			.locator('dl')
			.getByRole('link', {
				name: 'Filter Library by this name and ROR: Research Council',
				exact: true
			})
			.click();
		await expect.poll(() => new URL(page.url()).searchParams.get('author_ror')).toBe('02mhbdp94');
		expect(JSON.parse(new URL(page.url()).searchParams.get('authors')!)).toEqual([
			{ last_name: 'Research Council', first_name: '' }
		]);
	});
}
