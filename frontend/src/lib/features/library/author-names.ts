import { displayNameFromParts } from '#lib/features/item/metadata-draft.js';
import type { LibrarySearch } from './queries.js';

type Author = LibrarySearch['items'][number]['authors'][number];

export function authorFilterLabel(
	lastName: string,
	firstName: string | undefined,
	authors: readonly Author[] = []
): string {
	// Omitting the given-name criterion means every author with this family name.
	const names =
		firstName === undefined
			? []
			: [
					...new Set(
						authors
							.filter(
								(author) => author.last_name === lastName && (author.first_name ?? '') === firstName
							)
							.map((author) => author.full_name.trim())
					)
				];
	return names.length === 1 && names[0] ? names[0] : displayNameFromParts(firstName, lastName);
}
