<script lang="ts">
	import Panel from '$lib/design/Panel.svelte';
	import { dateTimeFormat } from '$lib/format';
	import { t } from '$lib/i18n';
	import type { DiscussionMessage } from '../types';
	import Button from '$lib/design/Button.svelte';
	import ItemRow from '$lib/design/ItemRow.svelte';

	let { messages, userId, isAdministrator, busy, onAdd, onDelete } = $props<{
		messages: DiscussionMessage[];
		userId?: string;
		isAdministrator: boolean;
		busy: boolean;
		onAdd: (event: SubmitEvent) => void;
		onDelete: (messageId: string) => void;
	}>();
</script>

<Panel class="mt-4">
	<h2>{$t('Discussion')}</h2>
	{#each messages as message (message.id)}
		<ItemRow>
			<div class="flex flex-wrap justify-between gap-2">
				<strong>{message.author_username}</strong>
				{#if message.author_id === userId || isAdministrator}
					<Button variant="danger" disabled={busy} onclick={() => onDelete(message.id)}
						>{$t('Delete')}</Button
					>
				{/if}
			</div>
			<span>{message.body}</span><span class="text-surface-600-400"
				>{$dateTimeFormat.format(new Date(message.created_at))}</span
			>
		</ItemRow>
	{:else}
		<p class="text-surface-600-400">{$t('No discussion messages.')}</p>
	{/each}
	<form class="grid grid-cols-1 gap-3" onsubmit={onAdd}>
		<label
			>{$t('Add message')}<textarea class="textarea" name="body" rows="4" required
			></textarea></label
		><Button variant="filled" disabled={busy}>{$t('Post message')}</Button>
	</form>
</Panel>
