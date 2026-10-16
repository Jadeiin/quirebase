import { libraryHref } from '#lib/features/library/filters.js';
import { contributorName, object, objects, text, type Metadata } from './metadata-draft.js';

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
					href: libraryHref(workspaceId, {
						author_last_name: family || text(entity.name) || text(entity.given_name),
						author_first_name: family ? text(entity.given_name) : ''
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
