import { describe, expect, it } from 'vitest';
import {
	createMetadataDraft,
	metadataFromDraft,
	contributorAffiliations,
	newContributor,
	type Metadata
} from './metadata-draft.js';

const snapshot: Metadata = {
	title: 'Research',
	reference_type: 'document',
	authors: [
		{
			display_name: 'John Smith Jr',
			family_name: 'Smith',
			given_name: 'John',
			suffix: 'Jr',
			kind: 'person',
			is_corresponding: true,
			identifiers: [{ provider: 'orcid', value: '0000-0002-1825-0097' }],
			affiliations: [
				{
					name: 'University',
					country_code: 'CN',
					raw_name: 'Lab, University',
					identifiers: [{ provider: 'ror', value: '03yrm5c26' }]
				}
			]
		}
	],
	editors: [
		{
			display_name: 'Council',
			kind: 'organization',
			identifiers: [],
			affiliations: [{ name: 'University', identifiers: [] }]
		}
	],
	urls: [
		{
			url: 'https://example.test/paper',
			kind: 'full_text',
			media_type: 'application/pdf',
			version: 'publishedVersion',
			license: 'cc-by',
			is_open_access: false,
			intended_application: 'text-mining'
		}
	],
	keywords: ['Graph; theory'],
	identifiers: [{ provider: 'openalex', value: 'W123' }],
	custom_fields: [
		{ name: 'code', value: '123' },
		{ name: 'flag', value: 'true' },
		{ name: 'missing', value: 'null' },
		{ name: 'empty', value: '' },
		{ name: 'boolean', value: false },
		{ name: 'number', value: 123 },
		{ name: 'null', value: null },
		{ name: 'nested', value: { array: ['123', false] } }
	]
};
function draft() {
	let nextKey = 0;
	return createMetadataDraft(snapshot, () => ++nextKey);
}

describe('metadata editor', () => {
	it('edits or clears DOI in the identifier list without sending a stale DOI alias', () => {
		let nextKey = 0;
		const edited = createMetadataDraft(
			{
				...snapshot,
				doi: '10.1000/old',
				identifiers: [
					{ provider: 'doi', value: '10.1000/old' },
					{ provider: 'openalex', value: 'W123' }
				]
			},
			() => ++nextKey
		);
		expect(edited).not.toHaveProperty('doi');
		expect(edited.identifiers.map(({ provider, value }) => ({ provider, value }))).toEqual([
			{ provider: 'doi', value: '10.1000/old' },
			{ provider: 'openalex', value: 'W123' }
		]);
		edited.identifiers[0].value = '10.1000/new';
		expect(metadataFromDraft(edited)).not.toHaveProperty('doi');
		expect(metadataFromDraft(edited).identifiers).toEqual([
			{ provider: 'doi', value: '10.1000/new' },
			{ provider: 'openalex', value: 'W123' }
		]);
		edited.identifiers.splice(0, 1);
		expect(metadataFromDraft(edited)).not.toHaveProperty('doi');
		expect(metadataFromDraft(edited).identifiers).toEqual([
			{ provider: 'openalex', value: 'W123' }
		]);
	});
	it('preserves contributor institutions, identifiers, suffixes and link attributes when only a title changes', () => {
		const edited = draft();
		edited.title = 'Revised';
		const result = metadataFromDraft(edited);
		expect(result.title).toBe('Revised');
		expect(result.authors[0]).toMatchObject(snapshot.authors[0]);
		expect(result.editors[0]).toMatchObject(snapshot.editors[0]);
		expect(result.urls).toEqual(snapshot.urls);
		expect(result.identifiers).toEqual(snapshot.identifiers);
		expect(result.keywords).toEqual(['Graph; theory']);
		expect(result.custom_fields).toEqual(snapshot.custom_fields);
		expect(result).not.toHaveProperty('affiliation');
		expect(result).not.toHaveProperty('affiliations');
	});
	it('uses an explicit value type so text resembling JSON remains text', () => {
		const edited = draft();
		edited.custom_fields[0].value = '456';
		expect(metadataFromDraft(edited).custom_fields[0].value).toBe('456');
		edited.custom_fields[0].type = 'json';
		expect(metadataFromDraft(edited).custom_fields[0].value).toBe(456);
		edited.custom_fields[0].value = '{invalid';
		expect(() => metadataFromDraft(edited)).toThrow();
	});
	it('clears institutions and URLs explicitly without changing the original snapshot', () => {
		const edited = draft();
		edited.authors[0].affiliations?.splice(0);
		edited.urls.splice(0);
		const result = metadataFromDraft(edited);
		expect(result.authors[0].affiliations).toEqual([]);
		expect(result.urls).toEqual([]);
		expect(snapshot.authors[0].affiliations).toHaveLength(1);
		expect(snapshot.urls).toHaveLength(1);
	});
	it('derives institution display from the credited contributors', () => {
		expect(contributorAffiliations(snapshot)).toEqual(['University']);
	});
	it('saves a given-only name and a literal organization while skipping blank rows', () => {
		const edited = draft();
		edited.authors = [{ ...newContributor(100), given_name: 'Wei' }, newContributor(101)];
		edited.editors = [
			{ ...newContributor(102), kind: 'organization', display_name: 'Research Council' }
		];
		const result = metadataFromDraft(edited);
		expect(result.authors).toHaveLength(1);
		expect(result.authors[0].display_name).toBe('Wei');
		expect(result.authors[0].family_name).toBeNull();
		expect(result.editors[0].display_name).toBe('Research Council');
	});
});
