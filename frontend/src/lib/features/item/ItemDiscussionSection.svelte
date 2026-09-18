<script lang="ts">
	import { t } from '$lib/i18n';
	import type { DiscussionMessage } from './types';

	let { messages, userId, isAdministrator, busy, onAdd, onDelete } = $props<{
		messages: DiscussionMessage[];
		userId?: string;
		isAdministrator: boolean;
		busy: boolean;
		onAdd: (event: SubmitEvent) => void;
		onDelete: (messageId: string) => void;
	}>();
</script>

<section class="list-panel card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
	<h2>{$t('Discussion')}</h2>
	{#each messages as message (message.id)}
		<div class="item-row">
			<div class="toolbar justify-between">
				<strong>{message.author_username}</strong>
				{#if message.author_id === userId || isAdministrator}
					<button
						class="btn preset-tonal-error font-semibold"
						disabled={busy}
						onclick={() => onDelete(message.id)}>{$t('Delete')}</button
					>
				{/if}
			</div>
			<span>{message.body}</span><span class="text-surface-600-400"
				>{new Date(message.created_at).toLocaleString()}</span
			>
		</div>
	{:else}
		<p class="text-surface-600-400">{$t('No discussion messages.')}</p>
	{/each}
	<form class="stack" onsubmit={onAdd}>
		<label
			>{$t('Add message')}<textarea class="textarea" name="body" rows="4" required
			></textarea></label
		><button class="btn preset-filled-primary-700-300 font-semibold" disabled={busy}
			>{$t('Post message')}</button
		>
	</form>
</section>
