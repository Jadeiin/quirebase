<script lang="ts">
	import { Dialog, Portal } from '@skeletonlabs/skeleton-svelte';
	import { createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import type { components } from '#lib/api/schema.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { getSession } from '#lib/session.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { setDefaultWorkspacePreference } from '#lib/workspaces/preference.js';
	import Button from '#lib/design/Button.svelte';
	import { buttonClass } from '#lib/design/button-classes.js';
	import DialogCloseButton from '#lib/design/DialogCloseButton.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import { t } from 'lingui-for-svelte/macro';
	import { workspaceCreationMutationOptions } from './mutations';

	let {
		open = $bindable(false),
		availability,
		onCreated
	}: {
		open: boolean;
		availability: components['schemas']['WorkspaceCreationAvailabilityView'];
		onCreated: (message: string) => void;
	} = $props();
	const client = useQueryClient();
	const session = getSession().query;
	const mutation = createMutation(() => workspaceCreationMutationOptions(client));
	let name = $state('');
	let ownerUsername = $state('');
	let error = $state('');
	async function create() {
		if (
			!availability.allowed ||
			mutation.isPending ||
			!name.trim() ||
			(availability.owner_username_required && !ownerUsername.trim())
		)
			return;
		error = '';
		try {
			const owner = ownerUsername.trim();
			const needsOwner = availability.owner_username_required;
			const assignedToSelf = !needsOwner || owner === session.data?.user?.username;
			const created = await mutation.mutateAsync({
				name: name.trim(),
				...(needsOwner ? { owner_username: owner } : {})
			});
			open = false;
			name = '';
			ownerUsername = '';
			if (assignedToSelf) {
				setDefaultWorkspacePreference(created.id);
				await goto(resolve(workspaceHref(created.id)), { replace: true });
			} else {
				onCreated(
					$t`Workspace created. Its owner can open it; you have no content access unless you are also a member.`
				);
			}
		} catch (reason) {
			error = apiErrorMessage(reason, $t`Unable to create workspace`);
		}
	}
</script>

<Dialog
	{open}
	onOpenChange={(details) => {
		if (!mutation.isPending) open = details.open;
	}}
>
	<Portal>
		<Dialog.Backdrop class="fixed inset-0 z-70 bg-surface-950/45 backdrop-blur-[2px]" />
		<Dialog.Positioner class="fixed inset-0 z-71 grid grid-cols-1 place-items-center p-4">
			<Dialog.Content
				class="w-full max-w-lg rounded-container border border-surface-300-700 bg-surface-50-950 p-5 shadow-2xl"
			>
				<div class="flex items-center justify-between gap-3">
					<Dialog.Title class="text-xl font-semibold">{$t`Create a workspace`}</Dialog.Title
					><DialogCloseButton disabled={mutation.isPending} />
				</div>
				<p class="mt-2 text-sm text-surface-700-300">
					{#if availability.owner_username_required}{$t`Choose an active user to own this workspace. Instance administrators do not automatically get content access.`}{:else}{$t`You will own this Workspace and can invite members.`}{/if}
				</p>
				{#if error}<Notice variant="error" class="mt-3">{error}</Notice>{/if}
				<form
					class="mt-4 grid grid-cols-1 gap-4"
					onsubmit={(event) => {
						event.preventDefault();
						void create();
					}}
				>
					<label class="grid grid-cols-1 gap-1"
						>{$t`Workspace name`}<input
							class="input"
							bind:value={name}
							required
							minlength="1"
							maxlength="240"
							autocomplete="organization"
							disabled={mutation.isPending}
						/></label
					>
					{#if availability.owner_username_required}<label class="grid grid-cols-1 gap-1"
							>{$t`Owner username (exact match)`}<input
								class="input"
								bind:value={ownerUsername}
								required
								maxlength="120"
								autocomplete="username"
								disabled={mutation.isPending}
							/></label
						>{/if}
					<div class="flex flex-wrap justify-end gap-2">
						<Dialog.CloseTrigger class={buttonClass('tonal')} disabled={mutation.isPending}
							>{$t`Cancel`}</Dialog.CloseTrigger
						>
						<Button
							type="submit"
							variant="filled"
							disabled={mutation.isPending ||
								!name.trim() ||
								(availability.owner_username_required && !ownerUsername.trim())}
							>{$t`Create workspace`}</Button
						>
					</div>
				</form>
			</Dialog.Content>
		</Dialog.Positioner>
	</Portal>
</Dialog>
