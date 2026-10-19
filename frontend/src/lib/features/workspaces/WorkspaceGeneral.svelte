<script lang="ts">
	import { createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Button from '#lib/design/Button.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import StatusNotice from '#lib/design/StatusNotice.svelte';
	import { t } from '#lib/i18n.js';
	import { workspaceRenameMutationOptions } from './mutations';

	const workspace = getWorkspaceContext();
	const client = useQueryClient();
	const mutation = createMutation(() =>
		workspaceRenameMutationOptions(workspace.workspaceId, client)
	);
	let draft = $state<string | null>(null);
	let error = $state('');
	let notice = $state('');
	const name = $derived(draft ?? workspace.view?.name ?? '');
	async function saveName() {
		if (mutation.isPending || !name.trim()) return;
		error = '';
		notice = '';
		try {
			await mutation.mutateAsync(name.trim());
			draft = null;
			notice = $t('Workspace name updated');
		} catch (reason) {
			error = apiErrorMessage(reason, 'Workspace action failed');
		}
	}
</script>

<Panel class="grid grid-cols-1 gap-4">
	<div>
		<h2 class="text-xl font-semibold">{$t('General')}</h2>
		<p class="mt-1 text-sm text-surface-700-300">
			{$t('Update the name members see across this workspace.')}
		</p>
	</div>
	{#if workspace.can('workspace.update')}
		<form
			class="grid max-w-2xl grid-cols-1 justify-items-start gap-3"
			onsubmit={(event) => {
				event.preventDefault();
				void saveName();
			}}
		>
			<label class="grid w-full grid-cols-1 gap-1"
				>{$t('Name')}<input
					class="input"
					value={name}
					oninput={(event) => (draft = event.currentTarget.value)}
					maxlength="240"
					required
					disabled={mutation.isPending}
				/></label
			>
			<Button
				type="submit"
				variant="filled"
				disabled={mutation.isPending || !name.trim() || name.trim() === workspace.view?.name}
				>{$t('Save name')}</Button
			>
		</form>
	{:else}<div>
			<p class="text-sm text-surface-700-300">{$t('Name')}</p>
			<p class="font-semibold break-all">{workspace.view?.name}</p>
		</div>{/if}
	<StatusNotice {error} {notice} />
</Panel>
