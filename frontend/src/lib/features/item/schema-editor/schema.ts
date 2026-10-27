import { Validator, type OutputUnit } from '@cfworker/json-schema';
import { pathFromLocation } from '@sjsf/form/core';
import type { Schema, ValidationError } from '@sjsf/form';
import { convert } from '@sjsf/form/converters/draft-2020-12';
import { i18n } from '@lingui/core';
import { msg } from '@lingui/core/macro';

export function workSchemas(registry: Record<string, unknown>) {
	// Keep the official reference context; the registry's entity root is not a Work.
	const original = structuredClone({
		$schema: registry.$schema,
		$id: registry.$id,
		$defs: registry.$defs,
		$ref: '#/$defs/work'
	});
	return { original, rendering: convert(original as Schema) };
}

export function validationMessage(unit: OutputUnit): string {
	switch (unit.keyword) {
		case 'required':
			return i18n._(msg`Complete the required fields.`);
		case 'format':
			return i18n._(msg`Enter a valid absolute URI.`);
		case 'pattern':
			return i18n._(msg`The value does not match the required format.`);
		case 'enum':
		case 'const':
			return i18n._(msg`Choose a supported value.`);
		case 'anyOf':
		case 'oneOf':
			return i18n._(msg`Complete at least one of the identifying fields.`);
		case 'minItems':
			return i18n._(msg`Add an entry or remove this optional field.`);
		case 'additionalProperties':
			return i18n._(msg`Remove fields that are not part of the metadata standard.`);
		default:
			return i18n._(msg`Check this value against the metadata standard.`);
	}
}

export function workValidator(original: Record<string, unknown>) {
	const validator = new Validator(original, '2020-12', false);
	return (value: unknown): ValidationError[] => {
		const snapshot = JSON.parse(JSON.stringify(value));
		const result = validator.validate(snapshot);
		const errors = result.errors
			.filter(
				(unit) =>
					!['$ref', 'properties', 'items', 'allOf', 'if', 'then', 'else'].includes(unit.keyword)
			)
			.map((unit) => ({
				path: pathFromLocation(unit.instanceLocation, snapshot),
				message: validationMessage(unit)
			}));
		return errors.length || result.valid
			? errors
			: [{ path: [], message: i18n._(msg`Check this value against the metadata standard.`) }];
	};
}

export function isRequiredOnlyUnion(schema: Schema): boolean {
	return (
		schema.type === 'object' &&
		!!schema.properties &&
		!!schema.anyOf?.length &&
		schema.anyOf.every(
			(branch) =>
				typeof branch === 'object' &&
				branch !== null &&
				Array.isArray(branch.required) &&
				Object.keys(branch).every((key) => key === 'required')
		)
	);
}
