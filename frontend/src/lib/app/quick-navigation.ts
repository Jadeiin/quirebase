/* eslint-disable lingui/no-unlocalized-strings -- Navigation identifiers and DOM selectors are machine-readable; labels use msg. */
import { msg, type MessageKey } from '#lib/i18n.js';
import { workspaceHref, type WorkspacePath } from '#lib/workspaces/href.js';
import { navigation } from './navigation.js';

type PageLink = {
	id: string;
	label: MessageKey;
	icon: string;
	href: WorkspacePath | 'workspace' | 'account' | 'admin';
};

export function quickPageLinks(
	workspaceId: string | undefined,
	administration: boolean
): PageLink[] {
	const links: PageLink[] = workspaceId
		? navigation.map(([section, label, icon]) => ({
				id: `page-${section || 'dashboard'}`,
				label,
				icon,
				href: workspaceHref(workspaceId, section)
			}))
		: [];
	if (workspaceId)
		links.push({
			id: 'workspace-settings',
			label: msg('Workspace settings'),
			icon: 'settings',
			href: workspaceHref(workspaceId, 'settings')
		});
	links.push(
		{ id: 'workspaces', label: msg('My workspaces'), icon: 'panel', href: 'workspace' },
		{ id: 'account', label: msg('Account settings'), icon: 'user', href: 'account' }
	);
	if (administration)
		links.push({ id: 'admin', label: msg('Administration'), icon: 'admin', href: 'admin' });
	return links;
}

/** The hotkey library matches the chord; this policy protects the current editing/focus scope. */
export function canOpenQuickNavigation(event: KeyboardEvent, readerRoute: boolean): boolean {
	if (
		readerRoute ||
		event.defaultPrevented ||
		event.isComposing ||
		event.keyCode === 229 ||
		event.repeat ||
		event.getModifierState('AltGraph')
	)
		return false;
	const target = event.target;
	if (
		target instanceof Element &&
		target.closest(
			'textarea, select, input:not([type="checkbox"]):not([type="radio"]), [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"], [role="slider"]'
		)
	)
		return false;
	return ![
		...document.querySelectorAll<HTMLElement>(
			'[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"], dialog[open]'
		)
	].some((element) => element.getClientRects().length > 0);
}
