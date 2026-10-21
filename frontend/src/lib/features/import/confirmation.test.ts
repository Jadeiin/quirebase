// @vitest-environment jsdom
import { CancelledError, QueryClient, QueryObserver } from '@tanstack/svelte-query';
import { afterEach, expect, it, vi } from 'vitest';
import { confirmImportBatch } from './confirmation.js';
import { deleteImportBatch } from './mutations.js';
import {
	importBatchQuery,
	importBatchResponseWriter,
	readImportBatch,
	type ImportBatch
} from './queries.js';

const ready: ImportBatch = {
	id: 'batch-1',
	file_format: 'metadata',
	status: 'ready',
	workflow_id: null,
	records: [{ metadata: { id: 'urn:uuid:source-1', type: 'Book', title: 'A record' } }],
	errors: [],
	committed_item_ids: [],
	created_at: '2026-10-21T00:00:00Z'
};
const committed: ImportBatch = {
	...ready,
	status: 'committed',
	records: [],
	committed_item_ids: ['item-1']
};
const clients: QueryClient[] = [];
function queryClient() {
	const client = new QueryClient();
	clients.push(client);
	return client;
}
afterEach(() => {
	for (const client of clients.splice(0)) client.clear();
	vi.unstubAllGlobals();
});

it('caches the authoritative confirmation receipt without another read', async () => {
	const requests: Request[] = [];
	const receipt: ImportBatch = {
		...committed,
		file_format: 'bibtex',
		created_at: '2026-10-20T12:30:00Z'
	};
	vi.stubGlobal('fetch', async (request: Request) => {
		requests.push(request);
		return new Response(JSON.stringify(receipt));
	});
	const client = queryClient();
	const source: ImportBatch = {
		...ready,
		workflow_id: 'previous-preparation',
		errors: [{ message: 'Source warning', severity: 'warning' }]
	};
	client.setQueryData(importBatchQuery('workspace-1', ready.id).queryKey, source);
	const result = await confirmImportBatch(client, 'workspace-1', ready.id);
	expect(result).toEqual({ status: 'committed', batch: receipt });
	expect(requests.map((request) => request.method)).toEqual(['POST']);
	expect(client.getQueryData(importBatchQuery('workspace-1', ready.id).queryKey)).toEqual(receipt);
});

it('keeps the committed receipt when an earlier creation response arrives afterward', async () => {
	vi.stubGlobal('fetch', async () => new Response(JSON.stringify(committed)));
	const client = queryClient();
	await confirmImportBatch(client, 'workspace-1', ready.id);
	// A source command learns its new batch ID only when its delayed response arrives.
	const acceptCreated = await importBatchResponseWriter(client, 'workspace-1');
	expect(acceptCreated(ready)).toBe(false);
	expect(client.getQueryData(importBatchQuery('workspace-1', ready.id).queryKey)).toEqual(
		committed
	);
});

it.each([false, true])(
	'does not restore a deleted receipt when confirmation arrives late (lost deletion response: %s)',
	async (lostResponse) => {
		const response = Promise.withResolvers<Response>();
		const methods: string[] = [];
		vi.stubGlobal('fetch', async (request: Request) => {
			methods.push(request.method);
			if (request.method === 'POST') return response.promise;
			if (request.method === 'DELETE') {
				if (lostResponse) throw new TypeError('Deletion response lost');
				return new Response(null, { status: 204 });
			}
			return new Response(
				JSON.stringify({ code: 'import_batch_unavailable', message: 'Unavailable' }),
				{ status: 404 }
			);
		});
		const client = queryClient();
		const preview = importBatchQuery('workspace-1', ready.id);
		client.setQueryData(preview.queryKey, ready);
		const confirmation = confirmImportBatch(client, 'workspace-1', ready.id);
		await vi.waitFor(() => expect(methods).toEqual(['POST']));
		await deleteImportBatch(client, 'workspace-1', ready.id);
		response.resolve(new Response(JSON.stringify(committed)));

		expect(await confirmation).toEqual({ status: 'committed', batch: committed });
		expect(client.getQueryData(preview.queryKey)).toBeNull();
		expect(client.getQueryState(preview.queryKey)?.dataUpdatedAt).toBe(0);
		expect(methods).toEqual(lostResponse ? ['POST', 'DELETE', 'GET'] : ['POST', 'DELETE']);
	}
);

