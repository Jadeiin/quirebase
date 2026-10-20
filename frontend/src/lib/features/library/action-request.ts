import type { LibraryBulkAction } from './mutations.js';

export type LibraryActionRequest = {
	action: LibraryBulkAction;
	itemIds: string[];
	source: 'item' | 'selection';
	trigger: HTMLElement | null;
	project?: { id: string; name: string } | null;
	listing: string;
	afterMutation?: () => void;
};
