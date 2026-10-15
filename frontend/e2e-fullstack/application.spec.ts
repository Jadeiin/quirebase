import { readFile } from 'node:fs/promises';
import { expect, type Page, test } from '@playwright/test';
import { minimalPdf } from '../e2e/helpers';

async function signIn(page: Page) {
	await page.goto('/');
	await page.getByLabel('Username').fill('admin');
	await page.getByLabel('Password').fill('quirebase-e2e');
	await page.getByRole('button', { name: 'Sign in' }).click();
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	await expect(page).toHaveURL(/\/workspace\/[^/]+$/);
	return new URL(page.url()).pathname.split('/').at(-1)!;
}

test('applies the stored theme under production CSP before hydration', async ({ page }) => {
	const cspErrors: string[] = [];
	page.on('console', (message) => {
		if (message.text().includes('Content Security Policy')) cspErrors.push(message.text());
	});
	await page.addInitScript(() => localStorage.setItem('quirebase:theme', 'dark'));
	await page.route('**/_app/immutable/**/*.js', (route) => route.abort());

	await page.goto('/', { waitUntil: 'domcontentloaded' });

	await expect(page.locator('html')).toHaveAttribute('data-mode', 'dark');
	expect(cspErrors).toEqual([]);
});

test('serves the packaged application and revokes the Login Session', async ({ page }) => {
	await signIn(page);

	await page.goto('/account');
	await page.getByRole('button', { name: 'Sign out' }).click();

	await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
	await page.reload();
	await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible();
});

test('creates, edits, and finds duplicate-capable Commonmeta Items through the real API', async ({
	page
}) => {
	const workspaceId = await signIn(page);
	const initialTitle = 'Full-stack smoke Item';
	const revisedTitle = 'Revised full-stack smoke Item';

	await page.goto(`/workspace/${workspaceId}/import`);
	await page.getByRole('tab', { name: 'Manual creation', exact: true }).click();
	await page.getByLabel('Title', { exact: true }).fill(initialTitle);
	await page.getByRole('button', { name: 'Edit standard metadata JSON' }).click();
	const json = page.getByRole('textbox', { name: 'Metadata', exact: true });
	const work = {
		...JSON.parse(await json.inputValue()),
		id: 'https://doi.org/10.1000/fullstack',
		type: 'Dataset',
		date_published: '2024-02-29T12:34:56Z',
		identifiers: [
			{ identifier_type: 'DOI', identifier: '10.1000/secondary' },
			{ identifier_type: 'DOI', identifier: '10.1000/third' }
		],
		funding_references: [{ funder_name: 'Foundation', award_number: '123' }],
		contributors: [
			{
				type: 'Person',
				person: { name: 'Ada Researcher', affiliations: [{ name: 'University' }] },
				roles: ['Author']
			}
		],
		relations: [{ id: 'https://doi.org/10.1000/related', type: 'IsSupplementTo' }],
		container: { identifiers: [{ identifier_type: 'ISBN', identifier: '9780131103627' }] }
	};
	await json.fill(JSON.stringify(work));
	await page.getByRole('button', { name: 'Apply JSON', exact: true }).click();
	await page.getByRole('button', { name: 'Create Item' }).click();

	await expect(page).toHaveURL(/\/item\/[0-9a-f-]+$/);
	const itemId = new URL(page.url()).pathname.split('/').at(-1)!;
	await expect(page.getByRole('heading', { name: initialTitle })).toBeVisible();
	await page.getByRole('link', { name: 'Metadata', exact: true }).click();
	await page.getByLabel('Title', { exact: true }).fill(revisedTitle);
	await page
		.locator('[data-work-group] > summary')
		.filter({ hasText: /^Contributors$/ })
		.click();
	await page.locator('#root_contributors_0_person_name').fill('Ada Revised');
	await page.locator('#root_contributors_0_type').selectOption('Organization');
	await page.locator('#root_contributors_0_organization_name').fill('Research Council');
	await page
		.locator('[data-work-group] > summary')
		.filter({ hasText: /^Funding references$/ })
		.click();
	await page.locator('#root_funding_references_0_funder_name').fill('Revised Foundation');
	await page
		.locator('[data-work-group] > summary')
		.filter({ hasText: /^Identifiers$/ })
		.click();
	await page.locator('#root_identifiers_1_identifier').fill('10.1000/revised-third');
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect(page.getByRole('heading', { name: revisedTitle })).toBeVisible();
	const response = await page.request.get(`/api/v1/workspaces/${workspaceId}/items/${itemId}`);
	expect(response.ok()).toBe(true);
	const detail = await response.json();
	expect(detail.authors).toBe('Research Council');
	expect(detail.metadata).toEqual({
		...work,
		title: revisedTitle,
		contributors: [
			{
				...work.contributors[0],
				type: 'Organization',
				person: { ...work.contributors[0].person, name: 'Ada Revised' },
				organization: { name: 'Research Council' }
			}
		],
		funding_references: [{ ...work.funding_references[0], funder_name: 'Revised Foundation' }],
		identifiers: [
			work.identifiers[0],
			{ ...work.identifiers[1], identifier: '10.1000/revised-third' }
		]
	});

	await page.evaluate(() =>
		Object.defineProperty(window, 'showSaveFilePicker', { value: undefined, configurable: true })
	);
	await page.getByRole('button', { name: 'Export', exact: true }).click();
	for (const format of ['csl-json', 'commonmeta']) {
		await page.getByRole('combobox', { name: 'Format', exact: true }).selectOption(format);
		const downloaded = page.waitForEvent('download');
		await page.getByRole('button', { name: 'Download file', exact: true }).click();
		const file = await downloaded;
		expect(file.suggestedFilename()).toMatch(/\.json$/);
		const exported = JSON.parse(await readFile((await file.path())!, 'utf8'));
		if (format === 'commonmeta') expect(exported).toEqual([detail.metadata]);
		else {
			expect(exported).toHaveLength(1);
			expect(exported[0].title).toBe(revisedTitle);
			expect(exported[0].type).toBe('dataset');
		}
	}

	await page.goto(`/workspace/${workspaceId}/library`);
	await page.getByPlaceholder('Search title, author, Tag, or full text').fill(revisedTitle);
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page.getByRole('link', { name: revisedTitle })).toBeVisible();

	await page.goto(`/workspace/${workspaceId}/import`);
	await page.getByRole('tab', { name: 'Manual creation', exact: true }).click();
	await page.getByLabel('Title', { exact: true }).fill('Duplicate smoke Item');
	await page.getByRole('button', { name: 'Edit standard metadata JSON' }).click();
	await page
		.getByRole('textbox', { name: 'Metadata', exact: true })
		.fill(JSON.stringify({ ...work, title: 'Duplicate smoke Item' }));
	await page.getByRole('button', { name: 'Apply JSON', exact: true }).click();
	await page.getByRole('button', { name: 'Create Item' }).click();
	await expect(page).toHaveURL(/\/item\/[0-9a-f-]+$/);
	expect(new URL(page.url()).pathname.split('/').at(-1)).not.toBe(itemId);
	await expect(page.getByRole('heading', { name: 'Duplicate smoke Item' })).toBeVisible();
});

