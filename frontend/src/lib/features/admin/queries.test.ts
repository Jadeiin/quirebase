import { CancelledError, onlineManager, QueryClient, type QueryKey } from '@tanstack/svelte-query';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiRequest } from '#lib/api/client.js';
import { readAdminFilters, type AdminFilters } from './list-state';
import {
	adminAuditQuery,
	adminInvitationsQuery,
	adminKeys,
	adminMaintenanceQuery,
	adminOverviewQuery,
	adminSettingsQuery,
	adminUsersQuery,
	adminWorkspaceQuery,
	adminWorkspaceOptionsQuery,
	adminWorkspacesQuery,
	adminWorkflowDetailQuery,
	adminWorkflowsQuery
} from './queries';
import { adminReadState } from './read-state';

vi.mock('#lib/api/client.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.js')>()),
	apiRequest: vi.fn()
}));

const request = vi.mocked(apiRequest);
const sections = [
	'overview',
	'users',
	'invitations',
	'workspaces',
	'audit',
	'workflows',
	'settings',
	'maintenance'
] as const;
type ReadSection = (typeof sections)[number];
const snapshot = { items: [], total: 0, limit: 20, offset: 0 };
const clients: QueryClient[] = [];

function queryClient() {
	const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	client.mount();
	clients.push(client);
	return client;
}

function filters(section: ReadSection, parameters = '') {
	return readAdminFilters(new URLSearchParams(parameters), section);
}

function fetchSection(client: QueryClient, section: ReadSection, state: AdminFilters) {
	switch (section) {
		case 'overview':
			return client.fetchQuery(adminOverviewQuery(state));
		case 'users':
			return client.fetchQuery(adminUsersQuery(state));
		case 'invitations':
			return client.fetchQuery(adminInvitationsQuery(state));
		case 'workspaces':
			return client.fetchQuery(adminWorkspacesQuery(state));
		case 'audit':
			return client.fetchQuery(adminAuditQuery(state));
		case 'workflows':
			return client.fetchQuery(adminWorkflowsQuery(state));
		case 'settings':
			return client.fetchQuery(adminSettingsQuery(state));
		case 'maintenance':
			return client.fetchQuery(adminMaintenanceQuery(state));
	}
}

afterEach(() => {
	for (const client of clients.splice(0)) {
		client.unmount();
		client.clear();
	}
	onlineManager.setOnline(true);
	request.mockReset();
});

