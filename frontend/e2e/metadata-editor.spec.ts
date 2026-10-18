import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { mockMetadataSources, mockSession } from './helpers';

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

async function openEditor(
	page: Page,
	failure?: 409 | 422,
	metadata: Record<string, unknown> = work
) {
	await mockSession(page);
	let version = 4;
	let saved: Record<string, unknown> = structuredClone(metadata);
	const requests: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/editor/overview', (route) =>
		route.fulfill({
			json: {
				id: 'editor',
				version,
				metadata: saved,
				citation_key: 'Ada2024',
				authorization: { allowed: ['item.update'] },
				copy_targets: [],
				tags: [],
				latest_revision_id: null,
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
				version,
				metadata: saved,
				citation_key: 'Ada2024'
			}
		});
	});
	await page.goto('/workspace/workspace-1/item/editor/metadata');
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue(String(metadata.title));
	return requests;
}

test('uses given and family names in contributor summaries without changing the Work', async ({
	page
}) => {
	const metadata = {
		...work,
		contributors: [
			{
				type: 'Person',
				person: { given_name: 'Ada', family_name: 'Lovelace' },
				roles: ['Author']
			}
		]
	};
	const requests = await openEditor(page, undefined, metadata);
	const section = page.locator('[data-work-group="contributors"]');
	await expect(section.locator(':scope > summary')).toContainText('Ada Lovelace');
	await section.locator(':scope > summary').click();
	await expect(
		section.locator('[data-layout="array-item"]').getByText('Ada Lovelace', { exact: true })
	).toBeVisible();
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect.poll(() => requests[0]).toMatchObject({ metadata });
});

test('opens a reference-rich Work without blocking the editor', async ({ page }) => {
	const metadata = {
		...work,
		contributors: Array.from({ length: 30 }, (_, index) => ({
			...work.contributors[0],
			person: {
				name: `Researcher ${index}`,
				affiliations: [{ name: 'University' }, { name: 'Research Institute' }]
			}
		})),
		references: Array.from({ length: 100 }, (_, index) => ({
			id: `https://doi.org/10.1000/reference-${index}`,
			reference: `Referenced study ${index}`
		}))
	};
	const started = Date.now();
	const requests = await openEditor(page, undefined, metadata);
	await test.info().attach('metadata-open-performance', {
		body: JSON.stringify({
			elapsedMs: Date.now() - started,
			controls: await page.locator('input, select, textarea').count(),
			nodes: await page.locator('*').count()
		}),
		contentType: 'application/json'
	});
	// Bound actual rendering work instead of asserting a machine-dependent time limit.
	await expect(page.locator('[id^="root_contributors_"]')).toHaveCount(0);
	await expect(page.locator('[id^="root_references_"]')).toHaveCount(0);
	expect(await page.locator('input, select, textarea').count()).toBeLessThan(100);
	await page.getByLabel('Title', { exact: true }).fill('Updated reference-rich Work');
	expect(await readJson(page)).toEqual({ ...metadata, title: 'Updated reference-rich Work' });
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect
		.poll(() => requests[0])
		.toMatchObject({
			metadata: { ...metadata, title: 'Updated reference-rich Work' }
		});

	const contributors = await openGroup(page, 'Contributors');
	const name = page.locator('#root_contributors_0_person_name');
	await expect(name).toHaveValue('Researcher 0');
	await expect(page.locator('#root_contributors_0_person_country')).toHaveCount(0);
	await expect(page.locator('#root_contributors_0_person_affiliations_0_name')).toHaveCount(0);
	await name.fill('Edited credit');
	await contributors.locator(':scope > summary').click();
	await expect(name).toHaveCount(1);
	await expect(name).toBeHidden();
	await contributors.locator(':scope > summary').click();
	await expect(name).toHaveValue('Edited credit');
	const expected = structuredClone(metadata);
	expected.title = 'Updated reference-rich Work';
	expected.contributors[0].person.name = 'Edited credit';
	expect(await readJson(page)).toEqual(expected);
});

