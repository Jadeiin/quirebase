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
const library = dependencyGraph(
	[...runtime, ...routeNodes('/(app)/workspace/[workspaceId]/library')],
	false
);
const libraryPreviewKey = manifestKeyByName('LibraryPreview');
if (dashboard.has(libraryPreviewKey) || library.has(libraryPreviewKey))
	throw new Error('Item preview code must load only when the Library preview opens');
const libraryPreview = mergeGraphs(library, dependencyGraph([libraryPreviewKey], false));
const libraryOrganizeKey = manifestKeyByName('LibraryPreviewOrganize');
if (dashboard.has(libraryOrganizeKey) || libraryPreview.has(libraryOrganizeKey))
	throw new Error('Inline organization code must load only when organization opens');
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
// Library table styles and both locale catalogs add 4864 B raw / 1520 B gzip shared vs 8b9f138.
// Its route-specific table/selection/display controls add 57475 B raw / 16737 B gzip.
// Structured author links and contextual metadata filters add about 3 KiB raw to Library.
// Shared link styles add under 100 B raw; only exceeded shared-route limits move below.
// Sorting adds shared icons/catalog entries and about 4 KiB to Library. Only exceeded limits
// move to the next 1 kB raw / 500 B gzip boundary; isolation checks stay unchanged.
// First-author sorting and the consolidated results toolbar add about 1 KiB to Library.
// Icon view segments add about 14 KiB raw / 4.5 KiB gzip to Library through Skeleton’s radio
// behavior; shared icons, translations and styles add under 1 KiB raw to other routes.
// Joined sorting controls and their order hint add 645 B raw / about 150 B gzip shared.
// Project access-loss cleanup adds under 1 KiB raw to shared query code.
// Nineteen shortcut messages add 2424 B raw / about 750 B gzip to the shared catalogs.
// Mounted hotkeys and row commands add about 33 kB raw / 11.5 kB gzip to Library.
// Shared runtime, the keyboard glyph and focus styles add about 6 kB raw / 1 kB gzip.
// Selection hints and toolbar styles add 1894 B raw / about 420 B gzip to shared code.
// Range selection and scoped completion focus add about 2.3 kB raw to Library.
// Continuous preview, inline organization and return-context labels add shared catalog/styles code.
// Inline organization stays a separate lazy graph (about 10 kB raw / 4 kB gzip).
// Only exceeded budgets move to the next 1 kB raw / 500 B gzip boundary.
// Bulk-removal preview reconciliation adds about 1 kB raw to the Library graph.
// Library Item actions and lazy Project selectors add shared labels/styles and route-owned code.
// Measured budgets retain separate lazy preview and organization checks.
// Explicit scan coverage adds shared translations; retained citation recovery and refreshed
// PDF selection add about 2.4 kB raw to Item sections. Only exceeded limits move below.
enforce('Application shell', bundleSize(graphFiles(dashboard)), {
	// Includes shared Invitation and owner-governance navigation and translations.
	raw: 729000,
	gzip: 203000
});
enforce('Library route', bundleSize(graphFiles(library)), {
	raw: 1090000,
	// Includes destructive-detachment warnings, scoped selection cleanup and last-page recovery.
	gzip: 315000
});
enforce(
	'Library preview when open',
	bundleSize(graphFiles(libraryPreview)),
	// Bibliographic preview and scoped navigation add about 14 kB raw / 5.5 kB gzip on demand.
	{ raw: 1104000, gzip: 320500 }
);
enforce(
	'Library organization when open',
	bundleSize(graphFiles(mergeGraphs(libraryPreview, dependencyGraph([libraryOrganizeKey], false)))),
	{ raw: 1117000, gzip: 325500 }
);
enforce('Discovery route', routeBundle('/(app)/workspace/[workspaceId]/discovery'), {
	// Includes shared pagination, Invitation lifecycle and open reassignment form translations.
	raw: 863000,
	gzip: 243500
});
enforce('Account route', routeBundle('/(app)/account'), {
	raw: 845000,
	gzip: 238000
});
enforce('Tools route', routeBundle('/(app)/workspace/[workspaceId]/tools'), {
	// Includes shared pagination styles, account-management translations and recovery controls.
	raw: 874000,
	gzip: 250500
});
enforce('Import route', routeBundle('/(app)/workspace/[workspaceId]/import'), {
	raw: 849000,
	gzip: 244000
});
enforce(
	'Item overview route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)'),
	{
		raw: 867000,
		gzip: 248500
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
		raw: 914000,
		gzip: 264000
	}
);
enforce(
	'Item organize route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/organize'),
	{
		raw: 871000,
		// Organize now includes the destructive-detachment confirmation dialog.
		gzip: 250500
	}
);
enforce(
	'Item annotations route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/annotations'),
	{
		// Includes shared pagination styles and account-management translations.
		raw: 876000,
		gzip: 252000
	}
);
enforce(
	'Item discussion route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/discussion'),
	{
		// Includes shared pagination styles and account-management translations.
		raw: 864000,
		gzip: 248500
	}
);
enforce('Admin overview route', routeBundle('/(app)/admin'), {
	// Includes Skeleton pagination and the separate Invitation navigation entry.
	raw: 758000,
	gzip: 214000
});
enforce('Admin users route', routeBundle('/(app)/admin/users'), {
	// Includes account containment guidance and expandable role and sign-in controls.
	raw: 769000,
	gzip: 218000
});
enforce('Admin invitations route', routeBundle('/(app)/admin/invitations'), {
	// Owns invitation creation, history, status filtering and one pagination control.
	raw: 768000,
	gzip: 217500
});
enforce('Admin workspaces route', routeBundle('/(app)/admin/workspaces'), {
	// Includes owner reassignment, bounded User search, conflict recovery and scoped completion.
	raw: 810000,
	gzip: 229500
});
enforce('Admin audit route', routeBundle('/(app)/admin/audit'), {
	// Includes the separate Invitation navigation entry and shared translations.
	raw: 758000,
	gzip: 213500
});
enforce('Admin workflows route', routeBundle('/(app)/admin/workflows'), {
	// Includes Skeleton pagination and the separate Invitation navigation entry.
	raw: 757000,
	gzip: 213000
});
enforce('Admin settings route', routeBundle('/(app)/admin/settings'), {
	// Includes the separate Invitation navigation entry and shared translations.
	raw: 747000,
	gzip: 210500
});
enforce('Admin maintenance route', routeBundle('/(app)/admin/maintenance'), {
	// Includes the separate Invitation navigation entry and shared translations.
	raw: 747000,
	gzip: 211000
});
// Includes the conditional received-invitation section; no standalone inbox route.
enforce('Workspace directory', routeBundle('/(app)/workspace'), { raw: 787000, gzip: 222000 });
enforce('Workspace general settings', routeBundle('/(app)/workspace/[workspaceId]/settings'), {
	raw: 769000,
	gzip: 218500
});
enforce('Workspace members', routeBundle('/(app)/workspace/[workspaceId]/settings/members'), {
	raw: 789000,
	gzip: 224500
});
enforce(
	'Workspace invitations',
	routeBundle('/(app)/workspace/[workspaceId]/settings/invitations'),
	{ raw: 757000, gzip: 214500 }
);
enforce(
	'Workspace advanced settings',
	routeBundle('/(app)/workspace/[workspaceId]/settings/advanced'),
	{ raw: 773000, gzip: 219500 }
);
enforce('PDF reader route', bundleSize(graphFiles(pdfReader)), {
	raw: 8000000,
	gzip: 3100000
});

const metadataRoute = '/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/metadata';
const openedEditor = mergeGraphs(
	dependencyGraph([...runtime, ...routeNodes(metadataRoute)], false),
	dependencyGraph([metadataEditorKey], true)
);
enforce('Metadata editor when open', bundleSize(graphFiles(openedEditor)), {
	// Includes shared pagination styles and account-management translations.
	raw: 1106000,
	gzip: 317500
});
