import { msg, type MessageKey } from '#lib/i18n.js';
import type { LibraryBulkAction } from './mutations.js';

export type LibraryActionHandler = (action: LibraryBulkAction, trigger: HTMLElement) => void;

type LibraryActionEntry = {
	action: LibraryBulkAction;
	label: MessageKey;
	icon: string;
};

export const libraryPrimaryActions: readonly LibraryActionEntry[] = [
	{ action: 'add_tag', label: msg('Add Tag'), icon: 'plus' },
	{ action: 'add_project', label: msg('Add to Project'), icon: 'projects' },
	{ action: 'copy_bibliography', label: msg('Copy citation'), icon: 'file' },
	{ action: 'bibliography', label: msg('Export bibliography'), icon: 'download' }
];

export const librarySecondaryActions: readonly LibraryActionEntry[] = [
	{ action: 'documents', label: msg('Download documents'), icon: 'download' },
	{ action: 'remove_tag', label: msg('Remove Tag'), icon: 'minus' },
	{ action: 'remove_project', label: msg('Remove from current Project'), icon: 'projects' },
	{ action: 'delete_items', label: msg('Permanently delete'), icon: 'close' }
];
