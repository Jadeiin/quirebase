import { parse } from 'svelte/compiler';
import ts from 'typescript';

export type SvelteExtractedMessage = {
	id: string;
	message: string;
	origin: [filename: string, line: number, column: number];
	comment?: string;
};

type SvelteExtractor = {
	match(filename: string): boolean;
	extract(
		filename: string,
		source: string,
		onMessageExtracted: (message: SvelteExtractedMessage) => void,
		context: unknown
	): void;
};

type TypeScriptExtractor = SvelteExtractor;

type AstNode = {
	type?: string;
	loc?: { start: { line: number; column: number } };
	callee?: { type?: string; name?: string };
	arguments?: AstNode[];
	key?: { type?: string; name?: string; value?: unknown };
	properties?: AstNode[];
	value?: unknown;
};

function visit(value: unknown, callback: (node: AstNode) => void): void {
	if (!value || typeof value !== 'object') return;
	if (Array.isArray(value)) {
		for (const child of value) visit(child, callback);
		return;
	}

	const node = value as AstNode;
	if (node.type) callback(node);
	for (const [key, child] of Object.entries(node)) {
		if (key !== 'loc') visit(child, callback);
	}
}

const MESSAGE_FUNCTIONS = new Set(['$t', 'msg', 'translate']);

function objectPropertyText(object: AstNode, name: string): string | undefined {
	for (const property of object.properties ?? []) {
		if (property.type !== 'Property') continue;
		const key = property.key;
		const keyName =
			key?.type === 'Identifier' ? key.name : key?.type === 'Literal' ? key.value : undefined;
		if (keyName !== name) continue;
		const value = property.value as AstNode | undefined;
		if (value?.type === 'Literal' && typeof value.value === 'string') return value.value;
	}
	return undefined;
}

function literalMessage(node: AstNode, filename: string): SvelteExtractedMessage | undefined {
	if (node.type !== 'CallExpression' || node.callee?.type !== 'Identifier') return;
	if (!node.callee.name || !MESSAGE_FUNCTIONS.has(node.callee.name)) return;

	const argument = node.arguments?.[0];
	let message: string | undefined;
	let comment: string | undefined;
	if (argument?.type === 'Literal' && typeof argument.value === 'string') {
		message = argument.value;
	} else if (argument?.type === 'ObjectExpression') {
		message = objectPropertyText(argument, 'message');
		comment = objectPropertyText(argument, 'comment');
	}
	if (message !== undefined) {
		return {
			id: message,
			message,
			origin: [filename, node.loc!.start.line, node.loc!.start.column],
			comment
		};
	}
	if (node.callee.name === 'msg') {
		throw new Error(`${filename}:${node.loc!.start.line}: msg() requires a string literal`);
	}
}

export const svelteExtractor: SvelteExtractor = {
	match(filename) {
		return filename.endsWith('.svelte');
	},
	extract(filename, source, onMessageExtracted) {
		const ast = parse(source, { filename, modern: true });
		visit(ast, (node) => {
			const message = literalMessage(node, filename);
			if (message) onMessageExtracted(message);
		});
	}
};

export const typescriptExtractor: TypeScriptExtractor = {
	match(filename) {
		return filename.endsWith('.ts') && !filename.endsWith('.d.ts');
	},
	extract(filename, source, onMessageExtracted) {
		const sourceFile = ts.createSourceFile(
			filename,
			source,
			ts.ScriptTarget.Latest,
			true,
			ts.ScriptKind.TS
		);

		function propertyText(object: ts.ObjectLiteralExpression, name: string): string | undefined {
			for (const property of object.properties) {
				if (!ts.isPropertyAssignment(property)) continue;
				const key = property.name;
				if (!ts.isIdentifier(key) && !ts.isStringLiteral(key)) continue;
				if (key.text !== name) continue;
				if (ts.isStringLiteralLike(property.initializer)) return property.initializer.text;
			}
			return undefined;
		}

		function visitTypeScript(node: ts.Node): void {
			if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
				const name = node.expression.text;
				if (MESSAGE_FUNCTIONS.has(name)) {
					const argument = node.arguments[0];
					let message: string | undefined;
					let comment: string | undefined;
					if (argument && ts.isStringLiteralLike(argument)) {
						message = argument.text;
					} else if (argument && ts.isObjectLiteralExpression(argument)) {
						message = propertyText(argument, 'message');
						comment = propertyText(argument, 'comment');
					}
					if (message !== undefined) {
						const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
						onMessageExtracted({
							id: message,
							message,
							origin: [filename, position.line + 1, position.character],
							comment
						});
					} else if (name === 'msg') {
						const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
						throw new Error(`${filename}:${position.line + 1}: msg() requires a string literal`);
					}
				}
			}
			ts.forEachChild(node, visitTypeScript);
		}

		visitTypeScript(sourceFile);
	}
};
