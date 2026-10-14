import type { Schema, Translation } from '@sjsf/form';
import { fromRecord } from '@sjsf/form/lib/resolver';
import { translation as english } from '@sjsf/form/translations/en';
import { chain } from '@sjsf/form/lib/resolver';
import { translate } from '#lib/i18n.js';
import { metadataValueLabel } from '../metadata-labels.js';
export { fieldTitle } from '../metadata-labels.js';

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
