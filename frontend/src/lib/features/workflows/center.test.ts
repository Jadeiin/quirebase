import { afterEach, describe, expect, it, vi } from 'vitest';

import { toaster } from '$lib/toaster';
import { WorkflowCenter } from './center.svelte';
import type { WorkflowStatus } from './queries';

vi.mock('$lib/toaster', () => ({
	toaster: { success: vi.fn(), error: vi.fn() }
}));

const successToast = vi.mocked(toaster.success);
const errorToast = vi.mocked(toaster.error);

function status(overrides: Partial<WorkflowStatus> = {}): WorkflowStatus {
	return { id: 'workflow-1', state: 'succeeded', error: null, ...overrides };
}

function trackOptions() {
	return {
		label: 'Document processing',
		successMessage: 'Document processing completed',
		failureMessage: 'Document processing failed'
	};
}

afterEach(() => {
	vi.clearAllMocks();
	vi.unstubAllGlobals();
});

describe('WorkflowCenter', () => {
	it('resolves waiters and toasts on success', async () => {
		const center = new WorkflowCenter();
		const { job, settled } = center.track('workflow-1', trackOptions());
		expect(center.jobs).toHaveLength(1);

		center.resolve('workflow-1', status());
		await expect(settled).resolves.toMatchObject({ state: 'succeeded' });
		expect(job.outcome?.state).toBe('succeeded');
		expect(successToast).toHaveBeenCalledWith({ title: 'Document processing completed' });
		expect(errorToast).not.toHaveBeenCalled();
	});

	it('rejects waiters and toasts on failure', async () => {
		const center = new WorkflowCenter();
		const { settled } = center.track('workflow-1', trackOptions());

		center.resolve('workflow-1', status({ state: 'failed', error: 'boom' }));
		await expect(settled).rejects.toThrow('boom');
		expect(errorToast).toHaveBeenCalledWith({ title: 'boom' });
		expect(successToast).not.toHaveBeenCalled();
	});

	it('falls back to the failure message when the terminal error is empty', async () => {
		const center = new WorkflowCenter();
		const { settled } = center.track('workflow-1', trackOptions());

		center.resolve('workflow-1', status({ state: 'cancelled', error: null }));
		await expect(settled).rejects.toThrow('Document processing failed');
		expect(errorToast).toHaveBeenCalledWith({ title: 'Document processing failed' });
	});

	it('replays terminal outcomes without duplicate toasts', async () => {
		const center = new WorkflowCenter();
		center.track('workflow-1', trackOptions());
		center.resolve('workflow-1', status());
		expect(successToast).toHaveBeenCalledTimes(1);

		const replayed = center.track('workflow-1', trackOptions());
		await expect(replayed.settled).resolves.toMatchObject({ state: 'succeeded' });
		expect(successToast).toHaveBeenCalledTimes(1);
	});

	it('prunes succeeded jobs after a grace period but keeps failures', async () => {
		vi.useFakeTimers();
		try {
			const center = new WorkflowCenter();
			const first = center.track('workflow-1', trackOptions());
			const second = center.track('workflow-2', trackOptions());
			void first.settled.then(
				() => undefined,
				() => undefined
			);
			void second.settled.then(
				() => undefined,
				() => undefined
			);
			center.resolve('workflow-1', status({ id: 'workflow-1' }));
			center.resolve('workflow-2', status({ id: 'workflow-2', state: 'failed', error: 'boom' }));
			expect(center.jobs).toHaveLength(2);
			await vi.advanceTimersByTimeAsync(5000);
			expect(center.jobs.map((job) => job.id)).toEqual(['workflow-2']);
		} finally {
			vi.useRealTimers();
		}
	});

	it('fails jobs with a synthesized terminal status', () => {
		const center = new WorkflowCenter();
		const { job, settled } = center.track('workflow-1', trackOptions());
		void settled.then(
			() => undefined,
			() => undefined
		);

		center.fail('workflow-1', 'Document processing failed');
		expect(job.outcome).toMatchObject({ id: 'workflow-1', state: 'failed' });
		expect(errorToast).toHaveBeenCalledWith({ title: 'Document processing failed' });
		return expect(settled).rejects.toThrow('Document processing failed');
	});

	it('hands dismissed waiters back to direct polling', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(
				async () =>
					new Response(JSON.stringify({ id: 'workflow-1', state: 'succeeded', error: null }))
			)
		);
		const center = new WorkflowCenter();
		const { settled } = center.track('workflow-1', trackOptions());

		center.dismiss('workflow-1');
		await expect(settled).resolves.toMatchObject({ state: 'succeeded' });
		expect(center.jobs).toHaveLength(0);
	});

	it('never evicts active jobs when enforcing the tray limit', () => {
		const center = new WorkflowCenter();
		for (let index = 0; index < 25; index++) {
			const { settled } = center.track(`workflow-${index}`, trackOptions());
			void settled.then(
				() => undefined,
				() => undefined
			);
		}
		expect(center.jobs).toHaveLength(25);
		for (let index = 0; index < 10; index++) {
			center.resolve(`workflow-${index}`, status({ id: `workflow-${index}` }));
		}
		for (let index = 25; index < 30; index++) {
			const { settled } = center.track(`workflow-${index}`, trackOptions());
			void settled.then(
				() => undefined,
				() => undefined
			);
		}
		const ids = center.jobs.map((job) => job.id);
		expect(ids.length).toBeLessThanOrEqual(20);
		for (let index = 10; index < 30; index++) {
			expect(ids).toContain(`workflow-${index}`);
		}
	});
});
