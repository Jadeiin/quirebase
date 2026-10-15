import { contributorName, object, text } from '../metadata-draft.js';
import { metadataValueLabel } from '../metadata-labels.js';

export function fieldSummary(value: unknown, property?: string): string {
	if (Array.isArray(value))
		return (
			value
				.slice(0, 3)
				.map((row) => fieldSummary(row, property))
				.filter(Boolean)
				.join(' · ') + (value.length > 3 ? ' …' : '')
		);
	if (typeof value === 'string') return property === 'roles' ? metadataValueLabel(value) : value;
	if (value === null || typeof value !== 'object') return '';
	const row = object(value);
	if (row.type === 'Person' || row.type === 'Organization')
		return (
			contributorName(row) ||
			text(object(row[row.type === 'Person' ? 'person' : 'organization']).id)
		);
	return (
		text(row.name) ||
		text(row.title) ||
		text(row.identifier) ||
		text(row.subject) ||
		text(row.funder_name) ||
		text(row.url) ||
		text(row.id)
	);
}