describe('administration cache availability', () => {
	it.each(sections.flatMap((section) => [401, 403, 404].map((status) => ({ section, status }))))(
		'purges all cached $section pages and sorts after HTTP $status',
		async ({ section, status }) => {
			const client = queryClient();
			const current = filters(section);
			const related: QueryKey[] = [
				current,
				filters(section, 'page=2'),
				filters(section, 'sort=created&direction=asc')
			].map((state) => adminKeys.section(section, state));
			if (section === 'workspaces') {
				related.push(adminKeys.workspace('workspace-1'), adminKeys.workspaceOptions('target'));
			}
			if (section === 'workflows') {
				related.push(
					adminKeys.workflowDetail('workflow-1'),
					adminKeys.workflowDetail('workflow-2')
				);
			}
			const otherSection = section === 'users' ? 'invitations' : 'users';
			const unrelated = adminKeys.section(otherSection, filters(otherSection));
			for (const key of [...related, unrelated]) client.setQueryData(key, snapshot);
			const error = new ApiError(status, { code: 'not_available', message: 'Unavailable' });
			request.mockRejectedValueOnce(error);

			await expect(fetchSection(client, section, current)).rejects.toBe(error);

			for (const key of related) {
				expect(client.getQueryData(key)).toBeNull();
				expect(client.getQueryState(key)?.dataUpdatedAt).toBe(0);
			}
			expect(client.getQueryData(unrelated)).toEqual(snapshot);
		}
	);

	it.each(sections)(
		'retains cached %s content after a temporary refresh failure',
		async (section) => {
			const client = queryClient();
			const current = filters(section);
			const currentKey = adminKeys.section(section, current);
			const otherPage = adminKeys.section(section, filters(section, 'page=2'));
			for (const key of [currentKey, otherPage]) client.setQueryData(key, snapshot);
			const previousUpdate = client.getQueryState(currentKey)?.dataUpdatedAt;
			const error = new ApiError(503, { code: 'request_failed', message: 'Temporary outage' });
			request.mockRejectedValueOnce(error);

			await expect(fetchSection(client, section, current)).rejects.toBe(error);

			for (const key of [currentKey, otherPage]) expect(client.getQueryData(key)).toEqual(snapshot);
			expect(client.getQueryState(currentKey)?.dataUpdatedAt).toBe(previousUpdate);
			expect(adminReadState({ loading: false, failed: true, available: true, error })).toBe(
				'stale'
			);
		}
	);

	it.each(sections)(
		'does not restore denied %s content after a transient failure',
		async (section) => {
			const client = queryClient();
			const current = filters(section);
			const key = adminKeys.section(section, current);
			client.setQueryData(key, snapshot);
			request.mockRejectedValueOnce(new ApiError(403, { code: 'forbidden', message: 'Denied' }));
			await expect(fetchSection(client, section, current)).rejects.toMatchObject({ status: 403 });
			request.mockRejectedValueOnce(
				new ApiError(503, { code: 'request_failed', message: 'Temporary outage' })
			);
			await expect(fetchSection(client, section, current)).rejects.toMatchObject({ status: 503 });
			const state = client.getQueryState(key)!;
			expect(state.data).toBeNull();
			expect(
				adminReadState({
					loading: state.status === 'pending',
					failed: state.status === 'error',
					available: state.data != null,
					error: state.error
				})
			).toBe('unavailable');
		}
	);

	it.each(sections)(
		'keeps denied %s content unavailable while offline refetch is paused',
		async (section) => {
			const client = queryClient();
			const current = filters(section);
			const next = filters(section, 'page=2');
			const nextKey = adminKeys.section(section, next);
			client.setQueryData(adminKeys.section(section, current), snapshot);
			client.setQueryData(nextKey, snapshot);
			request.mockRejectedValueOnce(new ApiError(403, { code: 'forbidden', message: 'Denied' }));
			await expect(fetchSection(client, section, current)).rejects.toMatchObject({ status: 403 });

			onlineManager.setOnline(false);
			request.mockResolvedValueOnce(snapshot);
			const pending = fetchSection(client, section, next);
			try {
				const state = client.getQueryState(nextKey)!;
				expect(state.status).toBe('success');
				expect(state.fetchStatus).toBe('paused');
				expect(
					adminReadState({
						loading: state.status === 'pending',
						failed: state.status === 'error',
						available: state.data != null,
						error: state.error
					})
				).toBe('unavailable');
			} finally {
				onlineManager.setOnline(true);
				await pending;
			}
			expect(client.getQueryData(nextKey)).toEqual(snapshot);
		}
	);

	it('cancels older reads in the denied section before they can refill purged snapshots', async () => {
		const client = queryClient();
		const current = filters('users');
		const next = filters('users', 'page=2&sort=created&direction=desc');
		const unrelated = filters('invitations');
		const currentKey = adminKeys.section('users', current);
		const nextKey = adminKeys.section('users', next);
		const unrelatedKey = adminKeys.section('invitations', unrelated);
		for (const key of [currentKey, nextKey, unrelatedKey]) client.setQueryData(key, snapshot);
		let releaseNext!: (value: typeof snapshot) => void;
		let releaseUnrelated!: (value: typeof snapshot) => void;
		request.mockReturnValueOnce(
			new Promise((resolve) => {
				releaseNext = resolve;
			})
		);
		request.mockReturnValueOnce(
			new Promise((resolve) => {
				releaseUnrelated = resolve;
			})
		);
		request.mockRejectedValueOnce(new ApiError(403, { code: 'forbidden', message: 'Denied' }));
		const olderRead = fetchSection(client, 'users', next).catch((error: unknown) => error);
		const unrelatedRead = fetchSection(client, 'invitations', unrelated);
		try {
			await expect(fetchSection(client, 'users', current)).rejects.toMatchObject({ status: 403 });
			expect(request.mock.calls[0][2]?.signal?.aborted).toBe(true);
			expect(request.mock.calls[1][2]?.signal?.aborted).toBe(false);
		} finally {
			releaseNext(snapshot);
			releaseUnrelated(snapshot);
		}
		expect(await olderRead).toBeInstanceOf(CancelledError);
		await unrelatedRead;
		expect(client.getQueryData(currentKey)).toBeNull();
		expect(client.getQueryData(nextKey)).toBeNull();
		expect(client.getQueryData(unrelatedKey)).toEqual(snapshot);
	});
});

