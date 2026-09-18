<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import AuthPage from '$lib/design/AuthPage.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import { invitationQuery } from '$lib/features/auth/queries';
	import { activateLocale, t } from '$lib/i18n';
	import { sessionQuery } from '$lib/session';
	import Button from '$lib/design/Button.svelte';
	let { token } = $props<{ token: string }>();
	let password = $state('');
	let error = $state('');
	let busy = $state(false);
	const session = createQuery(() => sessionQuery());
	const invitation = createQuery(() => invitationQuery(token));
	$effect(() => {
		if (session.data?.locale) activateLocale(session.data.locale);
	});
	async function accept() {
		busy = true;
		error = '';
		try {
			await apiRequest('POST', '/invitations/{token}/accept', {
				params: { path: { token } },
				body: { password }
			});
			location.assign('/');
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
			</p>{:else}<p>{$t('Create a password for')} <strong>{invitation.data?.username}</strong>.</p>
			<label
				>{$t('Password')}<input
					class="input"
					type="password"
					bind:value={password}
					minlength="12"
					autocomplete="new-password"
					required
				/></label
			>{#if error}<p class="text-error-700-300">{error}</p>{/if}<Button
				variant="filled"
				disabled={busy}>{$t('Create account')}</Button
			>{/if}
	</Panel>
</AuthPage>
