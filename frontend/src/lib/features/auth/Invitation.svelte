<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { apiRequest } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import AuthPage from '#lib/design/AuthPage.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import { invitationQuery } from '#lib/features/auth/queries.js';
	import { t } from '#lib/i18n.js';
	import { domainLabel } from '#lib/domain-labels.js';
	import Button from '#lib/design/Button.svelte';
	import { sessionQuery } from '#lib/session.js';
	import { setDefaultWorkspacePreference } from '#lib/workspaces/preference.js';
	let { token } = $props<{ token: string }>();
	let password = $state('');
	let error = $state('');
	let busy = $state(false);
	const invitation = createQuery(() => invitationQuery(token));
	const session = createQuery(() => sessionQuery());
	const wrongAccount = $derived(
		invitation.data?.kind === 'workspace' &&
			session.data?.authenticated === true &&
			session.data.user?.username !== invitation.data.username
	);
	async function switchAccount() {
		busy = true;
		error = '';
		try {
			await apiRequest('DELETE', '/session');
			password = '';
			await session.refetch();
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to sign out'));
		} finally {
			busy = false;
		}
	}
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

			if (wrongAccount || session.isPending || session.isError) return;
			if (session.data?.authenticated !== true) {
				await apiRequest('POST', '/session', { body: { username: data.username, password } });
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
			<p>{$t('Create a password for')} <strong>{invitation.data.username}</strong>.</p>
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
				{$t('Join')} <strong>{invitation.data.workspace_name}</strong>
				{$t('as')} <strong>{invitation.data.username}</strong>
				({$t(domainLabel(invitation.data.role))}).
			</p>
			{#if session.isPending}
				<p>{$t('Checking account…')}</p>
			{:else if session.isError}
				<p class="text-error-700-300">{$t('Unable to check your account.')}</p>
				<Button type="button" onclick={() => void session.refetch()}>{$t('Retry')}</Button>
			{:else if wrongAccount}
				<p>
					{$t('You are signed in as {current}. Switch to {invited} to accept this invitation.', {
						current: session.data?.user?.username ?? '',
						invited: invitation.data.username
					})}
				</p>
				<Button type="button" disabled={busy} onclick={() => void switchAccount()}
					>{$t('Switch account')}</Button
				>
			{:else if session.data?.authenticated !== true}
				<p>{$t('Sign in with the invited account to accept this invitation.')}</p>
				<label
					>{$t('Username')}<input
						class="input"
						value={invitation.data.username}
						readonly
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
			<Button
				variant="filled"
				type="submit"
				disabled={busy || wrongAccount || session.isPending || session.isError}
			>
				{$t('Accept invitation')}
			</Button>
		{/if}
	</Panel>
</AuthPage>
