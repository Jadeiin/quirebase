export const workspaceKeys = {
	list: () => ['workspaces'] as const,
	creationAvailability: () => ['workspaces', 'creation-availability'] as const,
	root: (workspaceId: string) => ['workspace', workspaceId] as const,
	items: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'items'] as const,
	item: (workspaceId: string, itemId: string) =>
		[...workspaceKeys.items(workspaceId), 'item', itemId] as const,
	projects: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'projects'] as const,
	project: (workspaceId: string, projectId: string) =>
		[...workspaceKeys.projects(workspaceId), 'project', projectId] as const,
	projectDiscussions: (workspaceId: string, projectId: string) =>
		[...workspaceKeys.project(workspaceId, projectId), 'discussions'] as const,
	members: (workspaceId: string) => [...workspaceKeys.root(workspaceId), 'members'] as const,
	governanceMembers: (workspaceId: string) =>
		[...workspaceKeys.root(workspaceId), 'governance-members'] as const,
	invitations: (workspaceId: string) =>
		[...workspaceKeys.root(workspaceId), 'invitations'] as const,
	mutation: (workspaceId: string, name: string, ...resourceIds: string[]) =>
		[...workspaceKeys.root(workspaceId), 'mutation', name, ...resourceIds] as const
};
