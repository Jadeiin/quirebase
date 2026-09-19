<script lang="ts">
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import AuthPage from '$lib/design/AuthPage.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import { t } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';

	let username = $state('');
	let password = $state('');
	let error = $state('');
	let busy = $state(false);

	async function submit() {
		busy = true;
		error = '';
		try {
			await apiRequest('POST', '/session', {
				body: { username, password }
			});
			window.location.reload();
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to sign in'));
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
			submit();
		}}
	>
		<h1 class="m-0">Quirebase</h1>
		<p class="text-surface-600-400">{$t('Sign in to your research workspace.')}</p>
		<label
			>{$t('Username')}
			<input class="input" bind:value={username} autocomplete="username" required /></label
		>
		<label
			>{$t('Password')}
			<input
				class="input"
				bind:value={password}
				type="password"
				autocomplete="current-password"
				required
			/></label
		>
		{#if error}<Notice variant="error">{error}</Notice>{/if}
		<Button variant="filled" type="submit" disabled={busy}
			>{busy ? $t('Signing in…') : $t('Sign in')}</Button
		>
	</Panel>
</AuthPage>
