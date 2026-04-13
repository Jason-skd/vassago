"""Protocol-level parsing primitives for TI-style mmWave UART output."""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

MAGIC_WORD = b"\x02\x01\x04\x03\x06\x05\x08\x07"
MAGIC_WORD_SIZE = len(MAGIC_WORD)
HEADER_BODY_FORMAT = "<8I"
HEADER_BODY_SIZE = struct.calcsize(HEADER_BODY_FORMAT)
HEADER_SIZE = MAGIC_WORD_SIZE + HEADER_BODY_SIZE
TLV_HEADER_FORMAT = "<II"
TLV_HEADER_SIZE = struct.calcsize(TLV_HEADER_FORMAT)
MAX_PACKET_SIZE_BYTES = 1_048_576
type TlvLengthMode = Literal["payload", "total"]
type TlvParseScore = tuple[int, int, int, int, int, int]
TLV_TYPE_PLAUSIBLE_UPPER_BOUND = 255
SMALL_TRAILING_PADDING_LIMIT_BYTES = 32


@dataclass(slots=True, frozen=True)
class MmwaveTlv:
    """One parsed TLV plus its payload bytes."""

    tlv_type: int
    payload: bytes
    raw_length: int
    length_mode: TlvLengthMode

    @property
    def payload_length(self) -> int:
        """Return the TLV payload byte count."""
        return len(self.payload)

    @property
    def total_size(self) -> int:
        """Return the full TLV byte size including its header."""
        return TLV_HEADER_SIZE + self.payload_length


@dataclass(slots=True, frozen=True)
class MmwavePacket:
    """Parsed mmWave UART packet header plus TLV payloads."""

    version: int
    total_packet_length: int
    platform: int
    frame_number: int
    time_cpu_cycles: int
    num_detected_objects: int
    num_tlvs: int
    sub_frame_number: int
    tlvs: tuple[MmwaveTlv, ...]

    @property
    def tlv_types(self) -> tuple[int, ...]:
        """Return the TLV type list in wire order."""
        return tuple(tlv.tlv_type for tlv in self.tlvs)


@dataclass(slots=True, frozen=True)
class _MmwavePacketHeader:
    """Validated fixed-size mmWave packet header."""

    version: int
    total_packet_length: int
    platform: int
    frame_number: int
    time_cpu_cycles: int
    num_detected_objects: int
    num_tlvs: int
    sub_frame_number: int


@dataclass(slots=True, frozen=True)
class SmokeTestSummary:
    """Aggregated smoke-test result."""

    bytes_read: int
    valid_packet_count: int
    invalid_packet_count: int
    first_frame_number: int | None
    last_frame_number: int | None
    frame_gap_count: int
    non_monotonic_frame_count: int
    tlv_type_counts: dict[int, int]

    def passed(self, minimum_packet_count: int) -> bool:
        """Return whether the smoke test collected enough valid packets."""
        return self.valid_packet_count >= minimum_packet_count


class SmokeTestSummaryAccumulator:
    """Incrementally build a smoke-test summary from streamed UART bytes."""

    def __init__(self, *, packet_parser: MmwavePacketParser | None = None) -> None:
        """Initialize the accumulator with an optional shared packet parser."""
        self._packet_parser = packet_parser or MmwavePacketParser()
        self._packets: list[MmwavePacket] = []
        self._bytes_read = 0

    @property
    def bytes_read(self) -> int:
        """Return the total byte count fed into the accumulator."""
        return self._bytes_read

    @property
    def invalid_packet_count(self) -> int:
        """Return the invalid packet count reported by the shared parser."""
        return self._packet_parser.invalid_packet_count

    @property
    def buffered_byte_count(self) -> int:
        """Return the byte count still buffered by the shared parser."""
        return self._packet_parser.buffered_byte_count

    def feed(self, data: bytes) -> None:
        """Consume one raw byte chunk and update the incremental summary state."""
        self._bytes_read += len(data)
        self._packets.extend(self._packet_parser.feed(data))

    def build_summary(self) -> SmokeTestSummary:
        """Return the current aggregate summary from streamed bytes so far."""
        return summarize_packets(
            packets=self._packets,
            bytes_read=self._bytes_read,
            invalid_packet_count=self.invalid_packet_count,
        )


