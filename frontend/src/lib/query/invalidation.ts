import type { QueryClient, QueryKey } from '@tanstack/svelte-query';
import { dashboardKeys } from '$lib/features/dashboard/queries';
import { itemKeys } from '$lib/features/item/queries';
import { libraryKeys } from '$lib/features/library/queries';
import { projectKeys } from '$lib/features/projects/queries';

async function invalidate(queryClient: QueryClient, keys: QueryKey[]) {
	await Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
}

export function invalidateItem(queryClient: QueryClient, workspaceId: string, itemId: string) {
	return invalidate(queryClient, [
		itemKeys.detail(workspaceId, itemId),
		itemKeys.overview(workspaceId, itemId),
		libraryKeys.all(workspaceId),
		dashboardKeys.all(workspaceId)
	]);
}
export function invalidateItemFiles(queryClient: QueryClient, workspaceId: string, itemId: string) {
	return invalidate(queryClient, [
		itemKeys.files(workspaceId, itemId),
		itemKeys.overview(workspaceId, itemId)
	]);
}
export function invalidateItemOrganize(
	queryClient: QueryClient,
	workspaceId: string,
	itemId: string
) {
	return invalidate(queryClient, [
		itemKeys.organize(workspaceId, itemId),
		itemKeys.overview(workspaceId, itemId)
	]);
}
export function invalidateItemDiscussion(
	queryClient: QueryClient,
	workspaceId: string,
	itemId: string
) {
	return invalidate(queryClient, [
		itemKeys.discussion(workspaceId, itemId),
		itemKeys.overview(workspaceId, itemId)
	]);
}
export function invalidateLibrary(queryClient: QueryClient, workspaceId: string) {
	return invalidate(queryClient, [libraryKeys.all(workspaceId), dashboardKeys.all(workspaceId)]);
}
export function invalidateProject(
	queryClient: QueryClient,
	workspaceId: string,
	projectId?: string
) {
	return invalidate(
		queryClient,
		projectId
			? [
					projectKeys.detail(workspaceId, projectId),
					projectKeys.lists(workspaceId),
					projectKeys.joinable(workspaceId)
				]
			: [projectKeys.all(workspaceId)]
	);
}
