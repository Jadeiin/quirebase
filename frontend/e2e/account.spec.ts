import { expect, test, type Page } from '@playwright/test';
import { chooseSearchOption, defaultCitationKeyFormula, mockSession } from './helpers';

async function mockExportPreferences(page: Page) {
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
	await page.route('**/api/v1/workspaces/*/citation-styles*', (route) => {
		const url = new URL(route.request().url());
		const workspaceId = url.pathname.split('/')[4];
		const query = (url.searchParams.get('query') ?? '').toLowerCase();
		const include = url.searchParams.get('include');
		const styles = [
			{ key: 'apa', name: 'APA' },
			{ key: 'ieee', name: 'IEEE' },
			{ key: `${workspaceId}-custom`, name: 'Custom style' }
		];
		return route.fulfill({
			json: {
				styles: styles.filter(
					(style) => style.name.toLowerCase().includes(query) || style.key === include
				)
			}
		});
	});
	await page.route('**/api/v1/account/citation-key-preview*', (route) =>
		route.fulfill({ json: { key: 'Reader2026' } })
	);
}

async function savedCitationStyle(page: Page, workspaceId: string) {
	return page.evaluate(
		(id) =>
			localStorage.getItem(
				`quirebase:export-preferences:v1:account:user-1:workspace:${id}:citation-style`
			),
		workspaceId
	);
}

test('resetting export preferences resets the saved Workspace citation style', async ({ page }) => {
	await mockExportPreferences(page);
	await page.goto('/account');
	const style = page.getByLabel('Default CSL style');
	await chooseSearchOption(page, 'Workspace for citation style', 'Research');
	await style.focus();
	await style.press('End');
	await style.press('Enter');
	await expect.poll(() => savedCitationStyle(page, 'workspace-1')).toBe('workspace-1-custom');

	await page.getByRole('button', { name: 'Reset to defaults' }).click();
	await expect(style.locator('[data-value="apa"]')).toHaveAttribute('aria-selected', 'true');
	await expect.poll(() => savedCitationStyle(page, 'workspace-1')).toBe('apa');
	await page.reload();
	await chooseSearchOption(page, 'Workspace for citation style', 'Research');
	await expect(style.locator('[data-value="apa"]')).toHaveAttribute('aria-selected', 'true');
});

test('filtered cached catalogs do not overwrite a restored Workspace citation style', async ({
	page
}) => {
	await mockExportPreferences(page);
	await page.goto('/account');
	const style = page.getByLabel('Default CSL style');
	const search = page.getByLabel('Search Citation Styles');

	// Cache the destination catalog for the source's APA style under this search filter.
	await chooseSearchOption(page, 'Workspace for citation style', 'Archive');
	await search.fill('IEEE');
	await expect(style.locator('[data-value="ieee"]')).toHaveCount(1);
	await expect(style.locator('[data-value="workspace-2-custom"]')).toHaveCount(0);
	await search.fill('');
	await style.getByRole('option', { name: 'Custom style', exact: true }).click();
	await expect.poll(() => savedCitationStyle(page, 'workspace-2')).toBe('workspace-2-custom');
	await search.fill('IEEE');
	await expect(style.locator('[data-value="ieee"]')).toHaveCount(1);
	await expect(style.locator('[data-value="workspace-2-custom"]')).toHaveAttribute(
		'aria-selected',
		'true'
	);

	await chooseSearchOption(page, 'Workspace for citation style', 'Research');
	await expect(style.locator('[data-value="apa"]')).toHaveAttribute('aria-selected', 'true');
	await expect.poll(() => savedCitationStyle(page, 'workspace-1')).toBe('apa');
	await chooseSearchOption(page, 'Workspace for citation style', 'Archive');
	await expect(style.locator('[data-value="workspace-2-custom"]')).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await expect.poll(() => savedCitationStyle(page, 'workspace-2')).toBe('workspace-2-custom');
	await page.reload();
	await chooseSearchOption(page, 'Workspace for citation style', 'Archive');
	await expect(style.locator('[data-value="workspace-2-custom"]')).toHaveAttribute(
		'aria-selected',
		'true'
	);
});

