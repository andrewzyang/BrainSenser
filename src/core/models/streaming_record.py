"""
StreamingRecord data model for BrainSense streaming waveforms.

This module defines the StreamingRecord dataclass representing continuous
waveform data from IndefiniteStreaming or DefiniteStreaming sections of
BrainSense JSON files. Used by StreamingRepository for batch insertion with deduplication.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class StreamingRecord:
    """
    BrainSense streaming waveform record (continuous LFP data).

    Represents a continuous streaming session with:
    - Timestamp and channel information
    - Waveform data (array of voltage samples)
    - Sample rate and timing metadata
    - Packet reconstruction information
    - Data hash for deduplication

    The data_hash field is calculated by DeduplicationEngine using:
        SHA256(timestamp + channel + waveform_data)

    Attributes:
        timestamp: ISO format timestamp (TEXT in STRICT mode) - FirstPacketDateTime
        unix_timestamp: Unix epoch timestamp (REAL)
        channel: Channel identifier (ZERO_THREE_LEFT, ONE_TWO_RIGHT, etc)
        hemisphere: LEFT or RIGHT (derived from channel)
        waveform_data: JSON array string of voltage samples (large!)
        sample_count: Number of samples in waveform
        sample_rate: SampleRateInHz (typically 250 Hz)
        duration_seconds: Calculated duration of waveform
        gain: Gain value for amplitude conversion
        global_sequences: Comma-separated packet sequence numbers
        global_packet_sizes: Comma-separated packet sizes
        ticks_in_mses: Comma-separated timing ticks in milliseconds
        pass_info: Pass field from JSON
        source_file: Which uploaded file this came from (TEXT)
        session_id: Session identifier (TEXT)
        data_hash: SHA256 hash for deduplication (TEXT, UNIQUE)
        streaming_type: "indefinite" or "definite"

    Example:
        >>> import json
        >>> from datetime import datetime
        >>> record = StreamingRecord(
        ...     timestamp=datetime.now(),
        ...     channel="ZERO_THREE_LEFT",
        ...     hemisphere="LEFT",
        ...     waveform_data=json.dumps([20.4, 20.1, 20.0, ...]),
        ...     sample_count=3563,
        ...     sample_rate=250,
        ...     duration_seconds=14.252,
        ...     gain=228,
        ...     source_file="session_2024.json",
        ...     data_hash="abc123...",
        ...     streaming_type="indefinite"
        ... )
    """

    # Timing (required)
    timestamp: datetime
    unix_timestamp: Optional[float] = None

    # Channel information (required)
    channel: str = ""
    hemisphere: Optional[str] = None  # LEFT, RIGHT (derived from channel)

    # Waveform data (required)
    waveform_data: str = ""  # JSON array of voltage samples
    sample_count: int = 0
    sample_rate: int = 0  # Hz
    duration_seconds: Optional[float] = None

    # Signal processing (optional)
    gain: Optional[int] = None

    # Packet reconstruction metadata (optional)
    global_sequences: Optional[str] = None  # Comma-separated
    global_packet_sizes: Optional[str] = None  # Comma-separated
    ticks_in_mses: Optional[str] = None  # Comma-separated
    pass_info: Optional[str] = None

    # Metadata (required)
    source_file: str = ""
    session_id: Optional[str] = None

    # Deduplication (required)
    data_hash: str = ""

    # Streaming type (required)
    streaming_type: str = "indefinite"  # "indefinite" or "definite"

    @property
    def is_indefinite(self) -> bool:
        """Whether this is indefinite streaming data."""
        return self.streaming_type == "indefinite"

    @property
    def is_definite(self) -> bool:
        """Whether this is definite streaming data."""
        return self.streaming_type == "definite"

    @property
    def is_left_hemisphere(self) -> bool:
        """Whether this waveform is from left hemisphere."""
        return self.hemisphere == "LEFT" or "LEFT" in self.channel

    @property
    def is_right_hemisphere(self) -> bool:
        """Whether this waveform is from right hemisphere."""
        return self.hemisphere == "RIGHT" or "RIGHT" in self.channel
