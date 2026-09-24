import { msg, type MessageKey } from '$lib/i18n';

const labels = {
	administrator: msg({ message: 'Administrator', comment: 'User role.' }),
	member: msg({ message: 'Member', comment: 'User role.' }),
	owner: msg({ message: 'Owner', comment: 'Workspace role or resource owner label.' }),
	admin: msg({ message: 'admin', comment: 'Workspace role.' }),
	editor: msg({ message: 'Editor', comment: 'Workspace role.' }),
	reviewer: msg({ message: 'reviewer', comment: 'Workspace role.' }),
	viewer: msg({ message: 'Viewer', comment: 'Workspace role.' }),
	active: msg({ message: 'Active', comment: 'Workspace or Project lifecycle state.' }),
	archived: msg({ message: 'Archived', comment: 'Workspace or Project lifecycle state.' }),
	suspended: msg({ message: 'suspended', comment: 'Workspace member state.' }),
	workspace: msg({ message: 'Workspace-wide', comment: 'Project participation policy.' }),
	open: msg({ message: 'Open', comment: 'Project participation policy.' }),
	managed: msg({ message: 'Managed', comment: 'Project participation policy.' }),
	private: msg({
		message: 'Private',
		comment: 'Project visibility or annotation scope.'
	}),
	public: msg({
		message: 'Public',
		comment: 'Project visibility or annotation scope.'
	}),
	pending: msg({ message: 'Pending', comment: 'Workflow or record state.' }),
	ready: msg({ message: 'Ready', comment: 'Workflow or record state.' }),
	failed: msg({ message: 'Failed', comment: 'Workflow or record state.' }),
	committed: msg({ message: 'Committed', comment: 'Import Batch state.' }),
	running: msg({ message: 'Running', comment: 'Workflow or record state.' }),
	succeeded: msg({ message: 'Succeeded', comment: 'Workflow or record state.' }),
	cancelled: msg({ message: 'Cancelled', comment: 'Workflow or record state.' }),
	expired: msg({ message: 'Expired', comment: 'API Token or invitation state.' }),
	revoked: msg({ message: 'Revoked', comment: 'API Token or session state.' }),
	empty: msg('Not generated'),
	revision: msg({ message: 'PDF', comment: 'File kind for a PDF revision.' }),
	attachment: msg({
		message: 'Attachment',
		comment: 'File kind for a supplementary file.'
	}),
	highlight: msg({ message: 'Highlight', comment: 'PDF annotation kind: text markup.' }),
	underline: msg({ message: 'Underline', comment: 'PDF annotation kind: text markup.' }),
	strikeout: msg({ message: 'Strikeout', comment: 'PDF annotation kind: text markup.' }),
	note: msg({
		message: 'Note',
		comment: 'PDF annotation kind: a text comment attached to a region.'
	}),
	free_text: msg({
		message: 'Free text',
		comment: 'PDF annotation kind: a text box placed directly on the page.'
	}),
	ink: msg({ message: 'Ink', comment: 'PDF annotation kind: a freehand drawing.' }),
	rectangle: msg({ message: 'Rectangle', comment: 'PDF shape annotation kind.' }),
	ellipse: msg({ message: 'Ellipse', comment: 'PDF shape annotation kind.' }),
	line: msg({ message: 'Line', comment: 'PDF shape annotation kind.' }),
	arrow: msg({ message: 'Arrow', comment: 'PDF shape annotation kind.' })
} satisfies Record<string, MessageKey>;

export type DomainLabelValue = keyof typeof labels;

export function domainLabel(value: string): MessageKey {
	return labels[value as DomainLabelValue];
}
