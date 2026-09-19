<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { createQuery } from '@tanstack/svelte-query';
	import { onMount, type Snippet } from 'svelte';
	import { apiRequest, onAuthenticationRequired } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import Notice from '$lib/design/Notice.svelte';
	import Toast from '$lib/design/Toast.svelte';
	import { activateLocale, t } from '$lib/i18n';
	import Login from '$lib/features/auth/Login.svelte';
	import { sessionQuery, setSession } from '$lib/session';
	import { WorkflowCenter, setWorkflowCenter } from '$lib/features/workflows/center.svelte';
	import { localStorageWorkflowLedger } from '$lib/features/workflows/ledger';
	import WorkflowTray from '$lib/features/workflows/WorkflowTray.svelte';
	import {
		applyTheme,
		readThemePreference,
		saveThemePreference,
		type ThemePreference
	} from '$lib/theme';
	import AppSidebar from './AppSidebar.svelte';
	import MobileNavigation from './MobileNavigation.svelte';

	let { children } = $props<{ children: Snippet }>();
	const session = createQuery(() => sessionQuery());
	setSession({ query: session, logout });
	const workflowCenter = new WorkflowCenter();
	setWorkflowCenter(workflowCenter);
	let ledgerUserId = '';
	$effect(() => {
		const userId = session.data?.user?.id;
		if (!userId || userId === ledgerUserId) return;
		ledgerUserId = userId;
		workflowCenter.bindLedger(localStorageWorkflowLedger(userId));
	});
	const routeIsActive = (route: string) =>
		route === '/' ? page.url.pathname === route : page.url.pathname.startsWith(route);
	const readerRoute = $derived(/\/item\/[^/]+\/pdf\/[^/]+$/.test(page.url.pathname));
	let sidebarCollapsed = $state(false);
	let actionError = $state('');
	let actionBusy = $state(false);
	let themePreference = $state<ThemePreference>('system');
	let colorSchemeQuery: MediaQueryList | undefined;

	onMount(() => {
		const unregisterAuthenticationHandler = onAuthenticationRequired(() => void session.refetch());
		sidebarCollapsed = localStorage.getItem('quirebase:sidebar-collapsed') === 'true';
		themePreference = readThemePreference();
		colorSchemeQuery = matchMedia('(prefers-color-scheme: dark)');
		applyTheme(themePreference, colorSchemeQuery.matches);
		const handleColorSchemeChange = () => {
			if (themePreference === 'system' && colorSchemeQuery)
				applyTheme(themePreference, colorSchemeQuery.matches);
		};
		colorSchemeQuery.addEventListener('change', handleColorSchemeChange);
		return () => {
			unregisterAuthenticationHandler();
			colorSchemeQuery?.removeEventListener('change', handleColorSchemeChange);
		};
	});

	function toggleSidebar() {
		sidebarCollapsed = !sidebarCollapsed;
		localStorage.setItem('quirebase:sidebar-collapsed', String(sidebarCollapsed));
	}

	function setThemePreference(preference: ThemePreference) {
		themePreference = preference;
		saveThemePreference(preference);
		applyTheme(preference, colorSchemeQuery?.matches ?? false);
	}

	async function logout() {
		if (actionBusy) return;
		actionBusy = true;
		actionError = '';
		try {
			await apiRequest('DELETE', '/session');
			location.assign('/');
		} catch (reason) {
			actionError = apiErrorMessage(reason, $t('Account action failed'));
		} finally {
			actionBusy = false;
		}
	}

	$effect(() => {
		if (session.data?.locale) activateLocale(session.data.locale);
	});
</script>

{#if session.isPending}
	<main class="mx-auto w-full max-w-[100rem] min-w-0 p-4 md:p-[clamp(1.25rem,3vw,2.75rem)]">
		<p class="text-surface-600-400">{$t('Loading Quirebase…')}</p>
	</main>
{:else if !session.data?.authenticated}
	<Login />
{:else}
	<WorkflowTray />
	<div
		class={`sticky top-0 z-40 items-center justify-between bg-primary-950 px-4 py-3 text-white md:hidden ${readerRoute ? 'hidden' : 'flex'}`}
	>
		<a class="flex items-center gap-2 font-bold no-underline" href={resolve('/')}
			><span
				class="grid size-7 grid-cols-1 place-items-center rounded-lg bg-white text-sm font-extrabold text-primary-800"
				>Q</span
			>Quirebase</a
		>
		<a
			class="grid size-8 grid-cols-1 place-items-center rounded-full bg-primary-100 font-extrabold text-primary-800 no-underline"
			href={resolve('/account')}>{session.data.user?.username.slice(0, 1).toUpperCase()}</a
		>
	</div>
	<div
		class={`min-h-screen md:grid ${sidebarCollapsed ? 'md:grid-cols-[4.75rem_minmax(0,1fr)]' : 'md:grid-cols-[15.5rem_minmax(0,1fr)]'} ${readerRoute ? '' : 'pb-16 md:pb-0'}`}
	>
		<AppSidebar
			user={session.data.user}
			collapsed={sidebarCollapsed}
			{routeIsActive}
			onToggle={toggleSidebar}
			{themePreference}
			onThemeChange={setThemePreference}
			{actionBusy}
			onLogout={logout}
		/>
		<main
			class={readerRoute
				? 'mx-auto min-h-0 w-full max-w-[100rem] min-w-0'
				: 'mx-auto w-full max-w-[100rem] min-w-0 p-4 md:p-[clamp(1.25rem,3vw,2.75rem)]'}
		>
			{#if actionError}<Notice variant="error">{actionError}</Notice>{/if}
			{@render children()}
		</main>
	</div>
	<MobileNavigation
		user={session.data.user}
		{routeIsActive}
		{readerRoute}
		{themePreference}
		onThemeChange={setThemePreference}
	/>
{/if}
<Toast />
