<script lang="ts">
	import { onMount } from 'svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import { domainLabel } from '$lib/domain-labels';
	import Badge from '$lib/design/Badge.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import Panel from '$lib/design/Panel.svelte';
	import ExportPreferences from '$lib/features/account/ExportPreferences.svelte';
	import { accountQuery } from '$lib/features/account/queries';
	import { dateFormat, dateTimeFormat } from '$lib/format';
	import { activeLocale, msg, setLocale, t, type MessageKey } from '$lib/i18n';
	import { SUPPORTED_LOCALES, type Locale } from '$lib/locale';
	import Button from '$lib/design/Button.svelte';

	const localeLabels: Record<Locale, string> = {
		'en-US': 'English',
		'zh-CN': '简体中文'
	};

	let tokenName = $state('');
	let tokenDays = $state(30);
	let createdToken = $state('');
	let externalOrigin = $state('');
	let sidebarCollapsed = $state(false);
	let error = $state('');
	let notice = $state<MessageKey | null>(null);
	let busy = $state(false);
	const account = createQuery(() => accountQuery());

	onMount(() => {
		externalOrigin = location.origin;
		sidebarCollapsed = localStorage.getItem('quirebase:sidebar-collapsed') === 'true';
	});

	function saveSidebarPreference() {
		localStorage.setItem('quirebase:sidebar-collapsed', String(sidebarCollapsed));
	}

	async function mutate(
		operation: () => Promise<unknown>,
		success: MessageKey,
		form?: HTMLFormElement
	) {
		busy = true;
		error = '';
		notice = null;
		try {
			await operation();
			await account.refetch();
			form?.reset();
			notice = success;
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Account action failed'));
		} finally {
			busy = false;
		}
	}

	async function navigateAfter(operation: () => Promise<unknown>) {
		if (busy) return;
		busy = true;
		error = '';
		notice = null;
		try {
			await operation();
			location.assign('/');
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Account action failed'));
		} finally {
			busy = false;
		}
	}

	async function createToken() {
		busy = true;
		error = '';
		notice = null;
		try {
			const grant = await apiRequest('POST', '/account/api-tokens', {
				body: { name: tokenName, days: tokenDays }
			});
			createdToken = grant.token;
			tokenName = '';
			await account.refetch();
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Unable to create token'));
		} finally {
			busy = false;
		}
	}

	function changePassword(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values = new FormData(form);
		void mutate(
			() =>
				apiRequest('PUT', '/account/password', {
					body: {
						current_password: String(values.get('current_password') ?? ''),
						new_password: String(values.get('new_password') ?? '')
					}
				}),
			msg('Password changed'),
			form
		);
	}

	function revokeToken(tokenId: string) {
		void mutate(
			() =>
				apiRequest('DELETE', '/account/api-tokens/{token_id}', {
					params: { path: { token_id: tokenId } }
				}),
			msg('API Token revoked')
		);
	}

	function revokeSession(sessionId: string, current: boolean) {
		if (current) {
			void navigateAfter(() =>
				apiRequest('DELETE', '/account/sessions/{session_id}', {
					params: { path: { session_id: sessionId } }
				})
			);
			return;
		}
		void mutate(
			() =>
				apiRequest('DELETE', '/account/sessions/{session_id}', {
					params: { path: { session_id: sessionId } }
				}),
			msg('Session revoked')
		);
	}

	async function revokeAllSessions() {
		await navigateAfter(() => apiRequest('DELETE', '/account/sessions'));
	}

	async function logout() {
		await navigateAfter(() => apiRequest('DELETE', '/session'));
	}
</script>

<div class="mb-8 flex flex-wrap items-end justify-between gap-4">
	<div>
		<p class="mb-2 text-xs font-bold tracking-[0.12em] text-primary-700-300 uppercase">
			{$t('Personal settings')}
		</p>
		<h1 class="mb-2">{$t('Account')}</h1>
		<p class="mb-0 text-surface-600-400">{$t('Sessions, API Tokens, locale, and password.')}</p>
	</div>
	<Button disabled={busy} onclick={logout}>{$t('Sign out')}</Button>
