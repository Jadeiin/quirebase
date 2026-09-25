import { describe, expect, it } from 'vitest';
import type { WorkspaceView } from '$lib/api/client';
import { workspaceCan, workspaceRole } from '$lib/workspaces/context.svelte';

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
	it('respects the archived and suspended server projection even for an owner', () => {
		const archived = {
			...view('owner', ['workspace.read', 'workspace.archive']),
			state: 'archived'
		};
		const suspended = { ...view('owner', ['workspace.read']), governance_suspended: true };
		expect(workspaceCan(archived, 'workspace.archive')).toBe(true);
		expect(workspaceCan(archived, 'items.edit')).toBe(false);
		expect(workspaceCan(suspended, 'workspace.archive')).toBe(false);
	});
	it('exposes the projected role for display without granting authority through it', () => {
		expect(workspaceRole(view('owner', ['workspace.read']))).toBe('owner');
		expect(workspaceCan(view('owner', ['workspace.read']), 'items.delete')).toBe(false);
	});
});
