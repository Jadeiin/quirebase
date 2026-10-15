import type { QueryClient, QueryKey } from '@tanstack/svelte-query';
import { dashboardKeys } from '#lib/features/dashboard/queries.js';
import { itemKeys } from '#lib/features/item/queries.js';
import { libraryKeys } from '#lib/features/library/queries.js';
import { projectKeys } from '#lib/features/projects/queries.js';
import { tagKeys } from '#lib/features/tags/queries.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

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
export function invalidateItemAnnotations(
	queryClient: QueryClient,
	workspaceId: string,
	itemId: string
) {
	return invalidate(queryClient, [
		itemKeys.annotations(workspaceId, itemId),
		itemKeys.overview(workspaceId, itemId)
	]);
}
export function invalidateTags(queryClient: QueryClient, workspaceId: string) {
	// Assignment changes Tag counts and options, and new Tag names create Tags.
	return invalidate(queryClient, [tagKeys.all(workspaceId)]);
}
export function invalidateLibrary(queryClient: QueryClient, workspaceId: string) {
	return invalidate(queryClient, [libraryKeys.all(workspaceId), dashboardKeys.all(workspaceId)]);
}
export function invalidateProject(queryClient: QueryClient, workspaceId: string) {
	return invalidate(queryClient, [projectKeys.all(workspaceId), libraryKeys.all(workspaceId)]);
}
export function invalidateWorkspaces(queryClient: QueryClient) {
	// The Workspace directory and each caller's eligibility in it feed every
	// Workspace-scoped projection, such as an Item's copy destinations.
	return invalidate(queryClient, [workspaceKeys.list(), workspaceKeys.all()]);
}
