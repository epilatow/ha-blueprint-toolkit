# This is AI generated code
"""Business logic for entity defaults watchdog.

Detects entity ID and name drift from their defaults.
Entity IDs drift when device names change after entity
creation.  Name overrides become stale when integrations
change their naming conventions and HA auto-preserves
old names.
"""

from dataclasses import dataclass, field

from .. import helpers


@dataclass
class DeviceEntry:
    """Device discovered during integration scan.

    Locally defined rather than in the shared ``helpers``
    module: only this port consumes the shape today. If a
    second port grows the same need, hoist into helpers.
    """

    id: str

    # Current device name. HA device registry
    # ``device.name_by_user`` (if set) or ``device.name``
    # (set by integration).
    name: str

    # Integration default name. HA device registry
    # ``device.name``. Non-deterministic for
    # multi-integration devices.
    default_name: str

    # Map integrations to the entity ids they provide.
    integration_entities: dict[str, set[str]] = field(
        default_factory=dict,
    )


# Check identifiers surfaced as blueprint options. Adding
# a new check = one new constant, add it to ``CHECK_ALL``,
# and test ``in config.drift_checks`` at the use site.
DRIFT_CHECK_DEVICE_ENTITY_ID = "device-entity-id"
DRIFT_CHECK_DEVICE_ENTITY_NAME = "device-entity-name"
DRIFT_CHECK_ENTITY_ID = "entity-id"
DRIFT_CHECK_VISIBLE_ALIASED_ENTITY = "visible-aliased-entity"

CHECK_ALL: frozenset[str] = frozenset(
    {
        DRIFT_CHECK_DEVICE_ENTITY_ID,
        DRIFT_CHECK_DEVICE_ENTITY_NAME,
        DRIFT_CHECK_ENTITY_ID,
        DRIFT_CHECK_VISIBLE_ALIASED_ENTITY,
    },
)

# Domains eligible for the deviceless entity_id drift
# check. Limited to user-named domains whose entity_ids
# are derived from a user-supplied name (and therefore
# drift when the user renames the name).  Integration-
# entity domains (media_player, camera, climate, etc.)
# are excluded because their entity_ids are derived from
# device + integration names -- the device_entity_id
# check already covers those.
DEVICELESS_DOMAINS: frozenset[str] = frozenset(
    {
        "automation",
        "script",
        "scene",
        "group",
        "schedule",
        "timer",
        "counter",
        "input_boolean",
        "input_number",
        "input_text",
        "input_select",
        "input_datetime",
        "input_button",
        "sensor",
        "binary_sensor",
        "switch",
        "light",
    },
)


@dataclass
class Config:
    """Configuration parameters (set per-instance)."""

    drift_checks: frozenset[str]
    exclude_device_name_regex: str
    exclude_entity_ids: list[str]
    exclude_entity_id_regex: str
    exclude_entity_name_regex: str
    # Per-instance notification ID prefix, ending with
    # the canonical ``__`` separator. Every notification
    # this module mints must start with this string so
    # the service wrapper's orphan sweep can safely scope
    # dismissals to one instance.
    notification_prefix: str = ""
    # Carried onto every ``PersistentNotification`` we
    # construct so the dispatcher can prepend
    # ``Automation: [name](edit-link)\n`` to the body.
    # ``None`` in pure-Python tests where the Config
    # carries no real instance binding; the dispatcher
    # silently skips the header in that case.
    instance_id: str | None = None


@dataclass
class EntityDriftInfo:
    """Per-entity drift data computed by service wrapper."""

    entity_id: str
    has_entity_name: bool
    has_name_override: bool
    expected_entity_id: str | None
    current_name: str
    expected_name: str | None


@dataclass
class DeviceInfo:
    """Device with its entity drift snapshots."""

    de: DeviceEntry
    entities: list[EntityDriftInfo] = field(
        default_factory=list,
    )


@dataclass
class DriftDetail:
    """One drift finding for an entity."""

    entity_id: str
    id_drifted: bool
    name_drifted: bool
    current_name: str
    expected_name: str | None
    has_redundant_prefix: bool = False
    recommended_override: str | None = None
    # Default entity_id the registry would have if no
    # rename had drifted it. Threaded through so the
    # repair-spec builder can hand it to
    # ``fix_edw_entity_id_drift`` as the target ID.
    expected_entity_id: str | None = None


@dataclass
class DevicelessEntityInfo:
    """Deviceless entity snapshot for drift evaluation."""

    entity_id: str
    # HA's effective display name for the entity.  For
    # registry entries, ``entry.name or entry.original_name``;
    # for state-only entities, ``attributes.friendly_name``.
    # Empty string when no name is set.
    effective_name: str
    # Registry ``entry.platform`` -- the integration that
    # supplied the entity.  None for state-only entities.
    platform: str | None
    # Registry ``entry.unique_id`` -- used to build the
    # automation edit link.  None for state-only entities.
    unique_id: str | None
    # True if this entity has a registry entry.  False for
    # state-only entities (YAML-defined without unique_id).
    from_registry: bool
    # Registry ``entry.config_entry_id`` -- set when the
    # entity was registered via a UI-created config entry,
    # ``None`` when it came through a YAML platform setup
    # (e.g. legacy ``sensor:`` YAML, ``template:`` YAML).
    # Discriminates "integration page is useful" from
    # "integration page doesn't show this entity, point
    # the user at the YAML instead".
    config_entry_id: str | None = None


