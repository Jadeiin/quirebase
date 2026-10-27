import type { TrackedWorkflow, WorkflowLedger, WorkflowTarget } from './center.svelte';
import type { WorkflowStatus } from './queries';

const STORAGE_PREFIX = 'quirebase:tracked-workflows';

function isWorkflowTarget(target: unknown): target is WorkflowTarget {
	return (
		target !== null &&
		typeof target === 'object' &&
		'kind' in target &&
		target.kind === 'import_batch' &&
		'id' in target &&
		typeof target.id === 'string' &&
		target.id.length > 0 &&
		target.id.length <= 256
	);
}

function isTerminalOutcome(outcome: unknown, id: string): outcome is WorkflowStatus {
	return (
		outcome !== null &&
		typeof outcome === 'object' &&
		'id' in outcome &&
		outcome.id === id &&
		'state' in outcome &&
		(outcome.state === 'succeeded' ||
			outcome.state === 'failed' ||
			outcome.state === 'cancelled') &&
		(!('error' in outcome) || outcome.error === null || typeof outcome.error === 'string')
	);
}

function isTrackedWorkflow(entry: unknown): entry is TrackedWorkflow {
	return (
		entry !== null &&
		typeof entry === 'object' &&
		'id' in entry &&
		typeof entry.id === 'string' &&
		'label' in entry &&
		typeof entry.label === 'string' &&
		'successMessage' in entry &&
		typeof entry.successMessage === 'string' &&
		entry.successMessage.length > 0 &&
		'failureMessage' in entry &&
		typeof entry.failureMessage === 'string' &&
		entry.failureMessage.length > 0 &&
		'startedAt' in entry &&
		typeof entry.startedAt === 'number' &&
		Number.isFinite(entry.startedAt) &&
		(!('workspaceId' in entry) ||
			entry.workspaceId === undefined ||
			typeof entry.workspaceId === 'string') &&
		(!('target' in entry) ||
			entry.target === undefined ||
			('workspaceId' in entry &&
				typeof entry.workspaceId === 'string' &&
				Boolean(entry.workspaceId) &&
				isWorkflowTarget(entry.target))) &&
		(!('unavailable' in entry) ||
			entry.unavailable === undefined ||
			typeof entry.unavailable === 'boolean') &&
		(!('outcome' in entry) ||
			entry.outcome === undefined ||
			('target' in entry && Boolean(entry.target) && isTerminalOutcome(entry.outcome, entry.id)))
	);
}

export function localStorageWorkflowLedger(userId: string): WorkflowLedger {
	const storageKey = `${STORAGE_PREFIX}:${userId}`;
	return {
		read() {
			try {
				const raw = localStorage.getItem(storageKey);
				if (!raw) return [];
				const parsed: unknown = JSON.parse(raw);
				if (!Array.isArray(parsed)) return [];
				return parsed.filter(isTrackedWorkflow);
			} catch {
				return [];
			}
		},
		write(entries) {
			try {
				localStorage.setItem(storageKey, JSON.stringify(entries));
			} catch {
				return;
			}
		}
	};
}
