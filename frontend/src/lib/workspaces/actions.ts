import type { LibraryBulkAction } from '#lib/features/library/mutations.js';
import type { AuthorizationAction } from '#lib/authorization/can.js';

export type CanResourceAction = (action: AuthorizationAction) => boolean;

const bulkResourceActions: Record<LibraryBulkAction, AuthorizationAction> = {
	add_project: 'project_item.manage',
	remove_project: 'project_item.manage',
	add_tag: 'tag.use',
	remove_tag: 'tag.use',
	copy_bibliography: 'workspace.export',
	bibliography: 'workspace.export',
	documents: 'workspace.export',
	delete_items: 'item.delete'
};

export function canRunBulkAction(can: CanResourceAction, action: LibraryBulkAction): boolean {
	return can(bulkResourceActions[action]);
}
