import { isCancelledError, onlineManager, QueryClient } from '@tanstack/svelte-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/client.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import { readWorkspaceInvitationsState, readWorkspaceMembersState } from './list-state';
import { workspaceInvitationsQuery, workspaceMembersQuery } from './queries';

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('#lib/api/client.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.js')>()),
	createWorkspaceApi: () => ({ request })
}));

const clients: QueryClient[] = [];
const snapshot = { items: [], total: 43, limit: 25, offset: 0 };
function queryClient() {
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	client.mount();
	clients.push(client);
	return client;
}
function query(
	section: 'members' | 'governance' | 'invitations',
	parameters = '',
	workspaceId = 'workspace-1'
) {
	return section === 'invitations'
		? workspaceInvitationsQuery(
				workspaceId,
				readWorkspaceInvitationsState(new URLSearchParams(parameters))
			)
		: workspaceMembersQuery(
				workspaceId,
				section === 'governance',
				readWorkspaceMembersState(new URLSearchParams(parameters), section === 'governance')
			);
}

function fetch(
	client: QueryClient,
	section: 'members' | 'governance' | 'invitations',
	parameters = ''
) {
	if (section === 'invitations') {
		return client.fetchQuery(
			workspaceInvitationsQuery(
				'workspace-1',
				readWorkspaceInvitationsState(new URLSearchParams(parameters))
			)
		);
	}
	return client.fetchQuery(
		workspaceMembersQuery(
			'workspace-1',
			section === 'governance',
			readWorkspaceMembersState(new URLSearchParams(parameters), section === 'governance')
		)
	);
}

afterEach(() => {
	for (const client of clients.splice(0)) {
		client.unmount();
		client.clear();
	}
	onlineManager.setOnline(true);
	request.mockReset();
});

