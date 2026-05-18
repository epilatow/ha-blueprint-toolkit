# This is AI generated code
"""Pure helpers (no HA imports anywhere).

The "pure" group of the three-flavour split documented in
``helpers.py``'s shim docstring. Safe to import from a
non-HA test environment; ``test_helpers_logic_has_no_ha_imports``
enforces this via AST walk.

Module-scope rule: NO ``homeassistant.*`` imports of any
kind, including ``if TYPE_CHECKING:`` (a pure helper that
needs an HA type for documentation should use
``from __future__ import annotations`` + a string-form
annotation).

Cross-flavour rule: this file imports from neither
``helpers_runtime`` nor ``helpers_lifecycle``. The single
intentional carve-out is ``make_emit_config_error``'s
returned closure, which lazily imports
``emit_config_error`` from ``helpers_runtime`` inside its
body -- the per-test allow-list in
``test_helpers_partial_order_layering`` notes this
explicitly.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote as _urlquote

from .const import DOMAIN

# Domains that respond to ``homeassistant.turn_on`` /
# ``turn_off``. Used by every on/off-driving controller's
# argparse to reject selector-bypassing YAML edits before
# the service layer dispatches a silent no-op against an
# unsupported entity. Per-blueprint selector ``domain:``
# lists are UI hints only; this set is the authoritative
# argparse-time guard.
CONTROLLABLE_DOMAINS: frozenset[str] = frozenset(
    {
        "automation",
        "climate",
        "cover",
        "fan",
        "humidifier",
        "input_boolean",
        "light",
        "lock",
        "media_player",
        "switch",
        "vacuum",
        "water_heater",
    },
)


def validate_controlled_entity_domains(
    entity_ids: list[str],
    field_name: str,
) -> list[str]:
    """Return one config-error bullet per uncontrollable entity.

    Each bullet matches the canonical
    ``"<field_name>: '<eid>' does not support on/off (pick
    an entity in one of: <sorted-domains>)"`` shape so
    every on/off-driving handler surfaces the same wording.
    Empty list when every entity is in
    ``CONTROLLABLE_DOMAINS``.

    Domain extraction is the everything-before-the-first-
    dot of each entity_id; entity_ids without a dot are
    treated as zero-length-domain (which is not in the set
    and so flags). Caller is expected to have already run
    state-existence checks if it cares about typos vs
    domain mismatches.
    """
    bullets: list[str] = []
    valid = ", ".join(sorted(CONTROLLABLE_DOMAINS))
    for eid in entity_ids:
        domain = eid.split(".", 1)[0] if "." in eid else ""
        if domain not in CONTROLLABLE_DOMAINS:
            bullets.append(
                f"{field_name}: {eid!r}"
                f" does not support on/off (pick an entity in one of:"
                f" {valid})",
            )
    return bullets


def notification_prefix(service: str, instance_id: str) -> str:
    """Common prefix for a handler's notification family.

    Format: ``blueprint_toolkit_{service}__{instance_id}__``.
    Per-category suffix is appended at each call site;
    the trailing ``__`` keeps the field separator parseable
    (HA entity IDs never contain ``__``).
    """
    return f"blueprint_toolkit_{service}__{instance_id}__"


def resolve_target_integrations(
    all_integrations: list[str],
    include: list[str],
    exclude: list[str],
) -> set[str]:
    """Apply include / exclude filters to a list of integrations.

    Empty ``include`` means "all integrations" (matches every
    watchdog blueprint's documented behaviour). ``exclude`` is
    then subtracted from the resulting set.
    """
    if include:
        target = set(include)
    else:
        target = set(all_integrations)
    for ex in exclude:
        target.discard(ex)
    return target


def format_timestamp(template: str, dt: datetime) -> str:
    """Format timestamp tokens in a template string.

    Supported tokens: YYYY, YY, MM, DD, HH, mm, ss.
    """
    if not template:
        return ""
    # Replace longest tokens first so YYYY is consumed
    # before YY can match.
    result = template
    result = result.replace("YYYY", f"{dt.year:04d}")
    result = result.replace("YY", f"{dt.year % 100:02d}")
    result = result.replace("MM", f"{dt.month:02d}")
    result = result.replace("DD", f"{dt.day:02d}")
    result = result.replace("HH", f"{dt.hour:02d}")
    result = result.replace("mm", f"{dt.minute:02d}")
    result = result.replace("ss", f"{dt.second:02d}")
    return result


def format_notification(
    text: str,
    prefix: str,
    suffix: str,
    current_time: datetime,
) -> str:
    """Format notification with prefix/suffix and timestamp tokens."""
    formatted_prefix = format_timestamp(prefix, current_time)
    formatted_suffix = format_timestamp(suffix, current_time)
    return f"{formatted_prefix}{text}{formatted_suffix}"


def md_escape(s: str) -> str:
    r"""Escape CommonMark ``\``, ``[``, ``]`` for safe interpolation.

    Apply to any HA-controlled string interpolated into a
    ``persistent_notification`` ``message`` body -- both
    inside ``[text](url)`` link text *and* in plain-text
    portions, since an unescaped ``[`` in plain text can
    still pair with a later ``](`` to form a bogus link.

    Done as a single ``str.translate`` pass so the
    backslashes inserted for ``[``/``]`` are not themselves
    re-escaped by the ``\`` mapping.

    Escaping is NOT needed for:

    - Notification ``title`` strings -- HA renders titles
      as plain text (frontend ``persistent-notification-item``
      uses a Lit ``<span>`` with auto-escaping, only
      ``message`` goes through ``<ha-markdown>``).
    - Integration domains and entity_ids -- constrained
      to ``[a-z0-9_]+``, no markdown specials possible.
    - URLs -- the ``(...)`` target portion of a markdown
      link is not displayed, only the ``[...]`` text
      portion is.
    - Numeric IDs (node ids, device counts, byte sizes).
    - Values rendered inside a backtick code span
      (`` `value` ``) -- code spans suppress markdown
      interpretation, so ``[``/``]`` inside backticks
      render literally.

    Escaping IS needed for human-typed strings such as
    automation friendly names, vol.Invalid messages
    (which can include the offending input value),
    error messages from external APIs, etc.
    """
    return s.translate(
        {
            ord("\\"): "\\\\",
            ord("["): "\\[",
            ord("]"): "\\]",
        },
    )


###############################################################
# URL + link helpers
#
# HA's frontend exposes a small handful of URL forms that
# actually navigate the user somewhere useful. None of them
# accept ``entity_id`` directly -- the only entity-id
# deep-link in HA's UI is opened via JavaScript (more-info /
# settings dialog), not URL navigation. See
# ``AUTOMATIONS.md`` "URL generation" for the full survey.
#
# The verified-working forms used by handlers in this
# integration:
#
# - ``/config/devices/device/<device_id>``
#       device panel listing the device's entities.
# - ``/config/entities/?device=<d>&config_entry=<c>``
#       entities table filtered to one device's entities
#       from one config entry. The narrowest entity-list
#       deep-link possible (excludes wrappers from other
#       integrations like ``switch_as_x`` even when they
#       share the device).
# - ``/config/entities/?config_entry=<id>``
#       entities table filtered to one config entry's
#       entities.
# - ``/config/entities/?domain=<platform>``
#       entities table filtered to one platform.
# - ``/config/entities/``
#       bare entities table (no filter).
# - ``/config/integrations/integration/<integration>``
#       per-integration page.
# - ``/config/automation/edit/<id>``
#       automation editor.
# - ``/config/script/edit/<unique_id>``
#       script editor.
# - ``/core_configurator/?loadfile=<path>``
#       file-editor add-on (HA OS / Supervised), opens the
#       named file at the top. ``<path>`` is filesystem-
#       relative to the configurator's BASEPATH (typically
#       ``/config/``). Line-number deep-linking is not
#       supported by the add-on. Only useful when the
#       ``core_configurator`` add-on is installed -- the
#       handler probes HA's hassio API and only emits this
#       link form when present.
#
# The ``*_url(...)`` functions below return raw URL strings.
# Most call sites should use the matching public
# ``*_link(name, ...)`` wrapper instead, which returns
# markdown-ready ``[name](url)`` text with the name
# ``md_escape``-d. The raw URL functions are public for the
# narrow cases that need them: storing a URL on a dataclass
# for later assembly, or building a link whose visible text
# is a code-span (backtick-wrapped entity_id) rather than a
# friendly name. Both happen in RW.
#
# Putting all URL templating in one place means a future
# routing change only requires updating one function, and
# per-call-site URL guessing (which has bitten us multiple
# times) is structurally prevented.
#
# For deviceless entities -- where no URL form lands the
# user on a single entity -- ``deviceless_entity_link``
# returns prose with a link to the bare entities table plus
# explicit "search for `<eid>` in the list" instructions.


def device_url(device_id: str) -> str:
    """Raw URL for a device's panel."""
    return f"/config/devices/device/{device_id}"


def device_entity_url(*, device_id: str, config_entry_id: str) -> str:
    """Raw URL for the entities table filtered to one
    device-attached entity.

    Both filters are required: the entities table requires
    ``device`` to be present for filtering to surface any
    rows, AND ``config_entry`` is what excludes wrappers
    (e.g. switch_as_x) that share the source's device_id.
    """
    return (
        f"/config/entities/?device={device_id}&config_entry={config_entry_id}"
    )


def config_entry_url(config_entry_id: str) -> str:
    """Raw URL for the entities table filtered to one config entry."""
    return f"/config/entities/?config_entry={config_entry_id}"


def domain_entities_url(domain: str) -> str:
    """Raw URL for the entities table filtered to one platform."""
    return f"/config/entities/?domain={domain}"


def integration_url(integration: str) -> str:
    """Raw URL for an integration's per-integration page."""
    return f"/config/integrations/integration/{integration}"


def automation_edit_url(automation_id: str) -> str:
    """Raw URL for the automation editor."""
    return f"/config/automation/edit/{automation_id}"


def script_edit_url(unique_id: str) -> str:
    """Raw URL for the script editor."""
    return f"/config/script/edit/{unique_id}"


def entities_dashboard_url() -> str:
    """Raw URL for the bare entities table (no filter)."""
    return "/config/entities/"


def dashboard_url(slug: str) -> str:
    """Raw URL for a Lovelace dashboard view by slug.

    Lovelace dashboards (the user-facing views, not the
    Settings panels) live at the bare ``/<slug>`` -- the
    default ``lovelace`` dashboard is at ``/lovelace``,
    custom user dashboards at ``/<their-slug>``.
    """
    return f"/{slug}"


def device_link(name: str, device_id: str) -> str:
    """Markdown link to a device's panel."""
    return f"[{md_escape(name)}]({device_url(device_id)})"


def device_entity_link(
    name: str,
    *,
    device_id: str,
    config_entry_id: str,
) -> str:
    """Markdown link to the entities table filtered to one
    device-attached entity (intersected with its config
    entry, which excludes wrappers from other integrations).

    Use when the source entity is device-attached AND has a
    config_entry_id. Switch_as_x sources from real
    integrations (Z-Wave, Lutron, etc.) fit; helper-based
    sources (input_boolean, template) do not -- use
    ``deviceless_entity_link`` for those.
    """
    url = device_entity_url(
        device_id=device_id,
        config_entry_id=config_entry_id,
    )
    return f"[{md_escape(name)}]({url})"


def config_entry_link(name: str, config_entry_id: str) -> str:
    """Markdown link to the entities table filtered to one
    config entry's entities.

    Use when the *config entry* is the unit of interest --
    e.g., RW source-orphan listings link a whole
    integration's worth of orphan entries.
    """
    return f"[{md_escape(name)}]({config_entry_url(config_entry_id)})"


def domain_entities_link(name: str, domain: str) -> str:
    """Markdown link to the entities table filtered to one
    platform.

    Use when no config_entry_id is available but the
    integration's platform name is. Less narrow than
    ``config_entry_link`` (shows entities from every config
    entry of that integration) but useful for orphan
    listings where the registry entry is the only signal
    that survives integration removal.
    """
    return f"[{md_escape(name)}]({domain_entities_url(domain)})"


def integration_link(name: str, integration: str) -> str:
    """Markdown link to an integration's per-integration page."""
    return f"[{md_escape(name)}]({integration_url(integration)})"


def automation_edit_link(name: str, automation_id: str) -> str:
    """Markdown link to the automation editor for one
    automation by its ``id`` (the YAML id).
    """
    return f"[{md_escape(name)}]({automation_edit_url(automation_id)})"


def script_edit_link(name: str, unique_id: str) -> str:
    """Markdown link to the script editor for one script by
    its registry ``unique_id`` (the script slug).
    """
    return f"[{md_escape(name)}]({script_edit_url(unique_id)})"


def script_dashboard_link(name: str) -> str:
    """Markdown link to the script-list dashboard.

    HA's per-integration page for ``script``
    (``/config/integrations/integration/script``) is empty
    because ``script`` is a built-in domain rather than a
    config-flow integration. ``/config/script/dashboard`` is
    the actual list-all-scripts page.
    """
    return f"[{md_escape(name)}](/config/script/dashboard)"


def dashboard_link(name: str, slug: str) -> str:
    """Markdown link to a Lovelace dashboard view by slug."""
    return f"[{md_escape(name)}]({dashboard_url(slug)})"


def _path_supports_file_editor_link(source_file: str) -> bool:
    """True when ``source_file`` is the kind of path that gets a link.

    HA-managed JSON state under ``.storage/`` is documented as
    not-for-hand-editing; pointing the configurator at one of
    those paths puts the user on exactly the surface HA tells
    them to avoid. Every other relative path under
    ``/config/`` (the typical RW source-file shapes:
    ``automations.yaml``, ``packages/foo.yaml``, etc.) is
    user-editable.
    """
    return not source_file.startswith(".storage/")


def file_editor_link(
    source_file: str,
    file_editor_ingress_url: str,
) -> str:
    """Render ``source_file`` for inclusion in a notification body.

    The single rendering helper for source-file paths in
    notifications: callers always invoke it and the helper
    decides whether to emit a clickable link to the file-
    editor add-on or a plain backtick-wrapped path.

    Returns the markdown link form
    ``[`<file>`]({ingress_url}?loadfile=<file>)`` when ALL
    of:

    - ``file_editor_ingress_url`` is non-empty (the handler
      detected the ``core_configurator`` add-on and read
      its per-installation ingress URL, e.g.
      ``/api/hassio_ingress/9V5z.../``). HA's panel route
      (``/core_configurator/``) consumes query strings on
      the way through the frontend router, so the link
      MUST point at the direct ingress URL.
    - ``source_file`` looks user-editable -- specifically
      not under ``.storage/`` (HA-managed JSON, not for
      hand-edits).

    Otherwise returns the bare ``\\`<file>\\``` form so a
    user without the add-on still sees the path in a code
    span. Centralising the decision here keeps call sites
    agnostic of whether links are supported in the current
    environment.

    The path is URL-quoted (``urllib.parse.quote`` with
    ``safe="/"``) so ``&``, ``#``, ``?``, spaces, and other
    query-string metacharacters survive the trip into the
    add-on. Path separators stay un-quoted so the
    configurator can resolve nested paths
    (``packages/foo.yaml``). Line-number deep-linking is
    not supported by the add-on (its HTML init code never
    calls Ace's ``editor.gotoLine``); the link opens the
    file at the top.

    Both branches wrap the path in backticks (a markdown
    code span). Code spans suppress markdown processing
    for the common metacharacters (``[``, ``]``, ``\\``,
    ``*``, ``_``), so neither branch needs ``md_escape``
    -- HA's ``<ha-markdown>`` renderer (markdown-it)
    treats the visible text as opaque code-span content.
    The ``[`` outside the link label in the link branch
    is structural markdown, not user input, and isn't a
    candidate for escaping. The only failure mode in
    either branch is a path that contains a literal
    backtick: that closes the code span early. RW's
    owner ``source_file`` values (filesystem paths under
    ``/config/`` from HA's parsed YAML / JSON) don't
    carry backticks in practice.

    The string argument keeps this helper pure (no HA
    runtime dependency); the handler probes
    ``file_editor_addon_ingress_url(hass)`` once per
    evaluation and threads the result through.
    """
    if file_editor_ingress_url and _path_supports_file_editor_link(source_file):
        url = (
            f"{file_editor_ingress_url}"
            f"?loadfile={_urlquote(source_file, safe='/')}"
        )
        return f"[`{source_file}`]({url})"
    return f"`{source_file}`"


def deviceless_entity_link(name: str, entity_id: str) -> str:
    """Prose with a link to the entities dashboard plus
    instructions to search for the entity_id.

    HA's frontend doesn't accept entity_id as a URL filter,
    and the search box is set via ``history.state`` (not URL
    params), so a deviceless entity can't be deep-linked to
    a single-row view. Best we can do: link to
    ``/config/entities/`` and tell the user to type the
    entity_id into the search box.
    """
    return (
        f"[{md_escape(name)}]({entities_dashboard_url()})"
        f" (search for `{entity_id}` in the list)"
    )


def device_header_line(name: str, device_id: str) -> str:
    """Render the canonical ``Device: [<name>](<url>)`` header line.

    Used as the first body line in every per-device watchdog
    notification (DW unavailable / stale, DW disabled-
    diagnostics, EDW per-device drift). Centralised so the
    line shape stays consistent across handlers; tests pin
    the format.
    """
    return f"Device: {device_link(name, device_id)}"


def slugify(text: str) -> str:
    """Return a Home Assistant-compatible slug from ``text``.

    Mirrors ``homeassistant.util.slugify(text, separator="_")``
    for the ASCII-only common case: NFKD decomposition,
    drop non-ASCII characters, lowercase, collapse runs of
    non-alphanumeric characters into a single underscore,
    and strip leading and trailing underscores. Empty input
    returns ``""``; non-empty input that collapses to an
    empty slug (e.g. emoji-only, punctuation-only) returns
    ``"unknown"``, matching HA's fallback.
    """
    import unicodedata  # noqa: PLC0415

    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
    return slug or "unknown"


def matches_pattern(text: str, pattern: str) -> bool:
    """Return True if ``text`` matches the case-insensitive regex ``pattern``.

    Empty pattern returns False (no match -- callers can
    short-circuit at the call site if they want
    "no pattern means match-all"). Invalid pattern returns
    False rather than raising; callers that need to
    surface invalid regex errors should validate the
    pattern explicitly at config-parse time via
    ``re.compile``.
    """

    if not pattern:
        return False
    try:
        return bool(re.search(pattern, text, re.IGNORECASE))
    except re.error:
        return False


@dataclass
class JoinedRegexLine:
    """One valid regex line surfaced from a multi-line blueprint input.

    ``line_number`` is 1-indexed against the original raw
    string (counting empty / whitespace-only lines so the
    number lines up with what the user sees in their
    blueprint editor). ``raw`` is the stripped pattern
    text; ``compiled`` is the corresponding
    ``re.Pattern`` so per-line "matched no candidates"
    checks can run without re-compiling.
    """

    line_number: int
    raw: str
    compiled: re.Pattern[str]


@dataclass
class JoinedRegexResult:
    """Result of parsing + validating a multi-line regex input.

    ``joined`` is the pipe-joined alternation of every
    valid line (empty string when no valid lines remain),
    suitable for handing to ``re.search`` /
    ``matches_pattern``. ``errors`` is the list of
    config-error bullets for invalid lines (caller appends
    these to its argparse errors list). ``lines`` exposes
    each valid line individually -- the per-line
    attribution that ``validate_directives`` needs to flag
    "regex matched no candidates" against the specific
    offending line rather than the whole alternation.
    """

    joined: str
    errors: list[str]
    lines: list[JoinedRegexLine]


def validate_and_join_regex_patterns(
    raw: str,
    field_name: str,
) -> JoinedRegexResult:
    """Split a multi-line regex-list input, validate, and join with ``|``.

    Blueprint inputs that accept "one regex per line"
    surface as a single multi-line string at the schema
    boundary. Callers want a single combined regex they
    can hand to ``re.search`` (or to ``matches_pattern``).
    Joining naively with ``|`` would silently accept
    invalid lines and fail at runtime; we want loud
    config-time errors so the user knows which line was
    bad.

    Per-line validation:

    - Empty / whitespace-only lines are skipped silently.
    - Patterns that fail ``re.compile`` produce an error
      bullet identifying the offending line.
    - Patterns that match the empty string (``.*`` /
      ``|||||`` / ``a?`` / etc.) are rejected with an
      "matches empty string" error -- they would silently
      exclude every entity / device / id, defeating the
      purpose of the exclusion list.

    Returns a ``JoinedRegexResult`` with ``.joined`` (the
    pipe-joined alternation), ``.errors`` (config-error
    bullets the caller appends to its argparse errors
    list), and ``.lines`` (per-valid-line tracking with
    1-indexed line numbers and pre-compiled patterns,
    consumed by ``validate_directives`` for the
    "matched no candidates" check).
    """

    raw_lines = (raw or "").splitlines()
    valid_lines: list[JoinedRegexLine] = []
    errors: list[str] = []
    for idx, raw_line in enumerate(raw_lines, start=1):
        # Use the line content verbatim. Stripping would
        # silently rewrite the user's pattern -- a typo'd
        # leading or trailing space would compile to a
        # different regex than what the user wrote, AND the
        # validator would measure against the rewritten
        # pattern, hiding the typo from both surfaces.
        if not raw_line.strip():
            continue
        try:
            compiled = re.compile(raw_line)
        except re.error as exc:
            errors.append(f'{field_name}: "{raw_line}": {exc}')
            continue
        if compiled.match(""):
            errors.append(
                f'{field_name}: "{raw_line}": pattern matches empty string '
                "(would exclude everything; tighten the pattern -- e.g. "
                "anchor with ``^...$`` or drop the ``.*`` / ``?`` / "
                "trailing alternation that lets it match empty)",
            )
            continue
        valid_lines.append(
            JoinedRegexLine(line_number=idx, raw=raw_line, compiled=compiled),
        )
    joined = "|".join(line.raw for line in valid_lines)
    return JoinedRegexResult(joined=joined, errors=errors, lines=valid_lines)


@dataclass(frozen=True)
class TypedServiceResponse:
    """Typed response shape for handlers that opt into
    HA's ``SupportsResponse``.

    HA's ``ServiceResponse`` is ``dict[str, JsonValueType]
    | None``, so the on-the-wire contract between handler
    and blueprint is a free-form string-key dict. This
    dataclass pins each known field as a typed attribute
    in one place; the entrypoint converts to the wire
    dict via ``dataclasses.asdict`` only at the boundary.

    Internal handler functions (``_async_argparse``,
    ``_async_service_layer``) annotate ``-> TypedServiceResponse``
    so mypy rejects bare-dict returns -- a future agent
    cannot bypass the typed shape with ``return {"foo": "x"}``.
    All fields default so a no-data return is just
    ``return TypedServiceResponse()``.

    Add a new field here when a handler needs to expose
    one to its blueprint -- the union of all fields stays
    in this single class so callers cross-reference one
    place for the response shape.
    """

    notification_message: str = ""


@dataclass(frozen=True)
class FixService(ABC):
    """Typed payload for a per-device repair fix service.

    Each subclass corresponds to one registered service
    under the ``blueprint_toolkit`` domain. Subclasses are
    frozen dataclasses whose fields ARE the service's
    signature; ``service_name`` names the registered
    service. The dispatcher converts an instance to the
    wire payload via ``dataclasses.asdict`` only at the
    boundary, so the rest of the integration handles a
    strongly-typed object instead of a free-form
    ``(name, dict)`` tuple.

    Mirrors the ``TypedServiceResponse`` shape: typed in
    code, plain dict on the wire. The wire constraint is
    HA's issue registry: it persists ``data`` to
    ``.storage`` via JSON round-trip and types it as
    ``dict[str, str | int | float | None]``, so every
    field on every subclass must be a JSON primitive.

    Adding a new fix service means defining a subclass
    here, registering the matching
    ``hass.services.async_register`` in
    ``__init__.py:_register_fix_services``, and adding
    the spec to ``strings.json`` / ``translations/en.json``.
    """

    @property
    @abstractmethod
    def service_name(self) -> str:
        """The HA service name to dispatch this payload to."""


@dataclass(frozen=True)
class FixEdwDeviceDrift(FixService):
    """Per-device EDW fix: regenerate drifted entity IDs +
    clear stale name overrides on every entity attached to
    ``device_id``. Backed by ``fix_edw_device_drift``.
    """

    device_id: str

    @property
    def service_name(self) -> str:
        return "fix_edw_device_drift"


@dataclass(frozen=True)
class FixDwDeviceDisabledDiagnostics(FixService):
    """Per-device DW fix: re-enable each disabled
    recommended-diagnostic entity attached to ``device_id``.
    Backed by ``fix_dw_device_disabled_diagnostics``.
    """

    device_id: str

    @property
    def service_name(self) -> str:
        return "fix_dw_device_disabled_diagnostics"


@dataclass
class PersistentNotification:
    """A persistent notification or repair-issue spec.

    ``active=True`` means create (or refresh in place);
    ``active=False`` means dismiss. Pure data so logic
    layers can return these without taking an HA
    dependency, and ``process_persistent_notifications``
    can apply them in one batch.

    ``instance_id`` is the automation entity_id this
    notification belongs to. When set, the dispatcher
    looks the automation up in ``hass.states`` and
    prepends an ``Automation: [{name}](edit-link)\\n``
    line to the message body so users can click straight
    through to the broken / problematic automation. All
    notification builders that originate from a per-
    instance service call should set this; ad-hoc one-off
    notifications can leave it empty.

    ``repair_callback`` opts the spec into the HA Repairs
    surface. When set to a ``FixService`` instance AND the
    dispatcher is told ``create_repairs=True``, the spec
    routes to the issue registry instead of persistent
    notifications -- the issue's fix flow invokes
    ``hass.services.async_call(DOMAIN, fix.service_name,
    asdict(fix))`` when the user clicks Submit. The
    ``FixService`` subclass hierarchy pins each fix
    service's typed signature in one place; ``asdict`` at
    the boundary keeps the on-wire payload a flat dict of
    JSON primitives, which is what HA's issue registry can
    persist to ``.storage``.

    Other ``PersistentNotification`` fields remain
    meaningful for the issue: ``title`` / ``message`` feed
    the issue's translation placeholders,
    ``notification_id`` doubles as the issue ID. Specs with
    ``repair_callback=None`` always route to persistent
    notifications regardless of the dispatcher's
    ``create_repairs`` flag, so a non-repairable finding
    emitted alongside repairable ones still surfaces
    correctly.

    ``translation_key`` selects the entry under
    ``strings.json``'s ``issues:`` block when a spec is
    routed as a repair issue. Required (non-empty) for
    every spec with ``repair_callback`` set; ignored for
    notification-routed specs.

    ``translation_placeholders`` carries dynamic values the
    selected translation entry interpolates (``{device_name}``,
    ``{count}``, etc). Ignored for notification-routed
    specs.
    """

    active: bool
    notification_id: str
    title: str
    message: str
    instance_id: str | None = None
    repair_callback: FixService | None = None
    translation_key: str = ""
    translation_placeholders: dict[str, str] | None = None


def _config_error_notification_id(service: str, instance_id: str) -> str:
    # ``__`` is reserved as the field separator. HA entity_ids
    # (which is what ``instance_id`` always is) cannot contain
    # ``__`` -- ``slugify`` collapses repeated underscores --
    # so the resulting ID stays unambiguously parseable
    # ``blueprint_toolkit_{service}__{instance_id}__{kind}``.
    return f"blueprint_toolkit_{service}__{instance_id}__config_error"


def make_config_error_notification(
    *,
    service: str,
    instance_id: str,
    errors: list[str],
) -> PersistentNotification:
    """Build a config-error spec with the standard wire format.

    When ``errors`` is empty, the returned spec has
    ``active=False`` -- pass it straight through to the
    dispatcher and any prior config-error notification
    for this instance is dismissed. This lets handlers
    call ``emit_config_error`` unconditionally on every
    successful argparse without branching.

    The body is a markdown bulleted list of the errors;
    ``process_persistent_notifications`` prepends an
    ``Automation: [name](edit-link)\\n`` header when it
    dispatches (driven by the ``instance_id`` field on
    the spec). The same dispatcher prepends
    ``<friendly_name>: `` to the title, so this builder
    only sets the bare ``"Config Error"`` category.

    Every interpolated user-controlled string -- each
    entry of ``errors`` -- is ``md_escape``-d here.
    ``vol.Invalid`` messages can include the offending
    input value, which could otherwise smuggle stray
    ``[`` / ``]`` / ``\\`` into the rendered markdown.
    """
    notif_id = _config_error_notification_id(service, instance_id)
    if not errors:
        return PersistentNotification(
            active=False,
            notification_id=notif_id,
            title="",
            message="",
            instance_id=instance_id,
        )
    message = "\n".join(f"- {md_escape(e)}" for e in errors)
    return PersistentNotification(
        active=True,
        notification_id=notif_id,
        title="Config Error",
        message=message,
        instance_id=instance_id,
    )


@dataclass(frozen=True)
class UnmatchedDirective:
    """One include / exclude directive that matched nothing live.

    Emitted by ``validate_directives`` when a user-supplied
    integration name, entity ID, file glob, or regex line
    didn't intersect with the live truth-set candidates the
    handler assembled. Pure data: ``field`` is the
    blueprint input name (e.g. ``"exclude_integrations"``)
    so the user can find the offending row in the
    blueprint editor; ``value`` is the directive as
    supplied (or the regex line text); ``reason`` is the
    canonical short hint shown alongside in the
    notification body. ``line_number`` is set for
    regex-derived bullets (so the notif body can render
    "line 3") and ``None`` for everything else (where the
    field name + value already pin the row).
    """

    field: str
    value: str
    reason: str
    line_number: int | None = None


def validate_directives_item(
    *,
    field: str,
    directives: list[str],
    candidates: AbstractSet[str],
    reason: str,
) -> list[UnmatchedDirective]:
    """Membership-check one directive list against a candidate set.

    For include / exclude inputs whose values are exact
    string identifiers (integration names, entity IDs).
    Any directive not in ``candidates`` becomes an
    ``UnmatchedDirective`` with the supplied ``field`` and
    ``reason``. Order of returned bullets follows the
    order of ``directives`` so the body the user sees is
    deterministic.
    """
    return [
        UnmatchedDirective(field=field, value=value, reason=reason)
        for value in directives
        if value not in candidates
    ]


def validate_directives_regex(
    *,
    field: str,
    lines: list[JoinedRegexLine],
    candidates: AbstractSet[str],
    reason: str = "regex matched no candidates",
) -> list[UnmatchedDirective]:
    """Per-line regex check against the candidate set.

    ``lines`` is the per-line tracking from
    ``validate_and_join_regex_patterns``. Each line whose
    compiled pattern doesn't match any candidate becomes
    an ``UnmatchedDirective`` with ``value`` carrying the
    raw line text and ``line_number`` set so the
    notification body can render "line 3" and the user can
    find the offending row in a multi-line input.
    """
    return [
        UnmatchedDirective(
            field=field,
            value=line.raw,
            reason=reason,
            line_number=line.line_number,
        )
        for line in lines
        if not any(line.compiled.search(c) for c in candidates)
    ]


def make_unmatched_directives_notification(
    *,
    service: str,
    instance_id: str,
    unmatched: list[UnmatchedDirective],
) -> PersistentNotification:
    """Build the per-instance unmatched-directives spec.

    Empty ``unmatched`` returns an inactive spec keyed to
    the same notification ID, so a successful validation
    run dismisses any prior unmatched-directives
    notification automatically -- handlers can dispatch
    this spec on every run without branching.

    Notification ID:
    ``blueprint_toolkit_{service}__{instance_id}__unmatched_directives``.
    Distinct slot from the config-error notification --
    "directive doesn't match anything" is informational
    config staleness, not a structural argparse failure,
    and the user clears each independently.

    Body shape: a markdown bulleted list of
    ``- <field>: "<value>" (<reason>)``, with each
    user-controlled value ``md_escape``-d so stray ``[``
    / ``]`` / ``\\`` in directive text can't corrupt the
    rendering.
    """
    notif_id = (
        f"blueprint_toolkit_{service}__{instance_id}__unmatched_directives"
    )
    if not unmatched:
        return PersistentNotification(
            active=False,
            notification_id=notif_id,
            title="",
            message="",
            instance_id=instance_id,
        )
    bullets: list[str] = []
    for d in unmatched:
        loc = f" (line {d.line_number})" if d.line_number is not None else ""
        bullets.append(
            f'- {md_escape(d.field)}{loc}: "{md_escape(d.value)}" ({d.reason})',
        )
    return PersistentNotification(
        active=True,
        notification_id=notif_id,
        title="Unmatched include / exclude directives",
        message="\n".join(bullets),
        instance_id=instance_id,
    )


def instance_id_for_config_error(raw_data: dict[str, Any]) -> str:
    """Best-effort instance_id extraction for a config-error path.

    Handlers fall back to this when schema validation
    fails before the ``instance_id`` field could be
    parsed; the sentinel keeps the resulting
    notification ID from colliding with a real instance.
    """
    candidate = raw_data.get("instance_id")
    if isinstance(candidate, str) and candidate:
        return candidate
    return "unknown"


def make_emit_config_error(
    *,
    service: str,
    service_tag: str,
) -> Callable[[Any, str, list[str]], Awaitable[None]]:
    """Return an ``emit_config_error`` closure bound to a port's identifiers.

    Saves repeating ``service=_SERVICE,
    service_tag=_SERVICE_TAG`` at every call site in a
    handler. Equivalent to a `functools.partial`, but
    typed-for-handler-callers (positional ``hass``,
    ``instance_id``, ``errors``).

    Lazily imports ``emit_config_error`` from
    ``helpers_runtime`` inside the closure body to keep
    the partial-order layering rule intact (pure cannot
    import runtime at module scope). The lazy reference
    is the single intentional cross-flavour asymmetry --
    ``test_helpers_partial_order_layering``'s allow-list
    pins this site explicitly.
    """

    async def emit(
        hass: Any,
        instance_id: str,
        errors: list[str],
    ) -> None:
        from .helpers_runtime import emit_config_error  # noqa: PLC0415

        await emit_config_error(
            hass,
            service=service,
            service_tag=service_tag,
            instance_id=instance_id,
            errors=errors,
        )

    return emit


@runtime_checkable
class CappableResult(Protocol):
    """Structural type expected by ``prepare_notifications``.

    Watchdog result dataclasses naturally fit this shape:
    they expose

    - ``has_issue: bool``
    - ``notification_id: str``
    - ``notification_title: str``
    - ``to_notification(suppress: bool = False) -> PersistentNotification``

    Sorting uses ``(notification_title, notification_id)``
    so the shown / suppressed split is reproducible across
    runs. ``to_notification(suppress=True)`` MUST return an
    inactive notification keyed to the same ID, so the
    cap helper can dismiss prior-run notifications that
    no longer fit under the cap.

    Members are declared as ``@property`` so both
    plain-dataclass-attribute implementations
    (watchdogs) and property-backed wrappers
    (``IssueNotification``) satisfy the Protocol.
    """

    @property
    def has_issue(self) -> bool: ...

    @property
    def notification_id(self) -> str: ...

    @property
    def notification_title(self) -> str: ...

    def to_notification(
        self,
        suppress: bool = False,
    ) -> PersistentNotification:
        """Return a PersistentNotification for this result."""
        ...


@dataclass
class IssueNotification:
    """Adapter: pre-built ``PersistentNotification`` -> ``CappableResult``.

    For automations like ZRM that build issue
    notifications ad hoc rather than via a watchdog-style
    result dataclass. Always reports ``has_issue=True``;
    on ``suppress=True`` returns an inactive notification
    keyed to the same ID + ``instance_id``.
    """

    notification: PersistentNotification

    @property
    def has_issue(self) -> bool:
        return True

    @property
    def notification_id(self) -> str:
        return self.notification.notification_id

    @property
    def notification_title(self) -> str:
        return self.notification.title

    def to_notification(
        self,
        suppress: bool = False,
    ) -> PersistentNotification:
        if suppress:
            return PersistentNotification(
                active=False,
                notification_id=self.notification.notification_id,
                title="",
                message="",
                instance_id=self.notification.instance_id,
            )
        return self.notification


def instance_state_entity_id(service_tag: str, instance_id: str) -> str:
    """Build the ``blueprint_toolkit.<service_tag>_<slug>_state`` entity_id.

    ``service_tag`` is the per-handler short tag (``STSC`` /
    ``TEC`` / ``EDW`` / ``DW`` / ``RW`` / ``ZRM``); HA entity
    IDs require lowercase, so the helper lowercases it
    internally -- callers can pass the uppercase
    ``_SERVICE_TAG`` constant directly. ``instance_id`` is
    the automation entity_id (e.g. ``automation.foo_bar``);
    we strip the ``automation.`` prefix so the resulting
    diagnostic entity_id reads cleanly in Developer Tools /
    templates / dashboards.

    HA's `VALID_ENTITY_ID` regex rejects double-underscores
    anywhere in the entity_id, so a `__` visual separator
    between tag and slug isn't usable -- single `_`
    everywhere.
    """
    slug = instance_id.removeprefix("automation.")
    return f"{DOMAIN}.{service_tag.lower()}_{slug}_state"


@dataclass(frozen=True)
class LifecycleMutators:
    """The four standard per-instance mutator callbacks.

    Returned by ``make_lifecycle_mutators``; each field
    matches the corresponding hook on
    ``BlueprintHandlerSpec`` so callers can wire them
    directly:

    .. code-block:: python

        _MUTATORS = make_lifecycle_mutators(...)
        _SPEC = BlueprintHandlerSpec(
            ...,
            on_reload=_MUTATORS.on_reload,
            on_entity_remove=_MUTATORS.on_entity_remove,
            on_entity_rename=_MUTATORS.on_entity_rename,
            on_teardown=_MUTATORS.on_teardown,
        )
    """

    # Hass typed as ``Any`` here -- the pure flavour bans
    # HA imports even under ``TYPE_CHECKING``. Callers
    # supply the real ``HomeAssistant`` and runtime / lifecycle
    # consumers narrow the type at the receiving end.
    on_reload: Callable[[Any], None]
    on_entity_remove: Callable[[Any, str], None]
    on_entity_rename: Callable[[Any, str, str], None]
    on_teardown: Callable[[Any], None]


def parse_entity_registry_update(
    event_data: Mapping[str, Any],
) -> tuple[str, str, str] | None:
    """Extract ``(action, old_id, new_id)`` for an automation entity event.

    Returns ``None`` when the event is for a non-automation
    entity (the listener fires for every registry change),
    so callers can early-return cleanly. ``action`` is one
    of HA's registry actions: ``create`` / ``update`` /
    ``remove``. The dispatcher in
    ``register_blueprint_handler`` only acts on ``remove``
    and ``update`` (renames); ``create`` events are
    intentionally ignored because new automations come in
    through the blueprint reload path, which the
    automation_reload listener covers.
    """
    action = event_data.get("action")
    new_id = event_data.get("entity_id") or ""
    old_id = event_data.get("old_entity_id") or new_id
    if not (
        new_id.startswith("automation.") or old_id.startswith("automation.")
    ):
        return None
    if not isinstance(action, str):
        return None
    return action, old_id, new_id


@dataclass
class BlueprintHandlerSpec:
    """Per-port configuration for a blueprint handler.

    Bundles the identifiers, service callback, and
    optional lifecycle hooks the shared register /
    unregister helpers need to wire up the standard
    plumbing (idempotent service registration, bus
    subscriptions, restart-recovery scheduling, log
    messages).

    Required:
        service: Slug for the HA service registered as
            ``blueprint_toolkit.<service>`` and as the
            bucket key under ``hass.data[DOMAIN]``.
        service_tag: Short tag for notification titles
            and per-event log messages (e.g. ``TEC``).
        service_name: Human-readable name for the
            one-time registration log (e.g.
            ``Trigger Entity Controller``).
        blueprint_path: HA-relative path to the
            blueprint that uses this handler. Used for
            restart-recovery discovery.
        service_handler: Async service callback;
            receives ``(hass, ServiceCall)``.

    All lifecycle hooks default to ``None``. Each
    one a port supplies enables one piece of plumbing;
    a port that needs none of them (e.g. a periodic
    watchdog) gets just the service registration.

    Optional fields:
        supports_response: Pass
            ``homeassistant.core.SupportsResponse.OPTIONAL``
            (or ``ONLY``) when the handler returns a
            ``ServiceResponse`` mapping that the calling
            blueprint captures via ``response_variable``.
            STSC + TEC use this to hand the user-built
            notification message back to the blueprint
            runner, which then invokes the user-supplied
            ``notify_action`` step. Watchdog handlers
            leave it ``None`` (the dispatcher defaults to
            no response).

    Lifecycle hooks:
        kick_variables: When set, restart-recovery is
            enabled. At HA-started time + after every
            ``EVENT_AUTOMATION_RELOADED``, the dispatcher
            walks every automation using ``blueprint_path``
            and fires ``automation.trigger`` against each
            with this flat top-level ``variables`` payload.
            Per-handler ``_async_kick_for_recovery``
            wrappers used to live in each port; the spec
            now carries just the payload and the
            ``register_blueprint_handler`` dispatcher
            builds the call via
            ``kick_via_automation_trigger``.
        on_reload: When set, ``EVENT_AUTOMATION_RELOADED``
            invokes this synchronously (typical use:
            cancel pending per-instance work whose
            AutomationEntity objects have been
            replaced). Recovery still runs afterwards
            if ``kick_variables`` is also set.
        on_entity_remove: When set, an automation's
            entity-registry remove event invokes this
            with its entity_id (typical use: drop
            tracked state, cancel pending timers).
        on_entity_rename: When set, an automation's
            entity-registry rename event invokes this
            with ``(old_id, new_id)`` (typical use:
            move the per-instance state map entry).
        on_teardown: Invoked from
            ``unregister_blueprint_handler`` (typical
            use: cancel all pending work and clear
            tracked state).
    """

    service: str
    service_tag: str
    service_name: str
    blueprint_path: str
    # Hass / ServiceCall typed as ``Any`` here -- the pure
    # flavour bans HA imports even under ``TYPE_CHECKING``.
    # Callers supply real HA objects; runtime / lifecycle
    # consumers narrow the types at the receiving end. The
    # handler return type is ``Any`` rather than ``None`` so
    # handlers that opt into ``supports_response`` can hand
    # back a ``homeassistant.core.ServiceResponse`` mapping
    # without forcing every other handler to declare a
    # return type.
    service_handler: Callable[[Any, Any], Awaitable[Any]]
    # ``homeassistant.core.SupportsResponse`` value (typed
    # ``Any`` to keep this module HA-import-free). When set,
    # the dispatcher registers the service with this
    # ``supports_response=`` flag so the blueprint runner
    # can capture the handler's return value via the
    # automation step's ``response_variable``. Default
    # ``None`` means HA's own default applies (no response).
    supports_response: Any = None
    kick_variables: dict[str, Any] | None = None
    on_reload: Callable[[Any], None] | None = None
    on_entity_remove: Callable[[Any, str], None] | None = None
    on_entity_rename: Callable[[Any, str, str], None] | None = None
    on_teardown: Callable[[Any], None] | None = None


# Bucket key under which ``register_blueprint_handler``
# stashes the unsubscribe callables for every bus
# listener it registered. ``unregister_blueprint_handler``
# iterates and calls each. Generic list (no per-listener
# slot names) so future ports can add new listener types
# without changing the bookkeeping shape.
_UNSUBS_KEY = "unsubs"


def spec_bucket(entry: Any, service: str) -> dict[str, Any]:
    """Per-service slot under ``entry.runtime_data.handlers[service]``.

    Created lazily; idempotent so reloads don't lose
    pending unsubscribe handles or per-port state. Each
    port is free to stash additional keys here (e.g.
    TEC keeps its ``instances`` map under the same
    bucket).

    Public (no leading underscore) so per-port handlers
    -- e.g. ``tec/handler.py``'s ``_instances(...)``
    helper -- can fetch their own bucket without
    duplicating the entry-runtime-data wiring.
    """
    handlers: dict[str, dict[str, Any]] = entry.runtime_data.handlers
    bucket = handlers.setdefault(service, {_UNSUBS_KEY: []})
    bucket.setdefault(_UNSUBS_KEY, [])
    return bucket


__all__ = [
    "BlueprintHandlerSpec",
    "CONTROLLABLE_DOMAINS",
    "CappableResult",
    "FixDwDeviceDisabledDiagnostics",
    "FixEdwDeviceDrift",
    "FixService",
    "IssueNotification",
    "JoinedRegexLine",
    "JoinedRegexResult",
    "LifecycleMutators",
    "PersistentNotification",
    "TypedServiceResponse",
    "UnmatchedDirective",
    "automation_edit_link",
    "automation_edit_url",
    "config_entry_link",
    "config_entry_url",
    "dashboard_link",
    "dashboard_url",
    "device_entity_link",
    "device_entity_url",
    "device_header_line",
    "device_link",
    "device_url",
    "deviceless_entity_link",
    "domain_entities_link",
    "domain_entities_url",
    "entities_dashboard_url",
    "file_editor_link",
    "format_notification",
    "format_timestamp",
    "instance_state_entity_id",
    "integration_link",
    "integration_url",
    "make_config_error_notification",
    "make_emit_config_error",
    "make_unmatched_directives_notification",
    "matches_pattern",
    "md_escape",
    "notification_prefix",
    "resolve_target_integrations",
    "script_dashboard_link",
    "script_edit_link",
    "script_edit_url",
    "slugify",
    "spec_bucket",
    "validate_and_join_regex_patterns",
    "validate_controlled_entity_domains",
    "validate_directives_item",
    "validate_directives_regex",
]
