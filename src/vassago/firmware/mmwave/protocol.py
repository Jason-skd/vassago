"""Protocol-level parsing primitives for TI-style mmWave UART output."""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

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


@dataclass(slots=True, frozen=True)
class MmwavePacket:
    """Parsed mmWave UART packet header plus TLV type summary."""

    version: int
    total_packet_length: int
    platform: int
    frame_number: int
    time_cpu_cycles: int
    num_detected_objects: int
    num_tlvs: int
    sub_frame_number: int
    tlv_types: tuple[int, ...]


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

            tlv_types = self._parse_tlv_types(
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
                    tlv_types=tlv_types,
                ),
            )

    @staticmethod
    def _parse_header(buffer: bytearray) -> MmwavePacket | None:
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

        return MmwavePacket(
            version=version,
            total_packet_length=total_packet_length,
            platform=platform,
            frame_number=frame_number,
            time_cpu_cycles=time_cpu_cycles,
            num_detected_objects=num_detected_objects,
            num_tlvs=num_tlvs,
            sub_frame_number=sub_frame_number,
            tlv_types=(),
        )

    @staticmethod
    def _parse_tlv_types(
        *,
        packet_bytes: bytes,
        total_packet_length: int,
        num_tlvs: int,
    ) -> tuple[int, ...]:
        """Parse TLV headers and return the TLV type list for the packet."""
        return _parse_tlv_types_with_best_effort(
            packet_bytes=packet_bytes,
            total_packet_length=total_packet_length,
            num_tlvs=num_tlvs,
        )


def _parse_tlv_types_with_best_effort(
    *,
    packet_bytes: bytes,
    total_packet_length: int,
    num_tlvs: int,
) -> tuple[int, ...]:
    """Parse TLVs while tolerating both total-length and payload-length styles."""
    best_tlv_types: tuple[int, ...] = ()
    states: list[tuple[int, tuple[int, ...], int]] = [(HEADER_SIZE, (), num_tlvs)]

    while states:
        offset, parsed_tlv_types, tlvs_left = states.pop()
        if len(parsed_tlv_types) > len(best_tlv_types):
            best_tlv_types = parsed_tlv_types

        if tlvs_left <= 0 or offset + TLV_HEADER_SIZE > total_packet_length:
            continue

        tlv_type, tlv_length_raw = struct.unpack_from(
            TLV_HEADER_FORMAT,
            packet_bytes,
            offset,
        )
        states.extend(
            (
                offset + candidate_total_size,
                (*parsed_tlv_types, tlv_type),
                tlvs_left - 1,
            )
            for candidate_total_size in reversed(
                _candidate_tlv_total_sizes(
                    offset=offset,
                    tlv_length_raw=tlv_length_raw,
                    total_packet_length=total_packet_length,
                ),
            )
        )

        if len(best_tlv_types) == num_tlvs:
            break

    return best_tlv_types


def _candidate_tlv_total_sizes(
    *,
    offset: int,
    tlv_length_raw: int,
    total_packet_length: int,
) -> tuple[int, ...]:
    """Return viable TLV total sizes for standard and payload-length variants."""
    candidate_sizes: list[int] = []

    for candidate_total_size in (tlv_length_raw, TLV_HEADER_SIZE + tlv_length_raw):
        if candidate_total_size < TLV_HEADER_SIZE:
            continue
        if offset + candidate_total_size > total_packet_length:
            continue
        if candidate_total_size not in candidate_sizes:
            candidate_sizes.append(candidate_total_size)

    return tuple(candidate_sizes)


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