describe('workspace collaboration queries', () => {
	it.each(['members', 'governance', 'invitations'] as const)(
		'rechecks a warm %s variant despite a global freshness window',
		async (section) => {
			const client = queryClient();
			client.setDefaultOptions({ queries: { retry: false, staleTime: 30_000 } });
			client.setQueryData(query(section).queryKey, snapshot);
			const refreshed = { ...snapshot, total: 1 };
			request.mockResolvedValueOnce(refreshed);
			await expect(fetch(client, section)).resolves.toMatchObject({ total: 1 });
			expect(request).toHaveBeenCalledTimes(1);
		}
	);

	it('sends only public member filters for the ordinary directory', async () => {
		request.mockResolvedValueOnce({
			...snapshot,
			items: [{ user_id: 'user-1', username: 'alex', role: 'viewer' }]
		});
		const result = await fetch(
			queryClient(),
			'members',
			'q=alex&role=viewer&state=suspended&sort=joined&direction=desc&page=3&page_size=10'
		);
		expect(request).toHaveBeenCalledWith(
			'GET',
			'/workspaces/{workspace_id}/members',
			expect.objectContaining({
				params: {
					query: { limit: 10, offset: 20, search: 'alex', role: 'viewer', direction: 'desc' }
				}
			})
		);
		expect(result).not.toHaveProperty('items.0.governance');
	});

	it('retains current governance decisions and membership generation', async () => {
		const member = {
			membership_id: 'generation-2',
			user_id: 'user-1',
			username: 'alex',
			role: 'reviewer',
			state: 'suspended',
			joined_at: '2026-01-01',
			allowed_roles: ['viewer'],
			authorization: { decisions: {} }
		};
		request.mockResolvedValueOnce({ ...snapshot, items: [member] });
		const result = await fetch(
			queryClient(),
			'governance',
			'role=reviewer&state=suspended&sort=joined'
		);
		expect(request).toHaveBeenCalledWith(
			'GET',
			'/workspaces/{workspace_id}/governance/members',
			expect.objectContaining({
				params: {
					query: {
						limit: 25,
						offset: 0,
						search: '',
						role: 'reviewer',
						direction: 'asc',
						state: 'suspended',
						sort: 'joined'
					}
				}
			})
		);
		expect(result).toMatchObject({ items: [{ governance: member }] });
	});

	it('uses server invitation totals and pages instead of loading all invitations', async () => {
		request.mockResolvedValueOnce(snapshot);
		const result = await fetch(
			queryClient(),
			'invitations',
			'q=lee&role=editor&sort=expires&direction=desc&page=2&page_size=10'
		);
		expect(request).toHaveBeenCalledWith(
			'GET',
			'/workspaces/{workspace_id}/invitations',
			expect.objectContaining({
				params: {
					query: {
						limit: 10,
						offset: 10,
						search: 'lee',
						role: 'editor',
						sort: 'expires',
						direction: 'desc'
					}
				}
			})
		);
		expect(result).toMatchObject({ total: 43 });
	});

	it.each(['members', 'governance', 'invitations'] as const)(
		'retains cached %s pages on transient failures',
		async (section) => {
			const client = queryClient();
			const current = query(section);
			const other = query(section, 'page=2');
			for (const options of [current, other]) client.setQueryData(options.queryKey, snapshot);
			request.mockRejectedValueOnce(new TypeError('Offline'));
			await expect(fetch(client, section)).rejects.toThrow('Offline');
			for (const options of [current, other])
				expect(client.getQueryData(options.queryKey)).toEqual(snapshot);
		}
	);

	it.each(
		(['members', 'governance', 'invitations'] as const).flatMap((section) =>
			[401, 403, 404].map((status) => ({ section, status }))
		)
	)('purges $section page and sort variants after HTTP $status', async ({ section, status }) => {
		const client = queryClient();
		const related = [
			query(section),
			query(section, 'page=2'),
			query(section, 'direction=desc&sort=expires')
		];
		const unrelated = [
			query(section, '', 'workspace-2'),
			query(section === 'invitations' ? 'members' : 'invitations')
		];
		for (const options of [...related, ...unrelated])
			client.setQueryData(options.queryKey, snapshot);
		request.mockRejectedValueOnce(
			new ApiError(status, { code: 'permission_denied', message: 'Denied' })
		);
		await expect(fetch(client, section)).rejects.toMatchObject({ status });
		for (const options of related) {
			expect(client.getQueryData(options.queryKey)).toBeNull();
			expect(client.getQueryState(options.queryKey)?.dataUpdatedAt).toBe(0);
		}
		for (const options of unrelated)
			expect(client.getQueryData(options.queryKey)).toEqual(snapshot);
	});

	it('prevents an older invitation read from restoring revoked access', async () => {
		const client = queryClient();
		let complete!: (value: typeof snapshot) => void;
		const response = new Promise<typeof snapshot>((resolve) => {
			complete = resolve;
		});
		request.mockReturnValueOnce(response);
		const old = fetch(client, 'invitations', 'page=2').catch((error: unknown) => error);
		const signal = request.mock.calls[0][2].signal as AbortSignal;
		request.mockRejectedValueOnce(
			new ApiError(403, { code: 'permission_denied', message: 'Denied' })
		);
		await expect(fetch(client, 'invitations')).rejects.toMatchObject({ status: 403 });
		expect(signal.aborted).toBe(true);
		expect(isCancelledError(await old)).toBe(true);
		complete(snapshot);
		await response;
		const cached = client
			.getQueryCache()
			.findAll({ queryKey: workspaceKeys.invitations('workspace-1') });
		expect(cached.every((entry) => entry.state.data === null)).toBe(true);
	});

	it('keeps purged pages unavailable during offline navigation and subsequent failures', async () => {
		const client = queryClient();
		const current = query('governance');
		const other = query('governance', 'page=2');
		for (const options of [current, other]) client.setQueryData(options.queryKey, snapshot);
		request.mockRejectedValueOnce(
			new ApiError(403, { code: 'permission_denied', message: 'Denied' })
		);
		await expect(fetch(client, 'governance')).rejects.toMatchObject({ status: 403 });
		onlineManager.setOnline(false);
		const paused = fetch(client, 'governance', 'page=2').catch((error: unknown) => error);
		expect(client.getQueryState(other.queryKey)).toMatchObject({
			status: 'success',
			fetchStatus: 'paused',
			data: null
		});
		await client.cancelQueries({ queryKey: other.queryKey }, { revert: false });
		await paused;
		onlineManager.setOnline(true);
		request.mockRejectedValueOnce(new TypeError('Offline'));
		await expect(fetch(client, 'governance', 'page=2')).rejects.toThrow('Offline');
		expect(client.getQueryData(other.queryKey)).toBeNull();
	});
});
