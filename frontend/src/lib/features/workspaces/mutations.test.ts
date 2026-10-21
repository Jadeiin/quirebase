import { QueryClient, type QueryKey } from '@tanstack/svelte-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import {
	workspaceInvitationMutationOptions,
	workspaceInvitationRevokeMutationOptions,
	workspaceMemberMutationOptions
} from './mutations';

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('#lib/api/client.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.js')>()),
	createWorkspaceApi: () => ({ request })
}));

const clients: QueryClient[] = [];
function cachedClient() {
	const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
	clients.push(client);
	const keys: QueryKey[] = [
		workspaceKeys.list(),
		workspaceKeys.root('workspace-1'),
		[...workspaceKeys.members('workspace-1'), { page: 1 }],
		[...workspaceKeys.governanceMembers('workspace-1'), { role: 'viewer', page: 2 }],
		[...workspaceKeys.invitations('workspace-1'), { sort: 'created' }],
		[...workspaceKeys.invitations('workspace-1'), { sort: 'username', page: 3 }]
	];
	for (const key of [...keys, ['session']]) client.setQueryData(key, { previous: true });
	return { client, keys };
}

afterEach(() => {
	for (const client of clients.splice(0)) client.clear();
	request.mockReset();
});

describe('workspace command reconciliation', () => {
	it.each([false, true])(
		'refreshes membership and authority projections after command failure=%s',
		async (failed) => {
			const { client, keys } = cachedClient();
			if (failed) request.mockRejectedValueOnce(new TypeError('Response lost'));
			else request.mockResolvedValueOnce(undefined);
			const mutation = client
				.getMutationCache()
				.build(client, workspaceMemberMutationOptions('workspace-1', client));
			const result = mutation.execute({ action: 'terminate', membershipId: 'generation-2' });
			if (failed) await expect(result).rejects.toThrow('Response lost');
			else await result;
			for (const key of keys) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
			expect(client.getQueryState(['session'])?.isInvalidated).toBe(false);
			expect(request).toHaveBeenCalledTimes(1);
			expect(request.mock.calls[0][2].params.path.membership_id).toBe('generation-2');
		}
	);

	it.each([false, true])(
		'reconciles invitation creation without replay after response failure=%s',
		async (failed) => {
			const { client, keys } = cachedClient();
			if (failed) request.mockRejectedValueOnce(new TypeError('Response lost'));
			else request.mockResolvedValueOnce({ id: 'invite-1', token: 'one-time-secret' });
			const mutation = client
				.getMutationCache()
				.build(client, workspaceInvitationMutationOptions('workspace-1', client));
			const result = mutation.execute({ username: 'lee', role: 'editor' });
			if (failed) await expect(result).rejects.toThrow('Response lost');
			else await expect(result).resolves.toMatchObject({ token: 'one-time-secret' });
			for (const key of keys.filter(
				(key) => key[0] === 'workspaces' || key.includes('invitations')
			)) {
				expect(client.getQueryState(key)?.isInvalidated).toBe(true);
			}
			expect(request).toHaveBeenCalledTimes(1);
			for (const key of keys) expect(client.getQueryData(key)).not.toHaveProperty('token');
		}
	);

	it.each([false, true])(
		'refreshes invitation pages after revocation response failure=%s',
		async (failed) => {
			const { client, keys } = cachedClient();
			if (failed) request.mockRejectedValueOnce(new TypeError('Response lost'));
			else request.mockResolvedValueOnce(undefined);
			const mutation = client
				.getMutationCache()
				.build(client, workspaceInvitationRevokeMutationOptions('workspace-1', client));
			const result = mutation.execute('invite-1');
			if (failed) await expect(result).rejects.toThrow('Response lost');
			else await result;
			for (const key of keys) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
			expect(request).toHaveBeenCalledTimes(1);
			expect(request.mock.calls[0][2].params.path.invitation_id).toBe('invite-1');
		}
	);
});