@dataclass
class DevicelessDriftDetail:
    """One deviceless entity drift finding."""

    entity_id: str
    expected_object_id: str
    friendly_name: str
    stale_suffix: bool
    platform: str | None
    unique_id: str | None
    from_registry: bool
    config_entry_id: str | None = None


@dataclass
class DevicelessResult:
    """Aggregated deviceless drift result.

    Unlike DeviceResult (one per device), this is a single
    aggregate covering every drifted deviceless entity --
    deviceless entities have no natural grouping, so we
    emit one bucket notification instead of one per entity.
    """

    has_issue: bool
    notification_id: str
    notification_title: str
    notification_message: str
    drifted: list[DevicelessDriftDetail]
    entities_checked: int
    entities_excluded: int


@dataclass
class VisibleAliasedEntityInfo:
    """Per-switch_as_x-entry input for the visible-aliased
    drift check.

    Built by the handler from
    ``hass.config_entries.async_entries("switch_as_x")``
    plus entity-registry lookups; consumed by
    ``_evaluate_visible_aliased_entities``. The handler is
    responsible for defensive checks (entry disabled,
    malformed options, wrapper entity missing, source
    disabled in registry, source already hidden) -- entries
    that fail those checks are simply not added to the
    input list.

    Carrying the wrapper's ``target_domain`` + ``title``
    keeps the logic-side notification body self-contained
    without re-querying the registry.
    """

    source_entity_id: str
    wrapper_entity_id: str
    wrapper_target_domain: str
    wrapper_title: str
    source_friendly_name: str
    # Source's registry ``device_id`` / ``config_entry_id``
    # if set. Threaded into ``VisibleAliasedEntityFinding``
    # so the notification body picks ``device_entity_link``
    # for device-attached sources or
    # ``deviceless_entity_link`` for helper / template
    # sources without a device.
    source_device_id: str | None = None
    source_config_entry_id: str | None = None


@dataclass
class VisibleAliasedEntityFinding:
    """One flagged source entity from the visible-aliased
    check.

    The per-entity shape is deliberately distinct from
    ``DevicelessDriftDetail`` -- a future repair surface
    will want to stamp one repair per finding, and packing
    visible-aliased findings into the deviceless dataclass
    would either lose fields or pollute the deviceless
    schema with optional aliased-only fields.

    ``source_device_id`` / ``source_config_entry_id`` are
    threaded from ``VisibleAliasedEntityInfo`` so the body
    picks ``device_entity_link`` (both set) or
    ``deviceless_entity_link`` (neither set, or no
    device_id) per-finding.
    """

    source_entity_id: str
    wrapper_entity_id: str
    wrapper_target_domain: str
    source_friendly_name: str
    source_device_id: str | None
    source_config_entry_id: str | None


@dataclass
class VisibleAliasedResult:
    """Aggregated visible-aliased-entity result.

    Mirrors ``DevicelessResult``: one bucket notification
    covering every flagged source entity, plus the
    bookkeeping the handler needs for diagnostic state.
    The per-finding shape lives on ``findings``; the
    notification body assembles them into the rendered
    aggregate message.

    ``entries_kept`` is the count of ``infos`` that survived
    user exclusion (``len(infos) - entries_excluded``);
    ``entries_excluded`` is the count filtered out by
    ``exclude_entities`` / ``exclude_entity_id_regex`` /
    ``exclude_entity_name_regex``. Defensive-check
    bookkeeping (entries dropped at the handler before
    they ever reach logic) is the handler's responsibility.
    """

    has_issue: bool
    notification_id: str
    notification_title: str
    notification_message: str
    findings: list[VisibleAliasedEntityFinding]
    entries_kept: int
    entries_excluded: int


@dataclass
class DeviceResult:
    """Per-device evaluation result."""

    device_id: str
    device_name: str
    has_issue: bool
    device_excluded: bool
    notification_id: str
    notification_title: str
    notification_message: str
    drifted_entities: list[DriftDetail]
    entities_checked: int
    entities_excluded: int
    # Stamped from ``Config.instance_id`` at evaluation
    # time so ``to_notification`` can hand the dispatcher
    # the automation entity_id needed for the
    # ``Automation: [name](edit-link)\n`` body prefix.
    instance_id: str | None = None

    def to_notification(
        self,
        suppress: bool = False,
    ) -> helpers.PersistentNotification:
        return helpers.PersistentNotification(
            active=self.has_issue and not suppress,
            notification_id=self.notification_id,
            title=self.notification_title,
            message=self.notification_message,
            instance_id=self.instance_id,
        )


def _detect_redundant_prefix(
    entry_name: str | None,
    device_name: str,
    has_entity_name: bool,
) -> bool:
    """True if a name override redundantly includes the
    device name.

    Only applies to has_entity_name=True entities where
    HA already prepends the device name automatically.
    """
    if not has_entity_name:
        return False
    if not entry_name or not device_name:
        return False
    return entry_name.startswith(device_name)


