import { expect, test, type Locator, type Page } from '@playwright/test';
import { directoryPage, mockSession, projectPage, tagPage, workspaceView } from './helpers';

const dashboardPath = '/workspace/workspace-1';
const libraryPath = `${dashboardPath}/library`;
const searchLabel = 'Search pages, Workspaces, or Projects';
const hostModifier = process.platform === 'darwin' ? 'Meta' : 'Control';
const workspaceEndpoint = /\/api\/v1\/workspaces(?:\?.*)?$/;

async function mockQuickNavigation(page: Page) {
	await mockSession(page);
	const workspaces = [
		workspaceView('workspace-1', 'Research'),
		workspaceView('workspace-2', 'Archive'),
		...Array.from({ length: 28 }, (_, index) =>
			workspaceView(`workspace-${index + 3}`, `Reading space ${String(index + 3).padStart(2, '0')}`)
		)
	];
	const projects = Array.from({ length: 30 }, (_, index) => ({
		id: `project-${index + 1}`,
		name: `Reading Project ${String(index + 1).padStart(2, '0')}`,
		description: '',
		item_count: 1,
		state: 'active',
		participation: 'workspace',
		is_participating: true,
		allowed_participation_changes: [],
		authorization: { allowed: [] },
		active_participants: []
	}));
	const workspaceReads: URL[] = [];
	await page.route(workspaceEndpoint, (route) => {
		const url = new URL(route.request().url());
		workspaceReads.push(url);
		const search = url.searchParams.get('search')?.toLocaleLowerCase() ?? '';
		return route.fulfill({
			json: directoryPage(
				workspaces.filter((workspace) => workspace.name.toLocaleLowerCase().includes(search)),
				route
			)
		});
	});
	await page.route('**/api/v1/workspaces/*', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-1);
		return route.fulfill({ json: workspaces.find((workspace) => workspace.id === id) });
	});
	const projectReads: URL[] = [];
	await page.route('**/api/v1/workspaces/*/projects?*', (route) => {
		projectReads.push(new URL(route.request().url()));
		return route.fulfill({ json: projectPage(projects, route) });
	});
	await page.route('**/api/v1/workspaces/*/projects/project-*', (route) => {
		const id = new URL(route.request().url()).pathname.split('/').at(-1);
		return route.fulfill({ json: projects.find((project) => project.id === id) });
	});
	await page.route('**/api/v1/workspaces/*/projects/*/discussions', (route) =>
		route.fulfill({ json: [] })
	);
	await page.route('**/api/v1/workspaces/*/dashboard', (route) =>
		route.fulfill({ json: { new_items: [], recent_items: [], projects: [], session_count: 0 } })
	);
	await page.route('**/api/v1/workspaces/*/items?*', (route) =>
		route.fulfill({
			json: directoryPage(
				[
					{
						id: 'item-1',
						title_html: 'Reading Item',
						authors: [],
						publication_date: null,
						publication_title: null,
						doi: null,
						version: 1
					}
				],
				route
			)
		})
	);
	await page.route('**/api/v1/workspaces/*/tags?*', (route) =>
		route.fulfill({ json: tagPage([], route) })
	);
	await page.route('**/api/v1/account', (route) =>
		route.fulfill({
			json: {
				user: { id: 'user-1', username: 'reader', role: 'member' },
				sessions: [],
				api_tokens: []
			}
		})
	);
	return { workspaces, projects, workspaceReads, projectReads };
}

function trigger(page: Page) {
	return page.getByRole('button', { name: 'Quick navigation', exact: true });
}

async function openNavigation(page: Page) {
	await trigger(page).click();
	const dialog = page.getByRole('dialog', { name: 'Quick navigation', exact: true });
	await expect(dialog).toBeVisible();
	await expect(dialog.getByRole('searchbox', { name: searchLabel, exact: true })).toBeFocused();
	return dialog;
}

