import type { LibraryBulkAction } from '$lib/features/library/mutations';

export type CanCapability = (capability: string) => boolean;

const bulkCapabilities: Record<LibraryBulkAction, string> = {
	add_project: 'projects.manage',
	add_tag: 'tags.use',
	bibliography: 'workspace.export',
	documents: 'workspace.export',
	delete: 'items.delete'
};

export function canRunBulkAction(can: CanCapability, action: LibraryBulkAction): boolean {
	return can(bulkCapabilities[action]);
}

export function canCopyItem(can: CanCapability, targetCapabilities: readonly string[]): boolean {
	return can('workspace.export') && targetCapabilities.includes('items.create');
}
