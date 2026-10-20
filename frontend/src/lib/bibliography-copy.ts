import { bibliographyFilename } from '#lib/export-preferences.js';

export type BibliographyCopyState = { text: string | null };

/** Keep successful generation independent of clipboard permission and its retries. */
export async function copyBibliographyText(
	state: BibliographyCopyState,
	generate: () => Promise<string>,
	isActive: () => boolean = () => true,
	writeText: (text: string) => Promise<void> = (text) => navigator.clipboard.writeText(text)
): Promise<void> {
	if (state.text === null) state.text = await generate();
	if (isActive()) await writeText(state.text);
}

export function downloadBibliographyText(text: string, format: string): void {
	const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
	const link = document.createElement('a');
	link.href = url;
	link.download = bibliographyFilename(format);
	link.click();
	URL.revokeObjectURL(url);
}
