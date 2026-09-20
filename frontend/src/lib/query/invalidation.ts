import type { QueryClient, QueryKey } from '@tanstack/svelte-query';
import { dashboardKeys } from '$lib/features/dashboard/queries';
import { itemKeys } from '$lib/features/item/queries';
import { libraryKeys } from '$lib/features/library/queries';
import { projectKeys } from '$lib/features/projects/queries';

async function invalidate(queryClient: QueryClient, keys: QueryKey[]) {
	await Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
}

export function invalidateItem(queryClient: QueryClient, itemId: string) {
	return invalidate(queryClient, [
		itemKeys.detail(itemId),
		itemKeys.workspace(itemId),
		libraryKeys.all,
		dashboardKeys.all
	]);
}
export function invalidateItemFiles(queryClient: QueryClient, itemId: string) {
	return invalidate(queryClient, [itemKeys.files(itemId), itemKeys.workspace(itemId)]);
}
export function invalidateItemOrganize(queryClient: QueryClient, itemId: string) {
	return invalidate(queryClient, [itemKeys.organize(itemId), itemKeys.workspace(itemId)]);
}
export function invalidateItemDiscussion(queryClient: QueryClient, itemId: string) {
	return invalidate(queryClient, [itemKeys.discussion(itemId), itemKeys.workspace(itemId)]);
}
export function invalidateLibrary(queryClient: QueryClient) {
	return invalidate(queryClient, [libraryKeys.all, dashboardKeys.all]);
}
export function invalidateProject(queryClient: QueryClient, projectId?: string) {
	return invalidate(
		queryClient,
		projectId ? [projectKeys.detail(projectId), projectKeys.lists()] : [projectKeys.all]
	);
}
