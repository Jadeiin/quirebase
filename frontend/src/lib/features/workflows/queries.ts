import { queryOptions } from '@tanstack/svelte-query';
import { apiRequest } from '$lib/api/client';
import type { components } from '$lib/api/schema';

export type WorkflowStatus = components['schemas']['WorkflowStatusView'];
export type WorkflowState = WorkflowStatus['state'];

export const workflowKeys = {
	status: (workflowId: string) => ['workflow', workflowId] as const
};

export function isTerminalWorkflowState(state: WorkflowState | undefined): boolean {
	return state === 'succeeded' || state === 'failed' || state === 'cancelled';
}

export function workflowStatusQuery(workflowId: string, shouldPoll?: () => boolean) {
	return queryOptions({
		queryKey: workflowKeys.status(workflowId),
		queryFn: () =>
			apiRequest('GET', '/workflows/{workflow_id}', {
				params: { path: { workflow_id: workflowId } }
			}),
		refetchInterval: (query) => {
			if (shouldPoll && !shouldPoll()) return false;
			return isTerminalWorkflowState(query.state.data?.state) ? false : 2000;
		},
		refetchIntervalInBackground: false
	});
}
