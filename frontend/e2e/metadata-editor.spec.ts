import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { mockSession } from './helpers';

const work = {
	id: 'https://doi.org/10.1000/editor',
	type: 'Dataset',
	title: 'Schema editor record',
	date_published: '2024-02-29T12:34:56+08:00',
	contributors: [
		{
			type: 'Person',
			person: {
				name: 'Ada Researcher',
				family_name: 'Researcher',
				affiliations: [{ name: 'University' }]
			},
			roles: ['Author']
		}
	],
	identifiers: [
		{ identifier_type: 'Other', identifier: 'local-123', scheme: 'Local registry' },
		{ identifier_type: 'DOI', identifier: '10.1000/second' }
	],
	funding_references: [{ funder_name: 'Foundation', award_number: '123' }],
	relations: [{ id: 'https://doi.org/10.1000/related', type: 'IsSupplementTo' }],
	container: {
		title: 'Collection',
		identifiers: [{ identifier_type: 'ISBN', identifier: '9780131103627' }]
	},
	subjects: [{ subject: 'Research methods' }]
};

async function openEditor(page: Page, failure?: 409 | 422) {
	await mockSession(page);
	let version = 4;
	let saved: Record<string, unknown> = structuredClone(work);
	const requests: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/editor/overview', (route) =>
		route.fulfill({
			json: {
				item: { id: 'editor', title_html: saved.title, version },
				metadata: saved,
				citation_key: 'Ada2024',
				authorization: { allowed: ['item.update'] },
				copy_targets: [],
				tags: [],
				latest_revision: null,
				counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
			}
		})
	);
	await page.route('**/api/v1/workspaces/workspace-1/items/editor', (route) => {
		if (route.request().method() === 'PUT') {
			const body = route.request().postDataJSON();
			requests.push(body);
			if (failure && requests.length === 1) {
				if (failure === 409) {
					version += 1;
					saved = { ...saved, title: 'Remote revision', language: 'zh' };
				}
				return route.fulfill({
					status: failure,
					json: {
						code: failure === 409 ? 'version_conflict' : 'validation_failed',
						message: 'Rejected',
						...(failure === 422
							? {
									fields: [
										{
											path: ['body', 'metadata', 'date_published'],
											code: 'value_error',
											message: 'Invalid publication date'
										}
									]
								}
							: {})
					}
				});
			}
			version += 1;
			saved = body.metadata;
			return route.fulfill({ json: { id: 'editor', version } });
		}
		return route.fulfill({
			json: {
				id: 'editor',
				title_html: saved.title,
				version,
				metadata: saved,
				citation_key: 'Ada2024'
			}
		});
	});
	await page.goto('/workspace/workspace-1/item/editor/metadata');
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue(work.title);
	return requests;
}

async function openGroup(page: Page, name: string) {
	const summary =
		name === 'Additional metadata'
			? page.locator('summary').filter({ hasText: /^Additional metadata$/ })
			: page.locator('[data-work-group] > summary').filter({ hasText: new RegExp(`^${name}$`) });
	await summary.click();
	return summary.locator('..');
}

async function readJson(page: Page) {
	await page.getByRole('button', { name: 'Edit standard metadata JSON' }).click();
	return JSON.parse(
		await page.getByRole('textbox', { name: 'Metadata', exact: true }).inputValue()
	);
}

