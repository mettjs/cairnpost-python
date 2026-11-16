"""The Python client for CairnPost, a self-hostable gateway for transactional email.

It sends email, reads what became of it, manages suppressions, templates
and webhook endpoints, reads the email that comes in, and verifies the
webhooks CairnPost sends. It uses the standard library only.

The client never retries by itself. An error says what happened and
whether trying again is right (see `CairnPostError`); the application
decides.
"""

from ._batch import BatchResult, failed
from ._client import DEFAULT_MAX_ANSWER_BYTES, DEFAULT_TIMEOUT, CairnPost
from ._codes import ErrorCode
from ._deliveries import Delivery, DeliveryState
from ._email import Attachment, Email, Sent, UseTemplate
from ._emails import Emails
from ._errors import (
    CairnPostError,
    NotCapturingError,
    TransportError,
    TransportReason,
    is_not_found,
    is_wrong_address,
    may_have_sent,
)
from ._events import BounceType, EventEmail, EventReceived, EventSuppression, EventType, WebhookEvent
from ._message import Content, FileInfo, Message, MessageEvent, Recipient, State
from ._pages import Page
from ._received import Received, ReceivedContent, ReceivedEmails, ReceivedHeader
from ._status import CapturedEmail, Health, Limits, Quota
from ._suppressions import Reason, Suppression, Suppressions
from ._templates import Template, TemplateList, Templates, TemplateVariable
from ._verify import DEFAULT_TOLERANCE, RequestHeaders, Verifier, WebhookError, WebhookRefusal
from ._version import __version__
from ._webhooks import Webhook, Webhooks, WebhookTest

__all__ = [
    "DEFAULT_MAX_ANSWER_BYTES",
    "DEFAULT_TIMEOUT",
    "DEFAULT_TOLERANCE",
    "Attachment",
    "BatchResult",
    "BounceType",
    "CairnPost",
    "CairnPostError",
    "CapturedEmail",
    "Content",
    "Delivery",
    "DeliveryState",
    "Email",
    "Emails",
    "ErrorCode",
    "EventEmail",
    "EventReceived",
    "EventSuppression",
    "EventType",
    "FileInfo",
    "Health",
    "Limits",
    "Message",
    "MessageEvent",
    "NotCapturingError",
    "Page",
    "Quota",
    "Reason",
    "Received",
    "ReceivedContent",
    "ReceivedEmails",
    "ReceivedHeader",
    "Recipient",
    "RequestHeaders",
    "Sent",
    "State",
    "Suppression",
    "Suppressions",
    "Template",
    "TemplateList",
    "TemplateVariable",
    "Templates",
    "TransportError",
    "TransportReason",
    "UseTemplate",
    "Verifier",
    "Webhook",
    "WebhookError",
    "WebhookEvent",
    "WebhookRefusal",
    "WebhookTest",
    "Webhooks",
    "__version__",
    "failed",
    "is_not_found",
    "is_wrong_address",
    "may_have_sent",
]
