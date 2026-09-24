import { describe, expect, it } from 'vitest';
import { workspaceKeys } from '$lib/workspaces/keys';

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
});