test('creates a Project through the real API', async ({ page }) => {
	const workspaceId = await signIn(page);

	await page.goto(`/workspace/${workspaceId}/projects`);
	await page.getByRole('button', { name: 'New Project' }).click();
	await page.getByLabel('Name').fill('Full-stack smoke Project');
	await page.getByLabel('Description').fill('Created by the real browser-to-database smoke test.');
	await page.getByLabel('Participation').selectOption('open');
	await page.getByRole('button', { name: 'Create Project' }).click();

	await expect(page).toHaveURL(/\/workspace\/[^/]+\/projects\/[0-9a-f-]+$/);
	await expect(page.getByRole('heading', { name: 'Full-stack smoke Project' })).toBeVisible();
});

test('runs a staged PDF Import through the durable worker', async ({ page }) => {
	const workspaceId = await signIn(page);

	await page.goto(`/workspace/${workspaceId}/import`);
	await page.getByRole('tab', { name: 'PDFs', exact: true }).click();
	await page.locator('input[name="pdfs"]').setInputFiles({
		name: 'fullstack-smoke.pdf',
		mimeType: 'application/pdf',
		buffer: minimalPdf()
	});
	await page.getByRole('button', { name: 'Stage PDFs' }).click();

	await expect(page.getByRole('heading', { name: 'Import preview' })).toBeVisible();
	await expect(page.getByRole('heading', { name: 'Diagnostics' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Commit' })).toBeDisabled();
	await expect(page.getByText('fullstack-smoke.pdf')).toBeVisible();
});