describe('workflow detail cache availability', () => {
	const detailSnapshot = (id: string) => ({
		id,
		name: 'operations.check_objects',
		state: 'succeeded',
		raw_status: 'SUCCESS',
		output: { evidence: `private output for ${id}` }
	});

	it.each([401, 403])(
		'clears workflow lists and details and cancels older reads after detail HTTP %i',
		async (status) => {
			const client = queryClient();
			const current = filters('workflows');
			const listKey = adminKeys.section('workflows', current);
			const deniedKey = adminKeys.workflowDetail('workflow-1');
			const otherDetailKey = adminKeys.workflowDetail('workflow-2');
			const unrelatedKey = adminKeys.section('users', filters('users'));
			client.setQueryData(listKey, snapshot);
			client.setQueryData(deniedKey, detailSnapshot('workflow-1'));
			client.setQueryData(otherDetailKey, detailSnapshot('workflow-2'));
			client.setQueryData(unrelatedKey, snapshot);
			let releaseDetail!: (value: ReturnType<typeof detailSnapshot>) => void;
			let releaseList!: (value: typeof snapshot) => void;
			request.mockReturnValueOnce(
				new Promise((resolve) => {
					releaseDetail = resolve;
				})
			);
			request.mockReturnValueOnce(
				new Promise((resolve) => {
					releaseList = resolve;
				})
			);
			const error = new ApiError(status, { code: 'not_available', message: 'Unavailable' });
			request.mockRejectedValueOnce(error);
			const olderDetail = client
				.fetchQuery(adminWorkflowDetailQuery('workflow-2'))
				.catch((failure: unknown) => failure);
			const olderList = fetchSection(client, 'workflows', current).catch(
				(failure: unknown) => failure
			);
			try {
				await expect(client.fetchQuery(adminWorkflowDetailQuery('workflow-1'))).rejects.toBe(error);
				for (const key of [listKey, deniedKey, otherDetailKey]) {
					expect(client.getQueryData(key)).toBeNull();
					expect(client.getQueryState(key)?.dataUpdatedAt).toBe(0);
				}
				expect(client.getQueryData(unrelatedKey)).toEqual(snapshot);
				expect(request.mock.calls[0][2]?.signal?.aborted).toBe(true);
				expect(request.mock.calls[1][2]?.signal?.aborted).toBe(true);
			} finally {
				releaseDetail(detailSnapshot('workflow-2'));
				releaseList(snapshot);
			}
			expect(await olderDetail).toBeInstanceOf(CancelledError);
			expect(await olderList).toBeInstanceOf(CancelledError);
			expect(client.getQueryData(listKey)).toBeNull();
			expect(client.getQueryData(otherDetailKey)).toBeNull();
		}
	);

	it.each(['list', 'detail'] as const)(
		'cannot restore old output from a paused detail read after %s denial',
		async (source) => {
			const client = queryClient();
			const current = filters('workflows');
			client.setQueryData(adminKeys.section('workflows', current), snapshot);
			client.setQueryData(adminKeys.workflowDetail('workflow-1'), detailSnapshot('workflow-1'));
			client.setQueryData(adminKeys.workflowDetail('workflow-2'), detailSnapshot('workflow-2'));
			request.mockRejectedValueOnce(
				new ApiError(403, { code: 'permission_denied', message: 'Denied' })
			);
			const denied =
				source === 'list'
					? fetchSection(client, 'workflows', current)
					: client.fetchQuery(adminWorkflowDetailQuery('workflow-2'));
			await expect(denied).rejects.toMatchObject({ status: 403 });

			onlineManager.setOnline(false);
			request.mockResolvedValueOnce(detailSnapshot('workflow-1'));
			const pending = client.fetchQuery(adminWorkflowDetailQuery('workflow-1'));
			try {
				const state = client.getQueryState(adminKeys.workflowDetail('workflow-1'))!;
				expect(state.status).toBe('success');
				expect(state.fetchStatus).toBe('paused');
				expect(state.data).toBeNull();
			} finally {
				onlineManager.setOnline(true);
				await pending;
			}
			expect(client.getQueryData(adminKeys.workflowDetail('workflow-1'))).toEqual(
				detailSnapshot('workflow-1')
			);
		}
	);

	it('purges only the missing detail on HTTP 404 without cancelling other workflow reads', async () => {
		const client = queryClient();
		const listKey = adminKeys.section('workflows', filters('workflows'));
		const missingKey = adminKeys.workflowDetail('workflow-1');
		const otherKey = adminKeys.workflowDetail('workflow-2');
		client.setQueryData(listKey, snapshot);
		client.setQueryData(missingKey, detailSnapshot('workflow-1'));
		client.setQueryData(otherKey, detailSnapshot('workflow-2'));
		let release!: (value: ReturnType<typeof detailSnapshot>) => void;
		request.mockReturnValueOnce(
			new Promise((resolve) => {
				release = resolve;
			})
		);
		request.mockRejectedValueOnce(
			new ApiError(404, { code: 'not_found', message: 'Workflow not found' })
		);
		const pending = client.fetchQuery(adminWorkflowDetailQuery('workflow-2'));
		try {
			await expect(client.fetchQuery(adminWorkflowDetailQuery('workflow-1'))).rejects.toMatchObject(
				{
					status: 404
				}
			);
			expect(client.getQueryData(missingKey)).toBeNull();
			expect(client.getQueryState(missingKey)?.dataUpdatedAt).toBe(0);
			expect(client.getQueryData(listKey)).toEqual(snapshot);
			expect(client.getQueryData(otherKey)).toEqual(detailSnapshot('workflow-2'));
			expect(request.mock.calls[0][2]?.signal?.aborted).toBe(false);
		} finally {
			release(detailSnapshot('workflow-2'));
			await pending;
		}
	});

	it('retains cached output after a transient detail refresh failure', async () => {
		const client = queryClient();
		const key = adminKeys.workflowDetail('workflow-1');
		const detail = detailSnapshot('workflow-1');
		client.setQueryData(key, detail);
		const error = new ApiError(503, { code: 'request_failed', message: 'Temporary outage' });
		request.mockRejectedValueOnce(error);
		await expect(
			client.fetchQuery({ ...adminWorkflowDetailQuery('workflow-1'), retry: false })
		).rejects.toBe(error);
		expect(client.getQueryData(key)).toEqual(detail);
	});
});

