<script module lang="ts">
	import type { LucideIcon } from '@lucide/svelte';
	import ArrowDown from '@lucide/svelte/icons/arrow-down';
	import ArrowDownToLine from '@lucide/svelte/icons/arrow-down-to-line';
	import ArrowUp from '@lucide/svelte/icons/arrow-up';
	import ArrowUpDown from '@lucide/svelte/icons/arrow-up-down';
	import Book from '@lucide/svelte/icons/book';
	import Calendar from '@lucide/svelte/icons/calendar';
	import Check from '@lucide/svelte/icons/check';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import ChevronsLeft from '@lucide/svelte/icons/chevrons-left';
	import ChevronsRight from '@lucide/svelte/icons/chevrons-right';
	import Columns3 from '@lucide/svelte/icons/columns-3';
	import CreativeCommons from '@lucide/svelte/icons/creative-commons';
	import Download from '@lucide/svelte/icons/download';
	import Ellipsis from '@lucide/svelte/icons/ellipsis';
	import ExternalLink from '@lucide/svelte/icons/external-link';
	import File from '@lucide/svelte/icons/file';
	import Folder from '@lucide/svelte/icons/folder';
	import Hand from '@lucide/svelte/icons/hand';
	import Keyboard from '@lucide/svelte/icons/keyboard';
	import LayoutDashboard from '@lucide/svelte/icons/layout-dashboard';
	import List from '@lucide/svelte/icons/list';
	import Mail from '@lucide/svelte/icons/mail';
	import MessageSquareText from '@lucide/svelte/icons/message-square-text';
	import Minus from '@lucide/svelte/icons/minus';
	import Monitor from '@lucide/svelte/icons/monitor';
	import MonitorSmartphone from '@lucide/svelte/icons/monitor-smartphone';
	import Moon from '@lucide/svelte/icons/moon';
	import PanelLeft from '@lucide/svelte/icons/panel-left';
	import PanelRight from '@lucide/svelte/icons/panel-right';
	import Plus from '@lucide/svelte/icons/plus';
	import Redo2 from '@lucide/svelte/icons/redo-2';
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
	import Search from '@lucide/svelte/icons/search';
	import Settings from '@lucide/svelte/icons/settings';
	import ShieldCheck from '@lucide/svelte/icons/shield-check';
	import Sun from '@lucide/svelte/icons/sun';
	import Table2 from '@lucide/svelte/icons/table-2';
	import Undo2 from '@lucide/svelte/icons/undo-2';
	import UserRound from '@lucide/svelte/icons/user-round';
	import Wrench from '@lucide/svelte/icons/wrench';
	import X from '@lucide/svelte/icons/x';

	// Keep product names here; glyphs and their geometry belong to the libraries.
	const icons: Record<string, LucideIcon> = {
		dashboard: LayoutDashboard,
		library: Book,
		import: ArrowDownToLine,
		calendar: Calendar,
		search: Search,
		keyboard: Keyboard,
		projects: Folder,
		settings: Settings,
		tools: Wrench,
		admin: ShieldCheck,
		more: Ellipsis,
		'external-link': ExternalLink,
		user: UserRound,
		mail: Mail,
		panel: PanelLeft,
		'panel-right': PanelRight,
		columns: Columns3,
		'creative-commons': CreativeCommons,
		table: Table2,
		list: List,
		responsive: MonitorSmartphone,
		'arrow-up': ArrowUp,
		'arrow-down': ArrowDown,
		'arrows-up-down': ArrowUpDown,
		hand: Hand,
		minus: Minus,
		plus: Plus,
		rotate: RotateCw,
		undo: Undo2,
		redo: Redo2,
		download: Download,
		'chevron-left': ChevronLeft,
		'chevron-right': ChevronRight,
		'chevrons-left': ChevronsLeft,
		'chevrons-right': ChevronsRight,
		'chevron-down': ChevronDown,
		close: X,
		annotation: MessageSquareText,
		monitor: Monitor,
		sun: Sun,
		moon: Moon,
		check: Check,
		file: File
	};
</script>

<script lang="ts">
	let { name, size = 18 }: { name: string; size?: number } = $props();
	const Glyph = $derived(icons[name]);
</script>

{#if Glyph}
	<Glyph {size} strokeWidth={1.8} class="block shrink-0" aria-hidden="true" />
{/if}
