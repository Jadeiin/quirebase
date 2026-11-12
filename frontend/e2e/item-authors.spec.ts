import { expect, test, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { readFile } from 'node:fs/promises';
import { mockSession } from './helpers';

function person(name: string, institution?: string, orcid?: string) {
	return {
		type: 'Person',
		person: {
			name,
			...(orcid ? { id: orcid } : {}),
			...(institution ? { affiliations: [{ name: institution }] } : {})
		},
		roles: ['Author']
	};
}

const longCredits = Array.from({ length: 48 }, (_, index) =>
	person(
		index === 0
			? 'First Author'
			: index === 47
				? 'Last Author'
				: `Researcher With A Full Name ${index + 1}`,
		`Institute ${index + 1}`,
		index % 2 === 0 ? 'https://orcid.org/0000-0002-1825-0097' : undefined
	)
);

async function setup(page: Page, contributors: unknown[]) {
	await mockSession(page);
	const snapshot = {
		id: 'authors-item',
		version: 1,
		metadata: {
			id: 'urn:test:authors',
			type: 'JournalArticle',
			title: 'Header author details',
			contributors
		},
		citation_key: null,
		authorization: { allowed: [] },
		counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 },
		tags: [],
		latest_revision_id: null,
		copy_targets: []
	};
	await page.route('**/api/v1/workspaces/workspace-1/items/authors-item/overview', (route) =>
		route.fulfill({ json: snapshot })
	);
	return snapshot;
}

for (const width of [1280, 390]) {
	test(`${width}px author details recover a failed chunk through an explicit page refresh`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height: 900 });
		await setup(page, [person('Ada', 'Institute A')]);
		const manifest = JSON.parse(
			await readFile('.svelte-kit/output/client/.vite/manifest.json', 'utf8')
		) as Record<string, { name?: string; file: string }>;
		const entry = Object.values(manifest).find(({ name }) => name === 'ItemAuthorDetailsContent')!;
		let chunkRequests = 0;
		await page.route(`**/${entry.file}`, (route) => {
			chunkRequests++;
			return chunkRequests === 1
				? route.fulfill({
						status: 503,
						headers: { 'Cache-Control': 'no-store' },
						body: 'Unavailable'
					})
				: route.continue();
		});
		const url = '/workspace/workspace-1/item/authors-item?source=review';
		await page.goto(url);
		expect(chunkRequests).toBe(0);
		await page.getByRole('button', { name: 'View details for Ada', exact: true }).click();
		let details = page.getByRole('dialog', { name: 'Ada', exact: true });
		await expect(details.getByRole('alert')).toContainText('Unable to load author details.');
		await expect(details.getByRole('button', { name: 'Refresh page', exact: true })).toBeVisible();
		await expect(page).toHaveURL(url);
		expect(chunkRequests).toBe(1);

		// A new document clears failed entries in the browser's module map. A keyed rerender cannot.
		const loaded = page.waitForEvent('load');
		await details.getByRole('button', { name: 'Refresh page', exact: true }).click();
		await loaded;
		await expect(page).toHaveURL(url);
		await page.getByRole('button', { name: 'View details for Ada', exact: true }).click();
		details = page.getByRole('dialog', { name: 'Ada', exact: true });
		await expect(details.getByText('Institute A', { exact: true })).toBeVisible();
		await expect(
			details.getByRole('link', { name: 'Filter Library by this name', exact: true })
		).toHaveAttribute('href', /authors=/);
		expect(chunkRequests).toBe(2);
	});
}

test('short bylines stay complete and details keep same-name and organizational credits separate', async ({
	page
}) => {
	await page.setViewportSize({ width: 1280, height: 900 });
	await setup(page, [
		person('Alex Morgan', 'First Institute', 'https://orcid.org/0000-0002-1825-0097'),
		person('Alex Morgan', 'Second Institute'),
		{
			type: 'Organization',
			organization: { name: 'Research Council' },
			person: { affiliations: [{ name: 'Inactive institution' }] },
			roles: ['Author']
		}
	]);
	await page.goto('/workspace/workspace-1/item/authors-item');
	const names = page.getByRole('button', { name: 'View details for Alex Morgan', exact: true });
	await names.nth(0).click();
	let dialog = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
	await expect(dialog.getByText('First Institute', { exact: true })).toBeVisible();
	await expect(dialog.getByText('Second Institute', { exact: true })).toHaveCount(0);
	await expect(dialog.getByRole('link', { name: 'orcid.org/0000-0002-1825-0097' })).toHaveAttribute(
		'href',
		'https://orcid.org/0000-0002-1825-0097'
	);
	await page.keyboard.press('Escape');
	await expect(names.nth(0)).toBeFocused();
	await names.nth(1).click();
	dialog = page.getByRole('dialog', { name: 'Alex Morgan', exact: true });
	await expect(dialog.getByText('Second Institute', { exact: true })).toBeVisible();
	await expect(dialog.getByRole('link', { name: /orcid.org/ })).toHaveCount(0);
	await page.keyboard.press('Escape');
	await page
		.getByRole('button', { name: 'View details for Research Council', exact: true })
		.click();
	await expect(
		page.getByRole('dialog').getByText('Affiliations on this work', { exact: true })
	).toHaveCount(0);
	await expect(page.getByText('Inactive institution', { exact: true })).toHaveCount(0);
	await page.keyboard.press('Escape');
	await expect(page.getByRole('button', { name: 'Show authors', exact: true })).toHaveCount(0);
});