describe('administration list requests', () => {
	it('sends Workspace governance filters and sorting with bounded pagination', async () => {
		request.mockResolvedValueOnce(snapshot);
		await fetchSection(
			queryClient(),
			'workspaces',
			filters(
				'workspaces',
				'q=owner&state=archived&frozen=false&owner_active=false&sort=owner&direction=desc&page=3&page_size=10'
			)
		);
		expect(request).toHaveBeenCalledWith('GET', '/admin/workspaces', {
			params: {
				query: {
					search: 'owner',
					state: 'archived',
					frozen: false,
					owner_active: false,
					sort: 'owner',
					direction: 'desc',
					limit: 10,
					offset: 20
				}
			},
			signal: expect.any(AbortSignal)
		});
	});

	it('looks up inspection targets independently of filtered governance pages', async () => {
		const client = queryClient();
		request.mockResolvedValue(snapshot);
		await fetchSection(
			client,
			'workspaces',
			filters('workspaces', 'state=archived&page=3&frozen=true')
		);
		await client.fetchQuery(adminWorkspaceOptionsQuery('different target'));
		expect(request).toHaveBeenLastCalledWith('GET', '/admin/workspaces', {
			params: {
				query: { search: 'different target', limit: 20, offset: 0, sort: 'name', direction: 'asc' }
			},
			signal: expect.any(AbortSignal)
		});
		await client.fetchQuery(adminWorkspaceQuery('workspace-1'));
		expect(request).toHaveBeenLastCalledWith('GET', '/admin/workspaces/{workspace_id}', {
			params: { path: { workspace_id: 'workspace-1' } },
			signal: expect.any(AbortSignal)
		});
	});

	it('sends User search, status, server sorting and page-size offset', async () => {
		request.mockResolvedValueOnce(snapshot);
		await fetchSection(
			queryClient(),
			'users',
			filters(
				'users',
				'q=alice&role=member&active=false&sort=created&direction=desc&page=3&page_size=10'
			)
		);
		expect(request).toHaveBeenCalledWith('GET', '/admin/users', {
			params: {
				query: {
					search: 'alice',
					role: 'member',
					active: false,
					sort: 'created',
					direction: 'desc',
					limit: 10,
					offset: 20
				}
			},
			signal: expect.any(AbortSignal)
		});
	});

	it('combines Invitation state and role with search and expiry ordering', async () => {
		request.mockResolvedValueOnce(snapshot);
		await fetchSection(
			queryClient(),
			'invitations',
			filters(
				'invitations',
				'q=alice&role=administrator&state=pending&sort=expires&direction=asc&page=2&page_size=50'
			)
		);
		expect(request).toHaveBeenCalledWith('GET', '/admin/invitations', {
			params: {
				query: {
					search: 'alice',
					role: 'administrator',
					state: 'pending',
					sort: 'expires',
					direction: 'asc',
					limit: 50,
					offset: 50
				}
			},
			signal: expect.any(AbortSignal)
		});
	});

	it('sends Audit chronology alongside exact action and target filters', async () => {
		request.mockResolvedValueOnce(snapshot);
		await fetchSection(
			queryClient(),
			'audit',
			filters(
				'audit',
				'q=alice&action=admin.user.create&target_type=user&direction=asc&page=2&page_size=100'
			)
		);
		expect(request).toHaveBeenCalledWith('GET', '/admin/audit', {
			params: {
				query: {
					search: 'alice',
					action: 'admin.user.create',
					target_type: 'user',
					direction: 'asc',
					limit: 100,
					offset: 100
				}
			},
			signal: expect.any(AbortSignal)
		});
	});

	it('sends Workflow name and state to server filtering with oldest-first pagination', async () => {
		request.mockResolvedValueOnce(snapshot);
		await fetchSection(
			queryClient(),
			'workflows',
			filters(
				'workflows',
				'name=operations.check_objects&state=failed&direction=asc&page=3&page_size=25'
			)
		);
		expect(request).toHaveBeenCalledWith('GET', '/admin/workflows', {
			params: {
				query: {
					name: 'operations.check_objects',
					state: 'failed',
					direction: 'asc',
					limit: 25,
					offset: 50
				}
			},
			signal: expect.any(AbortSignal)
		});
	});

	it.each(sections)('refetches a successful %s cache on revisit', async (section) => {
		request.mockResolvedValue(snapshot);
		const client = queryClient();
		const current = filters(section);
		await fetchSection(client, section, current);
		await fetchSection(client, section, current);
		expect(request).toHaveBeenCalledTimes(2);
	});
});
