import { createContext } from 'svelte';
import { SvelteMap, SvelteSet } from 'svelte/reactivity';
import { waitForWorkflow } from '#lib/api/workflows.js';
import { i18n } from '@lingui/core';
import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';
import { toaster } from '#lib/toaster.js';
import type { WorkflowStatus } from './queries';

export type WorkflowTarget = { kind: 'import_batch'; id: string };

export type TrackedJob = {
	id: string;
	workspaceId?: string;
	target?: WorkflowTarget;
	label: string;
	successMessage: MessageDescriptor;
	failureMessage: MessageDescriptor;
	startedAt: number;
	outcome?: WorkflowStatus;
	unavailable?: boolean;
};

export type TrackedWorkflow = {
	id: string;
	workspaceId?: string;
	target?: WorkflowTarget;
	label: string;
	successMessage: string;
	failureMessage: string;
	startedAt: number;
	outcome?: WorkflowStatus;
	unavailable?: boolean;
};

export type WorkflowLedger = {
	read(): TrackedWorkflow[];
	write(entries: TrackedWorkflow[]): void;
};

export type TrackOptions = {
	workspaceId?: string;
	target?: WorkflowTarget;
	label: string;
	successMessage: MessageDescriptor;
	failureMessage: MessageDescriptor;
};

type Waiter = {
	resolve: (status: WorkflowStatus) => void;
	reject: (reason: Error) => void;
};

const MAX_JOBS = 20;
const SUCCESS_TOAST_DURATION = 6000;
const workflowToastId = (workflowId: string) => `workflow-toast-${workflowId}`;

function notificationId(message: MessageDescriptor): string {
	if (!message.id || (message.values && Object.keys(message.values).length)) {
		throw new Error('Workflow notifications require a static message ID');
	}
	return message.id;
}

export class WorkflowCenter {
	jobs = $state<TrackedJob[]>([]);
	private waiters = new SvelteMap<string, Waiter[]>();
	private dismissed = new SvelteSet<string>();
	private ledger: WorkflowLedger | undefined;

	constructor(ledger?: WorkflowLedger) {
		this.ledger = ledger;
	}

	bindLedger(ledger: WorkflowLedger) {
		if (this.ledger === ledger) return;
		if (this.jobs.length > 0 || this.waiters.size > 0) {
			const reason = new Error('Workflow tracking moved to another account');
			for (const pending of this.waiters.values())
				for (const waiter of pending) waiter.reject(reason);
			this.waiters.clear();
			this.jobs = [];
		}
		this.dismissed.clear();
		this.ledger = ledger;
		this.restore();
	}

	restore() {
		if (!this.ledger) return;
		for (const entry of this.ledger.read()) {
			if (this.dismissed.has(entry.id) || this.jobs.some((job) => job.id === entry.id)) continue;
			if (entry.target && (entry.outcome || entry.unavailable)) {
				// Completed destinations survive reload without polling or repeating the toast.
				this.jobs.push({
					...entry,
					successMessage: { id: entry.successMessage },
					failureMessage: { id: entry.failureMessage }
				});
				continue;
			}
			const tracked = this.track(entry.id, {
				workspaceId: entry.workspaceId,
				target: entry.target,
				label: entry.label,
				successMessage: { id: entry.successMessage },
				failureMessage: { id: entry.failureMessage }
			});
			const stored = this.jobs.find((job) => job.id === entry.id);
			if (stored) stored.startedAt = entry.startedAt;
			void tracked.settled.catch(() => undefined);
		}
		this.persist();
	}

	private persist() {
		if (!this.ledger) return;
		// Keep active work and explicit return destinations; only generic terminal jobs expire.
		this.ledger.write(
			this.jobs
				.filter((job) => (!job.outcome && !job.unavailable) || job.target)
				.map((job) => ({
					id: job.id,
					workspaceId: job.workspaceId,
					target: job.target,
					label: job.label,
					successMessage: notificationId(job.successMessage),
					failureMessage: notificationId(job.failureMessage),
					startedAt: job.startedAt,
					outcome: job.outcome,
					unavailable: job.unavailable
				}))
		);
	}