async function dispatchHotkey(
	target: Locator,
	properties: Pick<KeyboardEventInit, 'repeat' | 'isComposing' | 'keyCode'> = {},
	consumed = false
) {
	return target.evaluate(
		(element, { properties, consumed, modifier }) => {
			const init = {
				key: 'k',
				code: 'KeyK',
				bubbles: true,
				cancelable: true,
				[modifier]: true,
				...properties
			};
			const event = new KeyboardEvent('keydown', init);
			if (consumed) event.preventDefault();
			element.dispatchEvent(event);
			element.dispatchEvent(new KeyboardEvent('keyup', init));
			return event.defaultPrevented;
		},
		{ properties, consumed, modifier: hostModifier === 'Meta' ? 'metaKey' : 'ctrlKey' }
	);
}

for (const [platform, modifier] of [
	['MacIntel', 'Meta'],
	['Win32', 'Control']
] as const) {
	test(`${platform} Quick navigation opens from a button and restores focus when cancelled`, async ({
		page
	}) => {
		await page.addInitScript((platform) => {
			Object.defineProperty(navigator, 'platform', { get: () => platform });
			Object.defineProperty(navigator, 'userAgent', { get: () => platform });
		}, platform);
		const { workspaceReads, projectReads } = await mockQuickNavigation(page);
		await page.goto(dashboardPath);
		await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
		expect(workspaceReads.filter((url) => url.searchParams.has('search'))).toEqual([]);
		expect(projectReads).toEqual([]);
		const origin = page.getByRole('button', { name: 'Collapse sidebar', exact: true });
		await origin.focus();
		await origin.press(`${modifier}+k`);
		const dialog = page.getByRole('dialog', { name: 'Quick navigation', exact: true });
		await expect(dialog.getByRole('searchbox', { name: searchLabel, exact: true })).toBeFocused();
		await page.keyboard.press('Escape');
		await expect(dialog).toHaveCount(0);
		await expect(origin).toBeFocused();
		await trigger(page).click();
		await expect(dialog).toBeVisible();
		await dialog.getByRole('button', { name: 'Close', exact: true }).click();
		await expect(dialog).toHaveCount(0);
		await expect(trigger(page)).toBeFocused();
	});
}

test('cached page navigation keeps destination focus after the dialog closes', async ({ page }) => {
	await mockQuickNavigation(page);
	await page.goto(libraryPath);
	await expect(page.getByRole('heading', { name: 'Library', exact: true })).toBeVisible();
	await page
		.getByRole('navigation', { name: 'Main navigation', exact: true })
		.getByRole('link', { name: 'Dashboard', exact: true })
		.click();
	await expect(page).toHaveURL(dashboardPath);
	await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
	let dialog = await openNavigation(page);
	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0);
	await trigger(page).evaluate((element) => {
		element.addEventListener('focus', () => {
			const root = document.documentElement;
			root.dataset.quickNavigationReturnFocusCount = String(
				Number(root.dataset.quickNavigationReturnFocusCount ?? 0) + 1
			);
		});
	});
	dialog = await openNavigation(page);
	await page.locator('html').evaluate((element) => {
		element.dataset.quickNavigationReturnFocusCount = '0';
	});
	await page.evaluate(
		() =>
			new Promise<void>((resolve) =>
				requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
			)
	);
	await dialog
		.getByRole('region', { name: 'Pages and settings', exact: true })
		.getByRole('link', { name: 'Library', exact: true })
		.click();
	await expect(page).toHaveURL(libraryPath);
	await expect(dialog).toHaveCount(0);
	await expect(page.getByRole('heading', { name: 'Library', exact: true })).toBeVisible();
	await page.evaluate(
		() =>
			new Promise<void>((resolve) =>
				requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
			)
	);
	await expect(page.locator('body')).toBeFocused();
	expect(await page.locator('html').getAttribute('data-quick-navigation-return-focus-count')).toBe(
		'0'
	);
});

test('Escape restores the opening trigger after client navigation', async ({ page }) => {
	await mockQuickNavigation(page);
	await page.goto(libraryPath);
	await expect(page.getByRole('heading', { name: 'Library', exact: true })).toBeVisible();
	await page
		.getByRole('navigation', { name: 'Main navigation', exact: true })
		.getByRole('link', { name: 'Dashboard', exact: true })
		.click();
	await expect(page).toHaveURL(dashboardPath);
	const dialog = await openNavigation(page);
	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0);
	await expect(trigger(page)).toBeFocused();
});

