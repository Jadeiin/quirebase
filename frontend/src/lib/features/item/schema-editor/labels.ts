import type { Schema, Translation } from '@sjsf/form';
import { fromRecord } from '@sjsf/form/lib/resolver';
import { translation as english } from '@sjsf/form/translations/en';
import { chain } from '@sjsf/form/lib/resolver';
import { msg, translate, type MessageKey } from '#lib/i18n.js';
import { metadataValueLabel } from '../metadata-labels.js';
// UI labels are independent of the official validation schema.
const fields: Record<string, MessageKey> = {
	accepted: msg('Accepted'),
	accessed: msg('Accessed'),
	acronym: msg('Acronym'),
	additional_descriptions: msg('Additional descriptions'),
	additional_names: msg('Additional names'),
	additional_titles: msg('Additional titles'),
	additional_type: msg('Additional type'),
	affiliations: msg('Affiliations'),
	archive_locations: msg('Archive locations'),
	asserted_by: msg('Asserted by'),
	available: msg('Available'),
	award_id: msg('Award URI'),
	award_number: msg('Award number'),
	award_title: msg('Award title'),
	box_east_longitude: msg('Box east longitude'),
	box_north_latitude: msg('Box north latitude'),
	box_south_latitude: msg('Box south latitude'),
	box_west_longitude: msg('Box west longitude'),
	bucket: msg('Bucket'),
	checksum: msg('Checksum'),
	collected: msg('Collected'),
	container: msg('Publication'),
	content: msg('Content'),
	contributors: msg('Contributors'),
	copyrighted: msg('Copyrighted'),
	country: msg('Country'),
	created: msg('Created'),
	date_published: msg('Publication date'),
	date_updated: msg('Updated date'),
	dates: msg('Dates'),
	description: msg('Description'),
	end_date: msg('End date'),
	established: msg('Established'),
	family_name: msg('Family name'),
	files: msg('Files'),
	first_page: msg('First page'),
	funder_id: msg('Funder URI'),
	funder_name: msg('Funder name'),
	funding_references: msg('Funding references'),
	geo_locations: msg('Geo locations'),
	given_name: msg('Given name'),
	id: msg('Identifier URI'),
	identifier: msg('Identifier'),
	identifier_type: msg('Identifier type'),
	identifiers: msg('Identifiers'),
	image: msg('Image'),
	issue: msg('Issue'),
	key: msg('Key'),
	language: msg('Language'),
	last_page: msg('Last page'),
	license: msg('License'),
	location: msg('Location'),
	mime_type: msg('MIME type'),
	name: msg('Name'),
	organization: msg('Organization'),
	other: msg('Other'),
	person: msg('Person'),
	place: msg('Place'),
	platform: msg('Platform'),
	point_latitude: msg('Point latitude'),
	point_longitude: msg('Point longitude'),
	polygon: msg('Polygon'),
	provider: msg('Provider'),
	publisher: msg('Publisher'),
	reference: msg('Reference'),
	references: msg('References'),
	relations: msg('Relations'),
	role: msg('Role'),
	roles: msg('Contributor roles'),
	schema_version: msg('Schema version URI'),
	scheme: msg('Scheme'),
	scheme_uri: msg('Scheme URI'),
	series: msg('Series'),
	size: msg('Size'),
	start_date: msg('Start date'),
	status: msg('Status'),
	subject: msg('Subject'),
	subjects: msg('Keywords'),
	submitted: msg('Submitted'),
	title: msg('Title'),
	type: msg('Type'),
	types: msg('Types'),
	url: msg('URL'),
	urls: msg('URLs'),
	valid: msg('Valid'),
	version: msg('Version'),
	volume: msg('Volume'),
	withdrawn: msg('Withdrawn')
};

export function fieldTitle(path: readonly (string | number)[], fallback: string): string {
	const key = String(path.at(-1));
	if (path.length === 1 && key === 'type') return translate('Reference type');
	if (path.length === 1 && key === 'provider') return translate('Metadata provider');
	if (path.length === 1 && key === 'description') return translate('Abstract');
	if (key === 'title' && path.at(-2) === 'license') return translate('License title');
	if (path.length === 2 && path[0] === 'container' && key === 'title')
		return translate('Publication title');
	return fields[key] ? translate(fields[key]) : fallback;
}

export function enumLabels(schema: Schema): string[] | undefined {
	const values =
		schema.enum ??
		(typeof schema.items === 'object' && !Array.isArray(schema.items)
			? schema.items.enum
			: undefined);
	return values?.map((value) => metadataValueLabel(String(value)));
}
export function editorTranslation(): Translation {
	return chain(
		fromRecord({
			'add-array-item': () => translate('Add entry'),
			'remove-array-item': () => translate('Remove entry'),
			'copy-array-item': () => translate('Copy entry'),
			'move-array-item-up': () => translate('Move up'),
			'move-array-item-down': () => translate('Move down'),
			'add-object-property': () => translate('Add field'),
			'remove-object-property': () => translate('Remove field'),
			expand: () => translate('Expand'),
			yes: () => translate('Yes'),
			no: () => translate('No'),
			'validation-process-error': () => translate('Unable to validate metadata.')
		}),
		english
	);
}
