<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import AuthPage from '$lib/design/AuthPage.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import { invitationQuery } from '$lib/features/auth/queries';
	import { t } from '$lib/i18n';
	import { domainLabel } from '$lib/domain-labels';
	import Button from '$lib/design/Button.svelte';
	import { sessionQuery } from '$lib/session';
	import { setDefaultWorkspacePreference } from '$lib/workspaces/preference';
	let { token } = $props<{ token: string }>();
	let username = $state('');
	let password = $state('');
	let error = $state('');
	let busy = $state(false);
	const invitation = createQuery(() => invitationQuery(token));
	const session = createQuery(() => sessionQuery());
	async function accept() {
		busy = true;
		error = '';
		try {
			const data = invitation.data;
			if (!data) return;
			if (data.kind === 'account') {
				await apiRequest('POST', '/invitations/{token}/accept', {
					params: { path: { token } },
					body: { password }
				});
				location.assign('/');
				return;
			}

			if (session.data?.authenticated !== true) {
				await apiRequest('POST', '/session', { body: { username, password } });
			}
			const accepted = await apiRequest('POST', '/workspace-invitations/{token}/accept', {
				params: { path: { token } }
			});
			setDefaultWorkspacePreference(accepted.workspace_id);
			location.replace(`/workspace/${encodeURIComponent(accepted.workspace_id)}`);
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to accept invitation'));
		} finally {
			busy = false;
		}
	}
</script>

<AuthPage>
	<Panel
		as="form"
		class="grid grid-cols-1 gap-3"
		onsubmit={(event) => {
			event.preventDefault();
			accept();
		}}
	>
		<h1>{$t('Join Quirebase')}</h1>
		{#if invitation.isPending}<p class="text-surface-600-400">
				{$t('Checking invitation…')}
			</p>{:else if invitation.isError}<p class="text-error-700-300">
				{$t('This invitation is invalid or expired.')}
			</p>{:else if invitation.data?.kind === 'account'}
			<p>{$t('Create a password for')} <strong>{invitation.data.invitation.username}</strong>.</p>
			<label
				>{$t('Password')}<input
					class="input"
					type="password"
					bind:value={password}
					minlength="12"
					autocomplete="new-password"
					required
				/></label
			>
			{#if error}<p class="text-error-700-300">{error}</p>{/if}
			<Button variant="filled" type="submit" disabled={busy}>{$t('Create account')}</Button>
		{:else if invitation.data?.kind === 'workspace'}
			<p>
				{$t('Join')} <strong>{invitation.data.invitation.workspace_name}</strong>
				{$t('as')} <strong>{invitation.data.invitation.username}</strong>
				({$t(domainLabel(invitation.data.invitation.role))}).
			</p>
			{#if session.data?.authenticated !== true}
				<p>{$t('Sign in with the invited account to accept this invitation.')}</p>
				<label
					>{$t('Username')}<input
						class="input"
						bind:value={username}
						autocomplete="username"
						required
					/></label
				>
				<label
					>{$t('Password')}<input
						class="input"
						type="password"
						bind:value={password}
						autocomplete="current-password"
						required
					/></label
				>
			{/if}
			{#if error}<p class="text-error-700-300">{error}</p>{/if}
			<Button variant="filled" type="submit" disabled={busy}>
				{$t('Accept invitation')}
			</Button>
		{/if}
	</Panel>
</AuthPage>
