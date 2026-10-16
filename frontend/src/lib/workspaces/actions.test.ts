import { describe, expect, it } from 'vitest';
import type { AuthorizationAction } from '#lib/authorization/can.js';
import { canRunBulkAction } from './actions';

describe('Workspace action projection', () => {
	it('uses server resource actions for every Library action', () => {
		const allowed = new Set<AuthorizationAction>(['workspace.read', 'workspace.export', 'tag.use']);
		const can = (action: AuthorizationAction) => allowed.has(action);
		expect(
			['bibliography', 'documents', 'add_tag'].map((action) =>
				canRunBulkAction(can, action as Parameters<typeof canRunBulkAction>[1])
			)
		).toEqual([true, true, true]);
		expect(canRunBulkAction(can, 'add_project')).toBe(false);
		expect(canRunBulkAction(can, 'delete')).toBe(false);
	});
});
