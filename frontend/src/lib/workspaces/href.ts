export type WorkspacePath = `/workspace/${string}`;

export function workspaceHref(workspaceId: string, path = ''): WorkspacePath {
	const suffix = path ? `/${path.replace(/^\/+/, '')}` : '';
	return `/workspace/${encodeURIComponent(workspaceId)}${suffix}` as WorkspacePath;
}
