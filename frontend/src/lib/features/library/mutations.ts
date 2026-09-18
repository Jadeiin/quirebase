import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { apiDownload, apiRequest } from '$lib/api/client';
import type { ExportPreferences } from '$lib/export-preferences';

export type LibraryBulkAction = 'add_project' | 'add_tag' | 'bibliography' | 'documents' | 'delete';

export type LibraryBulkInput = {
	action: LibraryBulkAction;
	itemIds: string[];
	projectId: string;
	tagName: string;
	exportFormat: string;
	preferences: ExportPreferences;
};

export async function runLibraryBulkDownload(input: LibraryBulkInput): Promise<void> {
	if (input.action === 'bibliography') {
		const citation = input.preferences.citation;
		await apiDownload('/items/bibliography', {
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
		});
		return;
	}
	await apiDownload('/items/documents/archive', {
		body: {
			item_ids: input.itemIds,
			include_annotations: input.preferences.document.includeAnnotations,
			include_supplements: input.preferences.document.includeSupplements,
			timezone: Intl.DateTimeFormat().resolvedOptions().timeZone
		}
	});
}

export async function runLibraryBulkMutation(
	input: LibraryBulkInput,
	queryClient: QueryClient
): Promise<void> {
	await apiRequest('POST', '/items/bulk', {
		body: {
			item_ids: input.itemIds,
			action: input.action,
			project_id: input.projectId,
			tag_name: input.tagName,
			confirmation: input.action === 'delete' ? 'delete' : ''
		}
	});
	const invalidations = [
		queryClient.invalidateQueries({ queryKey: ['library'] }),
		queryClient.invalidateQueries({ queryKey: ['dashboard'] })
	];
	if (input.action === 'add_project' && input.projectId) {
		invalidations.push(
			queryClient.invalidateQueries({ queryKey: ['project', input.projectId] }),
			queryClient.invalidateQueries({ queryKey: ['projects'] })
		);
	}
	await Promise.all(invalidations);
}

export type LibraryBulkMutation = {
	input: LibraryBulkInput;
	afterMutation?: () => void;
};

export function libraryBulkMutationOptions(queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: ['library-bulk'],
		mutationFn: async ({ input }: LibraryBulkMutation) => {
			if (input.action === 'bibliography' || input.action === 'documents') {
				await runLibraryBulkDownload(input);
				return;
			}
			await runLibraryBulkMutation(input, queryClient);
		},
		onSuccess: async (_result, mutation) => {
			mutation.afterMutation?.();
		}
	});
}
