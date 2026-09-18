import { expect, test } from '@playwright/test';
import { defaultCitationKeyFormula, mockSession } from './helpers';

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
	await page.getByRole('button', { name: 'Save locale' }).click();
	await expect
		.poll(() => mutations)
		.toContainEqual({
			method: 'PUT',
			path: '/api/v1/account/locale',
			body: { locale: 'zh-CN' }
		});

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
	await page.route('**/api/v1/citation-styles*', (route) =>
		route.fulfill({ json: { styles: [{ key: 'apa', name: 'APA' }] } })
	);
	let previewedFormula = '';
	await page.route('**/api/v1/citation-key-preview*', (route) => {
		previewedFormula = new URL(route.request().url()).searchParams.get('formula') ?? '';
		return previewedFormula === 'broken('
			? route.fulfill({ status: 422, json: { detail: 'invalid Citation Key formula' } })
			: route.fulfill({ json: { key: 'Reader2026' } });
	});

	await page.goto('/account');
	const formula = page.getByLabel('Citation Key formula');
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