it('does not refill a retired cache lifetime when confirmation arrives late', async () => {
	const response = Promise.withResolvers<Response>();
	vi.stubGlobal('fetch', async () => response.promise);
	const client = queryClient();
	const preview = importBatchQuery('workspace-1', ready.id);
	client.setQueryData(preview.queryKey, ready);
	const confirmation = confirmImportBatch(client, 'workspace-1', ready.id);
	client.removeQueries({ queryKey: preview.queryKey, exact: true });
	// A new route may recreate the key after Workspace or account cache eviction.
	const refreshed: ImportBatch = { ...ready, status: 'failed' };
	client.setQueryData(preview.queryKey, refreshed);
	response.resolve(new Response(JSON.stringify(committed)));

	expect(await confirmation).toEqual({ status: 'committed', batch: committed });
	expect(client.getQueryData(preview.queryKey)).toEqual(refreshed);
});

it('preserves a later deletion recovery read when confirmation arrives before its result', async () => {
	const commitResponse = Promise.withResolvers<Response>();
	const recoveryResponse = Promise.withResolvers<Response>();
	let submitted = false;
	let recovery: Request | undefined;
	vi.stubGlobal('fetch', async (request: Request) => {
		if (request.method === 'POST') {
			submitted = true;
			return commitResponse.promise;
		}
		if (request.method === 'DELETE') throw new TypeError('Deletion response lost');
		recovery = request;
		return recoveryResponse.promise;
	});
	const client = queryClient();
	const preview = importBatchQuery('workspace-1', ready.id);
	client.setQueryData(preview.queryKey, ready);
	const confirmation = confirmImportBatch(client, 'workspace-1', ready.id);
	await vi.waitFor(() => expect(submitted).toBe(true));
	const deletion = deleteImportBatch(client, 'workspace-1', ready.id).catch(
		(reason: unknown) => reason
	);
	try {
		await vi.waitFor(() => expect(recovery).toBeDefined());
		commitResponse.resolve(new Response(JSON.stringify(committed)));
		expect(await confirmation).toEqual({ status: 'committed', batch: committed });
		expect(recovery?.signal.aborted).toBe(false);
		recoveryResponse.resolve(
			new Response(JSON.stringify({ code: 'import_batch_unavailable', message: 'Unavailable' }), {
				status: 404
			})
		);
		expect(await deletion).toBeUndefined();
		expect(client.getQueryData(preview.queryKey)).toBeNull();
		expect(client.getQueryState(preview.queryKey)?.dataUpdatedAt).toBe(0);
	} finally {
		commitResponse.resolve(new Response(JSON.stringify(committed)));
		recoveryResponse.resolve(new Response(null, { status: 404 }));
	}
});

it('keeps the authoritative receipt when an overlapping read returns its older ready snapshot', async () => {
	const commitResponse = Promise.withResolvers<Response>();
	const readResponse = Promise.withResolvers<Response>();
	const methods: string[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		methods.push(request.method);
		return request.method === 'POST' ? commitResponse.promise : readResponse.promise;
	});
	const client = queryClient();
	const preview = importBatchQuery('workspace-1', ready.id);
	client.setQueryData(preview.queryKey, ready);
	const confirmation = confirmImportBatch(client, 'workspace-1', ready.id);
	await vi.waitFor(() => expect(methods).toEqual(['POST']));
	const reread = readImportBatch(client, 'workspace-1', ready.id);
	try {
		await vi.waitFor(() => expect(methods).toEqual(['POST', 'GET']));
		commitResponse.resolve(new Response(JSON.stringify(committed)));
		expect(await confirmation).toEqual({ status: 'committed', batch: committed });
		readResponse.resolve(new Response(JSON.stringify(ready)));
		expect(await reread).toEqual(committed);
		expect(client.getQueryData(preview.queryKey)).toEqual(committed);
	} finally {
		commitResponse.resolve(new Response(JSON.stringify(committed)));
		readResponse.resolve(new Response(JSON.stringify(ready)));
	}
});