for (const { width, maxRows } of [
	{ width: 1280, maxRows: 3 },
	{ width: 320, maxRows: 1 }
]) {
	test(`${width}px bylines fold to ${maxRows} rows and expand inline`, async ({ page }) => {
		await page.setViewportSize({ width, height: 900 });
		await setup(page, longCredits);
		await page.goto('/workspace/workspace-1/item/authors-item');
		const byline = page.locator('[data-author-byline]');
		const names = byline.getByRole('button', { name: /^View details for / });
		const more = page.getByRole('button', { name: 'Show authors', exact: true });
		await expect(more).toBeVisible();
		await expect(more).toHaveAttribute('aria-expanded', 'false');
		await expect(more).toHaveAttribute('aria-controls', (await byline.getAttribute('id'))!);
		await expect.poll(() => names.count()).toBeGreaterThan(0);
		const initialCount = await names.count();
		expect(initialCount).toBeLessThan(48);
		await expect(names.first()).toHaveText('First Author');
		await expect(names.last()).toHaveText('Last Author');
		await expect(
			byline.getByRole('button', { name: 'Show all authors', exact: true })
		).toBeVisible();
		expect(await byline.innerText()).toContain('…');
		for (const name of await names.all()) {
			expect(await name.evaluate((element) => element.scrollWidth <= element.clientWidth + 1)).toBe(
				true
			);
		}
		const rowHeight = await byline.evaluate((element) =>
			Number.parseFloat(getComputedStyle(element).lineHeight)
		);
		expect((await byline.boundingBox())!.height).toBeLessThanOrEqual(rowHeight * maxRows + 1);
		expect(
			await names.first().evaluate((element) => getComputedStyle(element).textDecorationLine)
		).toBe('none');
		const tabs = page.getByRole('navigation', { name: 'Item sections' });
		const tabTop = (await tabs.boundingBox())!.y;

		await more.press('Enter');
		const fewer = page.getByRole('button', { name: 'Show fewer authors', exact: true });
		await expect(fewer).toHaveAttribute('aria-expanded', 'true');
		await expect(names).toHaveCount(48);
		await expect(page.getByRole('dialog')).toHaveCount(0);
		expect((await byline.boundingBox())!.height).toBeGreaterThan(rowHeight * maxRows);
		const author = page.getByRole('button', {
			name: 'View details for Researcher With A Full Name 30',
			exact: true
		});
		await author.click();
		const details = page.getByRole('dialog', {
			name: 'Researcher With A Full Name 30',
			exact: true
		});
		await expect(details.getByText('Institute 30', { exact: true })).toBeVisible();
		await expect(
			details.getByRole('heading', { name: 'Researcher With A Full Name 30', exact: true })
		).toBeFocused();
		await expect(
			details.getByRole('link', { name: 'Filter Library by this name', exact: true })
		).toHaveAttribute('href', /authors=/);
		expect(
			(await new AxeBuilder({ page }).include('[role="dialog"]').analyze()).violations
		).toEqual([]);
		await page.keyboard.press('Escape');
		await expect(author).toBeFocused();
		await expect(fewer).toBeVisible();

		await fewer.press('Enter');
		await expect(more).toBeFocused();
		await expect(names).toHaveCount(initialCount);
		await page.evaluate(() => window.scrollTo(0, 0));
		expect((await tabs.boundingBox())!.y).toBe(tabTop);
		expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
			true
		);
		expect(
			(await new AxeBuilder({ page }).include('[data-item-authors]').analyze()).violations
		).toEqual([]);
	});
}

