import { describe, expect, it } from 'vitest';
import { canRunBulkAction } from './actions';

describe('Workspace action projection', () => {
	it('uses server resource actions for every Library action', () => {
		const can = (resource: string, action: string) =>
			['workspace.read', 'workspace.export', 'tag.use'].includes(`${resource}.${action}`);
		expect(
			['bibliography', 'documents', 'add_tag'].map((action) =>
				canRunBulkAction(can, action as Parameters<typeof canRunBulkAction>[1])
			)
		).toEqual([true, true, true]);
		expect(canRunBulkAction(can, 'add_project')).toBe(false);
		expect(canRunBulkAction(can, 'delete')).toBe(false);
	});
});