it('recovers a committed batch after a lost response without resending the confirmation', async () => {
	const methods: string[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		methods.push(request.method);
		if (request.method === 'POST') throw new TypeError('response lost');
		return new Response(JSON.stringify(committed));
	});
	const client = queryClient();
	client.setQueryData(importBatchQuery('workspace-1', ready.id).queryKey, ready);
	expect(await confirmImportBatch(client, 'workspace-1', ready.id)).toEqual({
		status: 'committed',
		batch: committed
	});
	expect(methods).toEqual(['POST', 'GET']);
});

it.each(['commit', 'delete'] as const)(
	'recovers a lost %s response after its last preview observer unmounts',
	async (command) => {
		const response = Promise.withResolvers<Response>();
		const methods: string[] = [];
		let recovery: Request | undefined;
		vi.stubGlobal('fetch', async (request: Request) => {
			methods.push(request.method);
			if (request.method !== 'GET') throw new TypeError('Response lost');
			recovery = request;
			request.signal.addEventListener('abort', () => response.reject(request.signal.reason), {
				once: true
			});
			return response.promise;
		});
		const client = queryClient();
		const preview = importBatchQuery('workspace-1', ready.id);
		client.setQueryData(preview.queryKey, command === 'commit' ? ready : committed);
		const observer = new QueryObserver(client, { ...preview, staleTime: Infinity });
		const unsubscribe = observer.subscribe(() => {});
		const operation =
			command === 'commit'
				? confirmImportBatch(client, 'workspace-1', ready.id)
				: deleteImportBatch(client, 'workspace-1', ready.id);
		const settled = operation.catch((reason: unknown) => reason);
		const result = () =>
			command === 'commit'
				? new Response(JSON.stringify(committed))
				: new Response(
						JSON.stringify({ code: 'import_batch_unavailable', message: 'Unavailable' }),
						{ status: 404 }
					);
		try {
			await vi.waitFor(() => expect(recovery).toBeDefined());
			unsubscribe();
			expect(recovery?.signal.aborted).toBe(false);
			response.resolve(result());
			if (command === 'commit') {
				expect(await settled).toEqual({ status: 'committed', batch: committed });
				expect(client.getQueryData(preview.queryKey)).toEqual(committed);
			} else {
				expect(await settled).toBeUndefined();
				expect(client.getQueryData(preview.queryKey)).toBeNull();
				expect(client.getQueryState(preview.queryKey)?.dataUpdatedAt).toBe(0);
			}
			expect(methods).toEqual([command === 'commit' ? 'POST' : 'DELETE', 'GET']);
		} finally {
			unsubscribe();
			response.resolve(result());
			await settled;
		}
	}
);

it('keeps an uncommitted authoritative preview available for an explicit retry', async () => {
	const failure = new TypeError('confirmation failed');
	vi.stubGlobal('fetch', async (request: Request) => {
		if (request.method === 'POST') throw failure;
		return new Response(JSON.stringify(ready));
	});
	expect(await confirmImportBatch(queryClient(), 'workspace-1', ready.id)).toEqual({
		status: 'uncommitted',
		batch: ready,
		error: failure
	});
});

it('keeps an unknown outcome distinct and checks it later using only a fresh read', async () => {
	let online = false;
	const methods: string[] = [];
	vi.stubGlobal('fetch', async (request: Request) => {
		methods.push(request.method);
		if (!online) throw new TypeError('offline');
		return new Response(JSON.stringify(committed));
	});
	const client = queryClient();
	const result = await confirmImportBatch(client, 'workspace-1', ready.id);
	expect(result.status).toBe('unknown');
	online = true;
	expect(await readImportBatch(client, 'workspace-1', ready.id)).toEqual(committed);
	expect(methods).toEqual(['POST', 'GET', 'GET']);
});

it.each([ready, committed])(
	'recovers a previously unavailable batch with a fresh $status read',
	async (batch) => {
		const client = queryClient();
		const preview = importBatchQuery('workspace-1', ready.id);
		client.setQueryData(preview.queryKey, null, { updatedAt: 0 });
		const methods: string[] = [];
		vi.stubGlobal('fetch', async (request: Request) => {
			methods.push(request.method);
			return new Response(JSON.stringify(batch));
		});

		expect(await readImportBatch(client, 'workspace-1', ready.id)).toEqual(batch);
		expect(client.getQueryData(preview.queryKey)).toEqual(batch);
		expect(methods).toEqual(['GET']);
	}
);