test('a matching catalog resets an unavailable saved style to APA', async ({ page }) => {
	await mockExportPreferences(page);
	await page.addInitScript(() => {
		localStorage.setItem(
			'quirebase:export-preferences:v1:account:user-1:workspace:workspace-1:citation-style',
			'deleted-custom-style'
		);
	});
	await page.goto('/account');
	await chooseSearchOption(page, 'Workspace for citation style', 'Research');
	await expect(
		page.getByLabel('Default CSL style').getByRole('option', { name: 'APA', selected: true })
	).toBeVisible();
	await expect.poll(() => savedCitationStyle(page, 'workspace-1')).toBe('apa');
});

test('citation style defaults follow the selected Workspace', async ({ page }) => {
	await mockExportPreferences(page);

	await page.goto('/account');
	const style = page.getByLabel('Default CSL style');
	await chooseSearchOption(page, 'Workspace for citation style', 'Research');
	await style.getByRole('option', { name: 'Custom style', exact: true }).click();
	await chooseSearchOption(page, 'Workspace for citation style', 'Archive');
	await expect(style.locator('[data-value="apa"]')).toHaveAttribute('aria-selected', 'true');
	await style.getByRole('option', { name: 'Custom style', exact: true }).click();
	await chooseSearchOption(page, 'Workspace for citation style', 'Research');
	await expect(style.locator('[data-value="workspace-1-custom"]')).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await chooseSearchOption(page, 'Workspace for citation style', 'Archive');
	await expect(style.locator('[data-value="workspace-2-custom"]')).toHaveAttribute(
		'aria-selected',
		'true'
	);

	await page.reload();
	await chooseSearchOption(page, 'Workspace for citation style', 'Research');
	await expect(style.locator('[data-value="workspace-1-custom"]')).toHaveAttribute(
		'aria-selected',
		'true'
	);
	await chooseSearchOption(page, 'Workspace for citation style', 'Archive');
	await expect(style.locator('[data-value="workspace-2-custom"]')).toHaveAttribute(
		'aria-selected',
		'true'
	);
});

test('account settings expose credential and session security controls', async ({ page }) => {
	await mockSession(page);
	const mutations: Array<{ method: string; path: string; body: unknown }> = [];
	await page.route('**/api/v1/account**', async (route) => {
		const request = route.request();
		const path = new URL(request.url()).pathname;
		if (request.method() === 'GET' && path === '/api/v1/account') {
			return route.fulfill({
				json: {
					user: { id: 'user-1', username: 'reader', role: 'member' },
					sessions: [
						{
							id: 'session-2',
							current: false,
							created_at: '2026-01-01T00:00:00Z',
							expires_at: '2026-10-01T00:00:00Z'
						}
					],
					api_tokens: [
						{
							id: 'token-1',
							name: 'Laptop',
							status: 'active',
							expires_at: '2026-10-01T00:00:00Z'
						}
					]
				}
			});
		}
		mutations.push({ method: request.method(), path, body: request.postDataJSON() });
		return route.fulfill({ json: { ok: true } });
	});

	await page.goto('/account');
	await page.getByText('Client connection guide').click();
	await expect(page.getByText('Connect an MCP client')).toBeVisible();
	const guideLayout = await page.locator('details').evaluate((element) => ({
		clippedValues: [...element.querySelectorAll('dd')].filter(
			(dd) => dd.scrollWidth > dd.clientWidth
		).length,
		clippedCode: [...element.querySelectorAll('pre')].filter(
			(pre) => pre.scrollWidth > pre.clientWidth
		).length
	}));
	expect(guideLayout).toEqual({ clippedValues: 0, clippedCode: 0 });

	await page.getByLabel('Current password').fill('old-password');
	await page.getByLabel('New password').fill('new-password-long');
	await page.getByRole('button', { name: 'Change password' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/account/password',
			body: { current_password: 'old-password', new_password: 'new-password-long' }
		});

	await page.getByLabel('Locale').selectOption('zh-CN');
	await expect
		.poll(() => page.evaluate(() => localStorage.getItem('quirebase:locale')))
		.toBe('zh-CN');
	await expect(page.locator('html')).toHaveAttribute('lang', 'zh-CN');
	expect(mutations.some(({ path }) => path === '/api/v1/account/locale')).toBe(false);

	await page.getByRole('button', { name: '撤销令牌' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'DELETE',
			path: '/api/v1/account/api-tokens/token-1',
			body: null
		});

	await page.getByRole('button', { name: '撤销会话' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'DELETE',
			path: '/api/v1/account/sessions/session-2',
			body: null
		});
});

