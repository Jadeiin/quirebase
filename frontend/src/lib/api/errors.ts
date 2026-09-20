import { ApiError } from '$lib/api/client';
import { msg, translate, type MessageKey } from '$lib/i18n';

const messages: Record<string, MessageKey> = {
	invalid_credentials: msg('Invalid username or password.'),
	authentication_required: msg('Please sign in again.'),
	origin_mismatch: msg('This request came from an unexpected origin.'),
	invitation_not_found: msg('This invitation is invalid or has expired.'),
	login_throttled: msg('Too many sign-in attempts. Try again later.'),
	invitation_conflict: msg('This invitation can no longer be used.'),
	tag_conflict: msg('This Tag conflicts with an existing Tag.'),
	project_member_conflict: msg('This Project membership changed. Refresh and try again.'),
	document_not_ready: msg('This Document is not ready yet.'),
	import_batch_conflict: msg('This Import Batch cannot be changed in its current state.'),
	unsupported_media_type: msg('This file type is not supported.'),
	upstream_service_error: msg('The external service is temporarily unavailable.'),
	not_found: msg('The requested resource was not found.'),
	permission_denied: msg('You do not have permission to perform this action.'),
	validation_failed: msg('Please check the submitted values.'),
	content_too_large: msg('The uploaded content is too large.'),
	version_conflict: msg('This record changed. Refresh and try again.'),
	range_not_satisfiable: msg('The requested file range is not available.'),
	rate_limited: msg('Too many requests. Try again later.'),
	method_not_allowed: msg('This action is not available.'),
	conflict: msg('The request conflicts with the current state.'),
	invalid_request: msg('The request could not be completed.'),
	domain_error: msg('The request could not be completed.'),
	request_failed: msg('The request could not be completed.'),
	internal_error: msg('Something went wrong. Try again.')
};

export function apiErrorMessage(reason: unknown, fallback: string): string {
	if (!(reason instanceof ApiError)) return fallback;
	return translate(messages[reason.code] ?? fallback);
}