def _compute_recommended_override(
    entity_name: str,
    device_default_name: str,
    device_display_name: str,
    has_entity_name: bool,
    multi_integration: bool,
) -> str | None:
    """Compute the correct name override for legacy entities.

    For has_entity_name=False entities whose entity_name
    embeds the device default name, returns the override
    value that produces correct entity IDs.

    Returns None if not applicable (has_entity_name=True,
    entity_name doesn't start with the device default
    name, device hasn't been renamed, or device has
    multiple integrations).
    """
    if has_entity_name:
        return None
    # Multi-integration devices have non-deterministic
    # default_name -- skip recommendation to avoid
    # incorrect suggestions.
    if multi_integration:
        return None
    if not entity_name or not device_default_name:
        return None
    if device_default_name == device_display_name:
        return None
    if not entity_name.startswith(
        device_default_name,
    ):
        return None
    suffix = entity_name[len(device_default_name) :].strip()
    if not suffix:
        return device_display_name
    return suffix


def _check_id_enabled(config: Config) -> bool:
    """True if device-entity-id check is active."""
    return DRIFT_CHECK_DEVICE_ENTITY_ID in config.drift_checks


def _check_name_enabled(config: Config) -> bool:
    """True if device-entity-name check is active."""
    return DRIFT_CHECK_DEVICE_ENTITY_NAME in config.drift_checks


def _check_deviceless_enabled(config: Config) -> bool:
    """True if deviceless entity-id check is active."""
    return DRIFT_CHECK_ENTITY_ID in config.drift_checks


def _check_visible_aliased_enabled(config: Config) -> bool:
    """True if visible-aliased-entity check is active."""
    return DRIFT_CHECK_VISIBLE_ALIASED_ENTITY in config.drift_checks


def _matches_with_collision_suffix(
    obj_id: str,
    expected: str,
    peers: set[str],
) -> tuple[bool, bool]:
    """Decide whether ``obj_id`` is a match for ``expected``.

    Returns ``(matches, stale_suffix)``:

    - ``obj_id == expected`` -> ``(True, False)``.
    - ``obj_id`` equals ``<expected>_N`` for integer
      ``N >= 2`` AND ``expected`` is in ``peers``
      -> ``(True, False)`` -- a valid HA collision suffix.
    - ``obj_id`` equals ``<expected>_N`` for ``N >= 2``,
      ``expected`` is not in ``peers``, but a higher
      ``<expected>_M`` (``M > N``) is in ``peers``
      -> ``(True, False)`` -- not flagged; the highest
      entry in the chain is flagged instead so renaming
      it to ``expected`` resolves the whole chain.
    - ``obj_id`` equals ``<expected>_N`` for ``N >= 2``,
      no base peer, and no higher chain peer
      -> ``(False, True)`` -- a stale suffix.
    - Otherwise -> ``(False, False)`` -- plain drift.
    """
    if not expected:
        return (False, False)
    if obj_id == expected:
        return (True, False)
    if not obj_id.startswith(f"{expected}_"):
        return (False, False)
    rest = obj_id[len(expected) + 1 :]
    if not rest.isdigit():
        return (False, False)
    # Reject leading-zero forms ("01", "0") so "_0"
    # and "_01" aren't mistaken for HA suffixes; HA
    # uses "_2", "_3", ... starting at 2.
    if rest.startswith("0"):
        return (False, False)
    n = int(rest)
    if n < 2:
        return (False, False)
    if expected in peers:
        return (True, False)
    # No base peer. Scan for any higher-numbered chain
    # peer; if present, defer flagging to it so the user
    # fixes the chain in one rename.
    prefix = f"{expected}_"
    for p in peers:
        if not p.startswith(prefix):
            continue
        rest_p = p[len(prefix) :]
        if not rest_p.isdigit() or rest_p.startswith("0"):
            continue
        if int(rest_p) > n:
            return (True, False)
    return (False, True)


def _is_excluded(
    config: Config,
    entity_id: str,
    friendly_name: str,
) -> bool:
    """True if entity matches any exclusion mechanism."""
    if entity_id in config.exclude_entity_ids:
        return True
    if helpers.matches_pattern(
        entity_id,
        config.exclude_entity_id_regex,
    ):
        return True
    if helpers.matches_pattern(
        friendly_name,
        config.exclude_entity_name_regex,
    ):
        return True
    return False


def _check_entity_drift(
    config: Config,
    entity: EntityDriftInfo,
    device: DeviceInfo,
) -> DriftDetail | None:
    """Check a single entity for drift.

    Returns DriftDetail if drifted, None if clean or
    excluded. Computes redundant prefix and recommended
    override on the fly using device-level data.
    """
    if _is_excluded(
        config,
        entity.entity_id,
        entity.current_name,
    ):
        return None

    id_drifted = False
    name_drifted = False

    # Compute has_entity_name=False recommendations
    multi = len(device.de.integration_entities) > 1
    recommended = _compute_recommended_override(
        entity.expected_name or "",
        device.de.default_name,
        device.de.name,
        entity.has_entity_name,
        multi,
    )
    redundant = _detect_redundant_prefix(
        entity.current_name if entity.has_name_override else None,
        device.de.name,
        entity.has_entity_name,
    )

    # ID drift check
    if _check_id_enabled(config):
        if (
            entity.expected_entity_id is not None
            and entity.entity_id != entity.expected_entity_id
        ):
            id_drifted = True

    # Name drift check
    if _check_name_enabled(config):
        if not entity.has_entity_name and recommended is not None:
            # has_entity_name=False with extractable
            # device name prefix: compare override
            # against the recommended value. Flag even
            # without an existing override (entity IDs
            # will be broken without the correct
            # override).
            if entity.current_name != recommended:
                name_drifted = True
        elif (
            entity.has_name_override
            and entity.expected_name is not None
            and entity.current_name != entity.expected_name
        ):
            name_drifted = True

    if not id_drifted and not name_drifted:
        return None

    return DriftDetail(
        entity_id=entity.entity_id,
        id_drifted=id_drifted,
        name_drifted=name_drifted,
        current_name=entity.current_name,
        expected_name=entity.expected_name,
        has_redundant_prefix=redundant,
        recommended_override=recommended,
        expected_entity_id=entity.expected_entity_id,
    )