test('only validated Citation Key formulas replace the saved preference', async ({ page }) => {
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
		route.fulfill({ json: { styles: [{ key: 'apa', name: 'APA' }] } })
	);
	let previewedFormula = '';
	await page.route('**/api/v1/account/citation-key-preview*', (route) => {
		previewedFormula = new URL(route.request().url()).searchParams.get('formula') ?? '';
		return previewedFormula === 'broken('
			? route.fulfill({ status: 422, json: { detail: 'invalid Citation Key formula' } })
			: route.fulfill({ json: { key: 'Reader2026' } });
	});

	await page.goto('/account');
	await chooseSearchOption(page, 'Workspace for citation style', 'Research');
	const formula = page.getByLabel('Citation Key formula');
	await page.getByRole('tab', { name: 'BibTeX / BibLaTeX', exact: true }).click();
	await expect(formula).toHaveValue(defaultCitationKeyFormula);
	await formula.fill('broken(');
	await expect.poll(() => previewedFormula).toBe('broken(');
	await expect
		.poll(() =>
			page.evaluate(
				() =>
					JSON.parse(localStorage.getItem('quirebase:export-preferences:v1:account:user-1')!)
						.citation.citationKeyFormula
			)
		)
		.toBe(defaultCitationKeyFormula);

	await formula.fill('auth + year');
	await expect.poll(() => previewedFormula).toBe('auth + year');
	await expect
		.poll(() =>
			page.evaluate(
				() =>
					JSON.parse(localStorage.getItem('quirebase:export-preferences:v1:account:user-1')!)
						.citation.citationKeyFormula
			)
		)
		.toBe('auth + year');
});

test('Citation Key preview loads without a Workspace and follows formula and ASCII options', async ({
	page
}) => {
	await mockExportPreferences(page);
	const requests: Array<{ formula: string; ascii: boolean }> = [];
	await page.route('**/api/v1/account/citation-key-preview*', (route) => {
		const params = new URL(route.request().url()).searchParams;
		const formula = params.get('formula') ?? '';
		const ascii = params.get('force_ascii') === 'true';
		requests.push({ formula, ascii });
		return route.fulfill({ json: { key: `${formula}:${ascii ? 'ascii' : 'unicode'}` } });
	});
	await page.goto('/account');
	await expect.poll(() => requests.length).toBeGreaterThan(0);
	await page.getByRole('tab', { name: 'BibTeX / BibLaTeX', exact: true }).click();
	const preview = page.getByLabel('Preview Citation Key');
	await expect(preview).toHaveText(`${defaultCitationKeyFormula}:ascii`);
	await page.getByLabel('Citation Key formula').fill('auth + year');
	await expect(preview).toHaveText('auth + year:ascii');
	await page.getByLabel('Use ASCII characters only').uncheck();
	await expect(preview).toHaveText('auth + year:unicode');
	await expect(page.getByLabel('Encoding')).toBeVisible();
	await expect(page.getByLabel('Default CSL style')).not.toBeVisible();
});
