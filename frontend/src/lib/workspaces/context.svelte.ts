import { createContext } from 'svelte';
import { createWorkspaceApi, type WorkspaceView } from '$lib/api/client';

export type WorkspaceContext = {
	workspaceId: string;
	api: ReturnType<typeof createWorkspaceApi>;
	readonly view: WorkspaceView | undefined;
	readonly role: string | undefined;
	can: (capability: string) => boolean;
};

export function workspaceCan(view: WorkspaceView | undefined, capability: string): boolean {
	return view?.effective_capabilities.includes(capability) ?? false;
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
		can(capability) {
			return workspaceCan(getView(), capability);
		}
	};
	setWorkspaceContext(context);
	return context;
}

export { getWorkspaceContext };
