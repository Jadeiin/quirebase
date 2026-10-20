import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { ApiError, createWorkspaceApi } from '#lib/api/client.js';
import {
	invalidateLibrary,
	invalidateProject,
	invalidateTags,
	invalidateUnavailableProject
} from '#lib/query/invalidation.js';
import {
	bibliographyExportParameters,
	bibliographyFilename,
	type ExportPreferences
} from '#lib/export-preferences.js';
import { workspaceKeys } from '#lib/workspaces/keys.js';

export type LibraryBulkAction =
	| 'add_project'
	| 'remove_project'
	| 'add_tag'
	| 'remove_tag'
	| 'bibliography'
	| 'documents'
	| 'delete';

export type LibraryBulkInput = {
	action: LibraryBulkAction;
	itemIds: string[];
	projectId: string;
	tagName: string;
	tagId?: string;
	exportFormat: string;
	preferences: ExportPreferences;
};

function archiveFilename(includeAnnotations: boolean, includeSupplements: boolean): string {
	const kind =
		includeAnnotations && includeSupplements
			? 'annotated-bundle'
			: includeAnnotations
				? 'annotated-pdfs'
				: includeSupplements
					? 'bundle'
					: 'pdfs';
	return `quirebase-selected-${kind}.zip`;
}

export async function runLibraryBulkDownload(
	workspaceId: string,
	input: LibraryBulkInput
): Promise<void> {
	const api = createWorkspaceApi(workspaceId);
	if (input.action === 'bibliography') {
		await api.download(
			'/workspaces/{workspace_id}/items/bibliography',
			{
				body: {
					item_ids: input.itemIds,
					...bibliographyExportParameters(input.preferences.citation, input.exportFormat)
				}
			},
			{ suggestedName: bibliographyFilename(input.exportFormat) }
		);
		return;
	}
	await api.download(
		'/workspaces/{workspace_id}/items/documents/archive',
		{
			body: {
				item_ids: input.itemIds,
				include_annotations: input.preferences.document.includeAnnotations,
				include_supplements: input.preferences.document.includeSupplements,
				timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
			}
		},
		{
			suggestedName: archiveFilename(
				input.preferences.document.includeAnnotations,
				input.preferences.document.includeSupplements
			)
		}
	);
}

export async function runLibraryBulkMutation(
	workspaceId: string,
	input: LibraryBulkInput,
	queryClient: QueryClient
): Promise<void> {
	const api = createWorkspaceApi(workspaceId);
	await api.request('POST', '/workspaces/{workspace_id}/items/bulk', {
		body: {
			item_ids: input.itemIds,
			action: input.action,
			project_id:
				input.action === 'add_project' || input.action === 'remove_project'
					? input.projectId || undefined
					: undefined,
			tag_name: input.action === 'add_tag' ? input.tagName : '',
			tag_id: input.action === 'remove_tag' ? input.tagId || undefined : undefined,
			confirmation:
				input.action === 'delete'
					? 'delete'
					: input.action === 'remove_project'
						? 'remove_project'
						: ''
		}
	});
	const changesProjects =
		input.action === 'delete' ||
		input.action === 'add_project' ||
		input.action === 'remove_project';
	// Project invalidation includes Library, dashboard and reader projections.
	const invalidations = [
		changesProjects
			? invalidateProject(queryClient, workspaceId)
			: invalidateLibrary(queryClient, workspaceId)
	];
	if (input.action === 'add_tag' || input.action === 'remove_tag' || input.action === 'delete') {
		invalidations.push(invalidateTags(queryClient, workspaceId));
	}
	await Promise.all(invalidations);
}

export type LibraryBulkMutation = {
	input: LibraryBulkInput;
	afterMutation?: () => void;
};

export function libraryBulkMutationOptions(workspaceId: string, queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: workspaceKeys.mutation(workspaceId, 'library-bulk'),
		mutationFn: async ({ input }: LibraryBulkMutation) => {
			if (input.action === 'bibliography' || input.action === 'documents') {
				await runLibraryBulkDownload(workspaceId, input);
				return;
			}
			await runLibraryBulkMutation(workspaceId, input, queryClient);
		},
		onSuccess: async (_result, mutation) => {
			mutation.afterMutation?.();
		},
		onError: async (reason, { input }) => {
			if (
				(input.action !== 'add_project' && input.action !== 'remove_project') ||
				!(reason instanceof ApiError)
			)
				return;
			if ([403, 404].includes(reason.status) && input.projectId) {
				await invalidateUnavailableProject(queryClient, workspaceId, input.projectId);
			} else if (reason.code === 'project_lifecycle_error') {
				await invalidateProject(queryClient, workspaceId);
			}
		}
	});
}
