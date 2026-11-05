"""
Signal Integrity Cleaner for BrainSense streaming data.

This module implements detection and repair of data integrity issues that can
pollute downstream PSD analyses:

* NaN / Inf samples introduced during acquisition or transport
* Frozen segments where consecutive samples repeat the exact same value

Short corrupt runs are linearly interpolated while longer runs are dropped
entirely so that spectral calculations are not biased by stagnant or missing
data points. The implementation follows the time-domain hygiene guidance
described by Swinnen et al. (2025) for BrainSense streaming traces.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignalIntegrityConfig:
    """
    Configuration for `SignalIntegrityCleaner`.

    Attributes:
        enabled: Toggle the cleaner.
        max_interpolation_samples: Maximum consecutive samples that will be
            healed via interpolation. Longer runs are dropped.
        min_frozen_run_length: Minimum length (samples) of identical values to
            consider as a frozen segment.
        freeze_tolerance: Absolute tolerance when comparing samples for frozen
            detection. Useful when signals are quantized but not perfectly
            identical.
    """

    enabled: bool = True
    max_interpolation_samples: int = 50
    min_frozen_run_length: int = 5
    freeze_tolerance: float = 1e-6


class SignalIntegrityCleaner:
    """
    Detects NaNs and frozen points in streaming LFP data and repairs them.

    Usage:
        >>> cleaner = SignalIntegrityCleaner()
        >>> cleaned, stats = cleaner.clean(waveform_array, sampling_rate=250)
        >>> print(stats['total_interpolated_samples'])
    """

    def __init__(self, config: Optional[SignalIntegrityConfig] = None):
        self.config = config or SignalIntegrityConfig()

    def clean(
        self,
        data: np.ndarray,
        sampling_rate: Optional[float] = None
    ) -> Tuple[np.ndarray, Dict]:
        """
        Clean a streaming recording array.

        Args:
            data: 2D numpy array of shape (n_samples, n_channels).
            sampling_rate: Optional sampling rate (Hz) used for reporting.

        Returns:
            Tuple of:
                - np.ndarray: Cleaned waveform data (copy). May be shorter if
                  long corrupt runs were dropped.
                - Dict: Statistics describing detected segments and actions.

        Raises:
            ValueError: If input array is not 2D.
        """
        if data.ndim != 2:
            raise ValueError("SignalIntegrityCleaner expects a 2D array (samples x channels)")

        if not self.config.enabled:
            return data.copy(), {
                'enabled': False,
                'message': 'Signal integrity cleaner disabled',
                'total_interpolated_samples': 0,
                'total_dropped_samples': 0,
                'config': self.config.__dict__.copy()
            }

        n_samples, n_channels = data.shape
        cleaned = data.astype(float, copy=True)

        max_interp = max(0, int(self.config.max_interpolation_samples))
        min_frozen = max(2, int(self.config.min_frozen_run_length))
        tolerance = max(0.0, float(self.config.freeze_tolerance))

        stats: Dict = {
            'enabled': True,
            'sampling_rate_hz': sampling_rate,
            'total_interpolated_segments': 0,
            'total_interpolated_samples': 0,
            'total_dropped_segments': 0,
            'total_dropped_samples': 0,
            'channels': [],
            'dropped_intervals': [],
            'config': self.config.__dict__.copy()
        }

        global_drop_segments: List[Tuple[int, int]] = []

        for ch_idx in range(n_channels):
            channel = cleaned[:, ch_idx]
            channel_stats = {
                'channel_index': ch_idx,
                'nan_segments_found': 0,
                'frozen_segments_found': 0,
                'interpolated_segments': [],
                'dropped_segments': []
            }

            nan_segments = self._find_segments(np.logical_not(np.isfinite(channel)))
            if nan_segments:
                channel_stats['nan_segments_found'] = len(nan_segments)

            frozen_segments = self._find_frozen_segments(
                channel,
                min_length=min_frozen,
                tolerance=tolerance,
                invalid_mask=np.logical_not(np.isfinite(channel))
            )
            if frozen_segments:
                channel_stats['frozen_segments_found'] = len(frozen_segments)

            for seg_type, segments in (('nan', nan_segments), ('frozen', frozen_segments)):
                for start, end in segments:
                    length = end - start + 1

                    # Skip segments that already overlap a planned drop
                    if any(self._segment_overlaps_pair(start, end, s, e) for s, e in global_drop_segments):
                        continue

                    can_interpolate = (
                        length <= max_interp and
                        self._has_valid_neighbor(channel, start, direction=-1) and
                        self._has_valid_neighbor(channel, end, direction=1)
                    )

                    if can_interpolate:
                        success = self._interpolate_segment(channel, start, end)
                        if success:
                            stats['total_interpolated_segments'] += 1
                            stats['total_interpolated_samples'] += length
                            channel_stats['interpolated_segments'].append({
                                'type': seg_type,
                                'start': start,
                                'end': end,
                                'length': length
                            })
                            continue

                    # Fallback: drop the segment
                    global_drop_segments.append((start, end))
                    stats['total_dropped_segments'] += 1
                    stats['total_dropped_samples'] += length
                    channel_stats['dropped_segments'].append({
                        'type': seg_type,
                        'start': start,
                        'end': end,
                        'length': length
                    })

            stats['channels'].append(channel_stats)

        merged_drops = self._merge_segments(global_drop_segments)
        if merged_drops:
            drop_mask = np.zeros(n_samples, dtype=bool)
            for start, end in merged_drops:
                drop_mask[start:end + 1] = True
            cleaned = cleaned[~drop_mask]
            stats['dropped_intervals'] = [
                {
                    'start': start,
                    'end': end,
                    'length': end - start + 1,
                    'duration_seconds': self._samples_to_seconds(end - start + 1, sampling_rate)
                }
                for start, end in merged_drops
            ]

        return cleaned, stats

    @staticmethod
    def _find_segments(mask: np.ndarray) -> List[Tuple[int, int]]:
        """Return (start, end) tuples for contiguous True regions in mask."""
        segments: List[Tuple[int, int]] = []
        if mask.ndim != 1:
            raise ValueError("Mask must be 1D")

        indices = np.flatnonzero(mask)
        if indices.size == 0:
            return segments

        start = indices[0]
        prev = indices[0]
        for idx in indices[1:]:
            if idx != prev + 1:
                segments.append((start, prev))
                start = idx
            prev = idx
        segments.append((start, prev))
        return segments

    @classmethod
    def _find_frozen_segments(
        cls,
        channel: np.ndarray,
        min_length: int,
        tolerance: float,
        invalid_mask: np.ndarray
    ) -> List[Tuple[int, int]]:
        """Identify contiguous runs of identical values."""
        segments: List[Tuple[int, int]] = []
        n_samples = channel.shape[0]

        start: Optional[int] = None
        prev_value: Optional[float] = None

        for idx in range(n_samples):
            if invalid_mask[idx]:
                if start is not None:
                    if idx - start >= min_length:
                        segments.append((start, idx - 1))
                    start = None
                    prev_value = None
                continue

            value = channel[idx]

            if start is None:
                start = idx
                prev_value = value
                continue

            if np.isclose(value, prev_value, atol=tolerance):
                prev_value = value
            else:
                if idx - start >= min_length:
                    segments.append((start, idx - 1))
                start = idx
                prev_value = value

        if start is not None and n_samples - start >= min_length:
            segments.append((start, n_samples - 1))

        filtered_segments = []
        for start_idx, end_idx in segments:
            if invalid_mask[start_idx:end_idx + 1].any():
                continue
            filtered_segments.append((start_idx, end_idx))
        return filtered_segments

    @staticmethod
    def _segment_overlaps_pair(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
        """Check if two inclusive ranges overlap."""
        return not (a_end < b_start or b_end < a_start)

    @staticmethod
    def _has_valid_neighbor(
        channel: np.ndarray,
        index: int,
        direction: int
    ) -> bool:
        """Return True if a finite neighbor exists in the given direction."""
        step = -1 if direction < 0 else 1
        idx = index
        n_samples = channel.shape[0]

        while 0 <= idx < n_samples:
            current = channel[idx]
            if np.isfinite(current):
                return True
            idx += step
        return False

    @staticmethod
    def _interpolate_segment(
        channel: np.ndarray,
        start: int,
        end: int
    ) -> bool:
        """Linearly interpolate values between finite neighbors."""
        left_idx = SignalIntegrityCleaner._find_neighbor_index(channel, start - 1, -1)
        right_idx = SignalIntegrityCleaner._find_neighbor_index(channel, end + 1, 1)

        if left_idx is None or right_idx is None or left_idx == right_idx:
            return False

        left_val = channel[left_idx]
        right_val = channel[right_idx]
        if not (np.isfinite(left_val) and np.isfinite(right_val)):
            return False

        segment_indices = np.arange(start, end + 1, dtype=float)
        xp = np.array([left_idx, right_idx], dtype=float)
        fp = np.array([left_val, right_val], dtype=float)

        channel[start:end + 1] = np.interp(segment_indices, xp, fp)
        return True

    @staticmethod
    def _find_neighbor_index(
        channel: np.ndarray,
        start_idx: int,
        step: int
    ) -> Optional[int]:
        """Find first finite sample walking in the given direction."""
        idx = start_idx
        n_samples = channel.shape[0]
        while 0 <= idx < n_samples:
            if np.isfinite(channel[idx]):
                return idx
            idx += step
        return None

    @staticmethod
    def _merge_segments(segments: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """Merge overlapping inclusive segments."""
        sorted_segments = sorted(segments)
        if not sorted_segments:
            return []

        merged: List[Tuple[int, int]] = []
        current_start, current_end = sorted_segments[0]

        for start, end in sorted_segments[1:]:
            if start <= current_end + 1:
                current_end = max(current_end, end)
            else:
                merged.append((current_start, current_end))
                current_start, current_end = start, end

        merged.append((current_start, current_end))
        return merged

    @staticmethod
    def _samples_to_seconds(length: int, sampling_rate: Optional[float]) -> Optional[float]:
        if sampling_rate and sampling_rate > 0:
            return float(length) / float(sampling_rate)
        return None
