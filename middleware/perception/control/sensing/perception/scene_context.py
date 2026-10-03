"""Subject: scene-context profiles and their fail-conservative selection.

A learned scene is configuration, not authority (D-162 candidate): profiles
are registered offline with explicit revisions, the context set is closed,
every lookup fails closed on an unknown id, and classification falls back
to the generic profile after sustained misses. Contexts tune perception
only; they never grant motion authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .road import RoadObservation, RoadPerceptionConfig

GENERIC_CONTEXT_ID = "generic"
GENERIC_PROFILE_REVISION = "ctx-generic-v1"

# The context set is closed on purpose: a new situation needs a registered
# profile first, so classification can never invent an unconfigured scene.
KNOWN_CONTEXT_IDS = (
    GENERIC_CONTEXT_ID,
    "lane_follow",
    "stop_line",
    "crosswalk",
)


@dataclass(frozen=True)
class SceneContextProfile:
    """Explicit full perception parameter set bound to one scene context.

    Profiles record every field instead of a diff, so a profile never
    depends on which defaults happened to ship with the binary.
    """

    context_id: str
    profile_revision: str
    bright_threshold: int = 180
    lane_roi_top_fraction: float = 0.30
    horizontal_min_fraction: float = 0.40
    horizontal_padding_px: int = 2
    crosswalk_min_bars: int = 3
    crosswalk_max_gap_px: int = 20
    signal_roi_bottom_fraction: float = 0.35
    signal_min_pixels: int = 50

    def __post_init__(self) -> None:
        for name in ("context_id", "profile_revision"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if isinstance(self.bright_threshold, bool) \
                or not isinstance(self.bright_threshold, int) \
                or not 1 <= self.bright_threshold <= 254:
            raise ValueError("bright_threshold must be an int in [1, 254]")
        for name in ("lane_roi_top_fraction", "horizontal_min_fraction",
                     "signal_roi_bottom_fraction"):
            value = getattr(self, name)
            if (isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or not 0.0 < float(value) <= 1.0):
                raise ValueError(f"{name} must be finite in (0.0, 1.0]")
        for name in ("horizontal_padding_px", "crosswalk_max_gap_px"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) \
                    or value < 0:
                raise ValueError(f"{name} must be a non-negative int")
        if isinstance(self.crosswalk_min_bars, bool) \
                or not isinstance(self.crosswalk_min_bars, int) \
                or self.crosswalk_min_bars < 1:
            raise ValueError("crosswalk_min_bars must be an int >= 1")
        if isinstance(self.signal_min_pixels, bool) \
                or not isinstance(self.signal_min_pixels, int) \
                or self.signal_min_pixels < 1:
            raise ValueError("signal_min_pixels must be an int >= 1")

    def perception_config(self) -> RoadPerceptionConfig:
        """The exact detection config this profile applies."""
        return RoadPerceptionConfig(
            bright_threshold=self.bright_threshold,
            lane_roi_top_fraction=self.lane_roi_top_fraction,
            horizontal_min_fraction=self.horizontal_min_fraction,
            horizontal_padding_px=self.horizontal_padding_px,
            crosswalk_min_bars=self.crosswalk_min_bars,
            crosswalk_max_gap_px=self.crosswalk_max_gap_px,
            signal_roi_bottom_fraction=self.signal_roi_bottom_fraction,
            signal_min_pixels=self.signal_min_pixels,
        )


def generic_scene_context_profile() -> SceneContextProfile:
    """The always-safe profile used wherever no scene matched."""
    return SceneContextProfile(
        context_id=GENERIC_CONTEXT_ID,
        profile_revision=GENERIC_PROFILE_REVISION,
    )


def default_scene_context_store() -> SceneContextStore:
    """The v0 site-neutral store.

    Profile values intentionally equal the generic profile until DEVICE
    evidence justifies scene-specific tuning (D-162); identity and revision
    are what the mechanism proves first.
    """
    neutral = (
        ("lane_follow", "ctx-lane-v1"),
        ("stop_line", "ctx-stop-v1"),
        ("crosswalk", "ctx-crosswalk-v1"),
    )
    return SceneContextStore([
        generic_scene_context_profile(),
        *(
            SceneContextProfile(context_id=cid, profile_revision=rev)
            for cid, rev in neutral
        ),
    ])


class SceneContextStore:
    """Revision-bound profile registry; lookups fail closed."""

    def __init__(self, profiles) -> None:
        by_id: dict[str, SceneContextProfile] = {}
        revisions: set[str] = set()
        for profile in profiles:
            if not isinstance(profile, SceneContextProfile):
                raise ValueError("scene context store requires profiles")
            if profile.context_id not in KNOWN_CONTEXT_IDS:
                raise ValueError(
                    f"unknown scene context id {profile.context_id!r}")
            if profile.context_id in by_id:
                raise ValueError(
                    f"duplicate scene context id {profile.context_id!r}")
            if profile.profile_revision in revisions:
                raise ValueError(
                    "duplicate scene context profile revision "
                    f"{profile.profile_revision!r}")
            by_id[profile.context_id] = profile
            revisions.add(profile.profile_revision)
        if GENERIC_CONTEXT_ID not in by_id:
            raise ValueError("scene context store requires a generic profile")
        self._by_id = by_id

    def profile(self, context_id: str) -> SceneContextProfile:
        try:
            return self._by_id[context_id]
        except KeyError:
            raise KeyError(
                f"unregistered scene context {context_id!r}") from None

    @property
    def generic(self) -> SceneContextProfile:
        return self._by_id[GENERIC_CONTEXT_ID]


@dataclass(frozen=True)
class SceneContext:
    """One evidence item describing the selected scene context."""

    context_id: str
    confidence: float
    profile_revision: str


class SceneContextMatcher:
    """Classifies the road evidence stream into a stable scene context.

    L0 authored rules, no learning on device: crosswalk outranks a bare
    stop line, which outranks bare lane following. A candidate context must
    win enter_frames consecutive confirmations before switching, the
    current context must miss exit_frames consecutive frames before
    falling back to generic, and a signal-conflict frame freezes both
    counters — contradictory evidence must never steer the switch.
    """

    def __init__(self, store: SceneContextStore, *, enter_frames: int = 3,
                 exit_frames: int = 8, min_confidence: float = 0.5) -> None:
        for name, value in (("enter_frames", enter_frames),
                            ("exit_frames", exit_frames)):
            if isinstance(value, bool) or not isinstance(value, int) \
                    or value < 1:
                raise ValueError(f"{name} must be an int >= 1")
        if isinstance(min_confidence, bool) \
                or not isinstance(min_confidence, (int, float)) \
                or not math.isfinite(float(min_confidence)) \
                or not 0.0 <= float(min_confidence) <= 1.0:
            raise ValueError("min_confidence must be finite in [0.0, 1.0]")
        self._store = store
        self._enter_frames = int(enter_frames)
        self._exit_frames = int(exit_frames)
        self._min_confidence = float(min_confidence)
        self._context_id = store.generic.context_id
        self._confidence = 0.0
        self._pending_id: str | None = None
        self._pending_count = 0
        self._miss_count = 0

    @property
    def context_id(self) -> str:
        return self._context_id

    def reset(self) -> None:
        """Drop the stream state (session discard), back to generic."""
        self._context_id = self._store.generic.context_id
        self._confidence = 0.0
        self._pending_id = None
        self._pending_count = 0
        self._miss_count = 0

    def update(self, observation: RoadObservation) -> SceneContext:
        if not isinstance(observation, RoadObservation):
            raise ValueError("scene context requires a RoadObservation")
        candidate, confidence = self._classify(observation)
        if observation.signal_conflict:
            # Contradictory signal evidence: hold and forget both counters.
            self._pending_id = None
            self._pending_count = 0
            self._miss_count = 0
        elif candidate == self._context_id:
            self._pending_id = None
            self._pending_count = 0
            self._miss_count = 0
            self._confidence = confidence
        elif candidate is not None:
            # A different context must prove itself before it is trusted.
            if candidate == self._pending_id:
                self._pending_count += 1
            else:
                self._pending_id = candidate
                self._pending_count = 1
            self._miss_count = 0
            if self._pending_count >= self._enter_frames:
                self._context_id = candidate
                self._confidence = confidence
                self._pending_id = None
                self._pending_count = 0
        else:
            self._pending_id = None
            self._pending_count = 0
            if self._context_id != GENERIC_CONTEXT_ID:
                # Missing evidence must persist before the generic profile
                # returns; a single dark frame must not flap parameters.
                self._miss_count += 1
                if self._miss_count >= self._exit_frames:
                    self._context_id = GENERIC_CONTEXT_ID
                    self._confidence = 0.0
                    self._miss_count = 0
        return self.scene()

    def scene(self) -> SceneContext:
        profile = self._store.profile(self._context_id)
        return SceneContext(
            context_id=self._context_id,
            confidence=self._confidence,
            profile_revision=profile.profile_revision,
        )

    def _classify(self, observation: RoadObservation):
        checks = (
            (observation.crosswalk, "crosswalk"),
            (observation.stop_line, "stop_line"),
            (observation.lane, "lane_follow"),
        )
        for observed, context_id in checks:
            if observed is None:
                continue
            confidence = float(observed.confidence)
            if confidence >= self._min_confidence:
                return context_id, confidence
        return None, 0.0
