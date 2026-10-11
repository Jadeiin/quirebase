import type { components } from '#lib/api/schema.js';
import { msg, type MessageKey } from '#lib/i18n.js';

export const referenceTypeLabels = {
	article: msg('Article'),
	'article-journal': msg('Journal article'),
	'article-magazine': msg('Magazine article'),
	'article-newspaper': msg('Newspaper article'),
	book: msg('Book'),
	chapter: msg('Book chapter'),
	'paper-conference': msg('Conference paper'),
	thesis: msg('Thesis'),
	report: msg('Report'),
	webpage: msg('Web page'),
	dataset: msg('Dataset'),
	software: msg('Software'),
	patent: msg('Patent'),
	standard: msg('Standard'),
	manuscript: msg('Manuscript'),
	document: msg('Document'),
	preprint: msg('Preprint')
} satisfies Record<components['schemas']['ReferenceType'], MessageKey>;