for (const dirty of [false, true]) {
	test(`switching cached Items with equal versions resets the editing snapshot with dirty=${dirty}`, async ({
		page
	}) => {
		const sourceRequests = await openEditor(page);
		const other = { ...work, id: 'https://doi.org/10.1000/other', title: 'Other record' };
		const targetRequests: Record<string, unknown>[] = [];
		await page.route('**/api/v1/workspaces/workspace-1/items/other/overview', (route) =>
			route.fulfill({
				json: {
					item: { id: 'other', title_html: other.title, version: 4 },
					metadata: other,
					citation_key: 'OtherKey',
					authorization: { allowed: ['item.update'] },
					copy_targets: [],
					tags: [],
					latest_revision: null,
					counts: { revisions: 0, attachments: 0, annotations: 0, discussion: 0 }
				}
			})
		);
		await page.route('**/api/v1/workspaces/workspace-1/items/other', (route) => {
			if (route.request().method() === 'PUT') {
				targetRequests.push(route.request().postDataJSON());
				return route.fulfill({ json: { id: 'other', version: 5 } });
			}
			return route.fulfill({
				json: {
					id: 'other',
					title_html: other.title,
					version: 4,
					metadata: other,
					citation_key: 'OtherKey'
				}
			});
		});
		async function navigate(itemId: string) {
			await page.evaluate((id) => {
				document.querySelector('[data-testid="cached-item-link"]')?.remove();
				const link = document.createElement('a');
				link.href = `/workspace/workspace-1/item/${id}/metadata`;
				link.textContent = 'Navigate to cached Item';
				link.dataset.testid = 'cached-item-link';
				document.querySelector('main')!.append(link);
			}, itemId);
			await page.getByTestId('cached-item-link').click();
			await expect(page).toHaveURL(new RegExp(`/item/${itemId}/metadata$`));
		}
		await navigate('other');
		await expect(page.getByLabel('Title', { exact: true })).toHaveValue(other.title);
		await navigate('editor');
		await expect(page.getByLabel('Title', { exact: true })).toHaveValue(work.title);
		if (dirty) {
			await page.getByLabel('Title', { exact: true }).fill('Unsaved source title');
			await page.getByLabel('Citation key', { exact: true }).fill('SourceDraftKey');
		}
		await navigate('other');
		await expect(page.getByLabel('Title', { exact: true })).toHaveValue(other.title);
		await expect(page.getByLabel('Citation key', { exact: true })).toHaveValue('OtherKey');
		expect(await readJson(page)).toEqual(other);
		await page.getByLabel('Title', { exact: true }).fill('Saved other record');
		await page.getByRole('button', { name: 'Save metadata' }).click();
		await expect
			.poll(() => targetRequests[0])
			.toEqual({
				expected_version: 4,
				citation_key: 'OtherKey',
				metadata: { ...other, title: 'Saved other record' }
			});
		expect(sourceRequests).toHaveLength(0);
	});
}

test('opens without mutation and preserves identities during contributor and identifier type changes', async ({
	page
}) => {
	const errors: string[] = [];
	page.on('pageerror', (error) => errors.push(error.message));
	page.on('console', (message) => {
		if (
			/Content Security Policy|Invalid regular expression|component not found/.test(message.text())
		)
			errors.push(message.text());
	});
	const requests = await openEditor(page);
	expect(await readJson(page)).toEqual(work);
	await openGroup(page, 'Contributors');
	await page.locator('#root_contributors_0_type').selectOption('Organization');
	await page.locator('#root_contributors_0_organization_name').fill('Research Council');
	await openGroup(page, 'Identifiers');
	await page.locator('#root_identifiers_0_identifier_type').selectOption('DOI');
	const expected = {
		...work,
		contributors: [
			{ ...work.contributors[0], type: 'Organization', organization: { name: 'Research Council' } }
		],
		identifiers: [{ ...work.identifiers[0], identifier_type: 'DOI' }, work.identifiers[1]]
	};
	expect(await readJson(page)).toEqual(expected);
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect
		.poll(() => requests[0])
		.toEqual({ expected_version: 4, metadata: expected, citation_key: 'Ada2024' });
	expect(errors).toEqual([]);
});

