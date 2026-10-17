<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { components } from '#lib/api/schema.js';
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import ItemRow from '#lib/design/ItemRow.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { dateTimeFormat } from '#lib/format.js';
	import { t } from '#lib/i18n.js';
	import type { InvitationState } from './queries.js';

	let {
		invitations,
		busy,
		invitationUrl,
		invitationState,
		onInvitationState,
		pagination,
		onCreateInvitation,
		onRevokeInvitation,
		onReissueInvitation
	}: {
		invitations: components['schemas']['OffsetPagination_AdminInvitationView_'];
		busy: boolean;
		invitationUrl: string;
		invitationState: InvitationState | '';
		onInvitationState: (state: InvitationState | '') => void;
		pagination: Snippet;
		onCreateInvitation: (event: SubmitEvent) => void;
		onRevokeInvitation: (id: string) => void;
		onReissueInvitation: (id: string) => void;
	} = $props();
	let createOpen = $state(false);
</script>

<SectionHeader spacing="compact">
	<div>
		<h2>{$t('Invitations')} <span class="text-surface-600-400">({invitations.total})</span></h2>
		<p class="text-sm text-surface-600-400">
			{$t('Create sign-up links and track who has accepted them.')}
		</p>
	</div>
	{#snippet actions()}
		<Button
			variant="filled"
			disabled={busy}
			aria-expanded={createOpen}
			onclick={() => (createOpen = !createOpen)}>{$t('Invite user')}</Button
		>
	{/snippet}
</SectionHeader>

{#if createOpen}
	<Panel as="form" class="mb-4 grid grid-cols-1 gap-3" onsubmit={onCreateInvitation}>
		<h3>{$t('Create invitation')}</h3>
		<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
			<label>{$t('Username')}<input class="input" name="username" maxlength="120" required /></label
			>
			<label
				>{$t('Role')}<select class="select" name="role">
					<option value="member">{$t('Member')}</option>
					<option value="administrator">{$t('Administrator')}</option>
				</select></label
			>
		</div>
		<div class="flex flex-wrap gap-2">
			<Button variant="filled" disabled={busy}>{$t('Create invitation')}</Button>
			<Button type="button" disabled={busy} onclick={() => (createOpen = false)}
				>{$t('Cancel')}</Button
			>
		</div>
	</Panel>
{/if}

{#if invitationUrl}
	<Notice as="div" variant="warning" class="mb-4 grid grid-cols-1 gap-2 [overflow-wrap:anywhere]">
		<strong>{$t('Copy this invitation URL now')}</strong>
		<a href={invitationUrl} rel="external">{invitationUrl}</a>
	</Notice>
{/if}

<Panel>
	<div class="mb-3 max-w-xs">
		<label for="admin-invitation-state">{$t('Invitation status')}</label>
		<select
			id="admin-invitation-state"
			class="select"
			value={invitationState}
			disabled={busy}
			onchange={(event) => onInvitationState(event.currentTarget.value as InvitationState | '')}
		>
			<option value="">{$t('All')}</option>
			<option value="pending">{$t('Pending')}</option>
			<option value="expired">{$t('Expired')}</option>
			<option value="revoked">{$t('Revoked')}</option>
			<option value="accepted">{$t('Accepted')}</option>
		</select>
	</div>
	{#each invitations.items as invitation (invitation.id)}
		<ItemRow as="article">
			<div class="flex flex-wrap items-start justify-between gap-3">
				<div class="min-w-0">
					<strong class="break-words">{invitation.username}</strong>
					<p class="text-sm text-surface-600-400">{$t(domainLabel(invitation.role))}</p>
				</div>
				<Badge
					variant={invitation.state === 'pending'
						? 'primary'
						: invitation.state === 'accepted'
							? 'success'
							: invitation.state === 'expired'
								? 'warning'
								: 'surface'}>{$t(domainLabel(invitation.state))}</Badge
				>
			</div>
			<div class="flex flex-wrap gap-x-5 gap-y-1 text-sm text-surface-600-400">
				<span>{$t('Created')} {$dateTimeFormat.format(new Date(invitation.created_at))}</span>
				{#if invitation.accepted_at}
					<span>{$t('Accepted')} {$dateTimeFormat.format(new Date(invitation.accepted_at))}</span>
				{:else if invitation.revoked_at}
					<span>{$t('Revoked')} {$dateTimeFormat.format(new Date(invitation.revoked_at))}</span>
				{:else}
					<span>{$t('Expires')} {$dateTimeFormat.format(new Date(invitation.expires_at))}</span>
				{/if}
			</div>
			{#if invitation.state === 'pending' || invitation.state === 'expired'}
				<div class="mt-2 flex flex-wrap gap-2">
					<Button disabled={busy} onclick={() => onReissueInvitation(invitation.id)}
						>{$t('Reissue invitation link')}</Button
					>
					<Button disabled={busy} onclick={() => onRevokeInvitation(invitation.id)}
						>{$t('Revoke invitation')}</Button
					>
				</div>
			{/if}
		</ItemRow>
	{:else}
		<p class="py-6 text-surface-600-400">{$t('No invitations.')}</p>
	{/each}
	{@render pagination()}
</Panel>
