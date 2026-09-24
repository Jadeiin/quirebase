<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import type { components } from '$lib/api/schema';
	import { apiErrorMessage } from '$lib/api/errors';
	import Notice from '$lib/design/Notice.svelte';
	import ItemSectionState from '$lib/features/item/ItemSectionState.svelte';
	import ItemMetadataSection from '$lib/features/item/metadata/ItemMetadataSection.svelte';
	import { metadataMutationOptions } from '$lib/features/item/metadata/mutations';
	import { itemDetailsQuery, itemOverviewQuery } from '$lib/features/item/queries';
	import type { ItemDetail } from '$lib/features/item/types';
	import { t } from '$lib/i18n';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
	let mutationError = $state('');
	const queryClient = useQueryClient();
	const overview = createQuery(() => itemOverviewQuery(params.workspaceId, params.itemId));
	const details = createQuery(() => itemDetailsQuery(params.workspaceId, params.itemId, true));
	const metadataMutation = createMutation(() =>
		metadataMutationOptions(params.workspaceId, params.itemId, queryClient)
	);

	function updateMetadata(item: ItemDetail, metadata: components['schemas']['ItemMetadata-Input']) {
		mutationError = '';
		void metadataMutation.mutateAsync({ item, metadata }).catch((error) => {
			mutationError = apiErrorMessage(error, $t('Unable to save changes'));
		});
	}
</script>

{#if mutationError}<Notice variant="error">{mutationError}</Notice>{/if}
<ItemSectionState loading={details.isPending} failed={details.isError}>
	<ItemMetadataSection
		item={details.data!}
		canEdit={overview.data?.allowed_actions.edit ?? false}
		busy={metadataMutation.isPending}
		onSubmit={updateMetadata}
	/>
</ItemSectionState>