test('editing, IME, repeated and consumed events retain their own shortcut behavior', async ({
	page
}) => {
	await mockQuickNavigation(page);
	await page.goto(libraryPath);
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	await search.fill('Keep this Library draft');
	expect(await dispatchHotkey(search)).toBe(false);
	await expect(search).toBeFocused();
	await expect(search).toHaveValue('Keep this Library draft');
	await page.evaluate(() => {
		for (const [id, tag, role] of [
			['guard-textarea', 'textarea', ''],
			['guard-editable', 'div', ''],
			['guard-combobox', 'div', 'combobox'],
			['guard-textbox', 'div', 'textbox']
		]) {
			const element = document.createElement(tag);
			element.id = id;
			element.tabIndex = 0;
			if (role) element.setAttribute('role', role);
			if (id === 'guard-editable') element.contentEditable = 'true';
			document.querySelector('main')!.append(element);
		}
	});
	for (const id of ['guard-textarea', 'guard-editable', 'guard-combobox', 'guard-textbox']) {
		const field = page.locator(`#${id}`);
		await field.focus();
		expect(await dispatchHotkey(field)).toBe(false);
		await expect(field).toBeFocused();
	}
	const button = trigger(page);
	await button.focus();
	for (const properties of [{ isComposing: true }, { keyCode: 229 }, { repeat: true }]) {
		expect(await dispatchHotkey(button, properties)).toBe(false);
		await expect(page.getByRole('dialog', { name: 'Quick navigation', exact: true })).toHaveCount(
			0
		);
	}
	await dispatchHotkey(button, {}, true);
	await expect(page.getByRole('dialog', { name: 'Quick navigation', exact: true })).toHaveCount(0);
	await expect(button).toBeFocused();
});

test('visible dialogs, menus and listboxes keep ownership of their keyboard interaction', async ({
	page
}) => {
	await mockQuickNavigation(page);
	await page.goto(libraryPath);
	const selection = page.locator('[data-library-item-select="item-1"]');
	await selection.check();
	const search = page.getByRole('textbox', { name: 'Library Search', exact: true });
	await search.fill('Keep this draft');
	await page.getByRole('button', { name: 'Saved views', exact: true }).click();
	const savedViews = page.getByRole('dialog', { name: 'Saved views', exact: true });
	await expect(savedViews).toBeVisible();
	await dispatchHotkey(page.locator('body'));
	await expect(page.getByRole('dialog')).toHaveCount(1);
	await expect(savedViews).toBeVisible();
	await page.keyboard.press('Escape');
	await page.getByRole('button', { name: /^Quirebase/ }).click();
	await expect(page.getByRole('menu')).toBeVisible();
	await dispatchHotkey(page.locator('body'));
	await expect(page.getByRole('dialog', { name: 'Quick navigation', exact: true })).toHaveCount(0);
	await expect(page.getByRole('menu')).toBeVisible();
	await page.keyboard.press('Escape');
	await page.getByRole('button', { name: 'Filters', exact: true }).click();
	await page.getByRole('combobox', { name: 'Project', exact: true }).click();
	await expect(page.getByRole('listbox', { name: 'Project', exact: true })).toBeVisible();
	await dispatchHotkey(page.locator('body'));
	await expect(page.getByRole('dialog', { name: 'Quick navigation', exact: true })).toHaveCount(0);
	await expect(page.getByRole('listbox', { name: 'Project', exact: true })).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(selection).toBeChecked();
	await expect(search).toHaveValue('Keep this draft');
});

