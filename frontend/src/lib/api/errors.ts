import { ApiError } from '#lib/api/client.js';
import { i18n } from '@lingui/core';
import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';

const notFoundMessage = msg`The requested resource was not found.`;
const requestFailedMessage = msg`The request could not be completed.`;

const messages: Record<string, MessageDescriptor> = {
	invalid_credentials: msg`Invalid username or password.`,
	authentication_required: msg`Please sign in again.`,
	origin_mismatch: msg`This request came from an unexpected origin.`,
	invitation_not_found: msg`This invitation is invalid or has expired.`,
	login_throttled: msg`Too many sign-in attempts. Try again later.`,
	invitation_conflict: msg`This invitation can no longer be used.`,
	tag_conflict: msg`This Tag conflicts with an existing Tag.`,
	project_participation_conflict: msg`This Project participation changed. Refresh and try again.`,
	workspace_context_required: msg`Unable to load Workspace information. Refresh and try again.`,
	workspace_unavailable: msg`You no longer have access to this Workspace.`,
	workspace_lifecycle_error: msg`This Workspace is read only.`,
	project_lifecycle_error: msg`This Project is read only.`,
	document_not_ready: msg`This Document is not ready yet.`,
	import_batch_conflict: msg`This Import Batch cannot be changed in its current state.`,
	import_batch_unavailable: notFoundMessage,
	unsupported_media_type: msg`This file type is not supported.`,
	upstream_service_error: msg`The external service is temporarily unavailable.`,
	not_found: notFoundMessage,
	permission_denied: msg`You do not have permission to perform this action.`,
	validation_failed: msg`Please check the submitted values.`,
	content_too_large: msg`The uploaded content is too large.`,
	version_conflict: msg`This record changed. Refresh and try again.`,
	range_not_satisfiable: msg`The requested file range is not available.`,
	rate_limited: msg`Too many requests. Try again later.`,
	method_not_allowed: msg`This action is not available.`,
	conflict: msg`The request conflicts with the current state.`,
	invalid_request: requestFailedMessage,
	domain_error: requestFailedMessage,
	request_failed: requestFailedMessage,
	internal_error: msg`Something went wrong. Try again.`
};

export function apiErrorMessage(reason: unknown, fallback: string): string {
	if (!(reason instanceof ApiError)) return fallback;
	const message = messages[reason.code];
	return message ? i18n._(message) : fallback;
}
