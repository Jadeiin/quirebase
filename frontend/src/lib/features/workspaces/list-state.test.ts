import { describe, expect, it } from 'vitest';
import {
	readWorkspaceInvitationsState,
	readWorkspaceListState,
	readWorkspaceMembersState,
	workspaceInvitationParameters,
	workspaceListParameters,
	workspaceMemberParameters
} from './list-state';

describe('workspace collaboration list URLs', () => {
	it('retains directory defaults and unrelated received-invitation parameters', () => {
		expect(readWorkspaceListState(new URLSearchParams('page=Infinity&page_size=3'))).toEqual({
			search: '',
			page: 1,
			pageSize: 25
		});
		const parameters = new URLSearchParams(
			workspaceListParameters('team', 2, 50, '?invitation_page=3&q=old')
		);
		expect(Object.fromEntries(parameters)).toEqual({
			invitation_page: '3',
			q: 'team',
			page: '2',
			page_size: '50'
		});
	});

	it('keeps ordinary members limited to role and username order', () => {
		const state = readWorkspaceMembersState(
			new URLSearchParams('role=owner&state=suspended&sort=joined&direction=desc'),
			false
		);
		expect(state).toEqual({
			search: '',
			page: 1,
			pageSize: 25,
			role: 'owner',
			state: '',
			sort: 'username',
			direction: 'desc'
		});
		expect(workspaceMemberParameters(state)).toBe('role=owner&direction=desc');
	});

	it('round trips governance filters, ordering and pagination', () => {
		const state = readWorkspaceMembersState(
			new URLSearchParams(
				'q=Alex&page=3&page_size=10&role=editor&state=suspended&sort=joined&direction=desc'
			),
			true
		);
		expect(
			readWorkspaceMembersState(new URLSearchParams(workspaceMemberParameters(state)), true)
		).toEqual(state);
		expect(state).toMatchObject({
			page: 3,
			pageSize: 10,
			search: 'Alex',
			role: 'editor',
			state: 'suspended',
			sort: 'joined',
			direction: 'desc'
		});
	});

	it('rejects invalid member fields and omits defaults', () => {
		const state = readWorkspaceMembersState(
			new URLSearchParams(
				'page=-2&page_size=7&role=administrator&state=terminated&sort=created&direction=sideways'
			),
			true
		);
		expect(workspaceMemberParameters(state)).toBe('');
	});

	it.each([
		['', 'created', 'desc'],
		['sort=username', 'username', 'asc'],
		['sort=expires', 'expires', 'asc'],
		['sort=created&direction=asc', 'created', 'asc']
	])('applies meaningful invitation defaults for %s', (parameters, sort, direction) => {
		expect(readWorkspaceInvitationsState(new URLSearchParams(parameters))).toMatchObject({
			sort,
			direction
		});
	});

	it('round trips invitation filters and rejects owner invitations', () => {
		const state = readWorkspaceInvitationsState(
			new URLSearchParams('q=Alex&role=reviewer&page=2&page_size=50&sort=expires&direction=desc')
		);
		expect(
			readWorkspaceInvitationsState(new URLSearchParams(workspaceInvitationParameters(state)))
		).toEqual(state);
		expect(
			workspaceInvitationParameters(
				readWorkspaceInvitationsState(new URLSearchParams('role=owner&sort=joined'))
			)
		).toBe('');
	});

	it('lets dependent changes reset the page without losing submitted filters', () => {
		const state = readWorkspaceMembersState(
			new URLSearchParams('q=Lee&role=admin&page=4&state=active&sort=joined'),
			true
		);
		const next = { ...state, page: 1, pageSize: 50 };
		expect(
			readWorkspaceMembersState(new URLSearchParams(workspaceMemberParameters(next)), true)
		).toEqual(next);
	});
});
