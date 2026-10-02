import { describe, expect, it } from 'vitest';
import type { WorkspaceView } from '#lib/api/client.js';
import type { AuthorizationAction } from '#lib/authorization/can.js';
import { workspaceCan, workspaceRole } from '#lib/workspaces/context.svelte.js';

const view = (role: string, allowed: AuthorizationAction[]): WorkspaceView => ({
	id: 'workspace-1',
	name: 'Research',
	owner_id: 'user-1',
	state: 'active',
	current_role: role,
	governance_suspended: false,
	authorization: { allowed }
});

describe('workspaceCan', () => {
	it('trusts the server projection instead of mapping role names to actions', () => {
		expect(workspaceCan(view('owner', ['workspace.read']), 'item.create')).toBe(false);
		expect(workspaceCan(view('viewer', ['item.create']), 'item.create')).toBe(true);
		expect(workspaceCan(undefined, 'workspace.read')).toBe(false);
	});
	it('respects the archived and suspended server projection even for an owner', () => {
		const archived = {
			...view('owner', ['workspace.read', 'workspace.archive']),
			state: 'archived'
		};
		const suspended = { ...view('owner', ['workspace.read']), governance_suspended: true };
		expect(workspaceCan(archived, 'workspace.archive')).toBe(true);
		expect(workspaceCan(archived, 'item.update')).toBe(false);
		expect(workspaceCan(suspended, 'workspace.archive')).toBe(false);
	});
	it('exposes the projected role for display without granting authority through it', () => {
		expect(workspaceRole(view('owner', ['workspace.read']))).toBe('owner');
		expect(workspaceCan(view('owner', ['workspace.read']), 'item.delete')).toBe(false);
	});
});
