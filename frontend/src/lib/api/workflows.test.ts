// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';

import { waitForWorkflow } from './workflows';

describe('waitForWorkflow', () => {
	it('returns a terminal workflow through the typed status endpoint', async () => {
		const fetcher = vi.fn<(input: Request) => Promise<Response>>(
			async () =>
				new Response(JSON.stringify({ id: 'workflow-1', state: 'succeeded', error: null }))
		);
		vi.stubGlobal('fetch', fetcher);

		await expect(waitForWorkflow('workflow-1')).resolves.toMatchObject({ state: 'succeeded' });
		expect(fetcher).toHaveBeenCalledTimes(1);
		const request = fetcher.mock.calls[0][0];
		expect(new URL(request.url).pathname).toBe('/api/v1/workflows/workflow-1');
		expect(request.method).toBe('GET');
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
