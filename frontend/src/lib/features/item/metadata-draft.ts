import type { components } from '#lib/api/schema.js';

export type Metadata = components['schemas']['ItemDetailView']['metadata'];

export function text(value: unknown): string {
	return typeof value === 'string' ? value : '';
}

export function object(value: unknown): Record<string, unknown> {
	return value !== null && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

export function objects(value: unknown): Record<string, unknown>[] {
	return Array.isArray(value) ? value.map(object) : [];
}

export function contributorName(row: Record<string, unknown>): string {
	const entity = object(row[row.type === 'Organization' ? 'organization' : 'person']);
	return (
		text(entity.name) ||
		[text(entity.given_name), text(entity.family_name)].filter(Boolean).join(' ')
	);
}

export function contributorAffiliations(work: Metadata): string[] {
	return [
		...new Set(
			objects(work.contributors)
				.filter((row) => row.type === 'Person')
				.flatMap((row) =>
					objects(object(row.person).affiliations)
						.map((affiliation) => text(affiliation.name).trim().replace(/\s+/g, ' '))
						.filter(Boolean)
				)
		)
	];
}

export function workKeywords(work: Metadata): string[] {
	return [
		...new Set(
			objects(work.subjects)
				.map((row) => text(row.subject))
				.filter(Boolean)
		)
	];
}

export function identifierRows(work: Metadata): { namespace: string; value: string }[] {
	const rows = objects(work.identifiers).map((row) => ({
		namespace: text(
			row.identifier_type === 'Other' ? row.scheme : row.identifier_type
		).toLowerCase(),
		value: text(row.identifier)
	}));
	return [
		...new Map(rows.map((row) => [JSON.stringify([row.namespace, row.value]), row])).values()
	];
}

export function pdfFileUrls(work: Metadata | undefined): string[] {
	return [
		...new Set(
			objects(work?.files).flatMap((file) => {
				const url = text(file.url);
				try {
					const parsed = new URL(url);
					if (!['http:', 'https:'].includes(parsed.protocol)) return [];
					const mime = text(file.mime_type).toLowerCase().split(';')[0].trim();
					return !mime || mime === 'application/pdf' || /\.pdf$/i.test(parsed.pathname)
						? [url]
						: [];
				} catch {
					return [];
				}
			})
		)
	];
}