it('keeps a batch unavailable when it is retired again during its recovery read', async () => {
	const client = queryClient();
	const preview = importBatchQuery('workspace-1', ready.id);
	client.setQueryData(preview.queryKey, null, { updatedAt: 0 });
	const response = Promise.withResolvers<Response>();
	let requested = false;
	vi.stubGlobal('fetch', async () => {
		requested = true;
		return response.promise;
	});
	const recovery = readImportBatch(client, 'workspace-1', ready.id).catch(
		(reason: unknown) => reason
	);
	await vi.waitFor(() => expect(requested).toBe(true));
	// A second retirement has the same null value but belongs to the newer operation.
	client.setQueryData(preview.queryKey, null, { updatedAt: 0 });
	response.resolve(new Response(JSON.stringify(committed)));

	expect(await recovery).toBeInstanceOf(Error);
	expect(client.getQueryData(preview.queryKey)).toBeNull();
	expect(client.getQueryState(preview.queryKey)?.dataUpdatedAt).toBe(0);
});

it.each(['removed', 'replaced', 'replaced with late denial'])(
	'does not refill or clear a %s cache lifetime after a recovery read',
	async (lifetime) => {
		const client = queryClient();
		const preview = importBatchQuery('workspace-1', ready.id);
		client.setQueryData(preview.queryKey, ready);
		const response = Promise.withResolvers<Response>();
		let requested = false;
		vi.stubGlobal('fetch', async () => {
			requested = true;
			return response.promise;
		});
		const recovery = readImportBatch(client, 'workspace-1', ready.id).catch(
			(reason: unknown) => reason
		);
		await vi.waitFor(() => expect(requested).toBe(true));
		client.removeQueries({ queryKey: preview.queryKey, exact: true });
		const replacement: ImportBatch = { ...ready, status: 'failed' };
		if (lifetime !== 'removed') client.setQueryData(preview.queryKey, replacement);
		const denied = lifetime === 'replaced with late denial';
		response.resolve(
			denied
				? new Response(
						JSON.stringify({ code: 'import_batch_unavailable', message: 'Unavailable' }),
						{ status: 404 }
					)
				: new Response(JSON.stringify(committed))
		);

		const result = await recovery;
		if (denied) expect(result).toMatchObject({ code: 'import_batch_unavailable' });
		else expect(result).toEqual(lifetime === 'removed' ? committed : replacement);
		expect(client.getQueryData(preview.queryKey)).toEqual(
			lifetime === 'removed' ? undefined : replacement
		);
	}
);

it('cancels a read started before confirmation before checking its outcome', async () => {
	let reads = 0;
	let firstRequest: Request | undefined;
	vi.stubGlobal('fetch', async (request: Request) => {
		reads++;
		if (reads > 1) return new Response(JSON.stringify(committed));
		firstRequest = request;
		return new Promise<Response>((_, reject) => {
			request.signal.addEventListener('abort', () => reject(request.signal.reason), { once: true });
		});
	});
	const client = queryClient();
	const earlier = client.fetchQuery(importBatchQuery('workspace-1', ready.id));
	const earlierOutcome = earlier.catch((reason: unknown) => reason);
	await vi.waitFor(() => expect(firstRequest).toBeDefined());
	expect(await readImportBatch(client, 'workspace-1', ready.id)).toEqual(committed);
	expect(firstRequest?.signal.aborted).toBe(true);
	expect(await earlierOutcome).toBeInstanceOf(CancelledError);
	expect(reads).toBe(2);
});

it('clears denied previews without changing other batches or Workspaces', async () => {
	const client = queryClient();
	const denied = importBatchQuery('workspace-1', ready.id);
	const otherBatch = importBatchQuery('workspace-1', 'batch-2');
	const otherWorkspace = importBatchQuery('workspace-2', ready.id);
	for (const options of [denied, otherBatch, otherWorkspace])
		client.setQueryData(options.queryKey, ready);
	vi.stubGlobal(
		'fetch',
		async () =>
			new Response(JSON.stringify({ code: 'not_found', message: 'Unavailable' }), { status: 404 })
	);
	await expect(client.fetchQuery(denied)).rejects.toMatchObject({ status: 404 });
	expect(client.getQueryData(denied.queryKey)).toBeNull();
	expect(client.getQueryData(otherBatch.queryKey)).toEqual(ready);
	expect(client.getQueryData(otherWorkspace.queryKey)).toEqual(ready);
});
