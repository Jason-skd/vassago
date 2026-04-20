"""Strict packet slicing for offline mmWave UART captures."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from vassago.firmware.mmwave.protocol import HEADER_BODY_FORMAT
from vassago.firmware.mmwave.protocol import HEADER_SIZE
from vassago.firmware.mmwave.protocol import MAGIC_WORD
from vassago.firmware.mmwave.protocol import MAGIC_WORD_SIZE
from vassago.firmware.mmwave.protocol import MAX_PACKET_SIZE_BYTES
from vassago.firmware.mmwave.protocol import TLV_HEADER_FORMAT
from vassago.firmware.mmwave.protocol import TLV_HEADER_SIZE

LEADING_NOISE_REASON = "leading_noise"
INTER_PACKET_NOISE_REASON = "inter_packet_noise"
TRAILING_INCOMPLETE_PACKET_REASON = "trailing_incomplete_packet"
TRAILING_BYTES_WITHOUT_MAGIC_REASON = "trailing_bytes_without_magic"
PACKET_TOO_SMALL_ERROR = "packet_too_small"
MISSING_MAGIC_WORD_ERROR = "missing_magic_word"
INVALID_TOTAL_PACKET_LENGTH_ERROR = "invalid_total_packet_length"
PACKET_LENGTH_MISMATCH_ERROR = "packet_length_mismatch"
TLV_HEADER_TRUNCATED_ERROR = "tlv_header_truncated"
TLV_PAYLOAD_OVERFLOW_ERROR = "tlv_payload_overflow"


class PacketDecodeError(ValueError):
    """Raised when a packet cannot be decoded under strict rules."""

    def __init__(self, message: str, *, code: str) -> None:
        """Store a stable machine-readable error code alongside the message."""
        super().__init__(message)
        self.code = code


@dataclass(slots=True, frozen=True)
class DiscardedByteSpan:
    """A discarded byte region encountered while slicing a stream."""

    start_offset: int
    end_offset: int
    reason: str

    @property
    def size(self) -> int:
        """Return the number of bytes in the discarded span."""
        return self.end_offset - self.start_offset


@dataclass(slots=True, frozen=True)
class UartPacketHeader:
    """Strictly decoded mmWave UART packet header."""

    version: int
    total_packet_length: int
    platform: int
    frame_number: int
    time_cpu_cycles: int
    num_detected_objects: int
    num_tlvs: int
    sub_frame_number: int


@dataclass(slots=True, frozen=True)
class UartTlv:
    """One strict TLV record within a packet."""

    tlv_index: int
    tlv_type: int
    payload_length: int
    header_start_offset: int
    payload_start_offset: int
    payload_end_offset: int
    payload: bytes

    @property
    def total_size(self) -> int:
        """Return the on-wire size of this TLV including its header."""
        return TLV_HEADER_SIZE + self.payload_length


@dataclass(slots=True, frozen=True)
class UartPacket:
    """One strictly decoded packet plus its TLVs and padding."""

    packet_index: int
    packet_start_offset: int
    packet_end_offset: int
    header: UartPacketHeader
    tlvs: tuple[UartTlv, ...]
    padding_bytes: bytes
    raw_packet: bytes

    @property
    def frame_number(self) -> int:
        """Return the frame number declared in the packet header."""
        return self.header.frame_number

    @property
    def total_packet_length(self) -> int:
        """Return the total packet length declared in the packet header."""
        return self.header.total_packet_length

    @property
    def num_tlvs(self) -> int:
        """Return the declared TLV count for the packet."""
        return self.header.num_tlvs

    @property
    def padding_size(self) -> int:
        """Return the number of bytes left after strict TLV parsing."""
        return len(self.padding_bytes)


@dataclass(slots=True, frozen=True)
class InvalidPacketCandidate:
    """A candidate packet start that failed strict decoding."""

    packet_start_offset: int
    declared_total_packet_length: int | None
    error_code: str
    error_message: str


@dataclass(slots=True, frozen=True)
class PacketStreamSliceResult:
    """Strict slicing result for one offline UART byte stream."""

    packets: tuple[UartPacket, ...]
    discarded_spans: tuple[DiscardedByteSpan, ...]
    invalid_candidates: tuple[InvalidPacketCandidate, ...]

    @property
    def leading_discarded_bytes(self) -> int:
        """Return bytes discarded before the first complete packet."""
        return sum(
            span.size
            for span in self.discarded_spans
            if span.reason == LEADING_NOISE_REASON
        )

    @property
    def inter_packet_discarded_bytes(self) -> int:
        """Return bytes discarded between complete packets."""
        return sum(
            span.size
            for span in self.discarded_spans
            if span.reason == INTER_PACKET_NOISE_REASON
        )

    @property
    def trailing_incomplete_bytes(self) -> int:
        """Return bytes left after the last complete packet."""
        return sum(
            span.size
            for span in self.discarded_spans
            if span.reason
            in {
                TRAILING_INCOMPLETE_PACKET_REASON,
                TRAILING_BYTES_WITHOUT_MAGIC_REASON,
            }
        )


def slice_uart_packet_stream(data: bytes) -> PacketStreamSliceResult:
    """Slice one offline UART stream into strict packets."""
    packets: list[UartPacket] = []
    discarded_spans: list[DiscardedByteSpan] = []
    invalid_candidates: list[InvalidPacketCandidate] = []
    search_offset = 0

    while search_offset < len(data):
        packet_start = data.find(MAGIC_WORD, search_offset)
        if packet_start < 0:
            discarded_spans.extend(
                _build_terminal_discard_span(
                    start_offset=search_offset,
                    end_offset=len(data),
                    packet_count=len(packets),
                ),
            )
            break

        if packet_start > search_offset:
            discarded_spans.append(
                DiscardedByteSpan(
                    start_offset=search_offset,
                    end_offset=packet_start,
                    reason=(
                        LEADING_NOISE_REASON
                        if not packets
                        else INTER_PACKET_NOISE_REASON
                    ),
                ),
            )

        if packet_start + HEADER_SIZE > len(data):
            discarded_spans.append(
                DiscardedByteSpan(
                    start_offset=packet_start,
                    end_offset=len(data),
                    reason=TRAILING_INCOMPLETE_PACKET_REASON,
                ),
            )
            break

        total_packet_length = _read_total_packet_length(
            data=data,
            packet_start=packet_start,
        )
        try:
            _validate_total_packet_length(total_packet_length)
        except PacketDecodeError as exc:
            invalid_candidates.append(
                InvalidPacketCandidate(
                    packet_start_offset=packet_start,
                    declared_total_packet_length=total_packet_length,
                    error_code=exc.code,
                    error_message=str(exc),
                ),
            )
            search_offset = packet_start + 1
            continue

        packet_end = packet_start + total_packet_length
        if packet_end > len(data):
            discarded_spans.append(
                DiscardedByteSpan(
                    start_offset=packet_start,
                    end_offset=len(data),
                    reason=TRAILING_INCOMPLETE_PACKET_REASON,
                ),
            )
            break

        try:
            packet = decode_uart_packet(
                packet_bytes=data[packet_start:packet_end],
                packet_index=len(packets),
                packet_start_offset=packet_start,
            )
        except PacketDecodeError as exc:
            invalid_candidates.append(
                InvalidPacketCandidate(
                    packet_start_offset=packet_start,
                    declared_total_packet_length=total_packet_length,
                    error_code=exc.code,
                    error_message=str(exc),
                ),
            )
            search_offset = packet_start + 1
            continue

        packets.append(packet)
        search_offset = packet_end

    return PacketStreamSliceResult(
        packets=tuple(packets),
        discarded_spans=tuple(discarded_spans),
        invalid_candidates=tuple(invalid_candidates),
    )


def decode_uart_packet(
    *,
    packet_bytes: bytes,
    packet_index: int,
    packet_start_offset: int,
) -> UartPacket:
    """Strictly decode one packet whose boundaries are already known."""
    if len(packet_bytes) < HEADER_SIZE:
        msg = "Packet is smaller than the fixed header size"
        raise PacketDecodeError(msg, code=PACKET_TOO_SMALL_ERROR)
    if not packet_bytes.startswith(MAGIC_WORD):
        msg = "Packet does not start with the mmWave magic word"
        raise PacketDecodeError(msg, code=MISSING_MAGIC_WORD_ERROR)

    header = _decode_packet_header(packet_bytes)
    if header.total_packet_length != len(packet_bytes):
        msg = (
            "Packet byte length does not match the declared total length: "
            f"{len(packet_bytes)} != {header.total_packet_length}"
        )
        raise PacketDecodeError(msg, code=PACKET_LENGTH_MISMATCH_ERROR)

    tlvs: list[UartTlv] = []
    offset = HEADER_SIZE

    for tlv_index in range(header.num_tlvs):
        if offset + TLV_HEADER_SIZE > len(packet_bytes):
            msg = f"Packet ended before TLV header {tlv_index} could be read"
            raise PacketDecodeError(msg, code=TLV_HEADER_TRUNCATED_ERROR)

        tlv_type, payload_length = struct.unpack_from(
            TLV_HEADER_FORMAT,
            packet_bytes,
            offset,
        )
        payload_start = offset + TLV_HEADER_SIZE
        payload_end = payload_start + payload_length
        if payload_end > len(packet_bytes):
            msg = (
                f"TLV {tlv_index} payload exceeds packet boundary: "
                f"{payload_end} > {len(packet_bytes)}"
            )
            raise PacketDecodeError(msg, code=TLV_PAYLOAD_OVERFLOW_ERROR)

        tlvs.append(
            UartTlv(
                tlv_index=tlv_index,
                tlv_type=tlv_type,
                payload_length=payload_length,
                header_start_offset=packet_start_offset + offset,
                payload_start_offset=packet_start_offset + payload_start,
                payload_end_offset=packet_start_offset + payload_end,
                payload=packet_bytes[payload_start:payload_end],
            ),
        )
        offset = payload_end

    return UartPacket(
        packet_index=packet_index,
        packet_start_offset=packet_start_offset,
        packet_end_offset=packet_start_offset + len(packet_bytes),
        header=header,
        tlvs=tuple(tlvs),
        padding_bytes=packet_bytes[offset:],
        raw_packet=packet_bytes,
    )


def _build_terminal_discard_span(
    *,
    start_offset: int,
    end_offset: int,
    packet_count: int,
) -> tuple[DiscardedByteSpan, ...]:
    """Return the final discarded region when no more magic words exist."""
    if start_offset >= end_offset:
        return ()

    return (
        DiscardedByteSpan(
            start_offset=start_offset,
            end_offset=end_offset,
            reason=(
                LEADING_NOISE_REASON
                if packet_count == 0
                else TRAILING_BYTES_WITHOUT_MAGIC_REASON
            ),
        ),
    )


def _read_total_packet_length(*, data: bytes, packet_start: int) -> int:
    """Read the declared total packet length from the packet header."""
    return struct.unpack_from(
        "<I",
        data,
        packet_start + MAGIC_WORD_SIZE + 4,
    )[0]


def _decode_packet_header(packet_bytes: bytes) -> UartPacketHeader:
    """Decode and validate the fixed packet header."""
    (
        version,
        total_packet_length,
        platform,
        frame_number,
        time_cpu_cycles,
        num_detected_objects,
        num_tlvs,
        sub_frame_number,
    ) = struct.unpack_from(HEADER_BODY_FORMAT, packet_bytes, MAGIC_WORD_SIZE)

    _validate_total_packet_length(total_packet_length)

    return UartPacketHeader(
        version=version,
        total_packet_length=total_packet_length,
        platform=platform,
        frame_number=frame_number,
        time_cpu_cycles=time_cpu_cycles,
        num_detected_objects=num_detected_objects,
        num_tlvs=num_tlvs,
        sub_frame_number=sub_frame_number,
    )


def _validate_total_packet_length(total_packet_length: int) -> None:
    """Reject packet lengths that cannot be valid."""
    if total_packet_length < HEADER_SIZE:
        msg = (
            "Declared total packet length is smaller than the fixed header size: "
            f"{total_packet_length} < {HEADER_SIZE}"
        )
        raise PacketDecodeError(msg, code=INVALID_TOTAL_PACKET_LENGTH_ERROR)
    if total_packet_length > MAX_PACKET_SIZE_BYTES:
        msg = (
            "Declared total packet length exceeds the configured safety limit: "
            f"{total_packet_length} > {MAX_PACKET_SIZE_BYTES}"
        )
        raise PacketDecodeError(msg, code=INVALID_TOTAL_PACKET_LENGTH_ERROR)
