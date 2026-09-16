<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { apiRequest, type SessionView } from '$lib/api/client';
	import { activateLocale, t } from '$lib/i18n';
	let { token } = $props<{ token: string }>();
	let password = $state('');
	let error = $state('');
	let busy = $state(false);
	const session = createQuery(() => ({
		queryKey: ['session'],
		queryFn: () => apiRequest<SessionView>('/session'),
		retry: false
	}));
	const invitation = createQuery(() => ({
		queryKey: ['invitation', token],
		queryFn: () =>
			apiRequest<{ username: string; role: string; expires_at: string }>(`/invitations/${token}`),
		retry: false
	}));
	$effect(() => {
		if (session.data?.locale) activateLocale(session.data.locale);
	});
	async function accept() {
		busy = true;
		error = '';
		try {
			await apiRequest(`/invitations/${token}/accept`, { method: 'POST', body: { password } });
			location.assign('/');
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to accept invitation');
		} finally {
			busy = false;
		}
	}
</script>

<main class="workspace auth-page">
	<form
		class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm"
		onsubmit={(event) => {
			event.preventDefault();
			accept();
		}}
	>
		<h1>{$t('Join Quirebase')}</h1>
		{#if invitation.isPending}<p class="text-surface-600">
				{$t('Checking invitation…')}
			</p>{:else if invitation.isError}<p class="text-error-700">
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
			>{#if error}<p class="text-error-700">{error}</p>{/if}<button
				class="btn preset-filled-primary-700-300 font-semibold"
				disabled={busy}>{$t('Create account')}</button
			>{/if}
	</form>
</main>
