import { describe, expect, it } from 'vitest';
import type { AuthorizationAction } from '#lib/authorization/can.js';
import { canRunBulkAction } from './actions';

describe('Workspace action projection', () => {
	it('uses server resource actions for every Library action', () => {
		const allowed = new Set<AuthorizationAction>(['workspace.read', 'workspace.export', 'tag.use']);
		const can = (action: AuthorizationAction) => allowed.has(action);
		expect(
			['copy_bibliography', 'bibliography', 'documents', 'add_tag', 'remove_tag'].map((action) =>
				canRunBulkAction(can, action as Parameters<typeof canRunBulkAction>[1])
			)
		).toEqual([true, true, true, true, true]);
		expect(canRunBulkAction(can, 'add_project')).toBe(false);
		expect(canRunBulkAction(can, 'remove_project')).toBe(false);
		expect(canRunBulkAction(can, 'delete_items')).toBe(false);
	});

	it('requires Workspace export authority for copying references', () => {
		expect(canRunBulkAction((action) => action === 'workspace.export', 'copy_bibliography')).toBe(
			true
		);
		expect(canRunBulkAction((action) => action === 'workspace.read', 'copy_bibliography')).toBe(
			false
		);
	});

	it('uses Project-association authority for both assignment directions', () => {
		const can = (action: AuthorizationAction) => action === 'project_item.manage';
		expect(canRunBulkAction(can, 'add_project')).toBe(true);
		expect(canRunBulkAction(can, 'remove_project')).toBe(true);
		expect(canRunBulkAction(can, 'remove_tag')).toBe(false);
		expect(canRunBulkAction(can, 'delete_items')).toBe(false);
	});
});
