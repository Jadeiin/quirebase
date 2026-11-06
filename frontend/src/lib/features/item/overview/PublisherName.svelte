<script module lang="ts">
	import acmUrl from 'academicons/svg/acm.svg?url';
	import elsevierUrl from 'academicons/svg/elsevier.svg?url';
	import ieeeUrl from 'academicons/svg/ieee.svg?url';
	import springerUrl from 'academicons/svg/springer.svg?url';
	import wileyUrl from 'academicons/svg/wiley.svg?url';

	const logos = new Map([
		['ieee', ieeeUrl],
		['institute of electrical and electronics engineers', ieeeUrl],
		['institute of electrical and electronics engineers (ieee)', ieeeUrl],
		['elsevier', elsevierUrl],
		['elsevier bv', elsevierUrl],
		['elsevier b.v.', elsevierUrl],
		['elsevier ltd', elsevierUrl],
		['elsevier inc', elsevierUrl],
		['elsevier inc.', elsevierUrl],
		['springer', springerUrl],
		['springer-verlag', springerUrl],
		['springer international publishing', springerUrl],
		['springer science and business media llc', springerUrl],
		['springer berlin heidelberg', springerUrl],
		['wiley', wileyUrl],
		['john wiley & sons', wileyUrl],
		['john wiley & sons, inc.', wileyUrl],
		['john wiley & sons ltd', wileyUrl],
		['acm', acmUrl],
		['association for computing machinery', acmUrl],
		['association for computing machinery (acm)', acmUrl]
	]);
</script>

<script lang="ts">
	import { scholarlyLink } from '../scholarly-links.js';

	let { name, href }: { name: string; href?: string } = $props();
	const logo = $derived(logos.get(name.trim().toLowerCase()));
	const link = $derived(scholarlyLink(href ?? ''));
</script>

<svelte:element
	this={link.href ? 'a' : 'span'}
	href={link.href}
	target={link.href ? '_blank' : undefined}
	rel={link.href ? 'external noopener noreferrer' : undefined}
	class="inline-flex max-w-full items-center gap-1.5 align-middle underline-offset-4"
	class:hover:underline={Boolean(link.href)}
>
	{#if logo}
		<img
			src={logo}
			alt=""
			width={20}
			height={20}
			class="block shrink-0 object-contain dark:invert"
			aria-hidden="true"
		/>
	{/if}
	<span class="min-w-0 wrap-anywhere">{name}</span>
</svelte:element>
