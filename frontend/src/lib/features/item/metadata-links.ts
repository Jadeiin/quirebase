import {
	libraryHref,
	type LibraryAuthorFilter,
	type LibraryMetadataFilter
} from '#lib/features/library/filters.js';
import { orcidId } from '#lib/orcid.js';
import { rorId } from '#lib/ror.js';
import {
	contributorName,
	identifierRows,
	object,
	objects,
	text,
	type Metadata
} from './metadata-draft.js';
import { scholarlyLink, type ScholarlyLink } from './scholarly-links.js';

export function workIdentifierLinks(metadata: Metadata): ScholarlyLink[] {
	const candidates = [
		{ link: scholarlyLink(text(metadata.id)), typed: false },
		...identifierRows(metadata).map(({ namespace, value }) => ({
			link: scholarlyLink(value, namespace),
			typed: true
		}))
	].filter(({ link }) => link.label);
	const links = new Map<string, { link: ScholarlyLink; typed: boolean }>();
	for (const candidate of candidates) {
		const key = candidate.link.href ?? candidate.link.label;
		const previous = links.get(key);
		if (!previous || (candidate.typed && !previous.typed)) links.set(key, candidate);
	}
	return [...links.values()].map(({ link }) => link);
}

export function affiliationLinks(workspaceId: string, metadata: Metadata) {
	return uniqueAffiliations(
		objects(metadata.contributors)
			.filter((row) => row.type === 'Person')
			.flatMap((row) =>
				creditedAffiliations(
					objects(object(row.person).affiliations),
					Array.isArray(row.roles) && row.roles.includes('Author')
						? (filter) => libraryHref(workspaceId, filter)
						: undefined
				)
			)
	);
}

type FilterHref = (filter: LibraryMetadataFilter) => ReturnType<typeof libraryHref>;

function creditedAffiliations(
	values: Record<string, unknown>[],
	filterHref?: FilterHref,
	name?: LibraryAuthorFilter
) {
	const affiliations = values
		.map((affiliation) => {
			const ror = affiliationRor(affiliation);
			return {
				name: text(affiliation.name).trim().replace(/\s+/g, ' '),
				identifier: scholarlyLink(text(affiliation.identifier), text(affiliation.identifier_type)),
				rorFilterHref: ror && filterHref ? filterHref({ author_ror: ror }) : undefined,
				nameRorFilterHref:
					ror && filterHref && name ? filterHref({ authors: [name], author_ror: ror }) : undefined
			};
		})
		.filter((row) => row.name || row.identifier.label);
	return uniqueAffiliations(affiliations);
}

function uniqueAffiliations<
	T extends { name: string; identifier: ScholarlyLink; rorFilterHref?: string }
>(rows: T[]): T[] {
	const unique = new Map<string, T>();
	for (const row of rows) {
		const key = JSON.stringify([row.name, row.identifier.href ?? row.identifier.label]);
		const previous = unique.get(key);
		// An Editor's duplicate must not remove the matching Author's filter action.
		unique.set(key, previous?.rorFilterHref && !row.rorFilterHref ? previous : row);
	}
	return [...unique.values()];
}

export function licenseLink(value: unknown): ScholarlyLink {
	const license = object(value);
	const id = text(license.id);
	const cc = /^CC-(BY(?:-NC)?(?:-SA|-ND)?)-(1\.0|2\.0|2\.5|3\.0|4\.0)$/.exec(id);
	const deed = cc
		? `https://creativecommons.org/licenses/${cc[1].toLowerCase()}/${cc[2]}/`
		: id === 'CC0-1.0'
			? 'https://creativecommons.org/publicdomain/zero/1.0/'
			: id;
	return {
		...scholarlyLink(text(license.url) || deed),
		label: text(license.title) || id || text(license.url)
	};
}

function affiliationRor(affiliation: Record<string, unknown>) {
	const kind = text(affiliation.identifier_type);
	const value = text(affiliation.identifier);
	if (
		kind !== 'ROR' &&
		((kind !== '' && kind !== 'URL') || !/^https?:\/\/ror\.org\//i.test(value.trim()))
	)
		return undefined;
	return rorId(value);
}

export function metadataFilterLinks(
	workspaceId: string,
	metadata: Metadata,
	filterHref: FilterHref = (filter) => libraryHref(workspaceId, filter)
) {
	const publication = text(object(metadata.container).title);
	const date = text(metadata.date_published);
	const year = /^\d{4}(?:-|$)/.test(date) ? date.slice(0, 4) : '';
	const type = text(metadata.type);
	return {
		authors: objects(metadata.contributors)
			.filter((row) => Array.isArray(row.roles) && row.roles.includes('Author'))
			.map((row) => {
				const entity = object(row[row.type === 'Person' ? 'person' : 'organization']);
				const family = row.type === 'Person' ? text(entity.family_name) : '';
				const name = {
					last_name: family || text(entity.name) || text(entity.given_name),
					first_name: family ? text(entity.given_name) : ''
				};
				const filterByNameAndRor = (ror: string) =>
					filterHref({ authors: [name], author_ror: ror });
				const orcid = row.type === 'Person' ? orcidHref(entity.id) : undefined;
				const ror =
					row.type === 'Organization' && /^https?:\/\/ror\.org\//i.test(text(entity.id).trim())
						? rorId(entity.id)
						: undefined;
				return {
					label: contributorName(row),
					organization: row.type === 'Organization',
					roles: (row.roles as unknown[]).filter(
						(role): role is string => typeof role === 'string'
					),
					affiliations:
						row.type === 'Person'
							? creditedAffiliations(objects(entity.affiliations), filterHref, name)
							: [],
					orcidHref: orcid,
					orcidFilterHref: orcid ? filterHref({ author_orcid: orcid }) : undefined,
					rorHref: ror ? `https://ror.org/${ror}` : undefined,
					rorFilterHref: ror ? filterHref({ author_ror: ror }) : undefined,
					nameRorFilterHref: ror ? filterByNameAndRor(ror) : undefined,
					href: filterHref({ authors: [name] })
				};
			})
			.filter((author) => author.label),
		publication: {
			label: publication,
			href: publication ? filterHref({ publication_title: publication }) : undefined
		},
		date: { label: date, year, href: year ? filterHref({ year }) : undefined },
		type: {
			value: type,
			href: type ? filterHref({ reference_type: type }) : undefined
		}
	};
}

export type ItemAuthorCredit = ReturnType<typeof metadataFilterLinks>['authors'][number];

function orcidHref(value: unknown): string | undefined {
	if (!/^https?:\/\/orcid\.org\//i.test(text(value).trim())) return undefined;
	const id = orcidId(value);
	return id ? `https://orcid.org/${id}` : undefined;
}
