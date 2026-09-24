import { createContext } from 'svelte';
import { createWorkspaceApi, type WorkspaceView } from '$lib/api/client';

export type WorkspaceContext = {
	workspaceId: string;
	api: ReturnType<typeof createWorkspaceApi>;
	readonly view: WorkspaceView | undefined;
	can: (capability: string) => boolean;
};

export function workspaceCan(view: WorkspaceView | undefined, capability: string): boolean {
	return view?.effective_capabilities.includes(capability) ?? false;
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
		can(capability) {
			return workspaceCan(getView(), capability);
		}
	};
	setWorkspaceContext(context);
	return context;
}

export { getWorkspaceContext };
