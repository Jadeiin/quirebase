import { queryOptions } from '@tanstack/svelte-query';
import { ApiError, apiRequest, createWorkspaceApi } from '$lib/api/client';
import type { components } from '$lib/api/schema';
import { workspaceKeys } from '$lib/workspaces/keys';

export type WorkflowStatus = components['schemas']['WorkflowStatusView'];
export type WorkflowState = WorkflowStatus['state'];

export const workflowKeys = {
	all: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'workflows'] as const,
	status: (workspaceId: string, workflowId: string) =>
		[...workflowKeys.all(workspaceId), workflowId] as const
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

export function workflowStatusQuery(
	workspaceId: string | undefined,
	workflowId: string,
	shouldPoll?: () => boolean
) {
	return queryOptions({
		queryKey: workspaceId
			? workflowKeys.status(workspaceId, workflowId)
			: ['admin', 'workflow', workflowId],
		queryFn: ({ signal }) =>
			workspaceId
				? createWorkspaceApi(workspaceId).request(
						'GET',
						'/workspaces/{workspace_id}/workflows/{workflow_id}',
						{
							params: { path: { workflow_id: workflowId } },
							signal
						}
					)
				: apiRequest('GET', '/admin/workflows/{workflow_id}', {
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
