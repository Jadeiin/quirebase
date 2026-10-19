import { isCancelledError, QueryClient } from '@tanstack/svelte-query';
import { expect, it } from 'vitest';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import { workspaceListQuery, workspaceOptionsQuery } from '#lib/workspaces/queries.js';
import { reconcileWorkspaceAccessLoss } from './access-loss.js';
import { receivedInvitationKeys } from './received-invitations.js';

it('evicts lost Workspace projections and cancels late reads while refreshing shared access', async () => {
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	try {
		const workspaceId = 'workspace-1';
		const scopedKeys = [
			workspaceKeys.root(workspaceId),
			[...workspaceKeys.root(workspaceId), 'dashboard'],
			workspaceKeys.item(workspaceId, 'item-1'),
			workspaceKeys.members(workspaceId),
			workspaceKeys.invitations(workspaceId)
		];
		for (const key of scopedKeys) client.setQueryData(key, { content: 'Old projection' });
		const refreshedKeys = [
			workspaceListQuery().queryKey,
			workspaceListQuery(25, 'Research').queryKey,
			workspaceOptionsQuery().queryKey,
			receivedInvitationKeys.list('user-1', 0, 1)
		];
		for (const key of refreshedKeys) client.setQueryData(key, { items: [], total: 0 });
		const otherWorkspace = workspaceKeys.root('workspace-2');
		client.setQueryData(otherWorkspace, { name: 'Archive' });
		const unrelatedKeys = [['session'], receivedInvitationKeys.list('user-2', 0, 1)];
		for (const key of unrelatedKeys) client.setQueryData(key, { unchanged: true });

		let complete!: (data: string) => void;
		let readSignal!: AbortSignal;
		const response = new Promise<string>((resolve) => {
			complete = resolve;
		});
		const pending = client
			.fetchQuery({
				queryKey: workspaceKeys.item(workspaceId, 'pending-item'),
				queryFn: ({ signal }) => {
					readSignal = signal;
					return response;
				}
			})
			.catch((error: unknown) => error);

		await reconcileWorkspaceAccessLoss(client, workspaceId, 'user-1');
		expect(readSignal.aborted).toBe(true);
		expect(isCancelledError(await pending)).toBe(true);
		complete('Late old projection');
		await response;
		expect(client.getQueryCache().findAll({ queryKey: workspaceKeys.root(workspaceId) })).toEqual(
			[]
		);
		for (const key of refreshedKeys) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
		expect(client.getQueryData(otherWorkspace)).toEqual({ name: 'Archive' });
		for (const key of unrelatedKeys) {
			expect(client.getQueryData(key)).toEqual({ unchanged: true });
			expect(client.getQueryState(key)?.isInvalidated).toBe(false);
		}
	} finally {
		client.clear();
	}
});
