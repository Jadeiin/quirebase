<script lang="ts">
	import { createPluginRegistration } from '@embedpdf/core';
	import { EmbedPDF } from '@embedpdf/core/svelte';
	import { usePdfiumEngine } from '@embedpdf/engines/svelte';
	import wasmUrl from '@embedpdf/pdfium/pdfium.wasm?url';
	import { AnnotationLayer, AnnotationPluginPackage } from '@embedpdf/plugin-annotation/svelte';
	import {
		DocumentContent,
		DocumentManagerPluginPackage
	} from '@embedpdf/plugin-document-manager/svelte';
	import { RenderLayer, RenderPluginPackage } from '@embedpdf/plugin-render/svelte';
	import { PanMode, PanPluginPackage } from '@embedpdf/plugin-pan/svelte';
	import { Rotate, RotatePluginPackage } from '@embedpdf/plugin-rotate/svelte';
	import { SearchLayer, SearchPluginPackage } from '@embedpdf/plugin-search/svelte';
	import {
		Scroller,
		ScrollPluginPackage,
		type RenderPageProps
	} from '@embedpdf/plugin-scroll/svelte';
	import { SpreadPluginPackage } from '@embedpdf/plugin-spread/svelte';
	import { ThumbnailPluginPackage } from '@embedpdf/plugin-thumbnail/svelte';
	import { Viewport, ViewportPluginPackage } from '@embedpdf/plugin-viewport/svelte';
	import { ZoomGestureWrapper, ZoomMode, ZoomPluginPackage } from '@embedpdf/plugin-zoom/svelte';
	import { HistoryPluginPackage } from '@embedpdf/plugin-history/svelte';
	import {
		GlobalPointerProvider,
		InteractionManagerPluginPackage,
		PagePointerProvider
	} from '@embedpdf/plugin-interaction-manager/svelte';
	import { SelectionLayer, SelectionPluginPackage } from '@embedpdf/plugin-selection/svelte';
	import { t } from '$lib/i18n';
	import AnnotationSync from '$lib/pdf/AnnotationSync.svelte';
	import PdfReaderToolbar from '$lib/pdf/PdfReaderToolbar.svelte';
	import PdfThumbnails from '$lib/pdf/PdfThumbnails.svelte';

	let { itemId, documentId, name, url, editable, annotationAuthor, pageGeometry, projects } =
		$props<{
			itemId: string;
			documentId: string;
			name: string;
			url: string;
			editable: boolean;
			annotationAuthor: string;
			pageGeometry: number[][];
			projects: Array<{ id: string; name: string }>;
		}>();

	const pdfEngine = usePdfiumEngine({ wasmUrl, fontFallback: null });
	let thumbnailsOpen = $state(false);
	const plugins = $derived([
		createPluginRegistration(DocumentManagerPluginPackage, {
			initialDocuments: [
				{
					url,
					documentId,
					name,
					requestOptions: { credentials: 'same-origin' }
				}
			]
		}),
		createPluginRegistration(ViewportPluginPackage),
		createPluginRegistration(ScrollPluginPackage),
		createPluginRegistration(ZoomPluginPackage, { defaultZoomLevel: ZoomMode.FitWidth }),
		createPluginRegistration(SpreadPluginPackage),
		createPluginRegistration(RotatePluginPackage),
		createPluginRegistration(RenderPluginPackage),
		createPluginRegistration(InteractionManagerPluginPackage),
		createPluginRegistration(PanPluginPackage, { defaultMode: 'mobile' }),
		createPluginRegistration(ThumbnailPluginPackage, {
			width: 132,
			gap: 12,
			labelHeight: 24,
			paddingY: 12
		}),
		createPluginRegistration(SearchPluginPackage),
		createPluginRegistration(SelectionPluginPackage),
		createPluginRegistration(HistoryPluginPackage),
		createPluginRegistration(AnnotationPluginPackage, {
			autoCommit: false,
			annotationAuthor,
			selectAfterCreate: true,
			editAfterCreate: true
		})
	]);
</script>

{#if pdfEngine.error}
	<div class="grid h-full place-items-center text-danger" role="alert">
		{$t('Unable to initialize the PDF engine.')}
	</div>
{:else if pdfEngine.isLoading || !pdfEngine.engine}
	<div class="grid h-full place-items-center text-muted">{$t('Loading PDF engine…')}</div>
{:else}
	<EmbedPDF engine={pdfEngine.engine} {plugins}>
		{#snippet children({ activeDocumentId })}
			{#if activeDocumentId}
				{@const activeId = activeDocumentId}
				<DocumentContent documentId={activeId}>
					{#snippet children(documentContent)}
						{#if documentContent.isLoading}
							<div class="grid h-full place-items-center text-muted">{$t('Loading document…')}</div>
						{:else if documentContent.isError}
							<div class="grid h-full place-items-center text-danger" role="alert">
								{$t('Unable to load the document.')}
							</div>
						{:else if documentContent.isLoaded}
							<PdfReaderToolbar documentId={activeId} bind:thumbnailsOpen />
							<PanMode />
							{#snippet renderPage(page: RenderPageProps)}
								<PagePointerProvider
									documentId={activeId}
									pageIndex={page.pageIndex}
									class="relative bg-white shadow-[0_3px_16px_rgb(15_23_42_/_18%)]"
									style={`width:${page.width}px;height:${page.height}px`}
								>
									<Rotate documentId={activeId} pageIndex={page.pageIndex}>
										<RenderLayer documentId={activeId} pageIndex={page.pageIndex} />
										<SearchLayer documentId={activeId} pageIndex={page.pageIndex} />
										<SelectionLayer documentId={activeId} pageIndex={page.pageIndex} />
										<AnnotationLayer documentId={activeId} pageIndex={page.pageIndex} />
									</Rotate>
								</PagePointerProvider>
							{/snippet}
							<div class="flex min-h-0 flex-1">
								{#if thumbnailsOpen}<PdfThumbnails documentId={activeId} />{/if}
								<div class="flex min-h-0 min-w-0 flex-1 flex-col">
									<AnnotationSync
										{itemId}
										documentId={activeId}
										{editable}
										{pageGeometry}
										{projects}
									/>
									<ZoomGestureWrapper documentId={activeId} class="min-h-0 flex-1">
										<GlobalPointerProvider documentId={activeId} class="h-full min-h-0">
											<Viewport
												documentId={activeId}
												class="h-full min-h-0 overflow-hidden bg-[#dfe4e1]"
											>
												<Scroller documentId={activeId} {renderPage} />
											</Viewport>
										</GlobalPointerProvider>
									</ZoomGestureWrapper>
								</div>
							</div>
						{/if}
					{/snippet}
				</DocumentContent>
			{/if}
		{/snippet}
	</EmbedPDF>
{/if}
