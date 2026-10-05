import { createContext } from 'svelte';
import { createWorkspaceApi, type WorkspaceView } from '#lib/api/client.js';
import {
	can,
	canVariant,
	type AuthorizationAction,
	type AuthorizationVariant
} from '#lib/authorization/can.js';

export type WorkspaceContext = {
	workspaceId: string;
	api: ReturnType<typeof createWorkspaceApi>;
	readonly view: WorkspaceView | undefined;
	readonly role: WorkspaceView['current_role'] | undefined;
	can: (action: AuthorizationAction) => boolean;
	canVariant: (action: AuthorizationAction, variant: AuthorizationVariant) => boolean;
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
	variant: AuthorizationVariant
): boolean {
	return canVariant(view?.authorization, action, variant);
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
		},
		canVariant(action, variant) {
			return workspaceCanVariant(getView(), action, variant);
		}
	};
	setWorkspaceContext(context);
	return context;
}

export { getWorkspaceContext };
