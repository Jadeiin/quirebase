<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';
	import Icon from '$lib/design/Icon.svelte';
	import { t } from '$lib/i18n';
	import type { ThemePreference } from '$lib/theme';
	import { mobileMoreNavigation, mobileNavigation, themeOptions } from './navigation';

	let { routeIsActive, user, readerRoute, themePreference, onThemeChange } = $props<{
		routeIsActive: (route: string) => boolean;
		user?: { role: string } | null;
		readerRoute: boolean;
		themePreference: ThemePreference;
		onThemeChange: (preference: ThemePreference) => void;
	}>();
</script>

<nav
	class={`fixed inset-x-0 bottom-0 z-50 overflow-x-auto bg-primary-950 text-surface-300 md:hidden ${readerRoute ? 'hidden' : 'flex'}`}
	aria-label={$t('Mobile navigation')}
>
	{#each mobileNavigation as [route, label, icon] (route)}
		<a
			class="flex min-w-18 flex-1 flex-col items-center gap-1 px-1.5 py-2 text-xs no-underline aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
			href={resolve(route)}
			aria-current={route === '/library'
				? routeIsActive(route) || page.url.pathname.startsWith('/item/')
					? 'page'
					: undefined
				: routeIsActive(route)
					? 'page'
					: undefined}><Icon name={icon} size={19} /><span>{$t(label)}</span></a
		>
	{/each}
	<Menu positioning={{ placement: 'top-end', gutter: 8 }}>
		<Menu.Trigger
			class="flex min-w-18 flex-1 cursor-pointer flex-col items-center gap-1 border-0 bg-transparent px-1.5 py-2 text-xs text-inherit aria-[current=page]:bg-white/10 aria-[current=page]:text-white"
			aria-current={['/', '/import', '/tools', '/admin', '/account'].some((route) =>
				routeIsActive(route)
			)
				? 'page'
				: undefined}
		>
			<Icon name="more" size={19} /><span>{$t('More')}</span>
		</Menu.Trigger>
		<Portal>
			<Menu.Positioner class="z-100">
				<Menu.Content
					class="min-w-52 rounded-container border border-surface-300-700 bg-surface-50-950 p-1 text-surface-900-100 shadow-xl"
				>
					{#each mobileMoreNavigation as [route, label, icon] (route)}
						<Menu.Item
							value={route}
							class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
							onclick={() => goto(resolve(route))}><Icon name={icon} /> {$t(label)}</Menu.Item
						>
					{/each}
					<Menu.Separator class="m-1 h-px bg-surface-300-700" />
					<div class="px-2.5 py-1.5 text-xs font-bold tracking-wide text-surface-600-400 uppercase">
						{$t('Appearance')}
					</div>
					{#each themeOptions as [preference, label, icon] (preference)}
						<Menu.Item
							value={`mobile-theme-${preference}`}
							class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[active=true]:bg-primary-50-950 data-[active=true]:text-primary-800-200 data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
							data-active={themePreference === preference}
							onclick={() => onThemeChange(preference)}
							><Icon name={icon} /><span>{$t(label)}</span>{#if themePreference === preference}<span
									class="ml-auto"
									aria-hidden="true">✓</span
								>{/if}</Menu.Item
						>
					{/each}
					{#if user?.role === 'administrator'}
						<Menu.Item
							value="/admin"
							class="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[highlighted]:bg-primary-50-950 data-[highlighted]:text-primary-800-200"
							onclick={() => goto(resolve('/admin'))}
							><Icon name="admin" /> {$t('Administration')}</Menu.Item
						>
					{/if}
				</Menu.Content>
			</Menu.Positioner>
		</Portal>
	</Menu>
</nav>
