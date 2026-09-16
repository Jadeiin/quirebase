export type ExportPreferences = {
	citation: {
		format: 'csl' | 'bibtex' | 'biblatex' | 'ris' | 'endnote';
		style: string;
		includeAbstract: boolean;
		preserveCase: boolean;
		includeIdentifiers: boolean;
		includeCustomFields: boolean;
		encoding: 'unicode' | 'latex';
		journalMode: 'full' | 'abbreviated' | 'prefer_abbreviated';
		doiPolicy: 'include' | 'omit';
		urlPolicy: 'include' | 'omit' | 'omit_when_doi';
		excludedFields: string;
		sortBy: 'input' | 'citation_key' | 'author' | 'year' | 'title';
		citationKeyFormula: string;
		citationKeyForceAscii: boolean;
	};
	document: { includeAnnotations: boolean; includeSupplements: boolean };
};

export const defaultExportPreferences: ExportPreferences = {
	citation: {
		format: 'csl',
		style: 'apa',
		includeAbstract: true,
		preserveCase: false,
		includeIdentifiers: false,
		includeCustomFields: false,
		encoding: 'unicode',
		journalMode: 'full',
		doiPolicy: 'include',
		urlPolicy: 'include',
		excludedFields: '',
		sortBy: 'input',
		citationKeyFormula: 'auth.capitalize + year + shorttitle(1).capitalize',
		citationKeyForceAscii: true
	},
	document: { includeAnnotations: false, includeSupplements: false }
};

export function exportPreferencesKey(userId: string): string {
	return `quirebase:export-preferences:v1:account:${userId}`;
}

function cloneDefaults(): ExportPreferences {
	return structuredClone(defaultExportPreferences);
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function enumValue<T extends string>(value: unknown, values: readonly T[]): T | undefined {
	return typeof value === 'string' && values.includes(value as T) ? (value as T) : undefined;
}

function stringValue(value: unknown, maxLength: number): string | undefined {
	return typeof value === 'string' && value.length <= maxLength ? value : undefined;
}

function booleanValue(value: unknown): boolean | undefined {
	return typeof value === 'boolean' ? value : undefined;
}

export function readExportPreferences(userId: string): ExportPreferences {
	const preferences = cloneDefaults();
	try {
		const stored = localStorage.getItem(exportPreferencesKey(userId));
		if (!stored) return preferences;
		const parsed: unknown = JSON.parse(stored);
		if (!isRecord(parsed) || parsed.schemaVersion !== 1) return preferences;
		if (!isRecord(parsed.citation) || !isRecord(parsed.document)) return preferences;

		const citation = parsed.citation;
		preferences.citation.format =
			enumValue(citation.format, ['csl', 'bibtex', 'biblatex', 'ris', 'endnote']) ??
			preferences.citation.format;
		preferences.citation.style = stringValue(citation.style, 240) ?? preferences.citation.style;
		preferences.citation.includeAbstract =
			booleanValue(citation.includeAbstract) ?? preferences.citation.includeAbstract;
		preferences.citation.preserveCase =
			booleanValue(citation.preserveCase) ?? preferences.citation.preserveCase;
		preferences.citation.includeIdentifiers =
			booleanValue(citation.includeIdentifiers) ?? preferences.citation.includeIdentifiers;
		preferences.citation.includeCustomFields =
			booleanValue(citation.includeCustomFields) ?? preferences.citation.includeCustomFields;
		preferences.citation.encoding =
			enumValue(citation.encoding, ['unicode', 'latex']) ?? preferences.citation.encoding;
		preferences.citation.journalMode =
			enumValue(citation.journalMode, ['full', 'abbreviated', 'prefer_abbreviated']) ??
			(citation.abbreviateJournal === true
				? 'prefer_abbreviated'
				: preferences.citation.journalMode);
		preferences.citation.doiPolicy =
			enumValue(citation.doiPolicy, ['include', 'omit']) ?? preferences.citation.doiPolicy;
		preferences.citation.urlPolicy =
			enumValue(citation.urlPolicy, ['include', 'omit', 'omit_when_doi']) ??
			preferences.citation.urlPolicy;
		preferences.citation.excludedFields =
			stringValue(citation.excludedFields, 2000) ?? preferences.citation.excludedFields;
		preferences.citation.sortBy =
			enumValue(citation.sortBy, ['input', 'citation_key', 'author', 'year', 'title']) ??
			preferences.citation.sortBy;
		preferences.citation.citationKeyFormula =
			stringValue(citation.citationKeyFormula, 1000) ?? preferences.citation.citationKeyFormula;
		preferences.citation.citationKeyForceAscii =
			booleanValue(citation.citationKeyForceAscii) ?? preferences.citation.citationKeyForceAscii;
		preferences.document.includeAnnotations =
			booleanValue(parsed.document.includeAnnotations) ?? preferences.document.includeAnnotations;
		preferences.document.includeSupplements =
			booleanValue(parsed.document.includeSupplements) ?? preferences.document.includeSupplements;
		return preferences;
	} catch {
		return preferences;
	}
}

export function writeExportPreferences(userId: string, preferences: ExportPreferences): boolean {
	try {
		localStorage.setItem(
			exportPreferencesKey(userId),
			JSON.stringify({ schemaVersion: 1, ...preferences })
		);
		return true;
	} catch {
		return false;
	}
}
