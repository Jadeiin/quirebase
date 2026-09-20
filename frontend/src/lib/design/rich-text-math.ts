import temml from 'temml';

export function renderMathHtml(tex: string): string {
	// Temml intentionally rejects link commands. Preserve the visible body while
	// discarding the URL before parsing, matching the server Web projection.
	const inertTex = tex.replace(/\\href\s*\{[^{}]*\}\s*\{([^{}]*)\}/g, '$1');
	return temml.renderToString(inertTex, {
		annotate: false,
		displayMode: false,
		maxExpand: 1000,
		maxSize: [10, 10],
		strict: true,
		throwOnError: true,
		trust: false
	});
}
