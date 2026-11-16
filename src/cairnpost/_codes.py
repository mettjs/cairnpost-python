from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Names of the errors CairnPost answers, as `CairnPostError.code` holds them."""

    VALIDATION = "validation_error"
    REJECTED_BY_UPSTREAM = "rejected_by_upstream"
    #: The mail provider refused the email, and the sending domain's DNS
    #: lacks a record the provider asks. The domain is likely not set up
    #: with the provider, which then refuses every email from it: this is
    #: the sender failing, not one bad email. A server before 0.1.1 says
    #: REJECTED_BY_UPSTREAM instead.
    SENDER_DOMAIN_NOT_READY = "sender_domain_not_ready"
    RECIPIENT_SUPPRESSED = "recipient_suppressed"
    IDEMPOTENT_MISMATCH = "invalid_idempotent_request"
    IDEMPOTENT_IN_FLIGHT = "concurrent_idempotent_requests"
    MISSING_KEY = "missing_api_key"
    INVALID_KEY = "invalid_api_key"
    DOMAIN_NOT_ALLOWED = "domain_not_allowed"
    ADMIN_KEY_REQUIRED = "admin_key_required"
    NOT_FOUND = "not_found"
    #: The server has nothing at the path asked for: the base URL is
    #: wrong, or the server is older than this client.
    ROUTE_NOT_FOUND = "route_not_found"
    #: The path is there and does not take the method: the server is older
    #: or newer than this client.
    METHOD_NOT_ALLOWED = "method_not_allowed"
    TOO_LARGE = "request_too_large"
    #: The request did not arrive whole in time. Nothing was done with it.
    REQUEST_INCOMPLETE = "request_incomplete"
    RATE_LIMITED = "rate_limit_exceeded"
    UPSTREAM_UNKNOWN = "upstream_unknown"
    UPSTREAM_DOWN = "upstream_unavailable"
    UNAVAILABLE = "unavailable"
    #: The email to cancel or move does not wait to be sent: it is being
    #: sent, was sent, or was cancelled.
    NOT_SCHEDULED = "not_scheduled"
    #: The emails waiting to be sent hold as much as the server keeps.
    #: Nothing was kept or sent.
    SCHEDULE_FULL = "schedule_full"
    #: A batch ended before this email's turn. Nothing of it was sent.
    NOT_STARTED = "not_started"
    #: The sending domain already has a template of that name.
    NAME_TAKEN = "name_taken"
    #: What was to be changed was changed by others at the same time. Read
    #: it and try again.
    CHANGED_MEANWHILE = "changed_meanwhile"
    INTERNAL = "internal_error"


def known(name: object) -> ErrorCode | None:
    """The name as one of CairnPost's own; None for any other."""
    if not isinstance(name, str):
        return None
    try:
        return ErrorCode(name)
    except ValueError:
        return None
