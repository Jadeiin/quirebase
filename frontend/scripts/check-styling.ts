import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const sourceDirectory = 'src';
const appStylesheet = join(sourceDirectory, 'app.css');

const baseSelectors = new Set([
	'*',
	':root',
	":root[data-mode='light']",
	":root[data-mode='dark']",
	"[data-theme='quirebase']",
	'body',
	'a',
	'h1',
	'h2',
	'h3',
	'p',
	'button:focus-visible',
	'a:focus-visible',
	'input:focus-visible',
	'select:focus-visible',
	'textarea:focus-visible'
]);

const legacySelectors = new Set<string>([]);

const bannedUtilityPatterns = [
	/(?:bg|text|border|divide|ring|fill|stroke|from|via|to)-(?:surface|primary|success|warning|error)\//g,
	/(?:bg|text|border|divide|ring)-line\b/g,
	/(?:bg|text|border|divide|ring)-surface\b(?!-)/g
];

const primitivePattern = /\b(badge|btn|btn-icon|btn-sm|card)\b|preset-[a-z]/g;
const designDirectory = join(sourceDirectory, 'lib', 'design');

function ruleSelectors(stylesheet: string): string[] {
	const selectors: string[] = [];
	let prelude = '';
	for (const character of stylesheet.replace(/\/\*[\s\S]*?\*\//g, '')) {
		if (character === '{') {
			const head = prelude.replace(/\s+/g, ' ').trim();
			if (head && !head.startsWith('@')) {
				selectors.push(...head.split(',').map((selector) => selector.trim()));
			}
			prelude = '';
		} else if (character === '}' || character === ';') {
			prelude = '';
		} else {
			prelude += character;
		}
	}
	return selectors;
}

function svelteFiles(directory: string): string[] {
	const files: string[] = [];
	for (const entry of readdirSync(directory, { withFileTypes: true })) {
		const path = join(directory, entry.name);
		if (entry.isDirectory()) files.push(...svelteFiles(path));
		else if (entry.isFile() && entry.name.endsWith('.svelte')) files.push(path);
	}
	return files;
}

const findings: string[] = [];

const selectors = ruleSelectors(readFileSync(appStylesheet, 'utf8'));
const allowedSelectors = new Set([...baseSelectors, ...legacySelectors]);
for (const selector of selectors) {
	if (!allowedSelectors.has(selector)) {
		findings.push(
			`${appStylesheet}: global selector "${selector}" is not allowed; use a design token, a Tailwind utility, or a $lib/design component`
		);
	}
}
const presentSelectors = new Set(selectors);
for (const selector of legacySelectors) {
	if (!presentSelectors.has(selector)) {
		findings.push(
			`${appStylesheet}: legacy selector "${selector}" no longer exists; remove it from the ledger in scripts/check-styling.ts`
		);
	}
}

for (const file of svelteFiles(sourceDirectory)) {
	const contents = readFileSync(file, 'utf8');
	for (const pattern of bannedUtilityPatterns) {
		for (const match of contents.matchAll(pattern)) {
			findings.push(
				`${file}: "${match[0]}" references a Skeleton token that does not exist and produces no styles`
			);
		}
	}
	if (file.startsWith(designDirectory)) continue;
	for (const match of contents.matchAll(primitivePattern)) {
		findings.push(
			`${file}: Skeleton primitive "${match[0]}" must live inside a $lib/design component`
		);
	}
	for (const match of contents.matchAll(/class="([^"]*)"/g)) {
		const tokens = match[1].split(/\s+/);
		if (tokens.includes('grid') && !tokens.some((token) => token.startsWith('grid-cols'))) {
			findings.push(
				`${file}: grid layout must declare grid-cols-1 so min-content cannot widen the page`
			);
		}
	}
}

if (findings.length > 0) {
	throw new Error(`Styling check failed:\n- ${findings.join('\n- ')}`);
}

console.log(
	`Styling check passed: ${selectors.length} global selectors, ${legacySelectors.size} legacy selectors left to remove`
);
