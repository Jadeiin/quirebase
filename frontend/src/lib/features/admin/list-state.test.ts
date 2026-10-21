import { expect, it } from 'vitest';
import { adminListParameters, defaultAdminSortDirection, readAdminFilters } from './list-state.js';

it.each([
	['users', 'username', 'asc', 20],
	['invitations', 'created', 'desc', 20],
	['workspaces', 'name', 'asc', 20],
	['audit', 'created', 'desc', 50],
	['workflows', 'created', 'desc', 20]
] as const)(
	'omits the %s default view and rejects unsupported URL values',
	(section, sort, direction, pageSize) => {
		const defaults = readAdminFilters(new URLSearchParams(), section);
		expect(defaults).toMatchObject({ page: 1, pageSize, sort, direction });
		expect(adminListParameters(defaults, section)).toBe('');
		const invalid = readAdminFilters(
			new URLSearchParams(
				'page=Infinity&page_size=13&role=owner&active=yes&state=unknown&frozen=maybe&owner_active=no&sort=unknown&direction=down'
			),
			section
		);
		expect(invalid).toEqual(defaults);
		expect(adminListParameters(invalid, section)).toBe('');
	}
);

it.each([
	['users', ['username', 'created']],
	['invitations', ['username', 'created', 'expires']],
	['workspaces', ['name', 'owner', 'created']],
	['audit', ['created']],
	['workflows', ['created']]
] as const)('round-trips both directions of the supported %s sort fields', (section, sorts) => {
	for (const sort of sorts) {
		for (const direction of ['asc', 'desc']) {
			const filters = readAdminFilters(new URLSearchParams({ sort, direction }), section);
			const serialized = new URLSearchParams(adminListParameters(filters, section));
			const restored = readAdminFilters(serialized, section);
			expect(restored).toEqual(filters);
			expect(restored).toMatchObject({ sort, direction });
			expect(serialized.has('direction')).toBe(direction !== defaultAdminSortDirection(sort));
		}
	}
});

it.each([
	['users', 'username', 'asc'],
	['users', 'created', 'desc'],
	['invitations', 'username', 'asc'],
	['invitations', 'expires', 'asc'],
	['invitations', 'created', 'desc'],
	['workspaces', 'name', 'asc'],
	['workspaces', 'owner', 'asc'],
	['workspaces', 'created', 'desc'],
	['audit', 'created', 'desc'],
	['workflows', 'created', 'desc']
] as const)(
	'restores the %s %s default direction from URLs without a valid direction',
	(section, sort, expected) => {
		for (const direction of [undefined, 'invalid']) {
			const parameters = new URLSearchParams({ sort });
			if (direction !== undefined) parameters.set('direction', direction);
			const filters = readAdminFilters(parameters, section);
			expect(filters).toMatchObject({ sort, direction: expected });
			const canonical = new URLSearchParams(adminListParameters(filters, section));
			expect(canonical.has('direction')).toBe(false);
			expect(readAdminFilters(canonical, section)).toEqual(filters);
		}
	}
);

it.each([
	['users', 'expires', 'username'],
	['invitations', 'action', 'created'],
	['workspaces', 'username', 'name'],
	['audit', 'username', 'created'],
	['workflows', 'expires', 'created']
] as const)(
	'rejects another list’s sort field in %s without discarding an explicit direction',
	(section, sort, expected) => {
		const filters = readAdminFilters(new URLSearchParams({ sort, direction: 'asc' }), section);
		expect(filters).toMatchObject({ sort: expected, direction: 'asc' });
		expect(new URLSearchParams(adminListParameters(filters, section)).has('sort')).toBe(false);
	}
);

it('round-trips invitation criteria and encoded search text while discarding unrelated filters', () => {
	const input = new URLSearchParams({
		q: '研究 & username+prefix%_',
		role: 'administrator',
		state: 'pending',
		page: '3',
		page_size: '25',
		sort: 'expires',
		direction: 'asc',
		active: 'false',
		name: 'unrelated workflow',
		action: 'unrelated.action',
		target_type: 'item',
		unknown: 'discard me'
	});
	const filters = readAdminFilters(input, 'invitations');
	const parameters = new URLSearchParams(adminListParameters(filters, 'invitations'));
	expect(Object.fromEntries(parameters)).toEqual({
		q: '研究 & username+prefix%_',
		role: 'administrator',
		state: 'pending',
		page: '3',
		page_size: '25',
		sort: 'expires'
	});
	expect(readAdminFilters(parameters, 'invitations')).toEqual(filters);
	expect(input.get('unknown')).toBe('discard me');
});

