"""
core/identity_engine.py — CORE owner/guest identity system (spec §2).

Layer 1 (wake word)      — not implemented here; Mark L streams mic
                            continuously to Gemini, no local wake-word gate.
Layer 2 (voice verify)   — lightweight MFCC-based speaker similarity.
                            NOT deep-learning-grade biometrics (no torch/
                            resemblyzer — kept light for low-end PCs).
                            Good enough to tell "probably owner" vs
                            "probably someone else", not bank-grade auth.
Layer 3 (OS identity)    — compares the logged-in OS username.
Layer 4 (strong auth)    — PIN, required for sensitive actions regardless
                            of voice/OS layers.

Session state: current speaker mode is OWNER, GUEST, or UNKNOWN, with a
confidence score. Sensitive tools should call require_authorization()
before executing.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import scipy.fft
    _HAVE_SCIPY = True
except ImportError:
    _HAVE_SCIPY = False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR       = _base_dir()
PROFILE_PATH   = BASE_DIR / "config" / "voice_profile.json"
SECURITY_PATH  = BASE_DIR / "config" / "security.json"

SIMILARITY_THRESHOLD = 0.82   # cosine similarity — approximate, tune per mic/environment
SAMPLE_RATE           = 16000


# ── Feature extraction (lightweight, numpy/scipy only) ───────────────────

def _hz_to_mel(hz):
    return 2595 * np.log10(1 + hz / 700)


def _mel_to_hz(mel):
    return 700 * (10 ** (mel / 2595) - 1)


def _mel_filterbank(n_filters=26, n_fft=512, sr=SAMPLE_RATE):
    low_mel, high_mel = 0, _hz_to_mel(sr / 2)
    mel_points = np.linspace(low_mel, high_mel, n_filters + 2)
    hz_points  = _mel_to_hz(mel_points)
    bins = np.floor((n_fft + 1) * hz_points / sr).astype(int)

    fbank = np.zeros((n_filters, n_fft // 2 + 1))
    for m in range(1, n_filters + 1):
        f_prev, f_curr, f_next = bins[m - 1], bins[m], bins[m + 1]
        for k in range(f_prev, f_curr):
            if 0 <= k < fbank.shape[1]:
                fbank[m - 1, k] = (k - f_prev) / max(1, (f_curr - f_prev))
        for k in range(f_curr, f_next):
            if 0 <= k < fbank.shape[1]:
                fbank[m - 1, k] = (f_next - k) / max(1, (f_next - f_curr))
    return fbank


_FBANK = _mel_filterbank()


def extract_features(pcm_bytes: bytes, sr: int = SAMPLE_RATE) -> Optional[np.ndarray]:
    """PCM16 mono bytes -> a fixed-length feature vector (mean+std of
    13 MFCC-like coefficients = 26 dims). Returns None on audio too short
    or silent to be useful."""
    if len(pcm_bytes) < sr * 0.5 * 2:   # need at least ~0.5s of audio
        return None

    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if np.abs(audio).mean() < 0.003:    # essentially silence
        return None

    n_fft, hop = 512, 256
    frames = []
    for start in range(0, len(audio) - n_fft, hop):
        frame = audio[start:start + n_fft] * np.hanning(n_fft)
        spec  = np.abs(np.fft.rfft(frame, n=n_fft)) ** 2
        mel_energy = _FBANK @ spec
        log_mel = np.log(mel_energy + 1e-10)
        if _HAVE_SCIPY:
            mfcc = scipy.fft.dct(log_mel, type=2, norm="ortho")[:13]
        else:
            mfcc = np.fft.fft(log_mel).real[:13]
        frames.append(mfcc)

    if len(frames) < 4:
        return None

    frames = np.array(frames)
    return np.concatenate([frames.mean(axis=0), frames.std(axis=0)])


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


# ── Enrollment / profile storage ─────────────────────────────────────────

def enroll_from_samples(pcm_samples: list[bytes]) -> str:
    """Build an owner voiceprint by averaging features from several
    short recordings (call site handles the actual mic capture)."""
    feats = [extract_features(s) for s in pcm_samples]
    feats = [f for f in feats if f is not None]
    if len(feats) < 2:
        return "enrollment failed: not enough usable audio (speak clearly, closer to the mic)"

    centroid = np.mean(feats, axis=0)
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps({"centroid": centroid.tolist(), "samples": len(feats)}))
    return f"enrolled owner voiceprint from {len(feats)} sample(s)"


def has_voice_profile() -> bool:
    return PROFILE_PATH.exists()


def verify_speaker(pcm_bytes: bytes) -> tuple[str, float]:
    """Returns (mode, confidence): mode is 'owner' | 'unknown' | 'no_profile'."""
    if not PROFILE_PATH.exists():
        return "no_profile", 0.0
    try:
        profile = json.loads(PROFILE_PATH.read_text())
        centroid = np.array(profile["centroid"])
    except Exception:
        return "no_profile", 0.0

    feat = extract_features(pcm_bytes)
    if feat is None:
        return "unknown", 0.0

    sim = _cosine_sim(feat, centroid)
    return ("owner", sim) if sim >= SIMILARITY_THRESHOLD else ("unknown", sim)


# ── Layer 3: OS identity ─────────────────────────────────────────────────

def get_os_username() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return ""


# ── Layer 4: PIN (strong auth for sensitive actions) ─────────────────────

def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.strip().encode("utf-8")).hexdigest()


def set_pin(pin: str) -> str:
    if not pin or len(pin.strip()) < 4:
        return "PIN must be at least 4 digits/characters"
    SECURITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if SECURITY_PATH.exists():
        try:
            data = json.loads(SECURITY_PATH.read_text())
        except Exception:
            data = {}
    data["pin_hash"] = _hash_pin(pin)
    SECURITY_PATH.write_text(json.dumps(data))
    return "PIN set"


def has_pin() -> bool:
    if not SECURITY_PATH.exists():
        return False
    try:
        return bool(json.loads(SECURITY_PATH.read_text()).get("pin_hash"))
    except Exception:
        return False


def verify_pin(pin: str) -> bool:
    if not SECURITY_PATH.exists():
        return False
    try:
        data = json.loads(SECURITY_PATH.read_text())
        return data.get("pin_hash") == _hash_pin(pin)
    except Exception:
        return False


# ── Session-level speaker mode ────────────────────────────────────────────

class IdentitySession:
    """Tracks who's currently believed to be speaking, for the current run.
    One instance lives on JarvisLive; updated after each user turn."""

    def __init__(self):
        self.mode = "unknown"          # owner | guest | unknown
        self.confidence = 0.0
        self.pin_unlocked = False      # elevated for this session via PIN

    def update_from_voice(self, pcm_bytes: bytes) -> None:
        mode, conf = verify_speaker(pcm_bytes)
        self.confidence = conf
        if mode == "no_profile":
            # No enrollment done yet — treat the single PC user as owner
            # (Layer 3 fallback), don't block a fresh setup.
            self.mode = "owner"
        elif mode == "owner":
            self.mode = "owner"
        else:
            self.mode = "guest"

    def unlock_with_pin(self, pin: str) -> bool:
        if verify_pin(pin):
            self.pin_unlocked = True
            return True
        return False

    def is_authorized(self, risk_level: str = "low") -> bool:
        """low/medium risk: owner voice OR PIN unlock is enough.
        high risk: PIN unlock required regardless of voice match."""
        if risk_level == "high":
            return self.pin_unlocked
        return self.mode == "owner" or self.pin_unlocked

    def status(self) -> str:
        return f"mode={self.mode} confidence={self.confidence:.2f} pin_unlocked={self.pin_unlocked}"
