import { afterEach, describe, expect, it, vi } from 'vitest';

import { waitForWorkflow } from './workflows';

afterEach(() => {
	vi.unstubAllGlobals();
});

describe('waitForWorkflow', () => {
	it('returns a terminal workflow through the typed status endpoint', async () => {
		const fetcher = vi.fn(
			async () =>
				new Response(JSON.stringify({ id: 'workflow-1', state: 'succeeded', error: null }))
		);
		vi.stubGlobal('fetch', fetcher);

		await expect(waitForWorkflow('workflow-1')).resolves.toMatchObject({ state: 'succeeded' });
		expect(fetcher).toHaveBeenCalledWith(
			'/api/v1/workflows/workflow-1',
			expect.objectContaining({ method: 'GET', credentials: 'same-origin' })
		);
	});

	it('surfaces a terminal workflow error', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(
				async () =>
					new Response(JSON.stringify({ id: 'workflow-1', state: 'failed', error: 'boom' }))
			)
		);

		await expect(waitForWorkflow('workflow-1')).rejects.toThrow('boom');
	});
});
