import { createContext } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import { waitForWorkflow } from '$lib/api/workflows';
import { toaster } from '$lib/toaster';
import type { WorkflowStatus } from './queries';

export type TrackedJob = {
	id: string;
	label: string;
	successMessage: string;
	failureMessage: string;
	startedAt: number;
	outcome?: WorkflowStatus;
};

type Waiter = {
	resolve: (status: WorkflowStatus) => void;
	reject: (reason: Error) => void;
};

const MAX_JOBS = 20;

export class WorkflowCenter {
	jobs = $state<TrackedJob[]>([]);
	private waiters = new SvelteMap<string, Waiter[]>();

	track(
		workflowId: string,
		options: { label: string; successMessage: string; failureMessage: string }
	): { job: TrackedJob; settled: Promise<WorkflowStatus> } {
		const existing = this.jobs.find((job) => job.id === workflowId);
		if (existing?.outcome) {
			const terminal = Promise.resolve(existing.outcome);
			return {
				job: existing,
				settled:
					existing.outcome.state === 'succeeded'
						? terminal
						: terminal.then(() => {
								throw new Error(existing.outcome?.error || options.failureMessage);
							})
			};
		}
		const job: TrackedJob = {
			id: workflowId,
			label: options.label,
			successMessage: options.successMessage,
			failureMessage: options.failureMessage,
			startedAt: Date.now()
		};
		if (existing) {
			Object.assign(existing, job);
		} else {
			// Active jobs own polling and waiter settlement, so the cap only ever
			// prunes terminal jobs. The list may transiently exceed MAX_JOBS when
			// many workflows run concurrently.
			const active = this.jobs.filter((entry) => !entry.outcome);
			const terminal = this.jobs.filter((entry) => entry.outcome);
			const room = Math.max(0, MAX_JOBS - active.length - 1);
			this.jobs = [...active, ...(room > 0 ? terminal.slice(-room) : []), job];
		}
		const settled = new Promise<WorkflowStatus>((resolve, reject) => {
			const pending = this.waiters.get(workflowId) ?? [];
			pending.push({ resolve, reject });
			this.waiters.set(workflowId, pending);
		});
		// $state deeply proxies stored entries, so return the stored instance.
		const stored = this.jobs.find((entry) => entry.id === workflowId);
		if (!stored) throw new Error(`Workflow job missing after track: ${workflowId}`);
		return { job: stored, settled };
	}

	resolve(workflowId: string, status: WorkflowStatus) {
		const job = this.jobs.find((entry) => entry.id === workflowId);
		if (!job || job.outcome) return;
		job.outcome = status;
		const pending = this.waiters.get(workflowId) ?? [];
		this.waiters.delete(workflowId);
		for (const waiter of pending) {
			if (status.state === 'succeeded') waiter.resolve(status);
			else waiter.reject(new Error(status.error || job?.failureMessage || 'Workflow failed'));
		}
		if (job && status.state !== 'succeeded') {
			toaster.error({ title: status.error || job.failureMessage });
		} else if (job) {
			toaster.success({ title: job.successMessage });
			// The toast carries the success signal; prune the job shortly after so the
			// tray badge tracks live work and the tray hides itself at zero.
			const succeededId = workflowId;
			window.setTimeout(() => {
				const entry = this.jobs.find((candidate) => candidate.id === succeededId);
				if (entry?.outcome?.state === 'succeeded') this.dismiss(succeededId);
			}, 5000);
		}
	}

	fail(workflowId: string, message: string) {
		this.resolve(workflowId, { id: workflowId, state: 'failed', error: message });
	}

	dismiss(workflowId: string) {
		// Hand waiters back to direct polling so local busy states always settle.
		const pending = this.waiters.get(workflowId) ?? [];
		this.waiters.delete(workflowId);
		if (pending.length > 0) {
			void waitForWorkflow(workflowId).then(
				(status) => {
					for (const waiter of pending) waiter.resolve(status);
				},
				(reason) => {
					for (const waiter of pending)
						waiter.reject(reason instanceof Error ? reason : new Error(String(reason)));
				}
			);
		}
		this.jobs = this.jobs.filter((job) => job.id !== workflowId);
	}
}

const [getWorkflowCenter, setWorkflowCenter] = createContext<WorkflowCenter>();

export { getWorkflowCenter, setWorkflowCenter };