test('page links respect current Workspace context and permissions while Enter opens Library search', async ({
	page
}) => {
	await mockQuickNavigation(page);
	await page.goto(dashboardPath);
	let dialog = await openNavigation(page);
	let pages = dialog.getByRole('region', { name: 'Pages and settings', exact: true });
	for (const [label, path] of [
		['Dashboard', dashboardPath],
		['Library', libraryPath],
		['Projects', `${dashboardPath}/projects`],
		['Workspace settings', `${dashboardPath}/settings`],
		['My workspaces', '/workspace'],
		['Account settings', '/account']
	])
		await expect(pages.getByRole('link', { name: label, exact: true })).toHaveAttribute(
			'href',
			path
		);
	await expect(pages.getByRole('link', { name: 'Administration', exact: true })).toHaveCount(0);
	const input = dialog.getByRole('searchbox', { name: searchLabel, exact: true });
	await input.fill('quantum & graphs');
	const searchLink = pages.getByRole('link', {
		name: 'Search Library for quantum & graphs',
		exact: true
	});
	await expect(searchLink).toHaveAttribute(
		'href',
		`${libraryPath}?${new URLSearchParams({ q: 'quantum & graphs' })}`
	);
	await input.press('ArrowDown');
	await expect(searchLink).toBeFocused();
	await searchLink.press('ArrowUp');
	await expect(input).toBeFocused();
	await input.press('Enter');
	await expect(page).toHaveURL(`${libraryPath}?${new URLSearchParams({ q: 'quantum & graphs' })}`);
	await expect(dialog).toHaveCount(0);
	await expect(trigger(page)).not.toBeFocused();
	await page.route('**/api/v1/session', (route) =>
		route.fulfill({
			json: {
				authenticated: true,
				user: {
					id: 'user-1',
					username: 'reader',
					role: 'administrator',
					authorization: { allowed: ['audit.read'] }
				}
			}
		})
	);
	await page.reload();
	dialog = await openNavigation(page);
	pages = dialog.getByRole('region', { name: 'Pages and settings', exact: true });
	await expect(pages.getByRole('link', { name: 'Administration', exact: true })).toHaveAttribute(
		'href',
		'/admin'
	);
	const accountSearch = dialog.getByRole('searchbox', { name: searchLabel, exact: true });
	await accountSearch.fill('Account');
	await expect(pages.getByRole('link').first()).toHaveText('Account settings');
	await accountSearch.press('Enter');
	await expect(page).toHaveURL('/account');
	dialog = await openNavigation(page);
	pages = dialog.getByRole('region', { name: 'Pages and settings', exact: true });
	await expect(pages.getByRole('link', { name: 'My workspaces', exact: true })).toHaveAttribute(
		'href',
		'/workspace'
	);
	await expect(pages.getByRole('link', { name: 'Library', exact: true })).toHaveCount(0);
});

test('remote Workspace and Project search reaches later pages and resets both page positions', async ({
	page
}) => {
	const { workspaceReads, projectReads } = await mockQuickNavigation(page);
	await page.goto(dashboardPath);
	const dialog = await openNavigation(page);
	const workspaces = dialog.getByRole('region', { name: 'Workspaces', exact: true });
	const projects = dialog.getByRole('region', { name: 'Projects', exact: true });
	await expect(workspaces.getByRole('link')).toHaveCount(25);
	await expect(projects.getByRole('link')).toHaveCount(25);
	await workspaces.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(workspaces.getByRole('heading', { name: 'Workspaces', exact: true })).toBeFocused();
	await expect(
		workspaces.getByRole('link', { name: 'Reading space 30', exact: true })
	).toBeVisible();
	await expect(workspaces.getByText('Page 2 of 2', { exact: true })).toBeVisible();
	await page.keyboard.press('Tab');
	await expect(workspaces.getByRole('link').first()).toBeFocused();
	await projects.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(projects.getByRole('heading', { name: 'Projects', exact: true })).toBeFocused();
	await expect(
		projects.getByRole('link', { name: 'Reading Project 30', exact: true })
	).toHaveAttribute('href', `${dashboardPath}/projects/project-30`);
	await expect(projects.getByText('Page 2 of 2', { exact: true })).toBeVisible();
	expect(workspaceReads.some((url) => url.searchParams.get('offset') === '25')).toBe(true);
	expect(projectReads.some((url) => url.searchParams.get('offset') === '25')).toBe(true);
	const input = dialog.getByRole('searchbox', { name: searchLabel, exact: true });
	await input.fill('Reading');
	await expect.poll(() => workspaceReads.at(-1)?.searchParams.get('search')).toBe('Reading');
	await expect.poll(() => projectReads.at(-1)?.searchParams.get('search')).toBe('Reading');
	await expect(workspaces.getByText('Page 1 of 2', { exact: true })).toBeVisible();
	await expect(projects.getByText('Page 1 of 2', { exact: true })).toBeVisible();
	expect(workspaceReads.at(-1)?.searchParams.get('offset')).toBe('0');
	expect(projectReads.at(-1)?.searchParams.get('offset')).toBe('0');
	await input.fill('Reading Project 30');
	await expect(
		projects.getByRole('link', { name: 'Reading Project 30', exact: true })
	).toBeVisible();
	await expect(projects.getByRole('link')).toHaveCount(1);
	await projects.getByRole('link', { name: 'Reading Project 30', exact: true }).click();
	await expect(page).toHaveURL(`${dashboardPath}/projects/project-30`);
});