</div>
{#if error}<Notice variant="error">{error}</Notice>{/if}
{#if notice}<Notice variant="success">{$t(notice)}</Notice>{/if}
{#if account.isPending}
	<p class="text-surface-600-400">{$t('Loading account…')}</p>
{:else if account.data}
	<Panel class="mb-4 flex flex-wrap items-center justify-between gap-4">
		<div class="flex min-w-0 items-center gap-3">
			<span
				class="grid size-11 shrink-0 grid-cols-1 place-items-center rounded-full bg-primary-50-950 text-lg font-bold text-primary-800-200"
				>{account.data.user.username.slice(0, 1).toUpperCase()}</span
			>
			<div class="min-w-0">
				<h2 class="m-0 truncate text-lg">{account.data.user.username}</h2>
				<p class="m-0 text-sm text-surface-600-400">{$t(domainLabel(account.data.user.role))}</p>
			</div>
		</div>
		<Badge>{$t('Signed in')}</Badge>
	</Panel>
	<div
		class="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(18rem,0.8fr)_minmax(0,1.2fr)]"
	>
		<div class="grid min-w-0 grid-cols-1 content-start gap-4">
			<Panel class="grid grid-cols-1 gap-3">
				<div>
					<h2>{$t('Preferences')}</h2>
					<p class="mb-0 text-sm text-surface-600-400">
						{$t('Choose how Quirebase looks and speaks to you.')}
					</p>
				</div>
				<label
					>{$t('Language')}<select
						class="select"
						value={$activeLocale}
						onchange={(event) => setLocale(event.currentTarget.value)}
						aria-label={$t('Locale')}
						>{#each SUPPORTED_LOCALES as locale (locale)}<option value={locale} lang={locale}
								>{localeLabels[locale]}</option
							>{/each}</select
					></label
				>
				<label class="flex items-start gap-2 border-t border-surface-300-700 pt-4">
					<input type="checkbox" bind:checked={sidebarCollapsed} onchange={saveSidebarPreference} />
					<span
						><strong>{$t('Collapse navigation sidebar by default')}</strong><small
							class="block text-surface-600-400"
							>{$t('Free more horizontal space for reading and metadata work.')}</small
						></span
					>
				</label>
			</Panel>
			<Panel class="grid grid-cols-1 gap-3">
				<div>
					<h2>{$t('Password')}</h2>
					<p class="mb-0 text-sm text-surface-600-400">
						{$t('Use at least 12 characters for a strong password.')}
					</p>
				</div>
				<form class="grid grid-cols-1 gap-3" onsubmit={changePassword}>
					<label
						>{$t('Current password')}<input
							class="input"
							name="current_password"
							type="password"
							autocomplete="current-password"
							required
						/></label
					>
					<label
						>{$t('New password')}<input
							class="input"
							name="new_password"
							type="password"
							autocomplete="new-password"
							minlength="12"
							required
						/></label
					>
					<div>
						<Button variant="filled" disabled={busy}>{$t('Change password')}</Button>
					</div>
				</form>
			</Panel>
		</div>
		<div class="grid min-w-0 grid-cols-1 content-start gap-4">
			<Panel class="grid min-w-0 grid-cols-1 gap-3">
				<div class="flex flex-wrap items-center justify-between gap-3">
					<div>
						<h2 class="mb-1">{$t('Sessions')}</h2>
						<p class="mb-0 text-sm text-surface-600-400">
							{$t('{count, plural, one {# active session} other {# active sessions}}', {
								count: account.data.sessions.length
							})}
						</p>
					</div>
					<Button disabled={busy} onclick={revokeAllSessions}>{$t('Revoke all sessions')}</Button>
				</div>
				<div class="divide-y divide-surface-300-700">
					{#each account.data.sessions as session (session.id)}
						<div
							class="flex flex-wrap items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
						>
							<div class="min-w-0">
								<strong>{session.current ? $t('Current session') : $t('Session')}</strong>
								<p class="m-0 text-sm text-surface-600-400">
									{$t('Created')}
									{$dateTimeFormat.format(new Date(session.created_at))}
								</p>
								<p class="m-0 text-xs text-surface-600-400">
									{$t('Expires')}
									{$dateTimeFormat.format(new Date(session.expires_at))}
								</p>
							</div>
							<Button
								class="shrink-0"
								disabled={busy}
								onclick={() => revokeSession(session.id, session.current)}
								>{session.current ? $t('Revoke current session') : $t('Revoke session')}</Button
							>
						</div>
					{:else}
						<p class="text-surface-600-400">{$t('No sessions.')}</p>
					{/each}
				</div>
			</Panel>
			<Panel class="grid min-w-0 grid-cols-1 gap-3 overflow-hidden">
				<div>
					<h2 class="mb-1">{$t('API Tokens')}</h2>
					<p class="mb-0 text-sm text-surface-600-400">
						{$t('Create revocable credentials for API and MCP clients.')}
					</p>
				</div>
				<form
					class="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-[minmax(8rem,1fr)_8rem_auto]"
					onsubmit={(event) => {
						event.preventDefault();
						createToken();
					}}
				>
					<input
						class="input grow basis-64"
						bind:value={tokenName}
						placeholder={$t('Token name')}
						required
					/>
					<select class="select" bind:value={tokenDays} aria-label={$t('Expires after')}>
						<option value={7}>{$t('7 days')}</option><option value={30}>{$t('30 days')}</option
						><option value={90}>{$t('90 days')}</option><option value={365}>{$t('365 days')}</option
						>
					</select>
					<Button variant="filled" disabled={busy}>{$t('Create')}</Button>
				</form>
				{#if createdToken}
					<Notice
						as="div"
						variant="warning"
						class="grid min-w-0 grid-cols-1 gap-2 [overflow-wrap:anywhere]"
					>
						<strong>{$t('Copy this token now')}</strong><code>{createdToken}</code>
					</Notice>
				{/if}
				{#each account.data.api_tokens as token (token.id)}
					<div
						class="flex min-w-0 flex-wrap items-center justify-between gap-3 border-t border-surface-300-700 pt-3"
					>
						<div class="min-w-0">
							<strong class="block truncate">{token.name}</strong><span
								class="text-sm text-surface-600-400"
								>{$t(domainLabel(token.status))} · {$t('Expires')}
								{$dateFormat.format(new Date(token.expires_at))}</span
							>
						</div>
						<Button class="shrink-0" disabled={busy} onclick={() => revokeToken(token.id)}
							>{$t('Revoke token')}</Button
						>
					</div>
				{:else}
					<p class="text-surface-600-400">{$t('No API Tokens.')}</p>
				{/each}
				<details class="mt-2 min-w-0 border-t border-surface-300-700 pt-4">
					<summary class="cursor-pointer font-semibold">{$t('Client connection guide')}</summary>
					<div class="mt-4 min-w-0">
						<h3>{$t('Connect an HTTP API client')}</h3>
						<p class="text-sm text-surface-600-400">
							{$t(
								'Use the versioned JSON API and send your API Token in the Authorization header.'
							)}
						</p>
						<dl
							class="grid min-w-0 grid-cols-1 gap-x-3 gap-y-2 text-sm sm:grid-cols-[7rem_minmax(0,1fr)]"
						>
							<dt class="text-surface-600-400">{$t('Base endpoint')}</dt>
							<dd class="m-0 min-w-0 break-all">
								<code class="whitespace-normal">{externalOrigin}/api/v1</code>
							</dd>
							<dt class="text-surface-600-400">{$t('OpenAPI')}</dt>
							<dd class="m-0 min-w-0 break-all">
								<button
									type="button"
									class="cursor-pointer border-0 bg-transparent p-0 text-left underline"
									onclick={() => location.assign(`${externalOrigin}/docs`)}
									><code class="whitespace-normal">{externalOrigin}/docs</code></button
								>
							</dd>
							<dt class="text-surface-600-400">{$t('Header')}</dt>
							<dd class="m-0 min-w-0 break-all">
								<code class="whitespace-normal">Authorization: Bearer YOUR_API_TOKEN</code>
							</dd>
						</dl>
						<pre
							class="overflow-x-auto rounded-lg border border-surface-300-700 bg-surface-200-800 p-3 text-xs"><code
								class="block bg-transparent p-0 [overflow-wrap:anywhere] whitespace-pre-wrap"
								>curl \
  -H 'Authorization: Bearer YOUR_API_TOKEN' \
  '{externalOrigin}/api/v1/items'</code
							></pre>
					</div>
					<div class="mt-4 border-t border-surface-300-700 pt-4">
						<h3>{$t('Connect an MCP client')}</h3>
						<p class="text-sm text-surface-600-400">
							{$t('Use Streamable HTTP. Never put an API Token in the URL.')}
						</p>
						<pre
							class="overflow-x-auto rounded-lg border border-surface-300-700 bg-surface-200-800 p-3 text-xs"><code
								class="block bg-transparent p-0 [overflow-wrap:anywhere] whitespace-pre-wrap"
								>{`{
  "mcpServers": {
    "quirebase": {
      "url": "${externalOrigin}/mcp",
      "headers": {"Authorization": "Bearer YOUR_API_TOKEN"}
    }
  }
}`}</code
							></pre>
					</div>
				</details>
			</Panel>
		</div>
	</div>
	<div class="mt-4"><ExportPreferences userId={account.data.user.id} /></div>
{/if}
