export const optionalLibraryColumns = [
	'authors',
	'publication_date',
	'publication_title',
	'doi'
] as const;
export type LibraryTablePreferences = {
	view: 'auto' | 'table' | 'list';
	density: 'comfortable' | 'compact';
	visibility: Record<string, boolean>;
	widths: Record<string, number>;
};

export function defaultLibraryTablePreferences(): LibraryTablePreferences {
	return { view: 'auto', density: 'comfortable', visibility: { doi: false }, widths: {} };
}

function preferenceKey(userId: string) {
	return `quirebase:library-table:${userId}`;
}

export function readLibraryTablePreferences(userId: string): LibraryTablePreferences {
	const result = defaultLibraryTablePreferences();
	if (!userId) return result;
	try {
		const stored: unknown = JSON.parse(localStorage.getItem(preferenceKey(userId)) ?? 'null');
		if (!stored || typeof stored !== 'object') return result;
		const value = stored as Partial<LibraryTablePreferences>;
		if (value.view === 'table' || value.view === 'list') result.view = value.view;
		if (value.density === 'compact') result.density = 'compact';
		for (const id of optionalLibraryColumns) {
			if (typeof value.visibility?.[id] === 'boolean') result.visibility[id] = value.visibility[id];
		}
		for (const id of ['title_html', ...optionalLibraryColumns]) {
			const width = value.widths?.[id];
			if (typeof width === 'number' && Number.isFinite(width) && width >= 100 && width <= 800)
				result.widths[id] = width;
		}
	} catch {
		// Browser preferences are optional; unavailable or corrupt storage uses defaults.
	}
	return result;
}

export function writeLibraryTablePreferences(userId: string, preferences: LibraryTablePreferences) {
	if (!userId) return;
	try {
		localStorage.setItem(preferenceKey(userId), JSON.stringify(preferences));
	} catch {
		// Display controls remain usable when browser storage is unavailable.
	}
}
