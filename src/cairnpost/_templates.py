from __future__ import annotations

from builtins import list as List  # a method here is named list
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from ._answer import reading
from ._read import Misshapen, fields, flag, has, items, maybe_text, said, text, time
from ._transport import Call, Transport


@dataclass(frozen=True, slots=True, kw_only=True)
class TemplateVariable:
    """A variable a template names."""

    name: str
    #: What it is filled with when a send gives it no value; None for one
    #: every send must give, and then `required` is True.
    default: str | None
    required: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class Template:
    """An email written once to be sent many times.

    A subject and bodies that name variables as `{{name}}`.
    """

    id: str
    #: How a send asks for it.
    name: str
    #: The sending domain it belongs to; None for one that serves every
    #: domain.
    domain: str | None
    subject: str
    #: `html` and `text` are None in a list: `get` reads them.
    html: str | None
    text: str | None
    variables: List[TemplateVariable]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class TemplateList:
    """A list of templates, each without its bodies.

    `more` says the server has others than the list holds: ask for one
    sending domain's to see them.
    """

    data: List[Template]
    more: bool


def _read_variable(v: object) -> TemplateVariable:
    x = fields(v)
    by_default = x.get("default")
    # An empty default is a default all the same.
    if by_default is not None and not isinstance(by_default, str):
        raise Misshapen
    return TemplateVariable(name=text(x, "name"), default=by_default, required=flag(x, "required"))


def _read_template(v: object) -> Template:
    o = fields(v)
    return Template(
        id=said(o, "id"),
        name=text(o, "name"),
        domain=maybe_text(o, "domain"),
        subject=text(o, "subject"),
        html=maybe_text(o, "html"),
        text=maybe_text(o, "text"),
        variables=items(o, "variables", _read_variable),
        created_at=time(o, "created_at"),
        updated_at=time(o, "updated_at"),
    )


def _read_list(v: object) -> TemplateList:
    # Whether there are more is said either way: left out, it must not
    # read as "these are all".
    o = has(fields(v), "data", "more")
    return TemplateList(data=items(o, "data", _read_template), more=flag(o, "more"))


class Templates:
    """The templates emails are sent from. Every call needs an admin key."""

    __slots__ = ("_t",)

    def __init__(self, transport: Transport) -> None:
        self._t = transport

    def _one(self, k: Call) -> Template:
        return reading(self._t.read_json(k), _read_template)

    def create(
        self,
        *,
        name: str,
        subject: str,
        html: str | None = None,
        text: str | None = None,
        domain: str | None = None,
        defaults: Mapping[str, str] | None = None,
    ) -> Template:
        """Keeps a template.

        `html` or `text` is required. `domain` is the sending domain it is
        for; left out, it is the key's own domain, or serves every domain
        when the key is bound to none. `defaults` are what a variable is
        filled with when a send gives it no value. A `CairnPostError` with
        the code `name_taken` says its sending domain already has one of
        that name.
        """
        body: dict[str, object] = {"name": name}
        if domain:
            body["domain"] = domain
        body["subject"] = subject
        if html:
            body["html"] = html
        if text:
            body["text"] = text
        if defaults:
            body["defaults"] = dict(defaults)
        return self._one(Call(method="POST", path=("templates",), body=body))

    def list(self, domain: str | None = None) -> TemplateList:
        """Answers the templates the key manages, by sending domain and name.

        Its own domain's if it is bound to one; otherwise those of the
        domain given, or all when it is left out.
        """
        return reading(
            self._t.read_json(Call(method="GET", path=("templates",), query={"domain": domain or None})),
            _read_list,
        )

    def get(self, id: str) -> Template:
        """Answers one template whole.

        `is_not_found` says there is none, or that it is another sending
        domain's.
        """
        return self._one(Call(method="GET", path=("templates", id)))

    def update(
        self,
        id: str,
        *,
        name: str | None = None,
        subject: str | None = None,
        html: str | None = None,
        text: str | None = None,
        defaults: Mapping[str, str] | None = None,
    ) -> Template:
        """Changes a template and answers it as it now is.

        What is left out is left as it is; what is given is changed to
        exactly that, so `defaults={}` leaves no variable a default.
        Emails asked for from then on are made from it; one that already
        waits to be sent keeps what it was filled with. A `CairnPostError`
        with the code `changed_meanwhile` says others kept changing it at
        the same time: read it and try again.
        """
        given = {"name": name, "subject": subject, "html": html, "text": text}
        body: dict[str, object] = {key: value for key, value in given.items() if value is not None}
        if defaults is not None:
            body["defaults"] = dict(defaults)
        return self._one(Call(method="PATCH", path=("templates", id), body=body))

    def delete(self, id: str) -> None:
        """Deletes a template: a send that names it is refused from then on."""
        self._t.empty(Call(method="DELETE", path=("templates", id)))