def _build_device_notification_message(
    device: DeviceInfo,
    drifted: list[DriftDetail],
) -> str:
    """Build the notification body for a device with drift.

    Groups entities into up to four sections:
    - Name overrides to clear (has_entity_name=True stale
      overrides)
    - Name overrides with redundant device name
      (has_entity_name=True with device prefix in override)
    - Name overrides to set (has_entity_name=False with
      recommended override from device name extraction)
    - Non-default entity IDs (ID drift only, no name drift)

    Entities with both name+ID drift appear only in the
    name section -- the ID will be addressed after the name
    is fixed.
    """
    lines: list[str] = [
        helpers.device_header_line(device.de.name, device.de.id),
        "",
    ]
    integrations = sorted(
        device.de.integration_entities.keys(),
    )
    if integrations:
        escaped = ", ".join(helpers.md_escape(i) for i in integrations)
        lines.append(
            f"Integrations: {escaped}",
        )

    # Group entities by notification section
    name_clear: list[DriftDetail] = []
    name_redundant: list[DriftDetail] = []
    name_set: list[DriftDetail] = []
    id_only: list[DriftDetail] = []

    for d in drifted:
        if d.name_drifted and d.recommended_override is not None:
            name_set.append(d)
        elif d.name_drifted and d.has_redundant_prefix:
            name_redundant.append(d)
        elif d.name_drifted:
            name_clear.append(d)
        else:
            id_only.append(d)

    # Sort each section by entity_id for consistent
    # output
    name_clear = [
        d
        for _, _, d in sorted(
            [(d.entity_id, i, d) for i, d in enumerate(name_clear)]
        )
    ]
    name_redundant = [
        d
        for _, _, d in sorted(
            [(d.entity_id, i, d) for i, d in enumerate(name_redundant)]
        )
    ]
    name_set = [
        d
        for _, _, d in sorted(
            [(d.entity_id, i, d) for i, d in enumerate(name_set)]
        )
    ]
    id_only = [
        d
        for _, _, d in sorted(
            [(d.entity_id, i, d) for i, d in enumerate(id_only)]
        )
    ]

    has_name_issues = (
        len(name_clear) > 0 or len(name_redundant) > 0 or len(name_set) > 0
    )

    if name_clear:
        lines.append("")
        lines.append("**Name overrides to clear:**")
        for d in name_clear:
            current = helpers.md_escape(d.current_name)
            lines.append(
                f'- `{d.entity_id}`: "{current}"',
            )
        lines.append("")
        lines.append(
            "To keep a custom name, add the entity"
            " to the watchdog's exclusion list.",
        )

    if name_redundant:
        lines.append("")
        lines.append(
            "**Name overrides with redundant device name:**",
        )
        for d in name_redundant:
            current = helpers.md_escape(d.current_name)
            expected = helpers.md_escape(d.expected_name or "")
            lines.append(
                f'- `{d.entity_id}`: "{current}" -> "{expected}"',
            )
        device_name = helpers.md_escape(device.de.name)
        lines.append(
            "  The override includes the device name,"
            " which Home Assistant already adds."
            " Edit the override to remove"
            f' "{device_name} " or clear it entirely.',
        )

    if name_set:
        lines.append("")
        lines.append("**Name overrides to set:**")
        for d in name_set:
            override = helpers.md_escape(d.recommended_override or "")
            lines.append(
                f'- `{d.entity_id}`: set to "{override}"',
            )
        lines.append("")
        lines.append(
            "These are legacy entities whose names"
            " embed an old device name. Set the"
            " recommended overrides, then use"
            " Recreate entity IDs.",
        )

    if id_only:
        lines.append("")
        lines.append("**Non-default entity IDs:**")
        for d in id_only:
            lines.append(f"- `{d.entity_id}`")

    # How to fix section
    lines.append("")
    if has_name_issues and id_only:
        lines.append("**How to fix:**")
        lines.append(
            "1. Clear or edit the name overrides"
            " above in each entity's settings.",
        )
        lines.append(
            "2. Use **Recreate entity IDs** on the"
            " device page to fix non-default IDs.",
        )
        lines.append(
            "3. Fix names before recreating IDs"
            ' -- "Recreate entity IDs" uses the'
            " current name to compute the new ID."
            " Clearing a name override may reveal"
            " additional non-default IDs on the"
            " next check.",
        )
    elif has_name_issues:
        lines.append("**How to fix:**")
        lines.append(
            "Clear or edit the name overrides"
            " above in each entity's settings."
            " Clearing a name override may reveal"
            " non-default entity IDs on the next"
            " check.",
        )
    else:
        lines.append(
            "Use **Recreate entity IDs** on the"
            " device page to fix non-default IDs.",
        )

    return "\n".join(lines)


