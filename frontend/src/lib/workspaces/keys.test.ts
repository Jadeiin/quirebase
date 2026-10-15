import { describe, expect, it } from 'vitest';
import { workspaceKeys } from '#lib/workspaces/keys.js';

describe('workspaceKeys', () => {
	it('isolates every resource and mutation by Workspace', () => {
		expect(workspaceKeys.items('workspace-a')).not.toEqual(workspaceKeys.items('workspace-b'));
		expect(workspaceKeys.item('workspace-a', 'item-1')).not.toEqual(
			workspaceKeys.item('workspace-b', 'item-1')
		);
		expect(workspaceKeys.mutation('workspace-a', 'metadata', 'item-1')).not.toEqual(
			workspaceKeys.mutation('workspace-b', 'metadata', 'item-1')
		);
	});

	it('builds nested project discussion keys through the Workspace factory', () => {
		expect(workspaceKeys.projectDiscussions('workspace-a', 'project-1')).toEqual([
			'workspace',
			'workspace-a',
			'projects',
			'project',
			'project-1',
			'discussions'
		]);
	});

	it('nests every Workspace-scoped key under the invalidatable Workspace prefix', () => {
		const keys = [
			workspaceKeys.root('workspace-a'),
			workspaceKeys.items('workspace-a'),
			workspaceKeys.item('workspace-a', 'item-1'),
			workspaceKeys.projects('workspace-a'),
			workspaceKeys.project('workspace-a', 'project-1'),
			workspaceKeys.members('workspace-a'),
			workspaceKeys.governanceMembers('workspace-a'),
			workspaceKeys.invitations('workspace-a'),
			workspaceKeys.mutation('workspace-a', 'metadata', 'item-1')
		];
		for (const key of keys) {
			expect(key.slice(0, workspaceKeys.all().length)).toEqual(workspaceKeys.all());
		}
	});
});