test('remote loading stays modal, keeps page links usable and exposes independent retry controls', async ({
	page
}) => {
	const { workspaces, projects } = await mockQuickNavigation(page);
	const release = Promise.withResolvers<void>();
	let failing = true;
	const initialDirectoryRead = page.waitForResponse((response) =>
		workspaceEndpoint.test(response.url())
	);
	await page.goto(dashboardPath);
	await initialDirectoryRead;
	await page.route(workspaceEndpoint, async (route) => {
		await release.promise;
		return route.fulfill(
			failing
				? { status: 503, json: { code: 'internal_error' } }
				: { json: directoryPage(workspaces, route) }
		);
	});
	await page.route('**/api/v1/workspaces/*/projects?*', (route) =>
		route.fulfill(
			failing
				? { status: 503, json: { code: 'internal_error' } }
				: { json: projectPage(projects, route) }
		)
	);
	const dialog = await openNavigation(page);
	const workspaceSection = dialog.getByRole('region', { name: 'Workspaces', exact: true });
	const projectSection = dialog.getByRole('region', { name: 'Projects', exact: true });
	try {
		await expect(workspaceSection.getByText('Loading workspaces…', { exact: true })).toBeVisible();
		await expect(
			dialog
				.getByRole('region', { name: 'Pages and settings', exact: true })
				.getByRole('link', { name: 'Library', exact: true })
		).toBeEnabled();
		const close = dialog.getByRole('button', { name: 'Close', exact: true });
		await close.focus();
		release.resolve();
		await expect(workspaceSection.getByRole('alert')).toContainText('Unable to load workspaces.');
		await expect(projectSection.getByRole('alert')).toContainText('Unable to load Projects.');
		await expect(close).toBeFocused();
		failing = false;
		await workspaceSection.getByRole('button', { name: 'Retry', exact: true }).click();
		await expect(
			workspaceSection.getByRole('link', { name: 'Archive', exact: true })
		).toBeVisible();
		await projectSection.getByRole('button', { name: 'Retry', exact: true }).click();
		await expect(
			projectSection.getByRole('link', { name: 'Reading Project 01', exact: true })
		).toBeVisible();
		await expect(dialog.getByRole('alert')).toHaveCount(0);
	} finally {
		release.resolve();
	}
});

test('Workspace links preserve native modified clicks and only ordinary activation changes the default', async ({
	page
}) => {
	await mockQuickNavigation(page);
	await page.goto(dashboardPath);
	const dialog = await openNavigation(page);
	const archive = dialog
		.getByRole('region', { name: 'Workspaces', exact: true })
		.getByRole('link', { name: 'Archive', exact: true });
	await expect(archive).toHaveAttribute('href', '/workspace/workspace-2');
	await expect(archive).toHaveJSProperty('tagName', 'A');
	const prevented = await archive.evaluate(
		(link, modifier) => {
			const event = new MouseEvent('click', {
				bubbles: true,
				cancelable: true,
				button: 0,
				[modifier]: true
			});
			link.dispatchEvent(event);
			return event.defaultPrevented;
		},
		hostModifier === 'Meta' ? 'metaKey' : 'ctrlKey'
	);
	expect(prevented).toBe(false);
	await expect(page).toHaveURL(dashboardPath);
	await expect(dialog).toBeVisible();
	expect(await page.evaluate(() => localStorage.getItem('quirebase:default-workspace'))).toBe(
		'workspace-1'
	);
	await archive.click();
	await expect(page).toHaveURL('/workspace/workspace-2');
	await expect(dialog).toHaveCount(0);
	await expect
		.poll(() => page.evaluate(() => localStorage.getItem('quirebase:default-workspace')))
		.toBe('workspace-2');
	const next = await openNavigation(page);
	await expect(
		next
			.getByRole('region', { name: 'Pages and settings', exact: true })
			.getByRole('link', { name: 'Library', exact: true })
	).toHaveAttribute('href', '/workspace/workspace-2/library');
});