def _evaluate_device(
    config: Config,
    device: DeviceInfo,
) -> DeviceResult:
    """Evaluate drift for a single device."""
    notification_id = f"{config.notification_prefix}device_{device.de.id}"

    # Skip excluded devices
    if helpers.matches_pattern(
        device.de.name,
        config.exclude_device_name_regex,
    ):
        return DeviceResult(
            device_id=device.de.id,
            device_name=device.de.name,
            has_issue=False,
            device_excluded=True,
            notification_id=notification_id,
            notification_title="",
            notification_message="",
            drifted_entities=[],
            entities_checked=0,
            entities_excluded=0,
            instance_id=config.instance_id,
        )

    drifted: list[DriftDetail] = []
    excluded = 0
    for entity in device.entities:
        result = _check_entity_drift(config, entity, device)
        if result is None:
            if _is_excluded(
                config,
                entity.entity_id,
                entity.current_name,
            ):
                excluded += 1
        else:
            drifted.append(result)

    has_issue = len(drifted) > 0
    title = ""
    message = ""
    if has_issue:
        # Title carries just the per-device category; the
        # dispatcher prepends ``<automation_name>: ``.
        title = device.de.name
        message = _build_device_notification_message(
            device,
            drifted,
        )

    return DeviceResult(
        device_id=device.de.id,
        device_name=device.de.name,
        has_issue=has_issue,
        device_excluded=False,
        notification_id=notification_id,
        notification_title=title,
        notification_message=message,
        drifted_entities=drifted,
        entities_checked=len(device.entities) - excluded,
        entities_excluded=excluded,
        instance_id=config.instance_id,
    )


def _deviceless_line_suffix(
    entity_id: str,
    friendly_name: str,
    platform: str | None,
    unique_id: str | None,
    from_registry: bool,
    config_entry_id: str | None = None,
) -> str:
    """Build the indented second line of a deviceless
    drift bullet.

    The exact layout varies by entity kind:

    - ``automation`` / ``script``: the friendly name is
      itself the link to that entity's editor.
    - registry-backed, UI-configured (``config_entry_id``
      set): plain friendly name followed by
      `` -  integration [<platform>](...)`` so the user can
      click through to the integration's config page.
    - registry-backed, YAML-configured (``config_entry_id``
      is ``None``): same but the integration name is plain
      text with a `` -  YAML-configuration`` note. The
      integration page doesn't show YAML-defined entities,
      so a link there would mislead -- the user should edit
      the YAML instead.
    - otherwise (state-only YAML without ``unique_id:``):
      plain friendly name followed by a nudge to add a
      ``unique_id:`` -- no per-entity exclusion suggestion.

    The friendly name is markdown-escaped in every branch
    so brackets or backslashes in the name can't break the
    surrounding link markdown.

    See docs/entity_defaults_watchdog.md for rationale.
    """
    dom, obj_id = entity_id.split(".", 1)
    name = helpers.md_escape(friendly_name)
    if dom == "automation" and unique_id:
        return helpers.automation_edit_link(friendly_name, unique_id)
    if dom == "script":
        return helpers.script_edit_link(friendly_name, obj_id)
    if from_registry and platform:
        if config_entry_id:
            return (
                f"{name}  -  integration "
                f"{helpers.integration_link(platform, platform)}"
            )
        plat_label = helpers.md_escape(platform)
        return f"{name}  -  integration {plat_label}  -  YAML-configuration"
    return f"{name}  -  add `unique_id:` to make this entity manageable"


