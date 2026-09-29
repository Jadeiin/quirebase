import type { LibraryBulkAction } from '$lib/features/library/mutations';

export type CanResourceAction = (resource: string, action: string) => boolean;

const bulkResourceActions: Record<LibraryBulkAction, readonly [string, string]> = {
	add_project: ['project_item', 'manage'],
	add_tag: ['tag', 'use'],
	bibliography: ['workspace', 'export'],
	documents: ['workspace', 'export'],
	delete: ['item', 'delete']
};

export function canRunBulkAction(can: CanResourceAction, action: LibraryBulkAction): boolean {
	return can(...bulkResourceActions[action]);
}