test('cached pagination is not reset by the initial search debounce after reopening', async ({
	page
}) => {
	await mockQuickNavigation(page);
	await page.goto(dashboardPath);
	const dialog = await openNavigation(page);
	const workspaces = dialog.getByRole('region', { name: 'Workspaces', exact: true });
	await workspaces.getByRole('button', { name: 'Next page', exact: true }).click();
	await expect(workspaces.getByText('Page 2 of 2', { exact: true })).toBeVisible();
	await dialog.getByRole('button', { name: 'Close', exact: true }).click();
	await expect(dialog).toHaveCount(0);

	const clockStart = new Date('2026-10-21T12:00:00Z');
	await page.clock.install({ time: clockStart });
	await page.clock.pauseAt(new Date(clockStart.getTime() + 1_000));
	await trigger(page).press('Enter');
	await expect(dialog).toBeVisible();
	await page.clock.runFor(32);
	await expect(dialog.getByRole('searchbox', { name: searchLabel, exact: true })).toBeFocused();
	await workspaces.getByRole('button', { name: 'Next page', exact: true }).press('Enter');
	await expect(workspaces.getByText('Page 2 of 2', { exact: true })).toBeVisible();
	await page.clock.runFor(250);
	await expect(workspaces.getByText('Page 2 of 2', { exact: true })).toBeVisible();
});

test('mobile Quick navigation remains visible and long result names fit within the dialog', async ({
	page
}, testInfo) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await mockQuickNavigation(page);
	const longName = '非常长的工作区名称与阅读研究方向'.repeat(8);
	await page.route(workspaceEndpoint, (route) =>
		route.fulfill({ json: directoryPage([workspaceView('workspace-long', longName)], route) })
	);
	await page.goto(libraryPath);
	await expect(trigger(page)).toBeVisible();
	const dialog = await openNavigation(page);
	await expect(
		dialog
			.getByRole('region', { name: 'Workspaces', exact: true })
			.getByRole('link', { name: longName, exact: true })
	).toBeVisible();
	await expect
		.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
		.toBe(true);
	await expect
		.poll(() => dialog.evaluate((element) => element.scrollWidth <= element.clientWidth))
		.toBe(true);
	const bounds = await dialog.boundingBox();
	expect(bounds!.x).toBeGreaterThanOrEqual(0);
	expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
	await page.screenshot({
		path: testInfo.outputPath('quick-navigation-mobile.png'),
		fullPage: true
	});
	await dialog.getByRole('button', { name: 'Close', exact: true }).click();
	await expect(trigger(page)).toBeFocused();
});

test('the PDF route keeps its keys while the reader loads and Quick navigation recovers after leaving', async ({
	page
}) => {
	await mockQuickNavigation(page);
	const release = Promise.withResolvers<void>();
	await page.route(
		'**/api/v1/workspaces/workspace-1/items/item-1/revisions/revision-1/viewer',
		async (route) => {
			await release.promise;
			return route.fulfill({ status: 503, json: { code: 'internal_error' } });
		}
	);
	try {
		const pdfPath = `${dashboardPath}/item/item-1/pdf/revision-1?${new URLSearchParams({ return_to: libraryPath.slice(1) })}`;
		await page.goto(pdfPath);
		await expect(
			page.locator('header').getByRole('link', { name: 'Item', exact: true })
		).toBeVisible();
		await page.keyboard.press(`${hostModifier}+k`);
		await expect(page.getByRole('dialog', { name: 'Quick navigation', exact: true })).toHaveCount(
			0
		);
		await expect(page).toHaveURL(pdfPath);
		release.resolve();
		await page.locator('header').getByRole('link', { name: 'Library', exact: true }).click();
		await expect(page).toHaveURL(libraryPath);
		await expect(trigger(page)).toBeVisible();
		await trigger(page).focus();
		await page.keyboard.press(`${hostModifier}+k`);
		await expect(page.getByRole('dialog', { name: 'Quick navigation', exact: true })).toBeVisible();
	} finally {
		release.resolve();
	}
});