class MmwavePacketParser:
    """Streaming parser for TI mmWave-style UART packets."""

    def __init__(self) -> None:
        """Initialize the parser with an empty byte buffer."""
        self._buffer = bytearray()
        self.invalid_packet_count = 0

    @property
    def buffered_byte_count(self) -> int:
        """Return the number of bytes still buffered after parsing."""
        return len(self._buffer)

    def feed(self, data: bytes) -> list[MmwavePacket]:
        """Consume bytes and return any complete packets found."""
        self._buffer.extend(data)
        packets: list[MmwavePacket] = []

        while True:
            if len(self._buffer) < MAGIC_WORD_SIZE:
                return packets

            packet_start = self._buffer.find(MAGIC_WORD)
            if packet_start < 0:
                self._buffer = self._buffer[-(MAGIC_WORD_SIZE - 1) :]
                return packets

            if packet_start > 0:
                del self._buffer[:packet_start]

            if len(self._buffer) < HEADER_SIZE:
                return packets

            header = self._parse_header(self._buffer)
            if header is None:
                self.invalid_packet_count += 1
                del self._buffer[0]
                continue

            if len(self._buffer) < header.total_packet_length:
                return packets

            packet_bytes = bytes(self._buffer[: header.total_packet_length])
            del self._buffer[: header.total_packet_length]

            tlvs = self._parse_tlvs(
                packet_bytes=packet_bytes,
                total_packet_length=header.total_packet_length,
                num_tlvs=header.num_tlvs,
            )
            packets.append(
                MmwavePacket(
                    version=header.version,
                    total_packet_length=header.total_packet_length,
                    platform=header.platform,
                    frame_number=header.frame_number,
                    time_cpu_cycles=header.time_cpu_cycles,
                    num_detected_objects=header.num_detected_objects,
                    num_tlvs=header.num_tlvs,
                    sub_frame_number=header.sub_frame_number,
                    tlvs=tlvs,
                ),
            )

    @staticmethod
    def _parse_header(buffer: bytearray) -> _MmwavePacketHeader | None:
        """Parse the fixed-size packet header from the current buffer."""
        (
            version,
            total_packet_length,
            platform,
            frame_number,
            time_cpu_cycles,
            num_detected_objects,
            num_tlvs,
            sub_frame_number,
        ) = struct.unpack_from(HEADER_BODY_FORMAT, buffer, MAGIC_WORD_SIZE)

        if total_packet_length < HEADER_SIZE:
            return None
        if total_packet_length > MAX_PACKET_SIZE_BYTES:
            return None

        return _MmwavePacketHeader(
            version=version,
            total_packet_length=total_packet_length,
            platform=platform,
            frame_number=frame_number,
            time_cpu_cycles=time_cpu_cycles,
            num_detected_objects=num_detected_objects,
            num_tlvs=num_tlvs,
            sub_frame_number=sub_frame_number,
        )

    @staticmethod
    def _parse_tlvs(
        *,
        packet_bytes: bytes,
        total_packet_length: int,
        num_tlvs: int,
    ) -> tuple[MmwaveTlv, ...]:
        """Parse TLV headers and payloads for the packet."""
        return _parse_tlvs_with_best_effort(
            packet_bytes=packet_bytes,
            total_packet_length=total_packet_length,
            num_tlvs=num_tlvs,
        )


def _parse_tlvs_with_best_effort(
    *,
    packet_bytes: bytes,
    total_packet_length: int,
    num_tlvs: int,
) -> tuple[MmwaveTlv, ...]:
    """Parse TLVs while tolerating both total-length and payload-length styles."""
    best_tlvs: tuple[MmwaveTlv, ...] = ()
    best_score = _tlv_parse_score(
        parsed_tlvs=best_tlvs,
        offset=HEADER_SIZE,
        total_packet_length=total_packet_length,
    )
    states: list[tuple[int, tuple[MmwaveTlv, ...], int]] = [(HEADER_SIZE, (), num_tlvs)]

    while states:
        offset, parsed_tlvs, tlvs_left = states.pop()
        if _parsed_tlvs_are_better(
            parsed_tlvs=parsed_tlvs,
            offset=offset,
            best_score=best_score,
            total_packet_length=total_packet_length,
        ):
            best_tlvs = parsed_tlvs
            best_score = _tlv_parse_score(
                parsed_tlvs=parsed_tlvs,
                offset=offset,
                total_packet_length=total_packet_length,
            )

        if tlvs_left <= 0 or offset + TLV_HEADER_SIZE > total_packet_length:
            continue

        tlv_type, tlv_length_raw = struct.unpack_from(
            TLV_HEADER_FORMAT,
            packet_bytes,
            offset,
        )
        candidate_states = tuple(
            _candidate_tlv_state(
                packet_bytes=packet_bytes,
                offset=offset,
                tlv_type=tlv_type,
                tlv_length_raw=tlv_length_raw,
                candidate_total_size=candidate_total_size,
                length_mode=length_mode,
                parsed_tlvs=parsed_tlvs,
                tlvs_left=tlvs_left,
            )
            for candidate_total_size, length_mode in _candidate_tlv_layouts(
                offset=offset,
                tlv_length_raw=tlv_length_raw,
                total_packet_length=total_packet_length,
            )
        )
        states.extend(reversed(candidate_states))

    return best_tlvs


