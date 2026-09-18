import type { TrackedWorkflow, WorkflowLedger } from './center.svelte';

const STORAGE_PREFIX = 'quirebase:tracked-workflows';

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
		'failureMessage' in entry &&
		typeof entry.failureMessage === 'string' &&
		'startedAt' in entry &&
		typeof entry.startedAt === 'number'
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
