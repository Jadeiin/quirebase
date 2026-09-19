const RICH_TEXT_TAGS = new Set(['b', 'i', 'sub', 'sup']);
const DROP_CONTENT_TAGS = new Set(['script', 'style', 'template']);
const MATHML_NAMESPACE = 'http://www.w3.org/1998/Math/MathML';
const MATHML_TAGS = new Set([
	'math',
	'menclose',
	'mfrac',
	'mi',
	'mn',
	'mo',
	'mover',
	'mpadded',
	'mphantom',
	'mroot',
	'mrow',
	'mspace',
	'msqrt',
	'mstyle',
	'msub',
	'msubsup',
	'msup',
	'mtable',
	'mtd',
	'mtext',
	'mtr',
	'munder',
	'munderover'
]);
const MATHML_ATTRIBUTES = new Set([
	'accent',
	'accentunder',
	'columnalign',
	'columnlines',
	'columnspacing',
	'depth',
	'display',
	'displaystyle',
	'fence',
	'form',
	'height',
	'linebreak',
	'linethickness',
	'lspace',
	'mathsize',
	'mathvariant',
	'maxsize',
	'minsize',
	'movablelimits',
	'notation',
	'rowalign',
	'rowlines',
	'rowspacing',
	'rspace',
	'scriptlevel',
	'separator',
	'stretchy',
	'symmetric',
	'voffset',
	'width'
]);
const MAX_INLINE_MATH_SPAN = 200;
const CURRENCY_AMOUNT_START = /^\d+(?:[.,]\d+)?/;
const EXPLICIT_MATH_SYNTAX = /[\\_^{}=+*/<>]/;

function mathSpanEnd(value: string, openIndex: number): number | null {
	const start = openIndex + 1;
	if (start >= value.length || /\s/.test(value[start])) return null;
	let position = start;
	while (position < value.length) {
		if (value[position] === '\\') {
			position += 2;
			continue;
		}
		if (value[position] === '$') {
			if (
				position - start <= 0 ||
				position - start > MAX_INLINE_MATH_SPAN ||
				/\s/.test(value[position - 1])
			)
				return null;
			const content = value.slice(start, position);
			const amount = content.match(CURRENCY_AMOUNT_START)?.[0] ?? '';
			const remainder = content.slice(amount.length);
			if (
				amount &&
				/[A-Za-z]/.test(remainder) &&
				/\s/.test(remainder) &&
				!EXPLICIT_MATH_SYNTAX.test(content)
			)
				return null;
			return position + 1;
		}
		position += 1;
	}
	return null;
}

function mathSegments(value: string): Array<{ value: string; math: boolean }> {
	const segments: Array<{ value: string; math: boolean }> = [];
	let textStart = 0;
	let position = 0;
	while (position < value.length) {
		if (value[position] === '\\') {
			position += 2;
			continue;
		}
		if (value[position] === '$') {
			const end = mathSpanEnd(value, position);
			if (end !== null) {
				if (position > textStart)
					segments.push({ value: value.slice(textStart, position), math: false });
				segments.push({ value: value.slice(position + 1, end - 1), math: true });
				position = textStart = end;
				continue;
			}
		}
		position += 1;
	}
	if (textStart < value.length) segments.push({ value: value.slice(textStart), math: false });
	return segments;
}

function rebuildMathNode(source: Node): Node | null {
	if (source.nodeType === Node.TEXT_NODE) return document.createTextNode(source.textContent ?? '');
	if (!(source instanceof Element) || !MATHML_TAGS.has(source.localName)) return null;
	const target = document.createElementNS(MATHML_NAMESPACE, source.localName);
	for (const { name, value } of Array.from(source.attributes)) {
		if (MATHML_ATTRIBUTES.has(name)) target.setAttribute(name, value);
	}
	for (const child of Array.from(source.childNodes)) {
		const rebuilt = rebuildMathNode(child);
		if (rebuilt === null) return null;
		target.append(rebuilt);
	}
	if (source.localName === 'math') target.setAttribute('xmlns', MATHML_NAMESPACE);
	return target;
}

export type MathRenderer = (tex: string) => Node | null;

function projectMath(tex: string, renderMath: MathRenderer): Node | null {
	try {
		return renderMath(tex);
	} catch {
		return null;
	}
}

function appendTextProjection(value: string, target: Node, renderMath: MathRenderer): void {
	for (const segment of mathSegments(value)) {
		if (!segment.math) {
			target.appendChild(document.createTextNode(segment.value));
			continue;
		}
		const math = projectMath(segment.value, renderMath);
		target.appendChild(math ?? document.createTextNode(`$${segment.value}$`));
	}
}

function appendCanonicalNode(source: Node, target: Node, renderMath: MathRenderer): void {
	if (source.nodeType === Node.TEXT_NODE) {
		appendTextProjection(source.textContent ?? '', target, renderMath);
		return;
	}
	if (!(source instanceof Element) || DROP_CONTENT_TAGS.has(source.localName)) return;
	if (RICH_TEXT_TAGS.has(source.localName)) {
		const element = document.createElement(source.localName);
		for (const child of Array.from(source.childNodes))
			appendCanonicalNode(child, element, renderMath);
		target.appendChild(element);
		return;
	}
	for (const child of Array.from(source.childNodes)) appendCanonicalNode(child, target, renderMath);
}

export function projectRichText(canonicalHtml: string, renderMath?: MathRenderer): string {
	const parsed = new DOMParser().parseFromString(canonicalHtml, 'text/html');
	const output = document.createElement('span');
	const renderer = renderMath ?? (() => null);
	for (const child of Array.from(parsed.body.childNodes))
		appendCanonicalNode(child, output, renderer);
	return output.innerHTML;
}

export function hasInlineMath(canonicalHtml: string): boolean {
	const parsed = new DOMParser().parseFromString(canonicalHtml, 'text/html');
	const walker = parsed.createTreeWalker(parsed.body, NodeFilter.SHOW_TEXT);
	while (walker.nextNode()) {
		const parent = walker.currentNode.parentElement;
		if (parent && DROP_CONTENT_TAGS.has(parent.localName)) continue;
		const segments = mathSegments(walker.currentNode.textContent ?? '');
		if (segments.some((segment) => segment.math)) return true;
	}
	return false;
}

let pendingMathRenderer: Promise<MathRenderer> | undefined;

function loadMathRenderer(): Promise<MathRenderer> {
	pendingMathRenderer ??= import('$lib/design/rich-text-math').then(
		({ renderMathHtml }) =>
			(tex: string) => {
				const parsed = new DOMParser().parseFromString(renderMathHtml(tex), 'text/html');
				const root = parsed.body.firstElementChild;
				return root?.localName === 'math' ? rebuildMathNode(root) : null;
			}
	);
	return pendingMathRenderer;
}

export async function projectRichTextAsync(canonicalHtml: string): Promise<string> {
	return projectRichText(canonicalHtml, await loadMathRenderer());
}
