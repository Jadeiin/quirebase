<script lang="ts">
	import type { HTMLAttributes } from 'svelte/elements';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { Menu, Navigation, Portal } from '@skeletonlabs/skeleton-svelte';
	import type { components } from '#lib/api/schema.js';
	import { hasAllowedAction } from '#lib/authorization/can.js';
	import Icon from '#lib/design/Icon.svelte';
	import { domainLabel } from '#lib/domain-labels.js';
	import { t } from '#lib/i18n.js';
	import { navigation, themeOptions } from './navigation';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import type { ThemePreference } from '#lib/theme.js';
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
	}: {
		user?: components['schemas']['SessionUserView'] | null;
		collapsed: boolean;
		routeIsActive: (route: string) => boolean;
		onToggle: () => void;
		themePreference: ThemePreference;
		onThemeChange: (preference: ThemePreference) => void;
		actionBusy: boolean;
		onLogout: () => void;
		workspaceId?: string;
	} = $props();
	const navItems = $derived(
		(workspaceId ? navigation : []).map(
			([section, label, icon]) =>
				[
					workspaceId ? resolve(workspaceHref(workspaceId, section)) : resolve('workspace'),
					label,
					icon
				] as const
		)
	);
</script>

<Navigation
	layout={collapsed ? 'rail' : 'sidebar'}
	class={`sticky top-0 hidden h-screen w-full flex-col gap-4 bg-primary-950 py-5 text-primary-50 transition-[padding] md:flex ${collapsed ? 'px-2.5' : 'px-3.5'}`}
>
	{#snippet element(attributes)}
		<aside {...attributes as HTMLAttributes<HTMLElement>}>
			<Navigation.Header class="flex items-center gap-1 pb-3">
				<WorkspaceMenu {workspaceId} compact={collapsed} />

				{#if !collapsed}
					<button
						type="button"
						class="grid size-8 shrink-0 cursor-pointer grid-cols-1 place-items-center rounded-md border-0 bg-transparent text-surface-400 hover:bg-white/10 hover:text-white"
						aria-label={$t('Collapse sidebar')}
						onclick={onToggle}><Icon name="chevron-left" size={16} /></button
					>{/if}
			</Navigation.Header>
			{#if collapsed}<button
					type="button"
					class="mx-auto grid size-8 cursor-pointer grid-cols-1 place-items-center rounded-md border-0 bg-white/7 text-surface-400 hover:bg-white/12 hover:text-white"
					aria-label={$t('Expand sidebar')}
					onclick={onToggle}><Icon name="chevron-right" size={16} /></button
				>
			{/if}
			<Navigation.Menu class="flex-none gap-1">
				{#snippet element(attributes)}
					<nav {...attributes as HTMLAttributes<HTMLElement>} aria-label={$t('Main navigation')}>
						{#if !workspaceId}<Navigation.TriggerAnchor
								class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-surface-400 no-underline transition-colors hover:bg-white/9 hover:text-white aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
								href={resolve('workspace')}
								aria-label={$t('My workspaces')}
								title={collapsed ? $t('My workspaces') : undefined}
								aria-current={routeIsActive('/workspace') ? 'page' : undefined}
							>
								<Icon name="panel" />{#if !collapsed}<span>{$t('My workspaces')}</span>{/if}
							</Navigation.TriggerAnchor>{/if}
						{#each navItems as [route, label, icon] (label)}
							<Navigation.TriggerAnchor
								class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-surface-400 no-underline transition-colors hover:bg-white/9 hover:text-white aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
								href={route}
								aria-label={$t(label)}
								title={collapsed ? $t(label) : undefined}
								aria-current={workspaceId && routeIsActive(route) ? 'page' : undefined}
							>
								<Icon name={icon} />

								{#if !collapsed}
									<span class="min-w-0 flex-1">{$t(label)}</span>
								{/if}
							</Navigation.TriggerAnchor>
						{/each}
						{#if hasAllowedAction(user?.authorization)}
							<Navigation.TriggerAnchor
								class="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold text-surface-400 no-underline transition-colors hover:bg-white/9 hover:text-white aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
								href={resolve('admin')}
								aria-label={$t('Administration')}
								title={collapsed ? $t('Administration') : undefined}
								aria-current={routeIsActive('/admin') ? 'page' : undefined}
							>
								<Icon name="admin" />

								{#if !collapsed}
									<span>{$t('Administration')}</span>
								{/if}
							</Navigation.TriggerAnchor>
						{/if}
					</nav>
				{/snippet}
			</Navigation.Menu>
			<Navigation.Footer class="mt-auto border-t border-white/12 pt-3.5">
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
							<Menu.Content class="min-w-56 border-surface-300-700 p-1 shadow-xl">
								<Menu.Item
									value="account-settings"
									class="min-w-0 cursor-pointer justify-start gap-2 px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
									onclick={() => goto(resolve('account'))}
									><Icon name="user" />{$t('Account settings')}</Menu.Item
								>

								<Menu.Separator class="my-1 h-px bg-surface-300-700" />
								<div
									class="px-2.5 py-1.5 text-xs font-bold tracking-wide text-surface-600-400 uppercase"
								>
									{$t('Appearance')}
								</div>
								{#each themeOptions as [preference, label, icon] (preference)}
									<Menu.Item
										value={`theme-${preference}`}
										class="min-w-0 cursor-pointer justify-start gap-2 px-2.5 py-2 text-sm outline-none data-[active=true]:bg-primary-50-950 data-[active=true]:text-primary-800-200 data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
										data-active={themePreference === preference}
										onclick={() => onThemeChange(preference)}
									>
										<Icon name={icon} />
										<span class="min-w-0 flex-1">{$t(label)}</span>

										<span class="size-4 shrink-0 text-center" aria-hidden="true">
											{themePreference === preference ? '✓' : ''}
										</span>
									</Menu.Item>
								{/each}
								<Menu.Separator class="my-1 h-px bg-surface-300-700" />
								<Menu.Item
									value="sign-out"
									class="cursor-pointer px-2.5 py-2 text-sm text-error-700-300 outline-none data-[highlighted]:bg-error-50-950"
									disabled={actionBusy}
									onclick={onLogout}>{$t('Sign out')}</Menu.Item
								>
							</Menu.Content>
						</Menu.Positioner>
					</Portal>
				</Menu>
			</Navigation.Footer>
		</aside>
	{/snippet}
</Navigation>
