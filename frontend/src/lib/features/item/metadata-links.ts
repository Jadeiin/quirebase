import { libraryHref } from '#lib/features/library/filters.js';
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

export function affiliationLinks(metadata: Metadata) {
	const affiliations = objects(metadata.contributors)
		.filter((row) => row.type === 'Person')
		.flatMap((row) => objects(object(row.person).affiliations))
		.map((affiliation) => ({
			name: text(affiliation.name).trim().replace(/\s+/g, ' '),
			identifier: scholarlyLink(text(affiliation.identifier), text(affiliation.identifier_type))
		}))
		.filter((row) => row.name || row.identifier.label);
	return [
		...new Map(
			affiliations.map((row) => [
				JSON.stringify([row.name, row.identifier.href ?? row.identifier.label]),
				row
			])
		).values()
	];
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

export function metadataFilterLinks(workspaceId: string, metadata: Metadata) {
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
				return {
					label: contributorName(row),
					orcidHref: row.type === 'Person' ? orcidHref(entity.id) : undefined,
					href: libraryHref(workspaceId, {
						authors: [
							{
								last_name: family || text(entity.name) || text(entity.given_name),
								first_name: family ? text(entity.given_name) : ''
							}
						]
					})
				};
			})
			.filter((author) => author.label),
		publication: {
			label: publication,
			href: publication ? libraryHref(workspaceId, { publication_title: publication }) : undefined
		},
		date: { label: date, year, href: year ? libraryHref(workspaceId, { year }) : undefined },
		type: {
			value: type,
			href: type ? libraryHref(workspaceId, { reference_type: type }) : undefined
		}
	};
}

function orcidHref(value: unknown): string | undefined {
	const match = /^https?:\/\/orcid\.org\/(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\/?$/i.exec(
		text(value).trim()
	);
	if (!match) return undefined;
	const id = match[1].toUpperCase();
	const digits = id.replaceAll('-', '');
	// ORCID uses the ISO 7064 MOD 11-2 check digit, with X representing ten.
	let total = 0;
	for (const digit of digits.slice(0, -1)) total = (total + Number(digit)) * 2;
	const checksum = (12 - (total % 11)) % 11;
	if (digits.at(-1) !== (checksum === 10 ? 'X' : String(checksum))) return undefined;
	return `https://orcid.org/${id}`;
}
