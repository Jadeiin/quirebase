import type { Pathname } from '$app/types';
import { msg, type MessageKey } from '$lib/i18n';

export type NavigationItem = readonly [Pathname, MessageKey, string];

export const navigation: readonly NavigationItem[] = [
	['/', msg('Dashboard'), 'dashboard'],
	['/library', msg('Library'), 'library'],
	['/import', msg('Import'), 'import'],
	['/discovery', msg('Discovery'), 'search'],
	['/projects', msg('Projects'), 'projects'],
	['/tools', msg('Tools'), 'tools']
];

export const mobileNavigation: readonly NavigationItem[] = [
	['/library', msg('Library'), 'library'],
	['/discovery', msg('Discovery'), 'search'],
	['/projects', msg('Projects'), 'projects']
];

export const mobileMoreNavigation: readonly NavigationItem[] = [
	['/', msg('Dashboard'), 'dashboard'],
	['/import', msg('Import'), 'import'],
	['/tools', msg('Tools'), 'tools'],
	['/account', msg('Account settings'), 'user']
];

export const themeOptions = [
	['system', msg('System theme'), 'monitor'],
	['light', msg('Light theme'), 'sun'],
	['dark', msg('Dark theme'), 'moon']
] as const;
