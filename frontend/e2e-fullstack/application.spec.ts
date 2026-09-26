import { expect, type Page, test } from '@playwright/test';

async function signIn(page: Page) {
	await page.goto('/');
	await page.getByLabel('Username').fill('admin');
	await page.getByLabel('Password').fill('quirebase-e2e');
	await page.getByRole('button', { name: 'Sign in' }).click();
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
	await expect(page).toHaveURL(/\/workspace\/[^/]+$/);
	return new URL(page.url()).pathname.split('/').at(-1)!;
}

function minimalPdf(): Buffer {
	const objects = [
		'1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n',
		'2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n',
		'3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 400]>>\nendobj\n'
	];
	let body = '%PDF-1.4\n';
	const offsets = objects.map((object) => {
		const offset = Buffer.byteLength(body);
		body += object;
		return offset;
	});
	const xref = Buffer.byteLength(body);
	body += `xref\n0 4\n0000000000 65535 f \n${offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n `).join('\n')}\n`;
	body += `trailer\n<</Size 4/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
	return Buffer.from(body);
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

test('creates, edits, and finds an Item through the real API', async ({ page }) => {
	const workspaceId = await signIn(page);
	const initialTitle = 'Full-stack smoke Item';
	const revisedTitle = 'Revised full-stack smoke Item';

	await page.goto(`/workspace/${workspaceId}/import`);
	await page.getByRole('button', { name: 'Open metadata editor' }).click();
	await page.getByLabel('Title', { exact: true }).fill(initialTitle);
	await page.getByRole('button', { name: 'Create Item' }).click();

	await expect(page).toHaveURL(/\/item\/[0-9a-f-]+$/);
	await expect(page.getByRole('heading', { name: initialTitle })).toBeVisible();
	await page.getByRole('link', { name: 'Metadata', exact: true }).click();
	await page.getByLabel('Title', { exact: true }).fill(revisedTitle);
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect(page.getByRole('heading', { name: revisedTitle })).toBeVisible();

	await page.goto(`/workspace/${workspaceId}/library`);
	await page.getByPlaceholder('Search title, author, Tag, or full text').fill(revisedTitle);
	await page.getByRole('button', { name: 'Search', exact: true }).click();
	await expect(page.getByRole('link', { name: revisedTitle })).toBeVisible();
});

test('creates a Project through the real API', async ({ page }) => {
	const workspaceId = await signIn(page);

	await page.goto(`/workspace/${workspaceId}/projects`);
	await page.getByRole('button', { name: 'New Project' }).click();
	await page.getByLabel('Name').fill('Full-stack smoke Project');
	await page.getByLabel('Description').fill('Created by the real browser-to-database smoke test.');
	await page.getByLabel('Participation').selectOption('open');
	await page.getByRole('button', { name: 'Create Project' }).click();

	await expect(page.getByRole('link', { name: /Full-stack smoke Project/ })).toBeVisible();
});

test('runs a staged PDF Import through the durable worker', async ({ page }) => {
	const workspaceId = await signIn(page);

	await page.goto(`/workspace/${workspaceId}/import`);
	await page.locator('input[name="pdfs"]').setInputFiles({
		name: 'fullstack-smoke.pdf',
		mimeType: 'application/pdf',
		buffer: minimalPdf()
	});
	await page.getByRole('button', { name: 'Stage PDFs' }).click();

	await expect(page.getByRole('heading', { name: 'Import preview' })).toBeVisible();
	await expect(page.getByRole('button', { name: 'Commit' })).toBeEnabled({ timeout: 30_000 });
	await expect(page.getByRole('heading', { name: 'Diagnostics' })).toBeVisible();
	await expect(page.getByText('fullstack-smoke.pdf')).toBeVisible();
});