test('adds, reorders and removes nested entries without injecting null or empty required arrays', async ({
	page
}) => {
	await openEditor(page);
	const contributors = await openGroup(page, 'Contributors');
	const affiliations = page
		.locator('[data-layout="array-field"]')
		.filter({ has: page.locator('#root_contributors_0_person_affiliations_0_name') })
		.last();
	await expect(page.locator('#root_contributors_0_person_affiliations_0_name')).toBeHidden();
	await contributors
		.locator('summary')
		.filter({ hasText: /^Affiliations/ })
		.first()
		.click();
	await affiliations.getByRole('button', { name: 'Add entry', exact: true }).last().click();
	await page.locator('#root_contributors_0_person_affiliations_1_name').fill('Laboratory');
	await affiliations.getByRole('button', { name: 'Move up', exact: true }).last().click();
	expect((await readJson(page)).contributors[0].person.affiliations).toEqual([
		{ name: 'Laboratory' },
		{ name: 'University' }
	]);
	await contributors
		.locator('summary')
		.filter({ hasText: /^Affiliations/ })
		.first()
		.click();
	await expect(page.locator('#root_contributors_0_person_affiliations_0_name')).toBeHidden();
	expect((await readJson(page)).contributors[0].person.affiliations).toHaveLength(2);
	await contributors
		.locator('summary')
		.filter({ hasText: /^Affiliations/ })
		.first()
		.click();
	await affiliations.getByRole('button', { name: 'Remove entry', exact: true }).first().click();
	await contributors.getByRole('button', { name: 'Add entry', exact: true }).last().click();
	await page.locator('#root_contributors_1_type').selectOption('Organization');
	await page.locator('#root_contributors_1_organization_name').fill('Council');
	await contributors.getByRole('button', { name: 'Remove entry', exact: true }).last().click();

	const identifiers = await openGroup(page, 'Identifiers');
	await identifiers.getByRole('button', { name: 'Add entry', exact: true }).last().click();
	await page.locator('#root_identifiers_2_identifier').fill('10.1000/third');
	await page.locator('#root_identifiers_2_identifier_type').selectOption('DOI');
	await identifiers.getByRole('button', { name: 'Move up', exact: true }).last().click();
	expect(
		(await readJson(page)).identifiers.map((row: { identifier: string }) => row.identifier)
	).toEqual(['local-123', '10.1000/third', '10.1000/second']);
	await identifiers.getByRole('button', { name: 'Remove entry', exact: true }).nth(1).click();
	const funding = await openGroup(page, 'Funding references');
	await funding.getByRole('button', { name: 'Add entry', exact: true }).click();
	await page.locator('#root_funding_references_1_funder_name').fill('Second funder');
	await funding.getByRole('button', { name: 'Move up', exact: true }).last().click();
	expect((await readJson(page)).funding_references[0]).toEqual({ funder_name: 'Second funder' });
	await funding.getByRole('button', { name: 'Remove entry', exact: true }).first().click();
	await funding.getByRole('button', { name: 'Remove entry', exact: true }).click();
	const expected = structuredClone(work);
	delete (expected as Partial<typeof work>).funding_references;
	expect(await readJson(page)).toEqual(expected);
	await contributors.getByRole('button', { name: 'Remove entry', exact: true }).last().click();
	delete (expected as Partial<typeof work>).contributors;
	expect(await readJson(page)).toEqual(expected);
});

test('uses original schema validation even when native validation is bypassed and keeps invalid JSON unapplied', async ({
	page
}) => {
	const requests = await openEditor(page);
	await openGroup(page, 'Additional metadata');
	await page.locator('#root_id').fill('relative-id');
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect(page.getByText('Enter a valid absolute URI.').first()).toBeVisible();
	await expect(page.locator('#root_id')).toBeFocused();
	expect(requests).toHaveLength(0);
	await page.locator('#root_id').fill(work.id);
	await readJson(page);
	const raw = page.getByRole('textbox', { name: 'Metadata', exact: true });
	await raw.fill(JSON.stringify({ ...work, funding_references: [{}] }));
	await page.getByRole('button', { name: 'Apply JSON', exact: true }).click();
	await expect(page.getByText('Invalid metadata JSON.', { exact: true })).toBeVisible();
	await expect(raw).toBeVisible();
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect(page.getByText('Apply JSON changes before saving.')).toBeVisible();
	expect(requests).toHaveLength(0);
});

for (const failure of [409, 422] as const) {
	test(`keeps the full draft and Citation Key after HTTP ${failure} and requires an explicit conflict retry`, async ({
		page
	}) => {
		const requests = await openEditor(page, failure);
		await page.getByLabel('Title', { exact: true }).fill('My draft');
		await page.getByLabel('Citation key', { exact: true }).fill('MyKey');
		await page.getByRole('button', { name: 'Save metadata' }).click();
		await expect(page.getByRole('alert').first()).toBeVisible();
		await expect(page.getByLabel('Title', { exact: true })).toHaveValue('My draft');
		await expect(page.getByLabel('Citation key', { exact: true })).toHaveValue('MyKey');
		if (failure === 422) {
			await expect(page.getByText('Invalid publication date').first()).toBeVisible();
			await expect(
				page.getByRole('textbox', { name: 'Publication date', exact: true })
			).toBeFocused();
		}
		if (failure === 409) {
			await expect(page.getByRole('button', { name: 'Save metadata' })).toBeDisabled();
			await page.getByRole('button', { name: 'Use latest version and keep draft' }).click();
		}
		expect(await readJson(page)).toEqual({ ...work, title: 'My draft' });
		await page.getByRole('button', { name: 'Save metadata' }).click();
		await expect
			.poll(() => requests[1])
			.toEqual({
				expected_version: failure === 409 ? 5 : 4,
				metadata: { ...work, title: 'My draft' },
				citation_key: 'MyKey'
			});
	});
}

