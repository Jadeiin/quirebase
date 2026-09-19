// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';

import { msg } from '$lib/i18n';
import { toaster } from '$lib/toaster';
import { WorkflowCenter, type TrackedWorkflow, type WorkflowLedger } from './center.svelte';
import type { WorkflowStatus } from './queries';

vi.mock('$lib/toaster', () => ({
	toaster: { create: vi.fn(), dismiss: vi.fn() }
}));

const createToast = vi.mocked(toaster.create);
const dismissToast = vi.mocked(toaster.dismiss);

type ToastOptions = {
	id: string;
	type: string;
	title: string;
	duration: number;
	onStatusChange?: (details: { status: 'visible' | 'dismissing' | 'unmounted' }) => void;
};

function lastToast(): ToastOptions {
	expect(createToast).toHaveBeenCalled();
	return createToast.mock.lastCall![0] as ToastOptions;
}

function status(overrides: Partial<WorkflowStatus> = {}): WorkflowStatus {
	return { id: 'workflow-1', state: 'succeeded', error: null, ...overrides };
}

function trackOptions() {
	return {
		label: 'Document processing',
		successMessage: msg('Document processing completed'),
		failureMessage: msg('Document processing failed')
	};
}

function memoryLedger() {
	let entries: TrackedWorkflow[] = [];
	const ledger: WorkflowLedger = {
		read: () => entries,
		write: (next) => {
			entries = next;
		}
	};
	return { ledger, entries: () => entries };
}

