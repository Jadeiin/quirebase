import { queryOptions } from '@tanstack/svelte-query';
import { ApiError, apiRequest } from '$lib/api/client';
import type { components } from '$lib/api/schema';

export type WorkflowStatus = components['schemas']['WorkflowStatusView'];
export type WorkflowState = WorkflowStatus['state'];

export const workflowKeys = {
	all: ['workflows'] as const,
	status: (workflowId: string) => [...workflowKeys.all, workflowId] as const
};

export function isTerminalWorkflowState(state: WorkflowState | undefined): boolean {
	return state === 'succeeded' || state === 'failed' || state === 'cancelled';
}

export function isRecoverableWorkflowStatusError(error: unknown): boolean {
	if (!(error instanceof ApiError)) return true;
	return (
		error.status === 408 || error.status === 425 || error.status === 429 || error.status >= 500
	);
}

export function workflowStatusQuery(workflowId: string, shouldPoll?: () => boolean) {
	return queryOptions({
		queryKey: workflowKeys.status(workflowId),
		queryFn: ({ signal }) =>
			apiRequest('GET', '/workflows/{workflow_id}', {
				params: { path: { workflow_id: workflowId } },
				signal
			}),
		refetchInterval: (query) => {
			if (shouldPoll && !shouldPoll()) return false;
			return isTerminalWorkflowState(query.state.data?.state) ? false : 2000;
		},
		refetchIntervalInBackground: false
	});
}
