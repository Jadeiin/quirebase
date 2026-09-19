<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiErrorMessage } from '$lib/api/errors';
	import Notice from '$lib/design/Notice.svelte';
	import ItemSectionState from '$lib/features/item/ItemSectionState.svelte';
	import {
		addTagMutationOptions,
		projectMembershipMutationOptions,
		suggestedTagMutationOptions,
		tagRecommendationsMutationOptions,
		toggleTagMutationOptions
	} from '$lib/features/item/organize/mutations';
	import ItemOrganizeSection from '$lib/features/item/organize/ItemOrganizeSection.svelte';
	import { itemOrganizeQuery } from '$lib/features/item/queries';
	import type { OrganizeView } from '$lib/features/item/types';
	import { getWorkflowCenter } from '$lib/features/workflows/center.svelte';
	import { msg, t } from '$lib/i18n';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
	let mutationError = $state('');
	const queryClient = useQueryClient();
	const workflows = getWorkflowCenter();
	const organize = createQuery(() => itemOrganizeQuery(params.itemId, true));

	async function trackTagRecommendations(workflowId: string) {
		await workflows.track(workflowId, {
			label: $t('Tag recommendation'),
			successMessage: msg('Tag recommendations updated'),
			failureMessage: msg('Tag recommendation failed')
		}).settled;
	}

	const projectMembership = createMutation(() =>
		projectMembershipMutationOptions(params.itemId, queryClient)
	);
	const addTagMutation = createMutation(() => addTagMutationOptions(params.itemId, queryClient));
	const toggleTagMutation = createMutation(() =>
		toggleTagMutationOptions(params.itemId, queryClient)
	);
	const suggestedTagMutation = createMutation(() =>
		suggestedTagMutationOptions(params.itemId, queryClient)
	);
	const tagRecommendationsMutation = createMutation(() =>
		tagRecommendationsMutationOptions(params.itemId, queryClient, trackTagRecommendations)
	);
	const busy = $derived(
		projectMembership.isPending ||
			addTagMutation.isPending ||
			toggleTagMutation.isPending ||
			suggestedTagMutation.isPending ||
			tagRecommendationsMutation.isPending
	);

	function track(promise: Promise<unknown>) {
		mutationError = '';
		void promise.catch((error) => {
			mutationError = apiErrorMessage(error, $t('Unable to save changes'));
		});
	}

	function toggleProject(project: OrganizeView['projects'][number]) {
		track(projectMembership.mutateAsync({ project }));
	}

	function addTag(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const name = String(new FormData(form).get('name') ?? '').trim();
		if (name) track(addTagMutation.mutateAsync({ form, name }));
	}

	function toggleTagAssignment(tagId: string, assigned: boolean) {
		track(toggleTagMutation.mutateAsync({ tagId, assigned }));
	}

	function addSuggestedTag(name: string) {
		track(suggestedTagMutation.mutateAsync({ name }));
	}

	function refreshTagRecommendations() {
		track(tagRecommendationsMutation.mutateAsync());
	}
</script>

{#if mutationError}<Notice variant="error">{mutationError}</Notice>{/if}
<ItemSectionState loading={organize.isPending} failed={organize.isError}>
	<ItemOrganizeSection
		data={organize.data!}
		{busy}
		onToggleProject={toggleProject}
		onAddTag={addTag}
		onToggleTag={toggleTagAssignment}
		onAddSuggestedTag={addSuggestedTag}
		onRefresh={refreshTagRecommendations}
	/>
</ItemSectionState>
