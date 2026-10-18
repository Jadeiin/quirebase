<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import type { components } from '#lib/api/schema.js';
	import { ApiError } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { can } from '#lib/authorization/can.js';
	import Notice from '#lib/design/Notice.svelte';
	import Button from '#lib/design/Button.svelte';
	import LoadingState from '#lib/design/LoadingState.svelte';
	import ItemMetadataSection from '#lib/features/item/metadata/ItemMetadataSection.svelte';
	import { metadataMutationOptions } from '#lib/features/item/metadata/mutations.js';
	import { itemOverviewQuery } from '#lib/features/item/queries.js';
	import type { ItemDetail } from '#lib/features/item/types.js';
	import { t } from '#lib/i18n.js';
	import { invalidateItem } from '#lib/query/invalidation.js';
	import type { PageProps } from './$types';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';

	let { params }: PageProps = $props();
	let mutationError = $state('');
	let serverErrors = $state<components['schemas']['ErrorField'][]>([]);
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const overview = createQuery(() => itemOverviewQuery(params.workspaceId, params.itemId));
	const metadataMutation = createMutation(() =>
		metadataMutationOptions(params.workspaceId, params.itemId, queryClient)
	);

	async function updateMetadata(
		item: ItemDetail,
		metadata: components['schemas']['ItemDetailView']['metadata'],
		citationKey: string
	) {
		if (!workspace.can('item.update') || overview.isFetching || overview.isError) return false;
		mutationError = '';
		serverErrors = [];
		try {
			await metadataMutation.mutateAsync({ item, metadata, citationKey });
			return true;
		} catch (error) {
			if (error instanceof ApiError && error.status === 409) {
				await invalidateItem(queryClient, params.workspaceId, params.itemId);
				mutationError = $t(
					'This Item changed since it was loaded. Your draft was preserved; review the latest metadata.'
				);
				return false;
			}
			serverErrors = error instanceof ApiError ? error.fields : [];
			mutationError = apiErrorMessage(error, $t('Unable to save changes'));
			return false;
		}
	}
</script>

{#if mutationError}<Notice variant="error">{mutationError}</Notice>{/if}
{#if overview.isError}
	<Notice as="div" variant="error" class="mb-4 flex flex-wrap items-center justify-between gap-3">
		<span>{$t('Unable to open this Item section.')}</span>
		<Button disabled={overview.isFetching} onclick={() => void overview.refetch()}
			>{$t('Retry')}</Button
		>
	</Notice>
{/if}
{#if overview.data}
	<ItemMetadataSection
		item={overview.data}
		canEdit={can(overview.data?.authorization, 'item.update')}
		busy={metadataMutation.isPending || overview.isFetching || overview.isError}
		{serverErrors}
		onSubmit={updateMetadata}
	/>
{:else if overview.isPending}
	<LoadingState label={$t('Loading') + '…'} />
{/if}