test('adapts desktop columns to available space and keeps the localized mobile editor accessible', async ({
	page
}) => {
	await page.setViewportSize({ width: 1440, height: 1000 });
	await openEditor(page);
	await openGroup(page, 'Contributors');
	await openGroup(page, 'Identifiers');
	const publicationType = (await page.locator('#root_container_type').boundingBox())!;
	const publicationTitle = (await page.locator('#root_container_title').boundingBox())!;
	expect(publicationTitle.x).toBeGreaterThan(publicationType.x + publicationType.width);
	expect(Math.abs(publicationTitle.y - publicationType.y)).toBeLessThan(4);
	expect(publicationTitle.width).toBeGreaterThan(200);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
	await page
		.locator('summary')
		.filter({ hasText: /^Publication$/ })
		.locator('..')
		.screenshot({
			path: test.info().outputPath('desktop.png')
		});
	await page.setViewportSize({ width: 390, height: 844 });
	const mobileType = (await page.locator('#root_container_type').boundingBox())!;
	const mobileTitle = (await page.locator('#root_container_title').boundingBox())!;
	expect(mobileTitle.y).toBeGreaterThan(mobileType.y);
	expect(Math.abs(mobileTitle.x - mobileType.x)).toBeLessThan(4);
	await page.evaluate(() => window.scrollTo(0, 0));
	await page.screenshot({ path: test.info().outputPath('mobile.png') });
	const accessibility = await new AxeBuilder({ page }).analyze();
	expect(
		accessibility.violations.filter((violation) =>
			['serious', 'critical'].includes(violation.impact ?? '')
		)
	).toEqual([]);
	expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
	await page.evaluate(() => {
		localStorage.setItem('quirebase:locale', 'zh-CN');
		window.dispatchEvent(
			new StorageEvent('storage', { key: 'quirebase:locale', newValue: 'zh-CN' })
		);
	});
	await expect(page.getByLabel('文献类型')).toBeVisible();
	await expect(
		page.getByLabel('文献类型').getByRole('option', { name: '数据集', exact: true })
	).toHaveCount(1);
	await expect(page.getByRole('button', { name: '添加记录', exact: true }).first()).toBeVisible();
	await expect(page.getByLabel('Contributor roles', { exact: true })).toHaveCount(0);
});

test('can discard a conflicted draft explicitly and load the latest server metadata', async ({
	page
}) => {
	await openEditor(page, 409);
	await page.getByLabel('Title', { exact: true }).fill('Discard this');
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await page.getByRole('button', { name: 'Discard draft and load latest' }).click();
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Remote revision');
	expect(await readJson(page)).toEqual({ ...work, title: 'Remote revision', language: 'zh' });
});

test('shows schema loading failures and retries the authorized endpoint', async ({ page }) => {
	await mockSession(page);
	await page.route('**/api/v1/workspaces/*/metadata/schema', (route) =>
		route.fulfill({
			status: 503,
			json: { code: 'upstream_service_error', message: 'Schema unavailable' }
		})
	);
	await page.goto('/workspace/workspace-1/import');
	await page.getByRole('button', { name: 'Open metadata editor' }).click();
	await expect(page.getByText('Unable to load metadata editor.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Create Item' })).toHaveCount(0);
	await page.unroute('**/api/v1/workspaces/*/metadata/schema');
	await mockSession(page);
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByLabel('Title', { exact: true })).toBeVisible();
});

test('opens collapsed ancestors when a nested field fails server validation', async ({ page }) => {
	await openEditor(page);
	await page.route('**/api/v1/workspaces/workspace-1/items/editor', (route) =>
		route.fulfill({
			status: 422,
			json: {
				code: 'validation_failed',
				message: 'Rejected',
				fields: [
					{
						path: ['body', 'metadata', 'contributors', 0, 'person', 'affiliations', 0, 'name'],
						code: 'value_error',
						message: 'Invalid affiliation'
					}
				]
			}
		})
	);
	await expect(page.locator('#root_contributors_0_person_affiliations_0_name')).toBeHidden();
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect(page.locator('#root_contributors_0_person_affiliations_0_name')).toBeVisible();
	await expect(page.locator('#root_contributors_0_person_affiliations_0_name')).toBeFocused();
	expect(await readJson(page)).toEqual(work);
});
