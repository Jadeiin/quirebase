import { matchQuery, type Query, type QueryClient, type QueryKey } from '@tanstack/svelte-query';
import { exportPreferenceKeys } from '#lib/features/account/queries.js';
import { dashboardKeys } from '#lib/features/dashboard/queries.js';
import { itemKeys } from '#lib/features/item/queries.js';
import { libraryKeys } from '#lib/features/library/queries.js';
import { pdfReaderKeys } from '#lib/features/pdf-reader/queries.js';
import { projectKeys } from '#lib/features/projects/queries.js';
import { tagKeys } from '#lib/features/tags/queries.js';
import { toolKeys } from '#lib/features/tools/queries.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';
import type { LibraryFilters } from '#lib/features/library/filters.js';
import type { LibrarySearch } from '#lib/features/library/queries.js';
import type { OrganizeView } from '#lib/features/item/types.js';

async function invalidate(queryClient: QueryClient, keys: QueryKey[]) {
	// Overlapping scopes must refresh each query once, without cancelling and restarting it.
	await queryClient.invalidateQueries({
		predicate: (query) => keys.some((queryKey) => matchQuery({ queryKey }, query))
	});
}

export function invalidateItem(queryClient: QueryClient, workspaceId: string, itemId: string) {
	return invalidate(queryClient, [
		itemKeys.detail(workspaceId, itemId),
		itemKeys.overview(workspaceId, itemId),
		// The reader header projects the Item title and authors.
		pdfReaderKeys.item(workspaceId, itemId),
		libraryKeys.all(workspaceId),
		dashboardKeys.all(workspaceId)
	]);
}
export function invalidateItemFiles(queryClient: QueryClient, workspaceId: string, itemId: string) {
	// File changes feed the Library's file filter and the reader's Revision.
	return invalidate(queryClient, [
		itemKeys.files(workspaceId, itemId),
		itemKeys.overview(workspaceId, itemId),
		pdfReaderKeys.item(workspaceId, itemId),
		libraryKeys.all(workspaceId)
	]);
}
export function invalidateItemOrganize(
	queryClient: QueryClient,
	workspaceId: string,
	itemId: string
) {
	return invalidate(queryClient, [
		itemKeys.organize(workspaceId, itemId),
		itemKeys.overview(workspaceId, itemId),
		libraryKeys.lists(workspaceId),
		dashboardKeys.all(workspaceId)
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
export function invalidateCitationStyles(queryClient: QueryClient, workspaceId: string) {
	// Installed styles feed the Tools catalog and every Account export preference.
	return invalidate(queryClient, [toolKeys.all(workspaceId), exportPreferenceKeys.all]);
}
export function invalidateLibrary(queryClient: QueryClient, workspaceId: string) {
	return invalidate(queryClient, [libraryKeys.all(workspaceId), dashboardKeys.all(workspaceId)]);
}
export function invalidateProject(queryClient: QueryClient, workspaceId: string) {
	// The reader annotation sources project each linked Project's name and
	// editability, so Project changes refresh every cached reader configuration.
	return invalidate(queryClient, [
		projectKeys.all(workspaceId),
		libraryKeys.all(workspaceId),
		dashboardKeys.all(workspaceId),
		pdfReaderKeys.all(workspaceId)
	]);
}

export async function invalidateUnavailableProject(
	queryClient: QueryClient,
	workspaceId: string,
	projectId: string
) {
	const lists = libraryKeys.lists(workspaceId);
	const libraryScope = {
		queryKey: lists,
		predicate: ({ queryKey }: Query) =>
			(queryKey[lists.length] as LibraryFilters | undefined)?.project === projectId
	};
	const organizeScope = {
		queryKey: itemKeys.all(workspaceId),
		predicate: ({ queryKey }: Query) => queryKey.at(-1) === 'organize'
	};
	// A denied Project audience affects cached working sets and every Item's
	// organization projection. Late responses must not restore those associations.
	await Promise.all([
		queryClient.cancelQueries(libraryScope, { revert: false }),
		queryClient.cancelQueries(organizeScope, { revert: false })
	]);
	queryClient.setQueriesData<LibrarySearch | null>(libraryScope, null, { updatedAt: 0 });
	queryClient.setQueriesData<OrganizeView>(
		organizeScope,
		(data) =>
			data && { ...data, projects: data.projects.filter((project) => project.id !== projectId) }
	);
	await invalidateProject(queryClient, workspaceId);
}

export function invalidateWorkspaces(queryClient: QueryClient) {
	// The Workspace directory and each caller's eligibility in it feed every
	// Workspace-scoped projection, such as an Item's copy destinations.
	return invalidate(queryClient, [workspaceKeys.list(), workspaceKeys.all()]);
}