def _build_deviceless_notification_message(
    drift_items: list[DevicelessDriftDetail],
    stale_items: list[DevicelessDriftDetail],
) -> str:
    """Build the deviceless-bucket notification body.

    Two sections -- generic drift and stale collision
    suffixes -- each shown only when non-empty. Bullets
    carry current/expected entity_id, friendly name, and
    a per-domain pointer (edit link or integration page).
    """
    sections: list[str] = []

    if drift_items:
        lines = [
            f"Entity IDs do not match their names ({len(drift_items)}):",
        ]
        sorted_drift = [(d.entity_id, i, d) for i, d in enumerate(drift_items)]
        sorted_drift.sort()
        for _, _, d in sorted_drift:
            dom = d.entity_id.split(".", 1)[0]
            suffix = _deviceless_line_suffix(
                d.entity_id,
                d.friendly_name,
                d.platform,
                d.unique_id,
                d.from_registry,
                d.config_entry_id,
            )
            lines.append(
                f"- `{d.entity_id}` -> expected `{dom}.{d.expected_object_id}`",
            )
            lines.append(f"  {suffix}")
        sections.append("\n".join(lines))

    if stale_items:
        lines = [
            "Stale collision suffixes"
            " (original peer removed, rename recommended):",
        ]
        sorted_stale = [(d.entity_id, i, d) for i, d in enumerate(stale_items)]
        sorted_stale.sort()
        for _, _, d in sorted_stale:
            dom = d.entity_id.split(".", 1)[0]
            suffix = _deviceless_line_suffix(
                d.entity_id,
                d.friendly_name,
                d.platform,
                d.unique_id,
                d.from_registry,
                d.config_entry_id,
            )
            lines.append(
                f"- `{d.entity_id}` -> rename to"
                f" `{dom}.{d.expected_object_id}`",
            )
            lines.append(f"  {suffix}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _evaluate_deviceless(
    config: Config,
    entities: list[DevicelessEntityInfo],
    peers_by_domain: dict[str, set[str]],
) -> DevicelessResult:
    """Evaluate entity_id drift for deviceless entities.

    Classifies each entity into ok, drift, or stale
    suffix, then builds a single bucket notification
    covering all flagged entities.
    """
    drift_items: list[DevicelessDriftDetail] = []
    stale_items: list[DevicelessDriftDetail] = []
    excluded = 0

    for entity in entities:
        if _is_excluded(
            config,
            entity.entity_id,
            entity.effective_name,
        ):
            excluded += 1
            continue

        if not entity.effective_name:
            continue

        expected = helpers.slugify(entity.effective_name)
        if not expected:
            continue

        dom, obj_id = entity.entity_id.split(".", 1)
        peers = peers_by_domain.get(dom, set())
        matches, stale = _matches_with_collision_suffix(
            obj_id,
            expected,
            peers,
        )
        if matches:
            continue

        detail = DevicelessDriftDetail(
            entity_id=entity.entity_id,
            expected_object_id=expected,
            friendly_name=entity.effective_name,
            stale_suffix=stale,
            platform=entity.platform,
            unique_id=entity.unique_id,
            from_registry=entity.from_registry,
            config_entry_id=entity.config_entry_id,
        )
        if stale:
            stale_items.append(detail)
        else:
            drift_items.append(detail)

    has_issue = bool(drift_items) or bool(stale_items)
    title = ""
    message = ""
    if has_issue:
        title = "Deviceless entity drift"
        message = _build_deviceless_notification_message(
            drift_items,
            stale_items,
        )

    all_drifted: list[DevicelessDriftDetail] = []
    all_drifted.extend(drift_items)
    all_drifted.extend(stale_items)

    return DevicelessResult(
        has_issue=has_issue,
        notification_id=f"{config.notification_prefix}deviceless",
        notification_title=title,
        notification_message=message,
        drifted=all_drifted,
        entities_checked=len(entities) - excluded,
        entities_excluded=excluded,
    )


def _build_visible_aliased_notification_message(
    findings: list[VisibleAliasedEntityFinding],
) -> str:
    """Build the visible-aliased-entity bucket body.

    Per-finding bullets explain the symptom (both rows
    visible) and link to the per-entity Settings page. The
    leading paragraph names the integration that owns the
    wrapper (``switch_as_x``) and the surfaces where both
    rows show up.
    """
    sorted_findings = [
        f
        for _, _, f in sorted(
            ((f.source_entity_id, i, f) for i, f in enumerate(findings)),
            key=lambda triple: (triple[0], triple[1]),
        )
    ]

    lines: list[str] = [
        (
            f"Visible aliased sources ({len(sorted_findings)}):"
            " each entity below is wrapped by switch_as_x but its"
            " source row is still visible."
        ),
    ]
    for f in sorted_findings:
        wrapper_eid = f"{f.wrapper_target_domain}.{f.wrapper_entity_id}"
        if f.source_device_id and f.source_config_entry_id:
            link = helpers.device_entity_link(
                f.source_friendly_name,
                device_id=f.source_device_id,
                config_entry_id=f.source_config_entry_id,
            )
            cta = f'  Re-hide: open {link}, toggle "Visible" off.'
        else:
            link = helpers.deviceless_entity_link(
                f.source_friendly_name,
                f.source_entity_id,
            )
            cta = f'  Re-hide: open {link}, then toggle "Visible" off.'
        lines.append(
            f"- `{f.source_entity_id}` -> wrapped as `{wrapper_eid}`",
        )
        lines.append(cta)
    lines.append("")
    lines.append(
        "Toggling visibility off in the UI sets"
        ' `hidden_by="user"`, which sticks even if the'
        " switch_as_x wrapper is later removed. The integration"
        ' also re-hides with `hidden_by="integration"` only at'
        " switch_as_x config-entry creation, so a wrapper"
        " removed and re-added recovers the integration-managed"
        " hide; a `user` hide does not.",
    )
    return "\n".join(lines)


def _evaluate_visible_aliased_entities(
    config: Config,
    infos: list[VisibleAliasedEntityInfo],
) -> VisibleAliasedResult:
    """Evaluate switch_as_x sources for visibility drift.

    Each ``info`` represents a switch_as_x entry whose
    source is currently visible (``hidden_by is None``);
    handler-side defensive checks have already filtered
    out entries with malformed options, disabled wrappers,
    disabled sources, or missing wrapper entities.

    Per-entity exclusions still apply at the logic layer so
    users can keep a known-good aliased pair visible without
    disabling the whole check (the
    ``exclude_entities`` / ``exclude_entity_id_regex`` /
    ``exclude_entity_name_regex`` config fields are reused
    from the device-attached + deviceless paths).
    """
    findings: list[VisibleAliasedEntityFinding] = []
    excluded = 0

    for info in infos:
        if _is_excluded(
            config,
            info.source_entity_id,
            info.source_friendly_name,
        ):
            excluded += 1
            continue
        findings.append(
            VisibleAliasedEntityFinding(
                source_entity_id=info.source_entity_id,
                wrapper_entity_id=info.wrapper_entity_id,
                wrapper_target_domain=info.wrapper_target_domain,
                source_friendly_name=info.source_friendly_name,
                source_device_id=info.source_device_id,
                source_config_entry_id=info.source_config_entry_id,
            ),
        )

    has_issue = bool(findings)
    title = ""
    message = ""
    if has_issue:
        title = "Visible aliased entities"
        message = _build_visible_aliased_notification_message(
            findings,
        )

    return VisibleAliasedResult(
        has_issue=has_issue,
        notification_id=(f"{config.notification_prefix}visible_aliased"),
        notification_title=title,
        notification_message=message,
        findings=findings,
        entries_kept=len(infos) - excluded,
        entries_excluded=excluded,
    )


