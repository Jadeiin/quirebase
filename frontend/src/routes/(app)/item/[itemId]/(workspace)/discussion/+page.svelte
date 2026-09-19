<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiErrorMessage } from '$lib/api/errors';
	import Notice from '$lib/design/Notice.svelte';
	import {
		discussionCreateMutationOptions,
		discussionDeleteMutationOptions
	} from '$lib/features/item/discussion/mutations';
	import ItemDiscussionSection from '$lib/features/item/discussion/ItemDiscussionSection.svelte';
	import ItemSectionState from '$lib/features/item/ItemSectionState.svelte';
	import { itemDiscussionQuery } from '$lib/features/item/queries';
	import { t } from '$lib/i18n';
	import { getSession } from '$lib/session';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
	let mutationError = $state('');
	const queryClient = useQueryClient();
	const { query: session } = getSession();
	const discussion = createQuery(() => itemDiscussionQuery(params.itemId, true));
	const discussionCreate = createMutation(() =>
		discussionCreateMutationOptions(params.itemId, queryClient)
	);
	const discussionDelete = createMutation(() =>
		discussionDeleteMutationOptions(params.itemId, queryClient)
	);

	function track(promise: Promise<unknown>) {
		mutationError = '';
		void promise.catch((error) => {
			mutationError = apiErrorMessage(error, $t('Unable to save changes'));
		});
	}

	function addDiscussion(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const body = String(new FormData(form).get('body') ?? '').trim();
		if (body) track(discussionCreate.mutateAsync({ form, body }));
	}

	function deleteDiscussion(messageId: string) {
		track(discussionDelete.mutateAsync({ messageId }));
	}
</script>

{#if mutationError}<Notice variant="error">{mutationError}</Notice>{/if}
<ItemSectionState loading={discussion.isPending} failed={discussion.isError}>
	<ItemDiscussionSection
		messages={discussion.data!}
		userId={session.data?.user?.id}
		isAdministrator={session.data?.user?.role === 'administrator'}
		busy={discussionCreate.isPending || discussionDelete.isPending}
		onAdd={addDiscussion}
		onDelete={deleteDiscussion}
	/>
</ItemSectionState>
