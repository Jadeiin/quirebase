<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { components } from '#lib/api/schema.js';
	import Badge from '#lib/design/Badge.svelte';
	import Button from '#lib/design/Button.svelte';
	import DataTable from '#lib/design/DataTable.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { dateTimeFormat } from '#lib/format.js';
	import { t } from 'lingui-for-svelte/macro';

	let {
		invitations,
		busy,
		pagination,
		onRefresh,
		onCreateInvitation,
		onRevokeInvitation,
		onReissueInvitation
	}: {
		invitations: components['schemas']['OffsetPagination_AdminInvitationView_'];
		busy: boolean;
		pagination: Snippet;
		onRefresh: () => void;
		onCreateInvitation: (event: SubmitEvent) => void;
		onRevokeInvitation: (id: string) => void;
		onReissueInvitation: (id: string) => void;
	} = $props();
	let createOpen = $state(false);
</script>

<SectionHeader spacing="compact">
	<div>
		<h2>{$t`Invitations`} <span class="text-surface-600-400">({invitations.total})</span></h2>
		<p class="text-sm text-surface-600-400">
			{$t`Create sign-up links and track who has accepted them.`}
		</p>
	</div>
	{#snippet actions()}
		<Button type="button" disabled={busy} onclick={onRefresh}>{$t`Refresh`}</Button>
		<Button
			variant="filled"
			disabled={busy}
			aria-expanded={createOpen}
			onclick={() => (createOpen = !createOpen)}>{$t`Invite user`}</Button
		>
	{/snippet}
</SectionHeader>

{#if createOpen}
	<Panel as="form" class="mb-4 grid grid-cols-1 gap-3" onsubmit={onCreateInvitation}>
		<h3>{$t`Create invitation`}</h3>
		<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
			<label
				>{$t`Username`}<input
					disabled={busy}
					class="input"
					name="username"
					maxlength="120"
					required
				/></label
			>
			<label
				>{$t`Role`}<select disabled={busy} class="select" name="role">
					<option value="member">{$t`Member`}</option>
					<option value="administrator">{$t`Administrator`}</option>
				</select></label
			>
		</div>
		<div class="flex flex-wrap gap-2">
			<Button variant="filled" disabled={busy}>{$t`Create invitation`}</Button>
			<Button type="button" disabled={busy} onclick={() => (createOpen = false)}
				>{$t`Cancel`}</Button
			>
		</div>
	</Panel>
{/if}

<Panel padding="none">
	{#if invitations.items.length}
		<DataTable label={$t`Invitations`}>
			<thead>
				<tr>
					<th scope="col">{$t`Username`}</th>
					<th scope="col">{$t`Role`}</th>
					<th scope="col">{$t`Status`}</th>
					<th scope="col">{$t`Created`}</th>
					<th scope="col">{$t`Expires`}</th>
					<th scope="col">{$t`Actions`}</th>
				</tr>
			</thead>
			{#each invitations.items as invitation (invitation.id)}
				<tbody aria-label={invitation.username}>
					<tr>
						<th scope="row" class="font-semibold">{invitation.username}</th>
						<td data-label={$t`Role`}>{$t(domainLabel(invitation.role))}</td>
						<td data-label={$t`Status`}>
							<div class="grid grid-cols-1 justify-items-start gap-1">
								<Badge
									variant={invitation.state === 'pending'
										? 'primary'
										: invitation.state === 'accepted'
											? 'success'
											: invitation.state === 'expired'
												? 'warning'
												: 'surface'}>{$t(domainLabel(invitation.state))}</Badge
								>
								{#if invitation.accepted_at}
									<time class="text-xs text-surface-600-400" datetime={invitation.accepted_at}
										>{$dateTimeFormat.format(new Date(invitation.accepted_at))}</time
									>
								{:else if invitation.revoked_at}
									<time class="text-xs text-surface-600-400" datetime={invitation.revoked_at}
										>{$dateTimeFormat.format(new Date(invitation.revoked_at))}</time
									>
								{/if}
							</div>
						</td>
						<td data-label={$t`Created`}>
							<time datetime={invitation.created_at}
								>{$dateTimeFormat.format(new Date(invitation.created_at))}</time
							>
						</td>
						<td data-label={$t`Expires`}>
							<time datetime={invitation.expires_at}
								>{$dateTimeFormat.format(new Date(invitation.expires_at))}</time
							>
						</td>
						<td data-label={$t`Actions`}>
							{#if invitation.state === 'pending' || invitation.state === 'expired'}
								<div class="flex flex-wrap gap-2">
									<Button
										size="sm"
										disabled={busy}
										onclick={() => onReissueInvitation(invitation.id)}
										>{$t`Reissue invitation link`}</Button
									>
									<Button
										size="sm"
										disabled={busy}
										onclick={() => onRevokeInvitation(invitation.id)}
										>{$t`Revoke invitation`}</Button
									>
								</div>
							{:else}
								<span class="text-surface-600-400">—</span>
							{/if}
						</td>
					</tr>
				</tbody>
			{/each}
		</DataTable>
	{:else}
		<p class="px-5 py-6 text-surface-600-400">{$t`No invitations.`}</p>
	{/if}
	{@render pagination()}
</Panel>