def evaluate_devices(
    config: Config,
    devices: list[DeviceInfo],
) -> list[DeviceResult]:
    """Evaluate drift for all devices.

    Main entry point for the logic module.

    The service wrapper triggers every minute via a time
    pattern.  An interval gate checks whether enough time
    has passed since the last evaluation.

    When the gate passes, the wrapper:
    - Discovers devices across configured integrations
    - For each entity, computes drift data using the HA
      entity and device registries
    - Calls this function with the device list

    For each device, this function:
    - Filters by device exclusion regex
    - Checks each entity for ID and/or name drift
    - Builds a notification per device with drift details

    The wrapper then creates/dismisses persistent
    notifications per device.
    """
    results: list[DeviceResult] = []
    for device in devices:
        result = _evaluate_device(config, device)
        results.append(result)
    return results


@dataclass
class DirectiveInputs:
    """Per-instance include / exclude directive inputs for EDW.

    Carries the user-supplied directive lists, the enabled
    toggle, and the candidate sets the validators measure
    against. All candidate sets are sourced from the FULL
    registries (NOT filtered by include / exclude
    integrations), so the validator's "matches no
    candidates" signal doesn't depend on the order
    integration-filter vs regex-filter run inside the
    actual exclusion code -- a user with both layers
    configured shouldn't see "regex matches nothing" warnings
    when the integration filter already pruned the entities
    the regex would have caught.

    - ``all_registered_entity_ids``: every entity ID the
      registry knows about (used for ``exclude_entities``).
    - ``device_name_candidates``: every device's
      ``name_by_user or name`` the device registry knows
      about.
    - ``entity_id_candidates``: every entity ID in the
      registry.
    - ``entity_name_candidates``: the union of ``name`` and
      ``original_name`` across every entity-registry entry
      (NOT ``name_by_user``, which is device-registry only;
      the entity registry's user-set name lives in
      ``name``).
    """

    enabled: bool
    include_integrations: list[str]
    exclude_integrations: list[str]
    exclude_entities: list[str]
    all_registered_entity_ids: frozenset[str]
    exclude_device_name_regex_lines: list[helpers.JoinedRegexLine]
    exclude_entity_id_regex_lines: list[helpers.JoinedRegexLine]
    exclude_entity_name_regex_lines: list[helpers.JoinedRegexLine]
    device_name_candidates: frozenset[str]
    entity_id_candidates: frozenset[str]
    entity_name_candidates: frozenset[str]


@dataclass
class EvaluationResult:
    """Full evaluation result for the service wrapper."""

    results: list[DeviceResult]
    notifications: list[helpers.PersistentNotification]
    all_integrations_count: int
    stat_entities: int
    stat_devices_excluded: int
    stat_entities_excluded: int
    issues_count: int
    stat_entity_issues: int
    stat_name_issues: int
    stat_id_issues: int
    stat_deviceless_entities: int
    stat_deviceless_excluded: int
    stat_deviceless_drift: int
    stat_deviceless_stale: int
    # Visible-aliased-entity counters. ``kept`` is the count
    # of inputs the logic layer received that survived user
    # exclusion; ``excluded`` is the count filtered by user
    # exclusion. The handler adds defensive-skip bookkeeping
    # (entries dropped before they reached logic) on top to
    # populate the diagnostic state.
    stat_visible_aliased_kept: int = 0
    stat_visible_aliased_excluded: int = 0
    stat_visible_aliased_flagged: int = 0
    unmatched_directives: list[helpers.UnmatchedDirective] = field(
        default_factory=list,
    )


def _validate_edw_directives(
    inputs: DirectiveInputs,
    all_integrations: list[str],
) -> list[helpers.UnmatchedDirective]:
    """Compose the per-category validators into EDW's unmatched list.

    Integration directives match against
    ``all_integrations``. The other categories use the
    candidate sets the handler pre-built from the full
    registries (see ``DirectiveInputs`` for the rationale --
    candidates are deliberately broader than the
    post-include/exclude-integration set so the validator
    doesn't leak the actual exclusion code's layer
    ordering).
    """
    if not inputs.enabled:
        return []

    integration_candidates = frozenset(all_integrations)

    out: list[helpers.UnmatchedDirective] = []
    out.extend(
        helpers.validate_directives_item(
            field="include_integrations",
            directives=inputs.include_integrations,
            candidates=integration_candidates,
            reason="unknown integration",
        ),
    )
    out.extend(
        helpers.validate_directives_item(
            field="exclude_integrations",
            directives=inputs.exclude_integrations,
            candidates=integration_candidates,
            reason="unknown integration",
        ),
    )
    out.extend(
        helpers.validate_directives_item(
            field="exclude_entities",
            directives=inputs.exclude_entities,
            candidates=inputs.all_registered_entity_ids,
            reason="no entity matches",
        ),
    )
    out.extend(
        helpers.validate_directives_regex(
            field="exclude_device_name_regex",
            lines=inputs.exclude_device_name_regex_lines,
            candidates=inputs.device_name_candidates,
        ),
    )
    out.extend(
        helpers.validate_directives_regex(
            field="exclude_entity_id_regex",
            lines=inputs.exclude_entity_id_regex_lines,
            candidates=inputs.entity_id_candidates,
        ),
    )
    out.extend(
        helpers.validate_directives_regex(
            field="exclude_entity_name_regex",
            lines=inputs.exclude_entity_name_regex_lines,
            candidates=inputs.entity_name_candidates,
        ),
    )
    return out


