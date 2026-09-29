import { createContext } from 'svelte';
import { createWorkspaceApi, type WorkspaceView } from '$lib/api/client';
import { can } from '$lib/authorization/can';

export type WorkspaceContext = {
	workspaceId: string;
	api: ReturnType<typeof createWorkspaceApi>;
	readonly view: WorkspaceView | undefined;
	readonly role: string | undefined;
	can: (resource: string, action: string, relation?: string) => boolean;
};

export function workspaceCan(
	view: WorkspaceView | undefined,
	resource: string,
	action: string,
	relation?: string
): boolean {
	return can(view?.authorization, resource, action, relation);
}

export function workspaceRole(view: WorkspaceView | undefined): string | undefined {
	return view?.current_role;
}

const [getWorkspaceContext, setWorkspaceContext] = createContext<WorkspaceContext>();

export function provideWorkspaceContext(
	workspaceId: string,
	getView: () => WorkspaceView | undefined
): WorkspaceContext {
	const context: WorkspaceContext = {
		workspaceId,
		api: createWorkspaceApi(workspaceId),
		get view() {
			return getView();
		},
		get role() {
			return workspaceRole(getView());
		},
		can(resource, action, relation) {
			return workspaceCan(getView(), resource, action, relation);
		}
	};
	setWorkspaceContext(context);
	return context;
}

export { getWorkspaceContext };
