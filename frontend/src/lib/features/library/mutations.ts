import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { createWorkspaceApi } from '$lib/api/client';
import { invalidateLibrary, invalidateProject } from '$lib/query/invalidation';
import type { ExportPreferences } from '$lib/export-preferences';
import { workspaceKeys } from '$lib/workspaces/keys';

export type LibraryBulkAction = 'add_project' | 'add_tag' | 'bibliography' | 'documents' | 'delete';

export type LibraryBulkInput = {
	action: LibraryBulkAction;
	itemIds: string[];
	projectId: string;
	tagName: string;
	exportFormat: string;
	preferences: ExportPreferences;
};

function bibliographyFilename(format: string): string {
	if (format === 'csl') return 'quirebase-citations.txt';
	const extension = format === 'ris' ? 'ris' : format === 'endnote' ? 'enw' : 'bib';
	return `quirebase-export.${extension}`;
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
		const citation = input.preferences.citation;
		await api.download(
			'/workspaces/{workspace_id}/items/bibliography',
			{
				body: {
					item_ids: input.itemIds,
					file_format: input.exportFormat,
					style: citation.style,
					include_abstract: citation.includeAbstract,
					preserve_case: citation.preserveCase,
					include_identifiers: citation.includeIdentifiers,
					include_custom_fields: citation.includeCustomFields,
					encoding: citation.encoding,
					journal_mode: citation.journalMode,
					doi_policy: citation.doiPolicy,
					url_policy: citation.urlPolicy,
					excluded_fields: citation.excludedFields
						.split(',')
						.map((value) => value.trim())
						.filter(Boolean),
					sort_by: citation.sortBy,
					citation_key_formula: citation.citationKeyFormula,
					citation_key_force_ascii: citation.citationKeyForceAscii
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
			project_id: input.projectId,
			tag_name: input.tagName,
			confirmation: input.action === 'delete' ? 'delete' : ''
		}
	});
	const invalidations = [invalidateLibrary(queryClient, workspaceId)];
	if (input.action === 'add_project' && input.projectId) {
		invalidations.push(invalidateProject(queryClient, workspaceId, input.projectId));
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
		}
	});
}
