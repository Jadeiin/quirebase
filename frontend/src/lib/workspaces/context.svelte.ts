import { createContext } from 'svelte';
import { createWorkspaceApi, type WorkspaceView } from '#lib/api/client.js';
import { can, canVariant, type AuthorizationAction } from '#lib/authorization/can.js';

export type WorkspaceContext = {
	workspaceId: string;
	api: ReturnType<typeof createWorkspaceApi>;
	readonly view: WorkspaceView | undefined;
	readonly role: string | undefined;
	can: (action: AuthorizationAction) => boolean;
	canVariant: (action: AuthorizationAction, relation: string) => boolean;
};

export function workspaceCan(
	view: WorkspaceView | undefined,
	action: AuthorizationAction
): boolean {
	return can(view?.authorization, action);
}

export function workspaceCanVariant(
	view: WorkspaceView | undefined,
	action: AuthorizationAction,
	relation: string
): boolean {
	return canVariant(view?.authorization, action, relation);
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
		can(action) {
			return workspaceCan(getView(), action);
		},
		canVariant(action, relation) {
			return workspaceCanVariant(getView(), action, relation);
		}
	};
	setWorkspaceContext(context);
	return context;
}

export { getWorkspaceContext };
