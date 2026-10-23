import type { SidebarSchema } from '@embedpdf/svelte-pdf-viewer';

const MIN_WIDTH = 200;
const MAX_WIDTH = 600;
const DOCUMENT_WIDTH = 320;
const DESKTOP_WIDTH = 768;
const STORAGE_PREFIX = 'quirebase:pdf-sidebar-width:';

type Panel = {
	element: HTMLElement;
	handle: HTMLElement;
	schema: SidebarSchema;
	width: number;
	maxWidth: number;
	dispose: () => void;
};

const clamp = (width: number, max = MAX_WIDTH) => Math.max(MIN_WIDTH, Math.min(max, width));

/** Keep knowledge of EmbedPDF 2.15's shadow DOM in this adapter, outside reader UI and sync. */
export function resizePdfSidebars(
	container: HTMLElement,
	sidebars: Record<string, SidebarSchema>,
	labels: { name: string; instructions: string }
): () => void {
	const root = container.shadowRoot;
	if (!root) return () => {};
	const panels = new Map<HTMLElement, Panel>();
	const widths = new Map<string, number>();
	let frame = 0;
	let stopDrag: (() => void) | undefined;
	const styles = document.createElement('style');
	// eslint-disable-next-line lingui/no-unlocalized-strings -- CSS injected into the vendor shadow root.
	styles.textContent = `
		[data-quirebase-resizable-sidebar] { position: relative; flex-shrink: 0; min-width: 0; }
		[data-quirebase-sidebar-resize] {
			position: absolute; top: 0; bottom: 0; width: 8px; z-index: 1;
			cursor: col-resize; touch-action: none; user-select: none; outline: none;
		}
		[data-quirebase-sidebar-resize="left"] { right: -4px; }
		[data-quirebase-sidebar-resize="right"] { left: -4px; }
		[data-quirebase-sidebar-resize]::after {
			content: ''; position: absolute; top: 0; bottom: 0; left: 3px; width: 2px;
		}
		[data-quirebase-sidebar-resize]:is(:hover, :focus-visible, [data-dragging])::after {
			background: var(--ep-accent-primary);
		}
	`;
	root.append(styles);

	function preferredWidth(schema: SidebarSchema) {
		if (!widths.has(schema.id)) {
			let width = Number.parseFloat(schema.width ?? '250');
			try {
				const saved = localStorage.getItem(`${STORAGE_PREFIX}${schema.id}`);
				if (saved !== null && Number.isFinite(Number(saved))) width = Number(saved);
			} catch {
				// Layout controls still work when browser storage is unavailable.
			}
			widths.set(schema.id, clamp(Number.isFinite(width) ? width : 250));
		}
		return widths.get(schema.id)!;
	}

	function remember(panel: Panel) {
		try {
			localStorage.setItem(
				`${STORAGE_PREFIX}${panel.schema.id}`,
				String(preferredWidth(panel.schema))
			);
		} catch {
			// Retain the preference for this viewer session.
		}
	}

	function renderWidths() {
		const entries = [...panels.values()];
		const budget = Math.max(MIN_WIDTH * entries.length, container.clientWidth - DOCUMENT_WIDTH);
		const desired = entries.map((panel) => preferredWidth(panel.schema));
		const total = desired.reduce((sum, width) => sum + width, 0);
		const excess = Math.max(0, total - budget);
		const flexible = total - MIN_WIDTH * entries.length;
		entries.forEach((panel, index) => {
			const reduction = flexible > 0 ? (excess * (desired[index] - MIN_WIDTH)) / flexible : 0;
			panel.width = Math.floor(desired[index] - reduction);
			panel.element.style.width = `${panel.width}px`;
		});
		for (const panel of entries) {
			const others = entries.reduce((sum, other) => sum + (other === panel ? 0 : other.width), 0);
			panel.maxWidth = clamp(budget - others);
			panel.handle.setAttribute('aria-valuemin', String(MIN_WIDTH));
			panel.handle.setAttribute('aria-valuemax', String(panel.maxWidth));
			panel.handle.setAttribute('aria-valuenow', String(panel.width));
		}
	}

	function setWidth(panel: Panel, width: number) {
		// During direct manipulation, keep the opposite panel at its rendered size.
		for (const other of panels.values()) {
			if (other !== panel) widths.set(other.schema.id, other.width);
		}
		widths.set(panel.schema.id, clamp(width, panel.maxWidth));
		renderWidths();
	}

	function attach(element: HTMLElement, schema: SidebarSchema): Panel {
		const handle = document.createElement('div');
		const side = schema.position.placement;
		handle.setAttribute('data-quirebase-sidebar-resize', side);
		handle.setAttribute('role', 'separator');
		handle.setAttribute('aria-orientation', 'vertical');
		handle.setAttribute('aria-label', labels.name);
		handle.title = labels.instructions;
		handle.tabIndex = 0;
		const originalWidth = element.style.width;
		element.setAttribute('data-quirebase-resizable-sidebar', '');
		element.append(handle);
		const events = new AbortController();
		let endDrag: (() => void) | undefined;
		const panel: Panel = {
			element,
			handle,
			schema,
			width: 0,
			maxWidth: MAX_WIDTH,
			dispose: () => {
				endDrag?.();
				events.abort();
				handle.remove();
				element.removeAttribute('data-quirebase-resizable-sidebar');
				element.style.width = originalWidth;
			}
		};
		const reset = () => {
			setWidth(panel, Number.parseFloat(schema.width ?? '250'));
			remember(panel);
		};
		handle.addEventListener('dblclick', reset, { signal: events.signal });
		handle.addEventListener(
			'keydown',
			(event) => {
				const direction = side === 'left' ? 1 : -1;
				const step = event.shiftKey ? 50 : 10;
				switch (event.key) {
					case 'ArrowLeft':
						setWidth(panel, panel.width - direction * step);
						break;
					case 'ArrowRight':
						setWidth(panel, panel.width + direction * step);
						break;
					case 'Home':
						reset();
						break;
					case 'End':
						setWidth(panel, panel.maxWidth);
						break;
					default:
						return;
				}
				event.preventDefault();
				event.stopPropagation();
				remember(panel);
			},
			{ signal: events.signal }
		);
		handle.addEventListener(
			'pointerdown',
			(event) => {
				if (event.button !== 0 || !event.isPrimary) return;
				event.preventDefault();
				event.stopPropagation();
				stopDrag?.();
				handle.focus();
				handle.setPointerCapture(event.pointerId);
				handle.setAttribute('data-dragging', '');
				const startX = event.clientX;
				const startWidth = panel.width;
				const drag = new AbortController();
				stopDrag = endDrag = () => {
					drag.abort();
					if (handle.hasPointerCapture(event.pointerId))
						handle.releasePointerCapture(event.pointerId);
					handle.removeAttribute('data-dragging');
					remember(panel);
					stopDrag = endDrag = undefined;
				};
				handle.addEventListener(
					'pointermove',
					(move) => {
						if (move.pointerId !== event.pointerId) return;
						setWidth(panel, startWidth + (move.clientX - startX) * (side === 'left' ? 1 : -1));
					},
					{ signal: drag.signal }
				);
				for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
					handle.addEventListener(type, endDrag, { signal: drag.signal });
				}
				window.addEventListener('blur', endDrag, { signal: drag.signal });
			},
			{ signal: events.signal }
		);
		return panel;
	}

	function reconcile() {
		frame = 0;
		// Mobile sidebars are bottom drawers portalled outside #document-content.
		const elements = [
			...root!.querySelectorAll<HTMLElement>('#document-content>[data-sidebar-id]')
		].filter((element) => {
			const schema = sidebars[element.dataset.sidebarId!];
			return (
				container.clientWidth >= DESKTOP_WIDTH &&
				(schema?.position.placement === 'left' || schema?.position.placement === 'right')
			);
		});
		for (const [element, panel] of panels) {
			if (
				!elements.includes(element) ||
				panel.schema.id !== element.dataset.sidebarId ||
				!element.contains(panel.handle)
			) {
				panel.dispose();
				panels.delete(element);
			}
		}
		for (const element of elements) {
			if (!panels.has(element))
				panels.set(element, attach(element, sidebars[element.dataset.sidebarId!]));
		}
		renderWidths();
	}

	function schedule() {
		if (!frame) frame = requestAnimationFrame(reconcile);
	}
	const mutations = new MutationObserver(schedule);
	mutations.observe(root, {
		childList: true,
		subtree: true,
		attributes: true,
		attributeFilter: ['data-sidebar-id']
	});
	const resize = new ResizeObserver(schedule);
	resize.observe(container);
	schedule();
	return () => {
		mutations.disconnect();
		resize.disconnect();
		cancelAnimationFrame(frame);
		for (const panel of panels.values()) panel.dispose();
		styles.remove();
	};
}
