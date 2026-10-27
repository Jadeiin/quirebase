<script lang="ts">
	import Panel from '#lib/design/Panel.svelte';
	import { can } from '#lib/authorization/can.js';
	import { dateTimeFormat } from '#lib/format.js';
	import { t } from 'lingui-for-svelte/macro';
	import type { DiscussionMessage } from '../types';
	import Button from '#lib/design/Button.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';

	let {
		messages,
		canWrite,
		busy,
		onAdd,
		onDelete,
		onModerate
	}: {
		messages: DiscussionMessage[];
		canWrite: boolean;
		busy: boolean;
		onAdd: (event: SubmitEvent) => void;
		onDelete: (messageId: string) => void;
		onModerate: (messageId: string) => void;
	} = $props();
</script>

<Panel class="mt-4">
	<h2>{$t`Discussion`}</h2>
	{#each messages as message (message.id)}
		<ItemRow>
			<div class="flex flex-wrap justify-between gap-2">
				<strong>{message.author_username}</strong>
				{#if message.mine && can(message.authorization, 'item_discussion.delete')}
					<Button variant="danger" disabled={busy} onclick={() => onDelete(message.id)}
						>{$t`Delete`}</Button
					>
				{/if}
				{#if !message.mine && can(message.authorization, 'item_discussion.delete')}
					<Button variant="danger" disabled={busy} onclick={() => onModerate(message.id)}
						>{$t`Moderate`}</Button
					>{/if}
			</div>
			<span>{message.body}</span><span class="text-surface-600-400"
				>{$dateTimeFormat.format(new Date(message.created_at))}</span
			>
		</ItemRow>
	{:else}
		<p class="text-surface-600-400">{$t`No discussion messages.`}</p>
	{/each}
	{#if canWrite}<form class="grid grid-cols-1 gap-3" onsubmit={onAdd}>
			<label
				>{$t`Add message`}<textarea class="textarea" name="body" rows="4" required
				></textarea></label
			><Button variant="filled" class="justify-self-start" disabled={busy}
				>{$t`Post message`}</Button
			>
		</form>{/if}
</Panel>
