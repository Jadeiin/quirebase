<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import type { components } from '$lib/api/schema';
	import { ApiError } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import Notice from '$lib/design/Notice.svelte';
	import ItemSectionState from '$lib/features/item/ItemSectionState.svelte';
	import ItemMetadataSection from '$lib/features/item/metadata/ItemMetadataSection.svelte';
	import { metadataMutationOptions } from '$lib/features/item/metadata/mutations';
	import { itemDetailsQuery, itemOverviewQuery } from '$lib/features/item/queries';
	import type { ItemDetail } from '$lib/features/item/types';
	import { t } from '$lib/i18n';
	import type { PageProps } from './$types';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';

	let { params }: PageProps = $props();
	let mutationError = $state('');
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const overview = createQuery(() => itemOverviewQuery(params.workspaceId, params.itemId));
	const details = createQuery(() => itemDetailsQuery(params.workspaceId, params.itemId, true));
	const metadataMutation = createMutation(() =>
		metadataMutationOptions(params.workspaceId, params.itemId, queryClient)
	);

	function updateMetadata(item: ItemDetail, metadata: components['schemas']['ItemMetadata-Input']) {
		if (!workspace.can('items.edit')) return;
		mutationError = '';
		void metadataMutation.mutateAsync({ item, metadata }).catch(async (error) => {
			if (error instanceof ApiError && error.status === 409) {
				await Promise.all([details.refetch(), overview.refetch()]);
				mutationError = $t(
					'This Item changed since it was loaded. Latest metadata was loaded; review it and submit again.'
				);
				return;
			}
			mutationError = apiErrorMessage(error, $t('Unable to save changes'));
		});
	}
</script>

{#if mutationError}<Notice variant="error">{mutationError}</Notice>{/if}
<ItemSectionState loading={details.isPending} failed={details.isError}>
	<ItemMetadataSection
		item={details.data!}
		canEdit={(overview.data?.allowed_actions.edit ?? false) && workspace.can('items.edit')}
		busy={metadataMutation.isPending}
		onSubmit={updateMetadata}
	/>
</ItemSectionState>
