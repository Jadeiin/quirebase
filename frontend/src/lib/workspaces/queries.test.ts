import { QueryClient } from '@tanstack/svelte-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '#lib/api/client.js';
import { workspaceKeys } from './keys';
import { workspaceQuery } from './queries';

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('#lib/api/client.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.js')>()),
	createWorkspaceApi: () => ({ request })
}));

const clients: QueryClient[] = [];
const snapshot = { id: 'workspace-1', name: 'Research', current_role: 'admin' };
async function loadedWorkspace() {
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	clients.push(client);
	request.mockResolvedValueOnce(snapshot);
	await client.fetchQuery(workspaceQuery('workspace-1'));
	return client;
}

afterEach(() => {
	for (const client of clients.splice(0)) client.clear();
	request.mockReset();
});

describe('workspace context snapshots', () => {
	it.each([
		new TypeError('Offline'),
		new ApiError(503, { code: 'request_failed', message: 'Unavailable' })
	])('retains the loaded context after a temporary background failure', async (error) => {
		const client = await loadedWorkspace();
		request.mockRejectedValueOnce(error);
		await expect(client.fetchQuery(workspaceQuery('workspace-1'))).rejects.toBe(error);
		expect(client.getQueryState(workspaceKeys.root('workspace-1'))).toMatchObject({
			status: 'error',
			data: snapshot
		});
	});

	it.each([401, 403, 404])(
		'purges only the root snapshot after authoritative HTTP %s',
		async (status) => {
			const client = await loadedWorkspace();
			const memberOptionsKey = [...workspaceKeys.members('workspace-1'), 'options', ''];
			const child = { pages: [{ items: [], total: 0 }], pageParams: [0] };
			client.setQueryData(memberOptionsKey, child);
			client.setQueryData(workspaceKeys.root('workspace-2'), snapshot);
			request.mockRejectedValueOnce(
				new ApiError(status, { code: 'permission_denied', message: 'Denied' })
			);
			await expect(client.fetchQuery(workspaceQuery('workspace-1'))).rejects.toMatchObject({
				status
			});
			expect(client.getQueryState(workspaceKeys.root('workspace-1'))).toMatchObject({
				data: null,
				dataUpdatedAt: 0
			});
			expect(client.getQueryData(memberOptionsKey)).toEqual(child);
			expect(client.getQueryData(workspaceKeys.root('workspace-2'))).toEqual(snapshot);
		}
	);

	it('does not restore denied context on a later temporary failure', async () => {
		const client = await loadedWorkspace();
		request.mockRejectedValueOnce(
			new ApiError(403, { code: 'permission_denied', message: 'Denied' })
		);
		await expect(client.fetchQuery(workspaceQuery('workspace-1'))).rejects.toMatchObject({
			status: 403
		});
		request.mockRejectedValueOnce(new TypeError('Offline'));
		await expect(client.fetchQuery(workspaceQuery('workspace-1'))).rejects.toThrow('Offline');
		expect(client.getQueryData(workspaceKeys.root('workspace-1'))).toBeNull();
		request.mockResolvedValueOnce(snapshot);
		await expect(client.fetchQuery(workspaceQuery('workspace-1'))).resolves.toEqual(snapshot);
		expect(client.getQueryData(workspaceKeys.root('workspace-1'))).toEqual(snapshot);
	});
});
