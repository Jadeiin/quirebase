import { describe, expect, it } from 'vitest';
import type { WorkspaceView } from '$lib/api/client';
import { workspaceCan } from '$lib/workspaces/context.svelte';

const view = (role: string, effective_capabilities: string[]): WorkspaceView => ({
	id: 'workspace-1',
	name: 'Research',
	owner_id: 'user-1',
	state: 'active',
	current_role: role,
	governance_suspended: false,
	effective_capabilities
});

describe('workspaceCan', () => {
	it('trusts the server projection instead of mapping role names to capabilities', () => {
		expect(workspaceCan(view('owner', ['workspace.read']), 'items.create')).toBe(false);
		expect(workspaceCan(view('viewer', ['items.create']), 'items.create')).toBe(true);
		expect(workspaceCan(undefined, 'workspace.read')).toBe(false);
	});
});