test('folding follows width and font metrics and preserves focus when credits disappear', async ({
	page
}) => {
	await page.setViewportSize({ width: 1440, height: 900 });
	await setup(page, longCredits);
	await page.goto('/workspace/workspace-1/item/authors-item');
	const byline = page.locator('[data-author-byline]');
	const names = byline.getByRole('button', { name: /^View details for / });
	await expect.poll(() => names.count()).toBeGreaterThan(3);
	const wideCount = await names.count();
	await names.nth(wideCount - 2).focus();
	await page.setViewportSize({ width: 900, height: 900 });
	await expect.poll(() => names.count()).toBeLessThan(wideCount);
	await expect(page.getByRole('button', { name: 'Show all authors', exact: true })).toBeFocused();
	const narrowCount = await names.count();
	await page.addStyleTag({ content: '[data-item-authors] { font-size: 22px; }' });
	await expect.poll(() => names.count()).toBeLessThan(narrowCount);
	await page.getByRole('button', { name: 'Show authors', exact: true }).click();
	await page.setViewportSize({ width: 320, height: 900 });
	await expect(names).toHaveCount(48);
	await expect(page.getByRole('button', { name: 'Show fewer authors', exact: true })).toBeVisible();
});

test('a single overlong name uses the shared omission mark and can be revealed inline', async ({
	page
}) => {
	await page.setViewportSize({ width: 320, height: 900 });
	const name =
		'International Consortium for the Reproducibility of Scholarly Research and Open Metadata';
	await setup(page, [person(name, 'Institute A', 'https://orcid.org/0000-0002-1825-0097')]);
	await page.goto('/workspace/workspace-1/item/authors-item');
	const byline = page.locator('[data-author-byline]');
	await expect(page.getByRole('button', { name: 'Show authors', exact: true })).toBeVisible();
	const rowHeight = await byline.evaluate((element) =>
		Number.parseFloat(getComputedStyle(element).lineHeight)
	);
	expect((await byline.boundingBox())!.height).toBeLessThanOrEqual(rowHeight + 1);
	await expect(byline.getByRole('button', { name: /^View details for / })).toHaveCount(0);
	await byline.getByRole('button', { name: 'Show all authors', exact: true }).click();
	await expect(page.getByRole('button', { name: 'Show fewer authors', exact: true })).toBeFocused();
	expect((await byline.boundingBox())!.height).toBeGreaterThan(rowHeight);
	await expect(page.getByRole('dialog')).toHaveCount(0);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('short narrow bylines stay complete and detail state ends on saved Item changes', async ({
	page
}) => {
	const now = new Date();
	await page.clock.setFixedTime(now);
	await page.setViewportSize({ width: 390, height: 900 });
	const snapshot = await setup(page, [person('Ada', 'Institute A'), person('Bo'), person('Cy')]);
	await page.goto('/workspace/workspace-1/item/authors-item');
	await expect(
		page.getByRole('button', { name: 'View details for Cy', exact: true })
	).toBeVisible();
	await expect(page.getByRole('button', { name: 'Show authors', exact: true })).toHaveCount(0);
	const ada = page.getByRole('button', { name: 'View details for Ada', exact: true });
	await ada.click();
	await expect(page.getByRole('dialog')).toHaveAccessibleName('Ada');
	await expect(page.getByRole('heading', { name: 'Ada', exact: true })).toBeFocused();
	await page.keyboard.press('Escape');
	await expect(ada).toBeFocused();
	await ada.click();
	await expect(page.getByRole('heading', { name: 'Ada', exact: true })).toBeFocused();
	snapshot.version = 2;
	snapshot.metadata.contributors = [person('New author')];
	await page.clock.setFixedTime(new Date(now.getTime() + 31_000));
	const refreshed = page.waitForResponse('**/items/authors-item/overview');
	await page.evaluate(() => {
		// Other parallel browser pages may be foregrounded. Model returning to this page explicitly.
		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
		window.dispatchEvent(new Event('visibilitychange'));
	});
	await refreshed;
	await expect(page.getByRole('dialog')).toBeHidden();
	await expect(
		page.getByRole('button', { name: 'View details for New author', exact: true })
	).toBeVisible();
});

test('an open author popover closes gracefully when the byline becomes narrow', async ({
	page
}) => {
	await page.setViewportSize({ width: 1280, height: 900 });
	await setup(page, longCredits);
	await page.goto('/workspace/workspace-1/item/authors-item');
	await page
		.getByRole('button', { name: 'View details for Researcher With A Full Name 2', exact: true })
		.click();
	await expect(page.getByRole('dialog')).toBeVisible();
	await page.setViewportSize({ width: 320, height: 900 });
	await expect(page.getByRole('dialog')).toBeHidden();
	await expect
		.poll(() =>
			page
				.locator('[data-item-authors]')
				.evaluate((element) => element.contains(document.activeElement))
		)
		.toBe(true);
	await page.getByRole('button', { name: 'Show authors', exact: true }).click();
	await expect(page.getByRole('dialog')).toHaveCount(0);
	await expect(
		page.locator('[data-author-byline]').getByRole('button', { name: /^View details for / })
	).toHaveCount(48);
});
