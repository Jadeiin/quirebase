import { describe, expect, it } from 'vitest';
import { parse } from 'svelte/compiler';

const CHILD_KEYS = new Set([
	'fragment',
	'nodes',
	'children',
	'consequent',
	'alternate',
	'pending',
	'then',
	'catch',
	'body',
	'fallback'
]);
const USER_ATTRIBUTES = new Set(['aria-label', 'title', 'placeholder', 'alt', 'label']);
const CODE_ELEMENTS = new Set(['pre', 'code']);

const ALLOWED_TEXT = new Set([
	'BibLaTeX',
	'BibTeX',
	'CSL',
	'CSL citation',
	'Crossref',
	'DOI',
	'DataCite',
	'EndNote',
	'IEEE Xplore',
	'LaTeX',
	'NASA ADS',
	'Open Library',
	'OpenAlex',
	'PMC',
	'PubMed',
	'Q',
	'Quirebase',
	'RIS',
	'Unicode',
	'arXiv'
]);

const ALLOWED_ATTRIBUTES = new Set([
	'placeholder="journalArticle"',
	'placeholder="https://example.org/article.pdf"',
	'placeholder="https://example.org/supplement.zip"',
	'placeholder="abstract, keywords"',
	'placeholder="DOI, PMID, arXiv ID…"'
]);

const sources = import.meta.glob('/src/**/*.svelte', {
	query: '?raw',
	import: 'default',
	eager: true
}) as Record<string, string>;

type AstNode = {
	type?: string;
	start?: number;
	data?: string;
	name?: string;
	attributes?: AstNode[];
	value?: unknown;
	[key: string]: unknown;
};

type Finding = { file: string; line: number; text: string };

function lineAt(source: string, offset: number): number {
	return source.slice(0, offset).split('\n').length;
}

function staticAttributeValue(attribute: AstNode): string | undefined {
	if (!Array.isArray(attribute.value)) return undefined;
	return attribute.value
		.map((part) => (part.type === 'Text' && typeof part.data === 'string' ? part.data : ''))
		.join('')
		.replace(/\s+/g, ' ')
		.trim();
}

function collect(source: string, file: string): { text: Finding[]; attributes: Finding[] } {
	const text: Finding[] = [];
	const attributes: Finding[] = [];

	function walk(value: unknown, inCode: boolean): void {
		if (!value || typeof value !== 'object') return;
		if (Array.isArray(value)) {
			for (const child of value) walk(child, inCode);
			return;
		}
		const node = value as AstNode;
		if (node.type === 'Text' && typeof node.data === 'string' && !inCode) {
			const trimmed = node.data.replace(/\s+/g, ' ').trim();
			if (/[A-Za-z]/.test(trimmed)) {
				text.push({ file, line: lineAt(source, node.start ?? 0), text: trimmed });
			}
			return;
		}
		if (node.type === 'RegularElement' && Array.isArray(node.attributes) && !inCode) {
			for (const attribute of node.attributes) {
				if (attribute.type !== 'Attribute' || !attribute.name) continue;
				if (!USER_ATTRIBUTES.has(attribute.name)) continue;
				const content = staticAttributeValue(attribute);
				if (content && /[A-Za-z]/.test(content)) {
					attributes.push({
						file,
						line: lineAt(source, attribute.start ?? 0),
						text: `${attribute.name}="${content}"`
					});
				}
			}
		}
		const nextInCode =
			inCode || (node.type === 'RegularElement' && CODE_ELEMENTS.has(node.name ?? ''));
		for (const [key, child] of Object.entries(node)) {
			if (!CHILD_KEYS.has(key)) continue;
			walk(child, nextInCode);
		}
	}

	walk(parse(source, { filename: file, modern: true }).fragment, false);
	return { text, attributes };
}

const findings = Object.entries(sources).flatMap(([path, source]) =>
	collect(source, path.replace('/src/', 'src/'))
);

function unwrapped(items: Finding[], allowed: Set<string>): string[] {
	return items
		.filter(({ text }) => !allowed.has(text))
		.map(({ file, line, text }) => `${file}:${line} ${text}`);
}

describe('localization coverage', () => {
	it('wraps every user-facing Svelte text node', () => {
		expect(findings.flatMap(({ text }) => unwrapped(text, ALLOWED_TEXT))).toEqual([]);
	});

	it('wraps every static user-facing attribute', () => {
		expect(findings.flatMap(({ attributes }) => unwrapped(attributes, ALLOWED_ATTRIBUTES))).toEqual(
			[]
		);
	});
});
