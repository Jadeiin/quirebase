// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { canOpenQuickNavigation, quickPageLinks } from './quick-navigation.js';

afterEach(() => document.body.replaceChildren());

function eventFrom(target: HTMLElement, options: KeyboardEventInit = {}) {
	if (!target.isConnected) document.body.append(target);
	const event = new KeyboardEvent('keydown', {
		key: 'k',
		ctrlKey: true,
		cancelable: true,
		...options
	});
	target.dispatchEvent(event);
	return event;
}

describe('quick navigation scope', () => {
	it('offers only global pages without a Workspace and gates Administration by its projection', () => {
		expect(quickPageLinks(undefined, false).map(({ href }) => href)).toEqual([
			'workspace',
			'account'
		]);
		expect(quickPageLinks(undefined, true).map(({ href }) => href)).toContain('admin');
		const links = quickPageLinks('workspace/a', false);
		expect(links.find(({ id }) => id === 'page-library')?.href).toBe(
			'workspace/workspace%2Fa/library'
		);
		expect(links.find(({ id }) => id === 'workspace-settings')?.href).toBe(
			'workspace/workspace%2Fa/settings'
		);
		expect(new Set(links.map(({ id }) => id)).size).toBe(links.length);
	});

	it('allows navigation from ordinary controls but leaves the PDF reader alone', () => {
		const event = eventFrom(document.createElement('button'));
		expect(canOpenQuickNavigation(event, false)).toBe(true);
		expect(canOpenQuickNavigation(event, true)).toBe(false);
	});

	it.each([
		'input',
		'textarea',
		'select',
		'[contenteditable]',
		'[role="textbox"]',
		'[role="combobox"]'
	])('leaves editing in %s alone', (selector) => {
		const target = document.createElement(selector.startsWith('[') ? 'div' : selector);
		if (selector === '[contenteditable]') target.setAttribute('contenteditable', 'true');
		if (selector.startsWith('[role=')) target.setAttribute('role', selector.slice(7, -2));
		const child = document.createElement('span');
		if (target.tagName === 'DIV') target.append(child);
		expect(canOpenQuickNavigation(eventFrom(target), false)).toBe(false);
		if (target.tagName === 'DIV')
			expect(canOpenQuickNavigation(eventFrom(child), false)).toBe(false);
	});

	it('does not reopen on repeats or composition and respects earlier handlers', () => {
		const target = document.createElement('button');
		for (const options of [{ repeat: true }, { isComposing: true }, { keyCode: 229 }])
			expect(canOpenQuickNavigation(eventFrom(target, options), false)).toBe(false);
		const handled = eventFrom(target);
		handled.preventDefault();
		expect(canOpenQuickNavigation(handled, false)).toBe(false);
	});

	it.each(['dialog', 'alertdialog', 'menu', 'listbox'])(
		'defers to a visible %s while allowing unmounted/hidden popups',
		(role) => {
			const popup = document.createElement('div');
			popup.setAttribute('role', role);
			document.body.append(popup);
			const event = eventFrom(document.createElement('button'));
			expect(canOpenQuickNavigation(event, false)).toBe(true);
			vi.spyOn(popup, 'getClientRects').mockReturnValue([{}] as unknown as DOMRectList);
			expect(canOpenQuickNavigation(event, false)).toBe(false);
		}
	);
});
