"""Terminal UI helpers for RD collection workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

import questionary
from rich.table import Table

from vassago.collection.rd.quick_qc import describe_reason

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from rich.console import Console

    from vassago.collection.rd.config import CollectionProfile
    from vassago.collection.rd.config import WindowRange
    from vassago.collection.rd.quick_qc import QuickQcDecision
    from vassago.collection.rd.session import SessionSummary
    from vassago.firmware.mmwave.protocol import SmokeTestSummary


TAKE_ACTION_START = "start"
TAKE_ACTION_QUIT = "quit"
TAKE_DECISION_ACCEPT = "accept"
TAKE_DECISION_RETRY = "retry"
TAKE_DECISION_QUIT = "quit"


def render_collection_profiles(
    console: Console,
    profiles: Sequence[CollectionProfile],
) -> None:
    """Render the available collection profiles."""
    table = Table(title="Collection Configs")
    table.add_column("Config ID")
    table.add_column("Label")
    table.add_column("Batch Size", justify="right")
    table.add_column("Capture", justify="right")
    table.add_column("Firmware Config")
    table.add_column("Description")

    for profile in profiles:
        table.add_row(
            profile.config_id,
            profile.label,
            str(profile.batch_size),
            f"{profile.capture_window_duration_s:.2f}s",
            profile.firmware_config_id,
            profile.description,
        )

    if not profiles:
        table.add_row("-", "No collection configs", "0", "0.00s", "-", "-")

    console.print(table)


def render_sessions(
    console: Console,
    sessions: Sequence[SessionSummary],
) -> None:
    """Render resumable sessions."""
    table = Table(title="Unfinished Collection Sessions")
    table.add_column("Session ID")
    table.add_column("Status")
    table.add_column("Subject")
    table.add_column("Gesture")
    table.add_column("Accepted", justify="right")
    table.add_column("Remaining", justify="right")
    table.add_column("Manifest")

    for summary in sessions:
        table.add_row(
            summary.session_id,
            summary.session_status,
            summary.subject_name,
            summary.gesture,
            str(summary.accepted_take_count),
            str(summary.remaining_take_count),
            str(summary.manifest_path),
        )

    if not sessions:
        table.add_row("-", "-", "-", "-", "0", "0", "-")

    console.print(table)


def render_session_summary(
    console: Console,
    *,
    manifest_path: Path,
    manifest: dict[str, object],
) -> None:
    """Render a compact manifest summary after session init or resume."""
    table = Table(title="Collection Session Summary")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("manifest", str(manifest_path))
    table.add_row("session_id", str(manifest["session_id"]))
    table.add_row("session_status", str(manifest["session_status"]))
    table.add_row("subject_name", str(manifest["subject_name"]))
    table.add_row("gesture", str(manifest["gesture"]))
    table.add_row("config_id", str(manifest["config_id"]))
    table.add_row("cli_port", str(manifest["cli_port"]))
    table.add_row("data_port", str(manifest["data_port"]))
    console.print(table)


def render_take_state(  # noqa: PLR0913
    console: Console,
    *,
    take_id: str,
    take_index: int,
    batch_size: int,
    countdown_duration_s: float,
    target_window_duration_s: float,
    end_mark_key: str,
    accepted_take_count: int,
    remaining_take_count: int,
) -> None:
    """Render the current state before one take begins."""
    table = Table(title=f"Take {take_id}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("state", "ready")
    table.add_row("progress", f"{take_index}/{batch_size}")
    table.add_row("accepted", str(accepted_take_count))
    table.add_row("remaining", str(remaining_take_count))
    table.add_row("countdown", f"{countdown_duration_s:.2f}s")
    table.add_row("target_window_duration", f"{target_window_duration_s:.2f}s")
    table.add_row("end_mark_key", end_mark_key)
    table.add_row("controls", f"Start, wait for GO, then press {end_mark_key}.")
    console.print(table)


def render_capture_summary(
    console: Console,
    *,
    summary: SmokeTestSummary,
    capture_window: WindowRange,
    target_window: WindowRange,
    marked_window: WindowRange | None,
) -> None:
    """Render a short post-capture summary for operator review."""
    table = Table(title="Capture Review")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("bytes_read", str(summary.bytes_read))
    table.add_row("valid_packets", str(summary.valid_packet_count))
    table.add_row("invalid_packets", str(summary.invalid_packet_count))
    table.add_row("first_frame", str(summary.first_frame_number))
    table.add_row("last_frame", str(summary.last_frame_number))
    table.add_row("frame_gaps", str(summary.frame_gap_count))
    table.add_row(
        "capture_window",
        f"{capture_window.start_s:.2f}s -> {capture_window.end_s:.2f}s",
    )
    table.add_row(
        "target_window",
        f"{target_window.start_s:.2f}s -> {target_window.end_s:.2f}s",
    )
    table.add_row(
        "marked_window",
        (
            f"{marked_window.start_s:.2f}s -> {marked_window.end_s:.2f}s"
            if marked_window is not None
            else "null"
        ),
    )
    console.print(table)


def render_quick_qc(
    console: Console,
    *,
    decision: QuickQcDecision,
) -> None:
    """Render the minimal quick-QC result for one attempt."""
    table = Table(title="Quick QC")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("result", "pass" if decision.accepted else "reject")
    table.add_row(
        "reasons",
        ", ".join(describe_reason(reason) for reason in decision.reasons)
        if decision.reasons
        else "-",
    )
    console.print(table)


def prompt_for_collection_profile(
    profiles: Sequence[CollectionProfile],
) -> CollectionProfile:
    """Prompt for one collection profile."""
    response = questionary.select(
        "Choose a collection config",
        choices=[
            questionary.Choice(
                title=(
                    f"{profile.label} [{profile.config_id}] "
                    f"batch={profile.batch_size} fw={profile.firmware_config_id}"
                ),
                value=profile,
            )
            for profile in profiles
        ],
    ).ask()
    return _require_answer(response, "Collection config selection was cancelled.")


def prompt_for_session(
    sessions: Sequence[SessionSummary],
) -> SessionSummary:
    """Prompt for one unfinished session to resume."""
    response = questionary.select(
        "Choose an unfinished session",
        choices=[
            questionary.Choice(
                title=(
                    f"{summary.session_id} "
                    f"status={summary.session_status} "
                    f"subject={summary.subject_name} "
                    f"remaining={summary.remaining_take_count}"
                ),
                value=summary,
            )
            for summary in sessions
        ],
    ).ask()
    return _require_answer(response, "Session selection was cancelled.")


def prompt_for_choice(
    *,
    message: str,
    choices: Sequence[str],
    default: str | None = None,
) -> str:
    """Prompt for one string choice."""
    resolved_default = default if default in choices else None
    response = questionary.select(
        message,
        choices=list(choices),
        default=resolved_default,
    ).ask()
    return _require_answer(response, f"{message} was cancelled.")


def prompt_for_required_text(
    *,
    message: str,
    default: str | None = None,
) -> str:
    """Prompt for one required text value."""
    default_text = default or ""
    while True:
        response = questionary.text(message, default=default_text).ask()
        value = _require_answer(response, f"{message} was cancelled.").strip()
        if value:
            return value


def prompt_for_optional_text(
    *,
    message: str,
    default: str | None = None,
) -> str | None:
    """Prompt for one optional text value."""
    default_text = default or ""
    response = questionary.text(message, default=default_text).ask()
    value = _require_answer(response, f"{message} was cancelled.").strip()
    return value or None


def prompt_for_optional_float(
    *,
    message: str,
    default: float | None = None,
) -> float | None:
    """Prompt for one optional float value."""
    default_text = "" if default is None else f"{default:g}"
    while True:
        response = questionary.text(message, default=default_text).ask()
        value = _require_answer(response, f"{message} was cancelled.").strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            continue


def prompt_take_action(*, take_id: str) -> str:
    """Prompt for the next action before a take starts."""
    response = questionary.select(
        f"{take_id}: choose next step",
        choices=[
            questionary.Choice(title="Start capture", value=TAKE_ACTION_START),
            questionary.Choice(title="Leave session", value=TAKE_ACTION_QUIT),
        ],
    ).ask()
    return _require_answer(response, "Take action selection was cancelled.")


def prompt_take_decision(*, take_id: str) -> str:
    """Prompt for the operator decision after one capture."""
    response = questionary.select(
        f"{take_id}: review capture",
        choices=[
            questionary.Choice(title="Accept take", value=TAKE_DECISION_ACCEPT),
            questionary.Choice(title="Retry take", value=TAKE_DECISION_RETRY),
            questionary.Choice(title="Quit session", value=TAKE_DECISION_QUIT),
        ],
    ).ask()
    return _require_answer(response, "Take decision selection was cancelled.")


def prompt_rejected_take_action(*, take_id: str) -> str:
    """Prompt after quick-QC rejects one attempt."""
    response = questionary.select(
        f"{take_id}: quick QC rejected this attempt",
        choices=[
            questionary.Choice(title="Retry take", value=TAKE_DECISION_RETRY),
            questionary.Choice(title="Quit session", value=TAKE_DECISION_QUIT),
        ],
    ).ask()
    return _require_answer(response, "Rejected-take action selection was cancelled.")


def _require_answer[T](answer: T | None, error_message: str) -> T:
    """Turn a cancelled questionary prompt into a readable exception."""
    if answer is None:
        raise RuntimeError(error_message)
    return answer