def _candidate_tlv_state(
    *,
    packet_bytes: bytes,
    offset: int,
    tlv_type: int,
    tlv_length_raw: int,
    candidate_total_size: int,
    length_mode: TlvLengthMode,
    parsed_tlvs: tuple[MmwaveTlv, ...],
    tlvs_left: int,
) -> tuple[int, tuple[MmwaveTlv, ...], int]:
    """Build one parser state for a candidate TLV layout."""
    payload_start = offset + TLV_HEADER_SIZE
    payload_end = offset + candidate_total_size
    payload = packet_bytes[payload_start:payload_end]
    tlv = MmwaveTlv(
        tlv_type=tlv_type,
        payload=payload,
        raw_length=tlv_length_raw,
        length_mode=length_mode,
    )
    return (
        offset + candidate_total_size,
        (*parsed_tlvs, tlv),
        tlvs_left - 1,
    )


def _candidate_tlv_layouts(
    *,
    offset: int,
    tlv_length_raw: int,
    total_packet_length: int,
) -> tuple[tuple[int, TlvLengthMode], ...]:
    """Return viable TLV layouts for total-length and payload-length variants."""
    candidate_layouts: list[tuple[int, TlvLengthMode]] = []
    raw_layouts: tuple[tuple[int, TlvLengthMode], ...] = (
        (tlv_length_raw, "total"),
        (TLV_HEADER_SIZE + tlv_length_raw, "payload"),
    )

    for candidate_total_size, length_mode in raw_layouts:
        if candidate_total_size < TLV_HEADER_SIZE:
            continue
        if offset + candidate_total_size > total_packet_length:
            continue
        candidate_layout = (candidate_total_size, length_mode)
        if candidate_layout not in candidate_layouts:
            candidate_layouts.append(candidate_layout)

    return tuple(candidate_layouts)


def _parsed_tlvs_are_better(
    *,
    parsed_tlvs: tuple[MmwaveTlv, ...],
    offset: int,
    best_score: TlvParseScore,
    total_packet_length: int,
) -> bool:
    """Return whether one TLV parse path is better than the current best."""
    return (
        _tlv_parse_score(
            parsed_tlvs=parsed_tlvs,
            offset=offset,
            total_packet_length=total_packet_length,
        )
        > best_score
    )


def _tlv_parse_score(
    *,
    parsed_tlvs: tuple[MmwaveTlv, ...],
    offset: int,
    total_packet_length: int,
) -> TlvParseScore:
    """Rank one candidate TLV path by completeness and parse plausibility."""
    trailing_padding = total_packet_length - offset
    tlv_types = tuple(tlv.tlv_type for tlv in parsed_tlvs)
    return (
        len(parsed_tlvs),
        int(_has_small_aligned_trailing_padding(trailing_padding)),
        sum(1 for tlv in parsed_tlvs if tlv.payload_length % 4 == 0),
        sum(
            1
            for tlv in parsed_tlvs
            if 0 <= tlv.tlv_type <= TLV_TYPE_PLAUSIBLE_UPPER_BOUND
        ),
        len(set(tlv_types)),
        offset,
    )


def _has_small_aligned_trailing_padding(trailing_padding: int) -> bool:
    """Return whether one candidate leaves a small 32-bit-aligned tail."""
    return (
        trailing_padding >= 0
        and trailing_padding < SMALL_TRAILING_PADDING_LIMIT_BYTES
        and trailing_padding % 4 == 0
    )


def summarize_packets(
    *,
    packets: Iterable[MmwavePacket],
    bytes_read: int,
    invalid_packet_count: int,
) -> SmokeTestSummary:
    """Aggregate high-level counters from parsed packets."""
    packet_list = list(packets)
    tlv_type_counts: Counter[int] = Counter()
    frame_gap_count = 0
    non_monotonic_frame_count = 0

    previous_frame_number: int | None = None
    for packet in packet_list:
        tlv_type_counts.update(packet.tlv_types)

        if previous_frame_number is not None:
            if packet.frame_number > previous_frame_number + 1:
                frame_gap_count += packet.frame_number - previous_frame_number - 1
            elif packet.frame_number <= previous_frame_number:
                non_monotonic_frame_count += 1

        previous_frame_number = packet.frame_number

    first_frame_number = packet_list[0].frame_number if packet_list else None
    last_frame_number = packet_list[-1].frame_number if packet_list else None

    return SmokeTestSummary(
        bytes_read=bytes_read,
        valid_packet_count=len(packet_list),
        invalid_packet_count=invalid_packet_count,
        first_frame_number=first_frame_number,
        last_frame_number=last_frame_number,
        frame_gap_count=frame_gap_count,
        non_monotonic_frame_count=non_monotonic_frame_count,
        tlv_type_counts=dict(sorted(tlv_type_counts.items())),
    )
