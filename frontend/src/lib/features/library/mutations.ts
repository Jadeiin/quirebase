import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { ApiError, createWorkspaceApi } from '#lib/api/client.js';
import type { paths } from '#lib/api/schema.js';
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

type LibraryMutationRequest =
	paths['/api/v1/workspaces/{workspace_id}/items/bulk']['post']['requestBody']['content']['application/json'];

export type LibraryBulkAction =
	LibraryMutationRequest['action'] | 'copy_bibliography' | 'bibliography' | 'documents';

export type LibraryBulkInput = {
	action: LibraryBulkAction;
	itemIds: string[];
	projectId: string;
	tagName: string;
	tagId?: string;
	exportFormat: string;
	preferences: ExportPreferences;
};

export async function readLibraryBibliography(
	workspaceId: string,
	input: Pick<LibraryBulkInput, 'itemIds' | 'preferences' | 'exportFormat'>
): Promise<string> {
	return createWorkspaceApi(workspaceId).request(
		'POST',
		'/workspaces/{workspace_id}/items/bibliography',
		{
			body: {
				item_ids: input.itemIds,
				...bibliographyExportParameters(input.preferences.citation, input.exportFormat)
			},
			headers: { Accept: '*/*' },
			parseAs: 'text'
		}
	);
}

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
	if (
		input.action === 'copy_bibliography' ||
		input.action === 'bibliography' ||
		input.action === 'documents'
	) {
		throw new Error('Exports must use the Library export operations');
	}
	const api = createWorkspaceApi(workspaceId);
	const body: LibraryMutationRequest = (() => {
		const item_ids = input.itemIds;
		switch (input.action) {
			case 'add_project':
				return { action: input.action, item_ids, project_id: input.projectId };
			case 'remove_project':
				return {
					action: input.action,
					item_ids,
					project_id: input.projectId
				};
			case 'add_tag':
				return { action: input.action, item_ids, tag_name: input.tagName };
			case 'remove_tag':
				return { action: input.action, item_ids, tag_id: input.tagId ?? '' };
			case 'delete_items':
				return { action: input.action, item_ids };
			default:
				throw new Error('Exports must use the Library export operations');
		}
	})();
	await api.request('POST', '/workspaces/{workspace_id}/items/bulk', {
		body
	});
	const changesProjects =
		input.action === 'delete_items' ||
		input.action === 'add_project' ||
		input.action === 'remove_project';
	// Project invalidation includes Library, dashboard and reader projections.
	const invalidations = [
		changesProjects
			? invalidateProject(queryClient, workspaceId)
			: invalidateLibrary(queryClient, workspaceId)
	];
	if (
		input.action === 'add_tag' ||
		input.action === 'remove_tag' ||
		input.action === 'delete_items'
	) {
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
			if (input.action === 'copy_bibliography') {
				return readLibraryBibliography(workspaceId, input);
			}
			if (input.action === 'bibliography' || input.action === 'documents') {
				await runLibraryBulkDownload(workspaceId, input);
				return;
			}
			await runLibraryBulkMutation(workspaceId, input, queryClient);
		},
		onSuccess: async (_result, mutation) => {
			if (
				mutation.input.action !== 'copy_bibliography' &&
				mutation.input.action !== 'bibliography' &&
				mutation.input.action !== 'documents'
			) {
				mutation.afterMutation?.();
			}
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