async function openGroup(page: Page, name: string) {
	const summary =
		name === 'Additional metadata'
			? page.locator('summary').filter({ hasText: /^Additional metadata$/ })
			: page
					.locator('[data-work-group] > summary')
					.filter({ has: page.getByText(name, { exact: true }) });
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
					id: 'other',
					version: 4,
					metadata: other,
					citation_key: 'OtherKey',
					authorization: { allowed: ['item.update'] },
					copy_targets: [],
					tags: [],
					latest_revision_id: null,
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

test('shows populated metadata and summaries while optional empty fields stay out of the way', async ({
	page
}) => {
	const requests = await openEditor(page);
	const summary = page.locator('[data-work-group="contributors"] > summary');
	await expect(summary).toContainText('Ada Researcher');
	await expect(summary).toContainText('(1)');
	await expect(page.locator('#root_description')).toBeHidden();
	await expect(page.locator('#root_container_description')).toBeHidden();
	const editor = page.locator('form').filter({ has: page.locator('#root_title') });
	const compactCount = await editor
		.locator('input:visible, select:visible, textarea:visible')
		.count();
	await page.screenshot({ path: test.info().outputPath('compact-editor.png'), fullPage: true });
	await page.getByLabel('Show all fields', { exact: true }).check();
	const fullCount = await editor.locator('input:visible, select:visible, textarea:visible').count();
	expect(fullCount).toBeGreaterThan(compactCount + 8);
	await test.info().attach('visible-field-counts', {
		body: JSON.stringify({ compact: compactCount, full: fullCount }),
		contentType: 'application/json'
	});
	await expect(page.locator('#root_description')).toBeVisible();
	await expect(page.locator('#root_container_description')).toBeVisible();
	await page.getByLabel('Show all fields', { exact: true }).uncheck();
	await expect(page.locator('#root_description')).toBeHidden();
	expect(await readJson(page)).toEqual(work);
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect
		.poll(() => requests[0])
		.toEqual({ expected_version: 4, metadata: work, citation_key: 'Ada2024' });
});

test('adds one optional field within its object and retains edited fields when compacted', async ({
	page
}) => {
	const requests = await openEditor(page);
	await openGroup(page, 'Contributors');
	const country = page.locator('#root_contributors_0_person_country');
	const person = page
		.locator('[data-layout="object-field"]')
		.filter({ has: page.locator('#root_contributors_0_person_name') })
		.last();
	await expect(page.locator('#root_contributors_0_person_name')).toBeVisible();
	await expect(country).toBeHidden();
	await expect(page.locator('#root_contributors_0_person_description')).toBeHidden();
	await page.screenshot({
		path: test.info().outputPath('compact-contributor.png'),
		fullPage: true
	});
	await person
		.getByRole('combobox', { name: 'Add field to Person', exact: true })
		.selectOption('country');
	await expect(country).toBeVisible();
	await expect(country).toBeFocused();
	await expect(page.locator('#root_contributors_0_person_description')).toBeHidden();
	await country.fill('GB');
	await page.getByLabel('Show all fields', { exact: true }).check();
	await page.getByLabel('Show all fields', { exact: true }).uncheck();
	await expect(country).toHaveValue('GB');
	await expect(country).toBeVisible();
	await expect(page.locator('#root_contributors_0_person_description')).toBeHidden();
	await country.fill('');
	await expect(country).toBeVisible();
	await expect(country).toBeFocused();
	await country.fill('GB');
	const expected = structuredClone(work);
	Object.assign(expected.contributors[0].person, { country: 'GB' });
	expect(await readJson(page)).toEqual(expected);
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect.poll(() => requests[0]).toMatchObject({ metadata: expected });
});

for (const countryState of ['revealed', 'cleared'] as const) {
	test(`keeps ${countryState} optional fields with their contributor when entries move`, async ({
		page
	}) => {
		const metadata = {
			...work,
			contributors: [
				{ type: 'Person', person: { name: 'Ada Researcher' }, roles: ['Author'] },
				{
					type: 'Person',
					person: {
						name: 'Grace Researcher',
						...(countryState === 'cleared' ? { country: 'GB' } : {})
					},
					roles: ['Author']
				}
			]
		};
		const requests = await openEditor(page, undefined, metadata);
		const contributors = await openGroup(page, 'Contributors');
		const grace = contributors
			.locator('[data-layout="array-item"]')
			.filter({ has: page.getByText('Grace Researcher', { exact: true }) });
		if (countryState === 'cleared') {
			await page.locator('#root_contributors_1_person_country').fill('');
		} else {
			await grace
				.getByRole('combobox', { name: 'Add field to Person', exact: true })
				.selectOption('country');
		}
		await expect(page.locator('#root_contributors_1_person_country')).toBeVisible();
		await grace.getByRole('button', { name: 'Move up', exact: true }).click();
		await expect(page.locator('#root_contributors_0_person_name')).toHaveValue('Grace Researcher');
		await expect(page.locator('#root_contributors_0_person_country')).toBeVisible();
		await expect(page.locator('#root_contributors_1_person_country')).toBeHidden();
		await grace.getByRole('button', { name: 'Move down', exact: true }).click();
		await expect(page.locator('#root_contributors_1_person_country')).toBeVisible();
		await expect(page.locator('#root_contributors_0_person_country')).toBeHidden();
		const ada = contributors
			.locator('[data-layout="array-item"]')
			.filter({ has: page.getByText('Ada Researcher', { exact: true }) });
		await ada.getByRole('button', { name: 'Remove entry', exact: true }).click();
		await expect(page.locator('#root_contributors_0_person_name')).toHaveValue('Grace Researcher');
		await expect(page.locator('#root_contributors_0_person_country')).toBeVisible();
		await page.locator('#root_contributors_0_person_country').fill('GB');
		expect(await readJson(page)).toEqual({
			...work,
			contributors: [
				{ type: 'Person', person: { name: 'Grace Researcher', country: 'GB' }, roles: ['Author'] }
			]
		});
		await grace.getByRole('button', { name: 'Remove entry', exact: true }).click();
		await contributors.getByRole('button', { name: 'Add entry', exact: true }).click();
		await page.locator('#root_contributors_0_type').selectOption('Person');
		await page.locator('#root_contributors_0_person_name').fill('New Researcher');
		await expect(page.locator('#root_contributors_0_person_country')).toBeHidden();
		const expected = await readJson(page);
		expect(expected.contributors).toHaveLength(1);
		expect(expected.contributors[0].person).toEqual({ name: 'New Researcher' });
		await page.getByRole('button', { name: 'Save metadata' }).click();
		await expect.poll(() => requests[0]).toMatchObject({ metadata: expected });
	});
}

test('keeps nested field visibility and section state through inner and outer reordering', async ({
	page
}) => {
	const metadata = {
		...work,
		contributors: ['Ada', 'Grace'].map((name) => ({
			type: 'Person',
			person: { name, affiliations: [{ name: `${name} Lab` }, { name: `${name} University` }] },
			roles: ['Author']
		}))
	};
	await openEditor(page, undefined, metadata);
	const contributors = await openGroup(page, 'Contributors');
	const grace = contributors
		.locator('[data-layout="array-item"]')
		.filter({ has: page.getByText('Grace', { exact: true }) });
	const affiliations = grace.locator('summary').filter({ hasText: /^Affiliations/ });
	await affiliations.click();
	const university = grace
		.locator('[data-layout="array-item"]')
		.filter({ has: page.getByText('Grace University', { exact: true }) });
	await university.getByRole('combobox', { name: /^Add field to / }).selectOption('role');
	await university.getByRole('button', { name: 'Move up', exact: true }).click();
	await expect(page.locator('#root_contributors_1_person_affiliations_0_role')).toBeVisible();
	await expect(page.locator('#root_contributors_1_person_affiliations_1_role')).toBeHidden();
	await affiliations.click();
	await grace
		.locator(':scope > [data-layout="array-item-controls"]')
		.getByRole('button', { name: 'Move up', exact: true })
		.click();
	await expect(page.locator('#root_contributors_0_person_name')).toHaveValue('Grace');
	await expect(page.locator('#root_contributors_0_person_affiliations_0_role')).toBeHidden();
	await affiliations.click();
	await expect(page.locator('#root_contributors_0_person_affiliations_0_role')).toBeVisible();
	await expect(page.locator('#root_contributors_0_person_affiliations_1_role')).toBeHidden();
	await page.locator('#root_contributors_0_person_affiliations_0_role').fill('Researcher');
	expect((await readJson(page)).contributors[0].person.affiliations).toEqual([
		{ name: 'Grace University', role: 'Researcher' },
		{ name: 'Grace Lab' }
	]);
});

test('adds optional sections without creating data and focuses a single new scalar field', async ({
	page
}) => {
	const requests = await openEditor(page);
	const add = page.getByRole('combobox', { name: 'Add field to Metadata', exact: true });
	await add.selectOption('files');
	const files = page
		.locator('[data-metadata-field]')
		.filter({ has: page.getByText('Files', { exact: true }) });
	await expect(files.getByRole('button', { name: 'Add entry', exact: true })).toBeFocused();
	expect(await readJson(page)).toEqual(work);
	await add.selectOption('description');
	await expect(page.locator('#root_description')).toBeFocused();
	await page.locator('#root_description').fill('A concise abstract');
	await expect(page.locator('#root_language')).toBeHidden();
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect
		.poll(() => requests[0])
		.toMatchObject({ metadata: { ...work, description: 'A concise abstract' } });
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

test('metadata-save conflicts invalidate cached sources before the next synchronization', async ({
	page
}) => {
	const requests = await openEditor(page, 409);
	let sourceRequests = 0;
	await mockMetadataSources(page, 'editor', () => {
		sourceRequests += 1;
		return {
			version: requests.length ? 5 : 4,
			sources: [
				{
					namespace: 'doi',
					value: requests.length ? '10.1000/revised' : '10.1000/editor',
					providers: [{ id: 'crossref', name: 'Crossref' }]
				}
			]
		};
	});
	const synchronizations: Record<string, unknown>[] = [];
	await page.route('**/api/v1/workspaces/workspace-1/items/editor/metadata/sync', (route) => {
		const body = route.request().postDataJSON();
		synchronizations.push(body);
		return body.expected_version === 5
			? route.fulfill({ json: { ok: true } })
			: route.fulfill({
					status: 409,
					json: { code: 'version_conflict', message: 'Stale sources' }
				});
	});
	await page.getByRole('button', { name: 'Record tools', exact: true }).click();
	const dialog = page.getByRole('dialog', { name: 'Item actions' });
	await expect(dialog.getByText('10.1000/editor', { exact: true })).toBeVisible();
	expect(sourceRequests).toBe(1);
	await dialog.getByRole('button', { name: 'Close', exact: true }).click();

	await page.getByLabel('Title', { exact: true }).fill('My draft');
	await page.getByLabel('Citation key', { exact: true }).fill('MyKey');
	await page.getByRole('button', { name: 'Save metadata' }).click();
	await expect(
		page.getByText(
			'This Item changed since it was loaded. Your draft was preserved; review the latest metadata.',
			{ exact: true }
		)
	).toBeVisible();
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue('My draft');
	await expect(page.getByLabel('Citation key', { exact: true })).toHaveValue('MyKey');
	await expect(page.getByRole('button', { name: 'Save metadata' })).toBeDisabled();

	await page.getByRole('button', { name: 'Record tools', exact: true }).click();
	await expect(dialog.getByText('10.1000/revised', { exact: true })).toBeVisible();
	expect(sourceRequests).toBe(2);
	await dialog.getByLabel('Provider', { exact: true }).selectOption('crossref');
	await dialog.getByRole('button', { name: 'Autoupdate', exact: true }).click();
	await expect
		.poll(() => synchronizations)
		.toEqual([{ expected_version: 5, provider: 'crossref', uid: '10.1000/revised' }]);
	await expect(dialog.getByText('Metadata synchronized', { exact: true })).toBeVisible();
});

for (const failure of [409, 422] as const) {
	test(`keeps the full draft and Citation Key after HTTP ${failure} and requires an explicit conflict retry`, async ({
		page
	}) => {
		const requests = await openEditor(page, failure);
		await page.getByLabel('Title', { exact: true }).fill('My draft');
		await page.getByLabel('Citation key', { exact: true }).fill('MyKey');
		await page.getByRole('button', { name: 'Save metadata' }).click();
		await expect(
			page
				.getByRole('main')
				.getByRole('alert')
				.filter({
					hasText:
						failure === 409
							? 'This Item changed since it was loaded. Your draft was preserved; review the latest metadata.'
							: 'Please check the submitted values.'
				})
		).toBeVisible();
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
	await page.locator('[data-work-group="container"]').screenshot({
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
	await expect(page.getByRole('combobox', { name: '为元数据添加字段', exact: true })).toBeVisible();
	await expect(
		page
			.getByRole('combobox', { name: '为元数据添加字段', exact: true })
			.getByRole('option', { name: '语言', exact: true })
	).toHaveCount(1);
});

test('metadata conflict refresh failures preserve the full draft through recovery and retry', async ({
	page
}) => {
	const requests = await openEditor(page, 409);
	let unavailable = true;
	await page.route('**/api/v1/workspaces/workspace-1/items/editor/overview', (route) =>
		unavailable
			? route.fulfill({
					status: 500,
					json: { code: 'internal_error', message: 'Refresh unavailable' }
				})
			: route.fallback()
	);
	await page.getByLabel('Title', { exact: true }).fill('My preserved draft');
	await page.getByLabel('Citation key', { exact: true }).fill('PreservedKey');
	await page.getByRole('button', { name: 'Save metadata', exact: true }).click();
	await expect(
		page.getByText(
			'This Item changed since it was loaded. Your draft was preserved; review the latest metadata.',
			{ exact: true }
		)
	).toBeVisible();
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue('My preserved draft');
	await expect(page.getByLabel('Citation key', { exact: true })).toHaveValue('PreservedKey');
	await expect(page.getByRole('button', { name: 'Save metadata', exact: true })).toBeDisabled();
	unavailable = false;
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(
		page.getByText(
			'This Item has changed. Your draft is preserved. Review the latest metadata before retrying.',
			{ exact: true }
		)
	).toBeVisible();
	await expect(page.getByLabel('Title', { exact: true })).toHaveValue('My preserved draft');
	await expect(page.getByLabel('Citation key', { exact: true })).toHaveValue('PreservedKey');
	await page.getByRole('button', { name: 'Use latest version and keep draft' }).click();
	await page.getByRole('button', { name: 'Save metadata', exact: true }).click();
	await expect
		.poll(() => requests[1])
		.toEqual({
			expected_version: 5,
			metadata: { ...work, title: 'My preserved draft' },
			citation_key: 'PreservedKey'
		});
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
	await page.getByRole('tab', { name: 'Manual creation', exact: true }).click();
	await expect(page.getByText('Unable to load metadata editor.')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Create Item' })).toHaveCount(0);
	await page.unroute('**/api/v1/workspaces/*/metadata/schema');
	await mockSession(page);
	await page.getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(page.getByLabel('Title', { exact: true })).toBeVisible();
});

for (const field of ['affiliation', 'empty optional field', 'relation'] as const) {
	test(`reveals ${field} and opens its ancestors after server validation`, async ({ page }) => {
		await openEditor(page);
		const path =
			field === 'affiliation'
				? ['contributors', 0, 'person', 'affiliations', 0, 'name']
				: field === 'relation'
					? ['relations', 0, 'id']
					: ['contributors', 0, 'person', 'country'];
		const input = page.locator(`#root_${path.join('_')}`);
		await page.route('**/api/v1/workspaces/workspace-1/items/editor', (route) =>
			route.fulfill({
				status: 422,
				json: {
					code: 'validation_failed',
					message: 'Rejected',
					fields: [
						{
							path: ['body', 'metadata', ...path],
							code: 'value_error',
							message: 'Invalid affiliation'
						}
					]
				}
			})
		);
		await expect(input).toBeHidden();
		await page.getByRole('button', { name: 'Save metadata' }).click();
		await expect(input).toBeVisible();
		await expect(input).toBeFocused();
		expect(await readJson(page)).toEqual(work);
		const section = page.locator('details').filter({ has: input }).first();
		await section.locator(':scope > summary').click();
		await expect(input).toBeHidden();
		await page.getByRole('button', { name: 'Save metadata' }).click();
		await expect(input).toBeVisible();
		await expect(input).toBeFocused();
	});
}