	track(
		workflowId: string,
		options: TrackOptions
	): { job: TrackedJob; settled: Promise<WorkflowStatus> } {
		notificationId(options.successMessage);
		notificationId(options.failureMessage);
		const existing = this.jobs.find((job) => job.id === workflowId);
		if (existing?.unavailable) {
			return {
				job: existing,
				settled: Promise.reject(
					new Error(i18n._(msg`Workflow history is unavailable. Check the current result.`))
				)
			};
		}
		if (existing?.outcome) {
			const terminal = Promise.resolve(existing.outcome);
			return {
				job: existing,
				settled:
					existing.outcome.state === 'succeeded'
						? terminal
						: terminal.then(() => {
								throw new Error(existing.outcome?.error || i18n._(options.failureMessage));
							})
			};
		}
		const job: TrackedJob = {
			id: workflowId,
			workspaceId: options.workspaceId,
			target: options.target,
			label: options.label,
			successMessage: options.successMessage,
			failureMessage: options.failureMessage,
			startedAt: Date.now()
		};
		if (existing) {
			Object.assign(existing, job);
		} else {
			// Active jobs own waiters; saved destinations need explicit dismissal.
			const retained = this.jobs.filter(
				(entry) => (!entry.outcome && !entry.unavailable) || entry.target
			);
			const terminal = this.jobs.filter(
				(entry) => (entry.outcome || entry.unavailable) && !entry.target
			);
			const room = Math.max(0, MAX_JOBS - retained.length - 1);
			this.jobs = [...retained, ...(room > 0 ? terminal.slice(-room) : []), job];
		}
		const settled = new Promise<WorkflowStatus>((resolve, reject) => {
			const pending = this.waiters.get(workflowId) ?? [];
			pending.push({ resolve, reject });
			this.waiters.set(workflowId, pending);
		});
		// $state deeply proxies stored entries, so return the stored instance.
		const stored = this.jobs.find((entry) => entry.id === workflowId);
		if (!stored) throw new Error(`Workflow job missing after track: ${workflowId}`);
		this.persist();
		return { job: stored, settled };
	}

	resolve(workflowId: string, status: WorkflowStatus) {
		const job = this.jobs.find((entry) => entry.id === workflowId);
		if (!job || job.outcome || job.unavailable) return;
		job.outcome = status;
		const pending = this.waiters.get(workflowId) ?? [];
		this.waiters.delete(workflowId);
		for (const waiter of pending) {
			if (status.state === 'succeeded') waiter.resolve(status);
			else
				waiter.reject(
					new Error(status.error || i18n._(job.failureMessage) || i18n._(msg`Workflow failed`))
				);
		}
		if (job && status.state !== 'succeeded') {
			this.notify(job, {
				type: 'error',
				title: status.error || i18n._(job.failureMessage),
				duration: Infinity
			});
		} else if (job) {
			this.notify(job, {
				type: 'success',
				title: i18n._(job.successMessage),
				duration: SUCCESS_TOAST_DURATION
			});
		}
		this.persist();
	}

	private notify(
		job: TrackedJob,
		options: { type: 'success' | 'error'; title: string; duration: number }
	) {
		toaster.create({
			id: workflowToastId(job.id),
			type: options.type,
			title: options.title,
			duration: options.duration,
			onStatusChange: ({ status }) => {
				if (status === 'dismissing' && !job.target) this.dismiss(job.id);
			}
		});
	}

	markUnavailable(workflowId: string) {
		const job = this.jobs.find((entry) => entry.id === workflowId);
		if (!job || job.outcome || job.unavailable) return;
		job.unavailable = true;
		const message = i18n._(msg`Workflow history is unavailable. Check the current result.`);
		const pending = this.waiters.get(workflowId) ?? [];
		this.waiters.delete(workflowId);
		for (const waiter of pending) waiter.reject(new Error(message));
		this.notify(job, { type: 'error', title: message, duration: Infinity });
		this.persist();
	}

	fail(workflowId: string, message: string) {
		this.resolve(workflowId, { id: workflowId, state: 'failed', error: message });
	}

	dismiss(workflowId: string) {
		this.dismissed.add(workflowId);
		const job = this.jobs.find((candidate) => candidate.id === workflowId);
		// Hand waiters back to direct polling so local busy states always settle.
		const pending = this.waiters.get(workflowId) ?? [];
		this.waiters.delete(workflowId);
		if (pending.length > 0) {
			void waitForWorkflow(workflowId, { workspaceId: job?.workspaceId }).then(
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
		this.persist();
		toaster.dismiss(workflowToastId(workflowId));
	}
}

const [getWorkflowCenter, setWorkflowCenter] = createContext<WorkflowCenter>();

export { getWorkflowCenter, setWorkflowCenter };
