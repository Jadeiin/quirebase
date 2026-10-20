import { msg } from '#lib/i18n.js';
import type { components } from '#lib/api/schema.js';

export type BibliographyFormat = components['schemas']['BibliographyFormat'];

export const bibliographyFormats = [
	{ value: 'csl', label: msg('CSL citation'), extension: 'txt', importable: false },
	{ value: 'bibtex', label: msg('BibTeX'), extension: 'bib', importable: true },
	{ value: 'ris', label: msg('RIS'), extension: 'ris', importable: true },
	{ value: 'csl-json', label: msg('CSL-JSON'), extension: 'json', importable: true },
	{ value: 'commonmeta', label: msg('Commonmeta'), extension: 'json', importable: true }
] as const;

export type ExportPreferences = {
	citation: {
		format: BibliographyFormat;
		style: string;
		includeAbstract: boolean;
		preserveCase: boolean;
		encoding: 'unicode' | 'latex';
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
		encoding: 'unicode',
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

function citationStyleKey(userId: string, workspaceId: string): string {
	return `${exportPreferencesKey(userId)}:workspace:${workspaceId}:citation-style`;
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

export function readExportPreferences(userId: string, workspaceId = ''): ExportPreferences {
	const preferences = cloneDefaults();
	try {
		// Citation Styles belong to a Workspace; the other browser defaults belong to the User.
		if (workspaceId) {
			preferences.citation.style =
				stringValue(localStorage.getItem(citationStyleKey(userId, workspaceId)), 240) ??
				preferences.citation.style;
		}
		const stored = localStorage.getItem(exportPreferencesKey(userId));
		if (!stored) return preferences;
		const parsed: unknown = JSON.parse(stored);
		if (!isRecord(parsed) || parsed.schemaVersion !== 1) return preferences;
		if (!isRecord(parsed.citation) || !isRecord(parsed.document)) return preferences;

		const citation = parsed.citation;
		preferences.citation.format =
			enumValue(
				citation.format,
				bibliographyFormats.map((format) => format.value)
			) ?? preferences.citation.format;
		preferences.citation.includeAbstract =
			booleanValue(citation.includeAbstract) ?? preferences.citation.includeAbstract;
		preferences.citation.preserveCase =
			booleanValue(citation.preserveCase) ?? preferences.citation.preserveCase;
		preferences.citation.encoding =
			enumValue(citation.encoding, ['unicode', 'latex']) ?? preferences.citation.encoding;
		preferences.citation.doiPolicy =
			enumValue(citation.doiPolicy, ['include', 'omit']) ?? preferences.citation.doiPolicy;
		preferences.citation.urlPolicy =
			enumValue(citation.urlPolicy, ['include', 'omit', 'omit_when_doi']) ??
			preferences.citation.urlPolicy;
		preferences.citation.excludedFields =
			stringValue(citation.excludedFields, 8192) ?? preferences.citation.excludedFields;
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

export function bibliographyExportParameters(
	citation: ExportPreferences['citation'],
	format: BibliographyFormat
) {
	const bibtex = format === 'bibtex';
	const structured = bibtex || format === 'csl-json';
	const citationOutput = ['bibtex', 'ris', 'csl-json', 'csl'].includes(format);
	return {
		file_format: format,
		style: citation.style,
		include_abstract: format === 'commonmeta' || citation.includeAbstract,
		sort_by: format === 'csl' ? 'input' : citation.sortBy,
		citation_key_formula: citation.citationKeyFormula,
		citation_key_force_ascii: citation.citationKeyForceAscii,
		preserve_case: bibtex && citation.preserveCase,
		encoding: bibtex ? citation.encoding : 'unicode',
		doi_policy: citationOutput ? citation.doiPolicy : 'include',
		url_policy: citationOutput ? citation.urlPolicy : 'include',
		excluded_fields: structured
			? citation.excludedFields.split(/[,\s]+/).filter(Boolean)
			: undefined
	};
}

export function bibliographyFilename(format: string): string {
	if (format === 'csl') return 'quirebase-citations.txt';
	const extension =
		bibliographyFormats.find((choice) => choice.value === format)?.extension ?? 'json';
	return `quirebase-export.${extension}`;
}

export function writeExportPreferences(
	userId: string,
	preferences: ExportPreferences,
	workspaceId = ''
): boolean {
	try {
		const { style, ...citation } = preferences.citation;
		if (workspaceId) {
			localStorage.setItem(citationStyleKey(userId, workspaceId), style);
		}
		localStorage.setItem(
			exportPreferencesKey(userId),
			JSON.stringify({ schemaVersion: 1, ...preferences, citation })
		);
		return true;
	} catch {
		return false;
	}
}