describe('WorkflowCenter', () => {
	it('resolves waiters and shows a success toast with the job duration', async () => {
		const center = new WorkflowCenter();
		const { job, settled } = center.track('workflow-1', trackOptions());
		expect(center.jobs).toHaveLength(1);

		center.resolve('workflow-1', status());
		await expect(settled).resolves.toMatchObject({ state: 'succeeded' });
		expect(job.outcome?.state).toBe('succeeded');
		expect(lastToast()).toMatchObject({
			id: 'workflow-toast-workflow-1',
			type: 'success',
			title: 'Document processing completed',
			duration: 6000
		});
	});

	it('rejects waiters and shows a persistent failure toast', async () => {
		const center = new WorkflowCenter();
		const { settled } = center.track('workflow-1', trackOptions());

		center.resolve('workflow-1', status({ state: 'failed', error: 'boom' }));
		await expect(settled).rejects.toThrow('boom');
		expect(lastToast()).toMatchObject({
			id: 'workflow-toast-workflow-1',
			type: 'error',
			title: 'boom',
			duration: Infinity
		});
	});

	it('falls back to the failure message when the terminal error is empty', async () => {
		const center = new WorkflowCenter();
		const { settled } = center.track('workflow-1', trackOptions());

		center.resolve('workflow-1', status({ state: 'cancelled', error: null }));
		await expect(settled).rejects.toThrow('Document processing failed');
		expect(lastToast()).toMatchObject({ title: 'Document processing failed' });
	});

	it('replays terminal outcomes without duplicate toasts', async () => {
		const center = new WorkflowCenter();
		center.track('workflow-1', trackOptions());
		center.resolve('workflow-1', status());
		expect(createToast).toHaveBeenCalledTimes(1);

		const replayed = center.track('workflow-1', trackOptions());
		await expect(replayed.settled).resolves.toMatchObject({ state: 'succeeded' });
		expect(createToast).toHaveBeenCalledTimes(1);
	});

	it('keeps the tray job until its success toast dismisses', () => {
		const center = new WorkflowCenter();
		center.track('workflow-1', trackOptions());
		center.resolve('workflow-1', status());
		expect(center.jobs).toHaveLength(1);

		lastToast().onStatusChange?.({ status: 'dismissing' });

		expect(center.jobs).toHaveLength(0);
	});

	it('keeps failed jobs until their toast is dismissed', async () => {
		const center = new WorkflowCenter();
		const { settled } = center.track('workflow-1', trackOptions());
		center.resolve('workflow-1', status({ state: 'failed', error: 'boom' }));
		await expect(settled).rejects.toThrow('boom');
		expect(center.jobs).toHaveLength(1);

		lastToast().onStatusChange?.({ status: 'dismissing' });

		expect(center.jobs).toHaveLength(0);
	});

	it('dismisses the matching toast when the tray job is dismissed', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(
				async () =>
					new Response(JSON.stringify({ id: 'workflow-1', state: 'succeeded', error: null }))
			)
		);
		const center = new WorkflowCenter();
		center.track('workflow-1', trackOptions());

		center.dismiss('workflow-1');

		expect(dismissToast).toHaveBeenCalledWith('workflow-toast-workflow-1');
		await Promise.resolve();
	});

	it('fails jobs with a synthesized terminal status', async () => {
		const center = new WorkflowCenter();
		const { job, settled } = center.track('workflow-1', trackOptions());

		center.fail('workflow-1', 'Document processing failed');
		expect(job.outcome).toMatchObject({ id: 'workflow-1', state: 'failed' });
		expect(lastToast()).toMatchObject({ type: 'error', title: 'Document processing failed' });
		await expect(settled).rejects.toThrow('Document processing failed');
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

	it('restores active jobs from the ledger without duplicating tracked work', () => {
		const { ledger } = memoryLedger();
		const first = new WorkflowCenter(ledger);
		first.track('workflow-1', trackOptions());

		const reloaded = new WorkflowCenter(ledger);
		reloaded.restore();
		reloaded.restore();
		expect(reloaded.jobs).toHaveLength(1);
		expect(reloaded.jobs[0]).toMatchObject({
			id: 'workflow-1',
			label: 'Document processing',
			startedAt: expect.any(Number)
		});
	});

	it('drops settled jobs from the ledger', () => {
		const { ledger, entries } = memoryLedger();
		const center = new WorkflowCenter(ledger);
		center.track('workflow-1', trackOptions());

		center.resolve('workflow-1', status());
		expect(entries()).toEqual([]);
	});

	it('keeps dismissed jobs out of the restored tray', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(
				async () =>
					new Response(JSON.stringify({ id: 'workflow-1', state: 'succeeded', error: null }))
			)
		);
		const { ledger, entries } = memoryLedger();
		const first = new WorkflowCenter(ledger);
		first.track('workflow-1', trackOptions());

		first.dismiss('workflow-1');
		expect(entries()).toEqual([]);
		const reloaded = new WorkflowCenter(ledger);
		reloaded.restore();
		expect(reloaded.jobs).toHaveLength(0);
		await Promise.resolve();
	});

	it('shows the success toast when a restored job settles', () => {
		const { ledger } = memoryLedger();
		const first = new WorkflowCenter(ledger);
		first.track('workflow-1', trackOptions());

		const restored = new WorkflowCenter(ledger);
		restored.restore();
		restored.resolve('workflow-1', status());
		expect(lastToast()).toMatchObject({ type: 'success', title: 'Document processing completed' });
	});

	it('persists every active job beyond the tray limit', () => {
		const { ledger } = memoryLedger();
		const center = new WorkflowCenter(ledger);
		for (let index = 0; index < 25; index++) {
			center.track(`workflow-${index}`, trackOptions());
		}

		expect(ledger.read().map((entry) => entry.id)).toEqual(
			Array.from({ length: 25 }, (_, index) => `workflow-${index}`)
		);
	});

	it('binds a ledger per account and restores that account jobs', async () => {
		const first = memoryLedger();
		const second = memoryLedger();
		const center = new WorkflowCenter(first.ledger);
		const { settled } = center.track('workflow-a', trackOptions());
		second.ledger.write([
			{
				id: 'workflow-b',
				label: 'Import processing',
				successMessage: 'done',
				failureMessage: 'failed',
				startedAt: 1
			}
		]);

		center.bindLedger(second.ledger);
		await expect(settled).rejects.toThrow('Workflow tracking moved to another account');

		expect(center.jobs.map((job) => job.id)).toEqual(['workflow-b']);
		expect(first.entries().map((entry) => entry.id)).toEqual(['workflow-a']);
	});

	it('rejects in-flight waiters when the ledger switches accounts', async () => {
		const first = memoryLedger();
		const second = memoryLedger();
		const center = new WorkflowCenter(first.ledger);
		const { settled } = center.track('workflow-a', trackOptions());

		center.bindLedger(second.ledger);

		await expect(settled).rejects.toThrow('Workflow tracking moved to another account');
	});

	it('never evicts active jobs when enforcing the tray limit', () => {
		const center = new WorkflowCenter();
		for (let index = 0; index < 25; index++) {
			center.track(`workflow-${index}`, trackOptions());
		}
		expect(center.jobs).toHaveLength(25);
		for (let index = 0; index < 10; index++) {
			center.resolve(`workflow-${index}`, status({ id: `workflow-${index}` }));
		}
		for (let index = 25; index < 30; index++) {
			center.track(`workflow-${index}`, trackOptions());
		}
		const ids = center.jobs.map((job) => job.id);
		expect(ids.length).toBeLessThanOrEqual(20);
		for (let index = 10; index < 30; index++) {
			expect(ids).toContain(`workflow-${index}`);
		}
	});
});
