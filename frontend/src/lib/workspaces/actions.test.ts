import { describe, expect, it } from 'vitest';
import { canCopyItem, canRunBulkAction } from './actions';

describe('Workspace action projection', () => {
	it('uses server capabilities for every Library action', () => {
		const can = (capability: string) =>
			['workspace.read', 'workspace.export', 'tags.use'].includes(capability);
		expect(
			['bibliography', 'documents', 'add_tag'].map((action) =>
				canRunBulkAction(can, action as Parameters<typeof canRunBulkAction>[1])
			)
		).toEqual([true, true, true]);
		expect(canRunBulkAction(can, 'add_project')).toBe(false);
		expect(canRunBulkAction(can, 'delete')).toBe(false);
	});

	it('requires source export and destination creation for a cross-Workspace copy', () => {
		expect(canCopyItem(() => false, ['items.create'])).toBe(false);
		expect(canCopyItem((capability) => capability === 'workspace.export', ['workspace.read'])).toBe(
			false
		);
		expect(canCopyItem((capability) => capability === 'workspace.export', ['items.create'])).toBe(
			true
		);
	});
});
