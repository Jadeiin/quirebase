import { createContext } from 'svelte';
import { createWorkspaceApi, type WorkspaceView } from '#lib/api/client.js';
import { can, type AuthorizationAction } from '#lib/authorization/can.js';

export type WorkspaceContext = {
	workspaceId: string;
	api: ReturnType<typeof createWorkspaceApi>;
	readonly view: WorkspaceView | undefined;
	readonly role: WorkspaceView['current_role'] | undefined;
	can: (action: AuthorizationAction) => boolean;
};

export function workspaceCan(
	view: WorkspaceView | undefined,
	action: AuthorizationAction
): boolean {
	return can(view?.authorization, action);
}

export function workspaceRole(
	view: WorkspaceView | undefined
): WorkspaceView['current_role'] | undefined {
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
		can(action) {
			return workspaceCan(getView(), action);
		}
	};
	setWorkspaceContext(context);
	return context;
}

export { getWorkspaceContext };
