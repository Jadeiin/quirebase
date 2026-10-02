import { createContext } from 'svelte';
import { createWorkspaceApi, type WorkspaceView } from '#lib/api/client.js';
import { can, type AuthorizationAction } from '#lib/authorization/can.js';

export type WorkspaceContext = {
	workspaceId: string;
	api: ReturnType<typeof createWorkspaceApi>;
	readonly view: WorkspaceView | undefined;
	readonly role: string | undefined;
	can: (action: AuthorizationAction, relation?: string) => boolean;
};

export function workspaceCan(
	view: WorkspaceView | undefined,
	action: AuthorizationAction,
	relation?: string
): boolean {
	return can(view?.authorization, action, relation);
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
		can(action, relation) {
			return workspaceCan(getView(), action, relation);
		}
	};
	setWorkspaceContext(context);
	return context;
}

export { getWorkspaceContext };
