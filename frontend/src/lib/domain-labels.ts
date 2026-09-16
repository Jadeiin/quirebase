import { msg, type MessageKey } from '$lib/i18n';

const labels = {
	administrator: msg('Administrator'),
	member: msg('Member'),
	owner: msg('Owner'),
	editor: msg('Editor'),
	viewer: msg('Viewer'),
	active: msg('Active'),
	archived: msg('Archived'),
	private: msg('Private'),
	public: msg('Public'),
	pending: msg('Pending'),
	ready: msg('Ready'),
	failed: msg('Failed'),
	committed: msg('Committed'),
	running: msg('Running'),
	succeeded: msg('Succeeded'),
	cancelled: msg('Cancelled'),
	expired: msg('Expired'),
	revoked: msg('Revoked'),
	empty: msg('Not generated'),
	revision: msg('PDF'),
	attachment: msg('Attachment'),
	highlight: msg('Highlight'),
	underline: msg('Underline'),
	strikeout: msg('Strikeout'),
	note: msg('Note'),
	free_text: msg('Free text'),
	ink: msg('Ink'),
	rectangle: msg('Rectangle'),
	ellipse: msg('Ellipse'),
	line: msg('Line'),
	arrow: msg('Arrow')
} satisfies Record<string, MessageKey>;

export type DomainLabelValue = keyof typeof labels;

export function domainLabel(value: string): MessageKey {
	return labels[value as DomainLabelValue];
}
