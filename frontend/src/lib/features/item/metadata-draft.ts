import type { components } from '#lib/api/schema.js';

export type Metadata = components['schemas']['BibliographicMetadata-Input'];
type Contributor = components['schemas']['Contributor'];
type Link = components['schemas']['ResourceLink'];
type Affiliation = components['schemas']['Affiliation'];
export type IdentifierRow = { key: number; provider: string; value: string };
export type AffiliationRow = Omit<Affiliation, 'identifiers'> & {
	key: number;
	identifiers: IdentifierRow[];
};
export type ContributorRow = Omit<Contributor, 'identifiers' | 'affiliations'> & {
	key: number;
	identifiers: IdentifierRow[];
	affiliations: AffiliationRow[] | null;
};
export type LinkRow = Link & { key: number };
export type MetadataDraft = Omit<
	Metadata,
	| 'keywords'
	| 'urls'
	| 'authors'
	| 'editors'
	| 'identifiers'
	| 'custom_fields'
	| 'publication_date'
	| 'doi'
> & {
	publication_date: string;
	keywords: { key: number; value: string }[];
	urls: LinkRow[];
	authors: ContributorRow[];
	editors: ContributorRow[];
	identifiers: IdentifierRow[];
	custom_fields: { key: number; name: string; value: string; type: 'text' | 'json' }[];
};

function withoutRowKey<T extends { key: number }>(row: T): Omit<T, 'key'> {
	const value: Omit<T, 'key'> & { key?: number } = { ...row };
	delete value.key;
	return value;
}

export function newContributor(key: number): ContributorRow {
	return {
		key,
		display_name: '',
		family_name: '',
		given_name: '',
		suffix: '',
		kind: 'unknown',
		is_corresponding: null,
		identifiers: [],
		affiliations: []
	};
}

export function createMetadataDraft(value: Metadata, rowKey: () => number): MetadataDraft {
	const snapshot = { ...value };
	delete snapshot.doi;
	function identifiers(rows: Contributor['identifiers']): IdentifierRow[] {
		return (rows ?? []).map((row) => ({ ...row, key: rowKey() }));
	}
	function contributor(row: Contributor): ContributorRow {
		return {
			...newContributor(rowKey()),
			...row,
			identifiers: identifiers(row.identifiers),
			affiliations:
				row.affiliations?.map((affiliation) => ({
					...affiliation,
					key: rowKey(),
					identifiers: identifiers(affiliation.identifiers)
				})) ?? null
		};
	}
	return {
		...snapshot,
		publication_date: value.publication_date ?? '',
		keywords: (value.keywords ?? []).map((keyword) => ({ key: rowKey(), value: keyword })),
		urls: (value.urls ?? []).map((link) => ({ ...link, key: rowKey() })),
		authors: (value.authors ?? []).map(contributor),
		editors: (value.editors ?? []).map(contributor),
		identifiers: identifiers(value.identifiers),
		custom_fields: (value.custom_fields ?? []).map((field) => ({
			key: rowKey(),
			name: field.name,
			type: typeof field.value === 'string' ? 'text' : 'json',
			value: typeof field.value === 'string' ? field.value : JSON.stringify(field.value)
		}))
	};
}

export function metadataFromDraft(draft: MetadataDraft): Metadata {
	function nullable(value: string | null | undefined) {
		return value?.trim() || null;
	}
	function identifiers(rows: IdentifierRow[]) {
		return rows
			.filter((row) => row.provider.trim() && row.value.trim())
			.map(({ provider, value }) => ({ provider: provider.trim(), value: value.trim() }));
	}
	function contributor(row: ContributorRow): Contributor {
		return {
			...withoutRowKey(row),
			display_name:
				row.display_name.trim() ||
				[row.given_name, row.family_name, row.suffix].filter(Boolean).join(' ').trim(),
			family_name: nullable(row.family_name),
			given_name: nullable(row.given_name),
			suffix: nullable(row.suffix),
			identifiers: identifiers(row.identifiers),
			affiliations:
				row.affiliations
					?.filter((affiliation) => affiliation.name.trim())
					.map((affiliation) => ({
						...withoutRowKey(affiliation),
						name: affiliation.name.trim(),
						identifiers: identifiers(affiliation.identifiers),
						country_code: nullable(affiliation.country_code),
						raw_name: nullable(affiliation.raw_name)
					})) ?? null
		};
	}
	function hasContributorName(row: ContributorRow): boolean {
		return Boolean(row.display_name.trim() || row.family_name?.trim() || row.given_name?.trim());
	}
	return {
		...draft,
		title: draft.title.trim(),
		abstract: nullable(draft.abstract),
		publication_date: nullable(draft.publication_date),
		publication_title: nullable(draft.publication_title),
		volume: nullable(draft.volume),
		issue: nullable(draft.issue),
		pages: nullable(draft.pages),
		publisher: nullable(draft.publisher),
		place_published: nullable(draft.place_published),
		journal_abbreviation: nullable(draft.journal_abbreviation),
		citation_key: nullable(draft.citation_key),
		keywords: draft.keywords.map((row) => row.value.trim()).filter(Boolean),
		urls: draft.urls
			.filter((row) => row.url.trim())
			.map((link) => ({
				...withoutRowKey(link),
				url: link.url.trim(),
				media_type: nullable(link.media_type),
				version: nullable(link.version),
				license: nullable(link.license),
				intended_application: nullable(link.intended_application)
			})),
		authors: draft.authors.filter(hasContributorName).map(contributor),
		editors: draft.editors.filter(hasContributorName).map(contributor),
		identifiers: identifiers(draft.identifiers),
		custom_fields: draft.custom_fields
			.filter((row) => row.name.trim())
			.map(({ name, value, type }) => ({
				name: name.trim(),
				value: type === 'text' ? value : JSON.parse(value)
			}))
	};
}

export function contributorAffiliations(metadata: Pick<Metadata, 'authors' | 'editors'>): string[] {
	return [
		...new Set(
			[...(metadata.authors ?? []), ...(metadata.editors ?? [])]
				.flatMap((contributor) => contributor.affiliations ?? [])
				.map((affiliation) => affiliation.name)
		)
	];
}
