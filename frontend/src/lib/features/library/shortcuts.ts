/* eslint-disable lingui/no-unlocalized-strings -- Hotkey grammar and DOM selectors are machine-readable; UI labels use msg. */
import type { HotkeyChord } from '@tanstack/svelte-hotkeys';
import { msg } from '#lib/i18n.js';

function key(hotkey: HotkeyChord, character = false) {
	return { hotkey, character };
}

// The bindings and help share one list; actions stay with the Library's row model.
export const libraryRowCommands = [
	{
		id: 'previous',
		label: msg('Previous Item'),
		keys: [key('ArrowUp'), key('K', true)],
		repeat: true
	},
	{ id: 'next', label: msg('Next Item'), keys: [key('ArrowDown'), key('J', true)], repeat: true },
	{ id: 'first', label: msg('First Item on this page'), keys: [key('Home')], repeat: true },
	{ id: 'last', label: msg('Last Item on this page'), keys: [key('End')], repeat: true },
	{ id: 'extendUp', label: msg('Extend selection up'), keys: [key('Shift+ArrowUp')], repeat: true },
	{
		id: 'extendDown',
		label: msg('Extend selection down'),
		keys: [key('Shift+ArrowDown')],
		repeat: true
	},
	{
		id: 'toggle',
		label: msg('Select or unselect current Item'),
		keys: [key('X', true)],
		repeat: false
	},
	{
		id: 'only',
		label: msg('Select only current Item'),
		keys: [key('Shift+X', true)],
		repeat: false
	},
	{ id: 'all', label: msg('Select this page'), keys: [key('Mod+A')], repeat: false },
	{
		id: 'preview',
		label: msg('Preview current Item'),
		keys: [key('I', true), key('Enter')],
		repeat: false
	},
	{
		id: 'actions',
		label: msg('Open Item actions'),
		keys: [key('Shift+F10')],
		repeat: false
	}
] as const;

export type LibraryRowCommand = (typeof libraryRowCommands)[number]['id'];

export const libraryPreviewCommands = [
	{
		id: 'previous',
		label: msg('Previous Item in preview'),
		keys: [key('ArrowUp'), key('K', true)],
		repeat: true
	},
	{
		id: 'next',
		label: msg('Next Item in preview'),
		keys: [key('ArrowDown'), key('J', true)],
		repeat: true
	},
	{
		id: 'actions',
		label: msg('Open Item actions'),
		keys: [key('Shift+F10')],
		repeat: false
	}
] as const;

export function runLibraryShortcut(
	event: KeyboardEvent,
	action: () => boolean | void,
	allowRepeat = false
) {
	if (
		event.defaultPrevented ||
		event.isComposing ||
		event.keyCode === 229 ||
		(!allowRepeat && event.repeat)
	)
		return;
	const target = event.target;
	if (
		target instanceof HTMLElement &&
		(target.isContentEditable ||
			target.closest(
				'textarea, select, input:not([type="checkbox"]):not([type="radio"]), [role="textbox"], [role="combobox"], [role="slider"]'
			))
	)
		return;
	// Portalled widgets own their keys, including the first Escape before closing.
	if (
		[
			...document.querySelectorAll<HTMLElement>(
				'[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]'
			)
		].some((element) => element.getClientRects().length > 0)
	)
		return;
	if (action() !== false) event.preventDefault();
}
