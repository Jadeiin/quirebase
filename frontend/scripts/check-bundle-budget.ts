import { readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

type ManifestEntry = {
	file: string;
	name?: string;
	imports?: string[];
	dynamicImports?: string[];
	css?: string[];
	assets?: string[];
};

type BundleSize = { raw: number; gzip: number };

const outputDirectory = '.svelte-kit/output/client';
const manifest = JSON.parse(
	readFileSync(join(outputDirectory, '.vite/manifest.json'), 'utf8')
) as Record<string, ManifestEntry>;
const generatedApp = readFileSync('.svelte-kit/generated/build/client/app.js', 'utf8');

function manifestKeyByName(name: string): string {
	const match = Object.entries(manifest).find(([, entry]) => entry.name === name);
	if (!match) throw new Error(`Bundle manifest entry not found: ${name}`);
	return match[0];
}

function routeNodes(route: string): string[] {
	const escaped = route.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const match = generatedApp.match(new RegExp(`"${escaped}": \\[(\\d+),\\[([^\\]]*)\\]\\]`));
	if (!match) throw new Error(`SvelteKit route node not found: ${route}`);
	const layouts = match[2]
		.split(',')
		.map((value) => value.trim())
		.filter(Boolean);
	return [0, ...layouts, match[1]].map((index) => manifestKeyByName(`nodes/${index}`));
}

function dependencyGraph(roots: string[], includeDynamicImports: boolean): Set<string> {
	const graph = new Set<string>();
	const pending = [...roots];
	while (pending.length) {
		const key = pending.pop();
		if (!key || graph.has(key)) continue;
		const entry = manifest[key];
		if (!entry) throw new Error(`Bundle dependency not found: ${key}`);
		graph.add(key);
		pending.push(...(entry.imports ?? []));
		if (includeDynamicImports) pending.push(...(entry.dynamicImports ?? []));
	}
	return graph;
}

function mergeGraphs(...graphs: Set<string>[]): Set<string> {
	return new Set(graphs.flatMap((graph) => [...graph]));
}

function graphFiles(graph: Set<string>): Set<string> {
	const files = new Set<string>();
	for (const key of graph) {
		const entry = manifest[key];
		files.add(entry.file);
		for (const file of entry.css ?? []) files.add(file);
		for (const file of entry.assets ?? []) files.add(file);
	}
	return files;
}

function bundleSize(files: Set<string>): BundleSize {
	let raw = 0;
	let gzip = 0;
	for (const file of files) {
		const path = join(outputDirectory, file);
		const contents = readFileSync(path);
		raw += statSync(path).size;
		gzip += gzipSync(contents).byteLength;
	}
	return { raw, gzip };
}

function format(bytes: number): string {
	return `${(bytes / 1024).toFixed(1)} KiB`;
}

function enforce(name: string, actual: BundleSize, budget: BundleSize) {
	console.log(`${name}: ${format(actual.raw)} raw, ${format(actual.gzip)} gzip`);
	if (actual.raw > budget.raw || actual.gzip > budget.gzip) {
		throw new Error(
			`${name} exceeds its budget (${format(budget.raw)} raw, ${format(budget.gzip)} gzip)`
		);
	}
}

const runtime = [manifestKeyByName('entry/start'), manifestKeyByName('entry/app')];
const dashboard = dependencyGraph([...runtime, ...routeNodes('/(app)')], false);
const metadataEditorKey = manifestKeyByName('SchemaMetadataEditor');
if (dashboard.has(metadataEditorKey))
	throw new Error('Schema editor code leaked into the application shell');
const pdfRouteNodes = routeNodes('/(app)/workspace/[workspaceId]/item/[itemId]/pdf/[revisionId]');
const pdfReader = mergeGraphs(
	dependencyGraph([...runtime, ...pdfRouteNodes], false),
	dependencyGraph([pdfRouteNodes.at(-1)!], true)
);

// Initial route sizes exclude lazy imports; opened editors and readers include them separately.
function routeBundle(route: string): BundleSize {
	return bundleSize(graphFiles(dependencyGraph([...runtime, ...routeNodes(route)], false)));
}

const dashboardPdfDependencies = [...dashboard].filter((key) => {
	const entry = manifest[key];
	return (
		entry.name?.toLowerCase().includes('embedpdf') ||
		(entry.assets ?? []).some((asset) => asset.includes('pdfium'))
	);
});
if (dashboardPdfDependencies.length) {
	throw new Error(
		`PDF reader code leaked into the application shell: ${dashboardPdfDependencies.join(', ')}`
	);
}

if ([...dashboard].some((key) => manifest[key].name === 'DateField')) {
	throw new Error('DatePicker code leaked into the application shell');
}

// Workspace navigation, confirmation feedback and both locale catalogs add shared code/styles.
// Route budgets include that shared graph; settings sections remain independently loaded.
// Received invitations add a pending-count query/menu entry and both locale catalogs to the shell.
// Measured against 4fea97a: +7237 B raw / +1897 B gzip shared; Library also retains a delete snapshot.
// Leave translations add 1741 B raw / 373 B gzip to the shell; confirmation stays in settings.
// Access-loss cleanup adds 485 B raw / 284 B gzip to Workspace routes. Route-independent leave
// verification adds 165 B raw / 81 B gzip to General settings.
// Only exceeded limits move, with bounded rounding headroom; isolation checks stay unchanged.
enforce('Application shell', bundleSize(graphFiles(dashboard)), {
	// Includes shared Invitation and owner-governance navigation and translations.
	raw: 705000,
	gzip: 198000
});
enforce('Library route', routeBundle('/(app)/workspace/[workspaceId]/library'), {
	raw: 932000,
	// Includes destructive-detachment warnings, scoped selection cleanup and last-page recovery.
	gzip: 267000
});
enforce('Discovery route', routeBundle('/(app)/workspace/[workspaceId]/discovery'), {
	// Includes shared pagination, Invitation lifecycle and open reassignment form translations.
	raw: 838000,
	gzip: 238000
});
enforce('Account route', routeBundle('/(app)/account'), {
	raw: 820000,
	gzip: 233000
});
enforce('Tools route', routeBundle('/(app)/workspace/[workspaceId]/tools'), {
	// Includes shared pagination styles, account-management translations and recovery controls.
	raw: 848000,
	gzip: 244000
});
enforce('Import route', routeBundle('/(app)/workspace/[workspaceId]/import'), {
	raw: 829000,
	gzip: 238000
});
enforce(
	'Item overview route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)'),
	{
		raw: 838000,
		gzip: 241000
	}
);
enforce(
	'Item metadata route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/metadata'),
	{
		raw: 903000,
		gzip: 258000
	}
);
enforce(
	'Item files route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/files'),
	{
		raw: 884000,
		gzip: 256000
	}
);
enforce(
	'Item organize route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/organize'),
	{
		raw: 841000,
		// Organize now includes the destructive-detachment confirmation dialog.
		gzip: 243000
	}
);
enforce(
	'Item annotations route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/annotations'),
	{
		// Includes shared pagination styles and account-management translations.
		raw: 847000,
		gzip: 245000
	}
);
enforce(
	'Item discussion route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/discussion'),
	{
		// Includes shared pagination styles and account-management translations.
		raw: 835000,
		gzip: 241000
	}
);
enforce('Admin overview route', routeBundle('/(app)/admin'), {
	// Includes Skeleton pagination and the separate Invitation navigation entry.
	raw: 734000,
	gzip: 208000
});
enforce('Admin users route', routeBundle('/(app)/admin/users'), {
	// Includes account containment guidance and expandable role and sign-in controls.
	raw: 744000,
	gzip: 212000
});
enforce('Admin invitations route', routeBundle('/(app)/admin/invitations'), {
	// Owns invitation creation, history, status filtering and one pagination control.
	raw: 743000,
	gzip: 212000
});
enforce('Admin workspaces route', routeBundle('/(app)/admin/workspaces'), {
	// Includes owner reassignment, bounded User search, conflict recovery and scoped completion.
	raw: 785000,
	gzip: 224000
});
enforce('Admin audit route', routeBundle('/(app)/admin/audit'), {
	// Includes the separate Invitation navigation entry and shared translations.
	raw: 734000,
	gzip: 208000
});
enforce('Admin workflows route', routeBundle('/(app)/admin/workflows'), {
	// Includes Skeleton pagination and the separate Invitation navigation entry.
	raw: 733000,
	gzip: 208000
});
enforce('Admin settings route', routeBundle('/(app)/admin/settings'), {
	// Includes the separate Invitation navigation entry and shared translations.
	raw: 723000,
	gzip: 205000
});
enforce('Admin maintenance route', routeBundle('/(app)/admin/maintenance'), {
	// Includes the separate Invitation navigation entry and shared translations.
	raw: 723000,
	gzip: 206000
});
// Includes the conditional received-invitation section; no standalone inbox route.
enforce('Workspace directory', routeBundle('/(app)/workspace'), { raw: 762000, gzip: 216000 });
enforce('Workspace general settings', routeBundle('/(app)/workspace/[workspaceId]/settings'), {
	raw: 744000,
	gzip: 213000
});
enforce('Workspace members', routeBundle('/(app)/workspace/[workspaceId]/settings/members'), {
	raw: 764000,
	gzip: 220000
});
enforce(
	'Workspace invitations',
	routeBundle('/(app)/workspace/[workspaceId]/settings/invitations'),
	{ raw: 732000, gzip: 210000 }
);
enforce(
	'Workspace advanced settings',
	routeBundle('/(app)/workspace/[workspaceId]/settings/advanced'),
	{ raw: 747000, gzip: 215000 }
);
enforce('PDF reader route', bundleSize(graphFiles(pdfReader)), {
	raw: 8_000_000,
	gzip: 3_100_000
});

const metadataRoute = '/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/metadata';
const openedEditor = mergeGraphs(
	dependencyGraph([...runtime, ...routeNodes(metadataRoute)], false),
	dependencyGraph([metadataEditorKey], true)
);
enforce('Metadata editor when open', bundleSize(graphFiles(openedEditor)), {
	// Includes shared pagination styles and account-management translations.
	raw: 1077000,
	gzip: 310000
});
