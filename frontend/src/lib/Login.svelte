<script lang="ts">
	import { apiRequest, type SessionView } from '$lib/api/client';
	import { t } from '$lib/i18n';

	let username = $state('');
	let password = $state('');
	let error = $state('');
	let busy = $state(false);

	async function submit() {
		busy = true;
		error = '';
		try {
			await apiRequest<SessionView>('/session', {
				method: 'POST',
				body: { username, password }
			});
			window.location.assign('/');
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Unable to sign in');
		} finally {
			busy = false;
		}
	}
</script>

<main class="workspace" style="max-width: 28rem; margin: 10vh auto;">
	<form
		class="panel stack"
		onsubmit={(event) => {
			event.preventDefault();
			submit();
		}}
	>
		<h1 style="margin: 0;">Quirebase</h1>
		<p class="muted">{$t('Sign in to your research workspace.')}</p>
		<label
			>{$t('Username')}
			<input class="field" bind:value={username} autocomplete="username" required /></label
		>
		<label
			>{$t('Password')}
			<input
				class="field"
				bind:value={password}
				type="password"
				autocomplete="current-password"
				required
			/></label
		>
		{#if error}<p class="error" role="alert">{error}</p>{/if}
		<button class="button button-primary" type="submit" disabled={busy}
			>{busy ? $t('Signing in…') : $t('Sign in')}</button
		>
	</form>
</main>