_DISABLED_DIRECTIVES = DirectiveInputs(
    enabled=False,
    include_integrations=[],
    exclude_integrations=[],
    exclude_entities=[],
    all_registered_entity_ids=frozenset(),
    exclude_device_name_regex_lines=[],
    exclude_entity_id_regex_lines=[],
    exclude_entity_name_regex_lines=[],
    device_name_candidates=frozenset(),
    entity_id_candidates=frozenset(),
    entity_name_candidates=frozenset(),
)


def run_evaluation(
    config: Config,
    devices: list[DeviceInfo],
    deviceless_entities: list[DevicelessEntityInfo],
    peers_by_domain: dict[str, set[str]],
    all_integrations: list[str],
    max_notifications: int,
    directive_inputs: DirectiveInputs | None = None,
    visible_aliased_infos: list[VisibleAliasedEntityInfo] | None = None,
) -> EvaluationResult:
    """Run entity defaults evaluation in a worker thread.

    Called from the handler via
    ``hass.async_add_executor_job`` so the heavy per-device
    drift classification + notification body assembly stays
    off the event loop.
    """
    if visible_aliased_infos is None:
        visible_aliased_infos = []

    results = evaluate_devices(config, devices)

    notifications = helpers.prepare_notifications(
        results,
        max_notifications=max_notifications,
        cap_notification_id=f"{config.notification_prefix}cap",
        cap_title="Notification cap reached",
        cap_item_label="devices with drift",
        instance_id=config.instance_id,
    )

    if _check_deviceless_enabled(config):
        deviceless = _evaluate_deviceless(
            config,
            deviceless_entities,
            peers_by_domain,
        )
    else:
        deviceless = DevicelessResult(
            has_issue=False,
            notification_id=f"{config.notification_prefix}deviceless",
            notification_title="",
            notification_message="",
            drifted=[],
            entities_checked=0,
            entities_excluded=0,
        )
    notifications.append(
        helpers.PersistentNotification(
            active=deviceless.has_issue,
            notification_id=deviceless.notification_id,
            title=deviceless.notification_title,
            message=deviceless.notification_message,
            instance_id=config.instance_id,
        ),
    )

    if _check_visible_aliased_enabled(config):
        visible_aliased = _evaluate_visible_aliased_entities(
            config,
            visible_aliased_infos,
        )
    else:
        visible_aliased = VisibleAliasedResult(
            has_issue=False,
            notification_id=(f"{config.notification_prefix}visible_aliased"),
            notification_title="",
            notification_message="",
            findings=[],
            entries_kept=0,
            entries_excluded=0,
        )
    notifications.append(
        helpers.PersistentNotification(
            active=visible_aliased.has_issue,
            notification_id=visible_aliased.notification_id,
            title=visible_aliased.notification_title,
            message=visible_aliased.notification_message,
            instance_id=config.instance_id,
        ),
    )

    issues = [r for r in results if r.has_issue]
    stat_deviceless_stale = sum(
        [1 for d in deviceless.drifted if d.stale_suffix]
    )
    stat_deviceless_drift = len(deviceless.drifted) - stat_deviceless_stale

    return EvaluationResult(
        results=results,
        notifications=notifications,
        all_integrations_count=len(all_integrations),
        stat_entities=sum(
            [
                r.entities_checked + r.entities_excluded
                for r in results
                if not r.device_excluded
            ]
        ),
        stat_devices_excluded=sum([1 for r in results if r.device_excluded]),
        stat_entities_excluded=sum([r.entities_excluded for r in results]),
        issues_count=len(issues),
        stat_entity_issues=sum([len(r.drifted_entities) for r in issues]),
        stat_name_issues=sum(
            [1 for r in issues for d in r.drifted_entities if d.name_drifted]
        ),
        stat_id_issues=sum(
            [1 for r in issues for d in r.drifted_entities if d.id_drifted]
        ),
        stat_deviceless_entities=deviceless.entities_checked,
        stat_deviceless_excluded=deviceless.entities_excluded,
        stat_deviceless_drift=stat_deviceless_drift,
        stat_deviceless_stale=stat_deviceless_stale,
        stat_visible_aliased_kept=visible_aliased.entries_kept,
        stat_visible_aliased_excluded=visible_aliased.entries_excluded,
        stat_visible_aliased_flagged=len(visible_aliased.findings),
        unmatched_directives=_validate_edw_directives(
            directive_inputs
            if directive_inputs is not None
            else _DISABLED_DIRECTIVES,
            all_integrations,
        ),
    )
