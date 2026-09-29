import type { LibraryBulkAction } from '$lib/features/library/mutations';
import type { AuthorizationAction } from '$lib/authorization/can';

export type CanResourceAction = (action: AuthorizationAction) => boolean;

const bulkResourceActions: Record<LibraryBulkAction, AuthorizationAction> = {
	add_project: 'project_item.manage',
	add_tag: 'tag.use',
	bibliography: 'workspace.export',
	documents: 'workspace.export',
	delete: 'item.delete'
};

export function canRunBulkAction(can: CanResourceAction, action: LibraryBulkAction): boolean {
	return can(bulkResourceActions[action]);
}