it('keeps Workspace lifecycle, freeze and owner activity independent in shareable URLs', () => {
	const input = new URLSearchParams({
		q: '研究 & owner+name%_',
		state: 'archived',
		frozen: 'false',
		owner_active: 'false',
		sort: 'owner',
		direction: 'desc',
		page: '3',
		page_size: '10',
		role: 'administrator',
		active: 'false',
		name: 'not a workflow',
		action: 'not an event'
	});
	const filters = readAdminFilters(input, 'workspaces');
	const canonical = new URLSearchParams(adminListParameters(filters, 'workspaces'));
	expect(Object.fromEntries(canonical)).toEqual({
		q: '研究 & owner+name%_',
		state: 'archived',
		frozen: 'false',
		owner_active: 'false',
		sort: 'owner',
		direction: 'desc',
		page: '3',
		page_size: '10'
	});
	expect(filters).toMatchObject({
		workspaceState: 'archived',
		frozen: 'false',
		ownerActive: 'false'
	});
	expect(readAdminFilters(canonical, 'workspaces')).toEqual(filters);
	for (const section of ['users', 'invitations', 'audit', 'workflows'] as const) {
		const other = readAdminFilters(canonical, section);
		expect(other).toMatchObject({ workspaceState: '', frozen: '', ownerActive: '' });
		const parameters = new URLSearchParams(adminListParameters(other, section));
		expect(parameters.has('frozen')).toBe(false);
		expect(parameters.has('owner_active')).toBe(false);
	}
});

it('keeps the exact workflow name and state without interpreting another section’s search', () => {
	const filters = readAdminFilters(
		new URLSearchParams({
			name: 'PDF Import.Prepare & 一+Two',
			state: 'failed',
			q: 'different search',
			role: 'member',
			active: 'true',
			action: 'delete',
			target_type: 'item'
		}),
		'workflows'
	);
	const parameters = new URLSearchParams(adminListParameters(filters, 'workflows'));
	expect(Object.fromEntries(parameters)).toEqual({
		name: 'PDF Import.Prepare & 一+Two',
		state: 'failed'
	});
	expect(readAdminFilters(parameters, 'workflows')).toEqual(filters);
	const invitations = readAdminFilters(parameters, 'invitations');
	expect(invitations.workflowName).toBe('');
	expect(invitations.invitationState).toBe('');
	expect(adminListParameters(invitations, 'invitations')).toBe('');
});

it('keeps each section’s supported criteria when reading the same shared URL', () => {
	const input = new URLSearchParams({
		q: 'curator',
		role: 'member',
		active: 'false',
		state: 'pending',
		name: 'backup',
		action: 'user.update',
		target_type: 'user',
		sort: 'expires',
		direction: 'asc'
	});
	const destination = (section: Parameters<typeof readAdminFilters>[1]) =>
		Object.fromEntries(
			new URLSearchParams(adminListParameters(readAdminFilters(input, section), section))
		);
	expect(destination('users')).toEqual({ q: 'curator', role: 'member', active: 'false' });
	expect(destination('invitations')).toEqual({
		q: 'curator',
		role: 'member',
		state: 'pending',
		sort: 'expires'
	});
	expect(destination('audit')).toEqual({
		q: 'curator',
		action: 'user.update',
		target_type: 'user',
		direction: 'asc'
	});
	expect(destination('workflows')).toEqual({ state: 'pending', name: 'backup', direction: 'asc' });
	expect(destination('workspaces')).toEqual({ q: 'curator' });
});

it.each(['users', 'invitations', 'workspaces', 'audit', 'workflows'] as const)(
	'normalizes %s pagination and preserves every supported page size',
	(section) => {
		for (const page of ['', '-3', 'NaN', 'Infinity']) {
			expect(readAdminFilters(new URLSearchParams({ page }), section).page).toBe(1);
		}
		for (const pageSize of [10, 20, 25, 50, 100]) {
			const filters = readAdminFilters(
				new URLSearchParams({ page: '4.9', page_size: String(pageSize) }),
				section
			);
			const parameters = new URLSearchParams(adminListParameters(filters, section));
			expect(filters).toMatchObject({ page: 4, pageSize });
			expect(readAdminFilters(parameters, section)).toEqual(filters);
			expect(parameters.has('page_size')).toBe(pageSize !== (section === 'audit' ? 50 : 20));
		}
	}
);
