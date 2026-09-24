<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';
	import type { components } from '$lib/api/schema';
	import Icon from '$lib/design/Icon.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import { navigation, themeOptions } from './navigation';
	import { workspaceHref } from '$lib/workspaces/href';
	import type { ThemePreference } from '$lib/theme';
	import WorkspaceMenu from './WorkspaceMenu.svelte';

	let {
		user,
		collapsed,
		routeIsActive,
		onToggle,
		themePreference,
		onThemeChange,
		actionBusy,
		onLogout,
		workspaceId
	} = $props<{
		user?: components['schemas']['SessionUserView'] | null;
		collapsed: boolean;
		routeIsActive: (route: string) => boolean;
		onToggle: () => void;
		themePreference: ThemePreference;
		onThemeChange: (preference: ThemePreference) => void;
		actionBusy: boolean;
		onLogout: () => void;
		workspaceId?: string;
	}>();
	const navItems = $derived(
		navigation.map(
			([section, label, icon]) =>
				[workspaceId ? workspaceHref(workspaceId, section) : '/workspace', label, icon] as const
		)
	);
</script>

<aside
	class={`sticky top-0 hidden h-screen flex-col gap-4 bg-primary-950 py-5 text-primary-50 transition-[padding] md:flex ${collapsed ? 'px-2.5' : 'px-3.5'}`}
>
	<div class="flex items-center gap-1 pb-3">
		<WorkspaceMenu {workspaceId} compact={collapsed} />
		{#if !collapsed}<button
				type="button"
				class="grid size-8 shrink-0 cursor-pointer grid-cols-1 place-items-center rounded-md border-0 bg-transparent text-surface-400 hover:bg-white/10 hover:text-white"
				aria-label={$t('Collapse sidebar')}
				onclick={onToggle}><Icon name="chevron-left" size={16} /></button
			>{/if}
	</div>
	{#if collapsed}<button
			type="button"
			class="mx-auto grid size-8 cursor-pointer grid-cols-1 place-items-center rounded-md border-0 bg-white/7 text-surface-400 hover:bg-white/12 hover:text-white"
			aria-label={$t('Expand sidebar')}
			onclick={onToggle}><Icon name="chevron-right" size={16} /></button
		>
	{/if}
	<nav class="grid grid-cols-1 gap-1" aria-label={$t('Main navigation')}>
		{#each navItems as [route, label, icon] (label)}
			<a
				class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-surface-400 no-underline transition-colors hover:bg-white/9 hover:text-white aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
				href={resolve(route)}
				title={collapsed ? $t(label) : undefined}
				aria-current={workspaceId && routeIsActive(route) ? 'page' : undefined}
				><Icon name={icon} />{#if !collapsed}<span>{$t(label)}</span>{/if}</a
			>
		{/each}
		{#if user?.role === 'administrator'}
			<a
				class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-surface-400 no-underline transition-colors hover:bg-white/9 hover:text-white aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
				href={resolve('/admin')}
				title={collapsed ? $t('Administration') : undefined}
				aria-current={routeIsActive('/admin') ? 'page' : undefined}
				><Icon name="admin" />{#if !collapsed}<span>{$t('Administration')}</span>{/if}</a
			>
		{/if}
	</nav>
	<div class="mt-auto border-t border-white/12 pt-3.5">
		<Menu positioning={{ placement: 'top-start', gutter: 8 }}>
			<Menu.Trigger
				class="flex w-full cursor-pointer items-center gap-2.5 rounded-lg border-0 bg-white/7 p-2 text-white transition-colors hover:bg-white/12"
			>
				<span
					class="grid size-8 shrink-0 grid-cols-1 place-items-center rounded-full bg-primary-100 font-extrabold text-primary-800"
					>{user?.username.slice(0, 1).toUpperCase()}</span
				>
				{#if !collapsed}<span class="grid min-w-0 flex-1 grid-cols-1 text-left">
						<strong class="truncate text-sm">{user?.username}</strong><small
							class="truncate text-xs text-surface-400"
							>{$t(domainLabel(user?.role ?? 'member'))}</small
						></span
					>
					<Icon name="chevron-down" size={15} />{/if}
			</Menu.Trigger>
			<Portal>
				<Menu.Positioner class="z-100">
					<Menu.Content
						class="min-w-56 rounded-container border border-surface-300-700 bg-surface-50-950 p-1 shadow-xl"
					>
						<Menu.Item
							value="account-settings"
							class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
							onclick={() => goto(resolve('/account'))}
							><Icon name="user" /> {$t('Account settings')}</Menu.Item
						>
						<Menu.Separator class="m-1 h-px bg-surface-300-700" />
						<div
							class="px-2.5 py-1.5 text-xs font-bold tracking-wide text-surface-600-400 uppercase"
						>
							{$t('Appearance')}
						</div>
						{#each themeOptions as [preference, label, icon] (preference)}
							<Menu.Item
								value={`theme-${preference}`}
								class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[active=true]:bg-primary-50-950 data-[active=true]:text-primary-800-200 data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
								data-active={themePreference === preference}
								onclick={() => onThemeChange(preference)}
								><Icon name={icon} /><span>{$t(label)}</span
								>{#if themePreference === preference}<span class="ml-auto" aria-hidden="true"
										>✓</span
									>{/if}</Menu.Item
							>
						{/each}
						<Menu.Separator class="m-1 h-px bg-surface-300-700" />
						<Menu.Item
							value="sign-out"
							class="flex cursor-pointer items-center rounded-md px-2.5 py-2 text-sm text-error-700-300 outline-none data-[highlighted]:bg-error-50-950"
							disabled={actionBusy}
							onclick={onLogout}>{$t('Sign out')}</Menu.Item
						>
					</Menu.Content>
				</Menu.Positioner>
			</Portal>
		</Menu>
	</div>
</aside>
