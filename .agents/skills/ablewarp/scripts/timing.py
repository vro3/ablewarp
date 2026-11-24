from pathlib import Path

import numpy as np
from batch_warp import audio_features, estimate_tempo, FRAME, RATE, STEP

def fixed_grid(times, median_bpm, candidates):
    centers = [median_bpm, *(c["bpm"] for c in candidates if abs(c["bpm"] / median_bpm - 1) < .045)]
    rates = np.unique(np.round(np.concatenate([np.arange(s - .65, s + .65, .01) for s in centers]), 2))
    scores = np.abs(np.exp(2j * np.pi * np.outer(rates / 60, times)).mean(axis=1))
    best = rates[scores.argmax()]
    period = 60 / best
    phase = np.angle(np.exp(2j * np.pi * times / period).mean()) * period / (2 * np.pi)
    positions = np.rint((times - phase) / period).astype(int)
    good = abs(times - (phase + period * positions)) < .07
    if good.sum() > 20:
        period, phase = np.polyfit(positions[good], times[good], 1)
    return period, phase

def attacks_near(attacks, times, radius=.045):
    offsets = np.arange(-round(radius / STEP), round(radius / STEP) + 1)
    center = np.rint((times - FRAME / (2 * RATE)) / STEP).astype(int)
    bins = np.clip(center[:,None] + offsets, 0, len(attacks) - 1)
    strength = attacks[bins]
    peaks = bins[np.arange(len(times)), strength.argmax(axis=1)]
    return peaks * STEP + FRAME / (2 * RATE) - times, attacks[peaks]

def plan(data):
    times = np.array(data["beats"])
    down = np.array(data["downbeats"])
    if len(times) < 16 or len(down) < 4:
        raise ValueError('Too few confidently detected beats or downbeats for a full track.')
    duration, attacks = audio_features(Path(data["source"]))
    candidates = estimate_tempo(attacks)
    period, phase = fixed_grid(times, 60 / np.median(np.diff(times)), candidates)
    nominal = round(60 / period, 2)
    indices = np.rint((times - phase) / period).astype(int)
    fixed_error = abs(times - (phase + period * indices))
    close = fixed_error < .085
    fixed_fraction = np.mean(close)
    fixed = fixed_fraction >= .83
    if not fixed:
        period = float(np.median(np.diff(times)))
        keep = np.r_[True, np.diff(times) > period * .50]
        times = times[keep]
        indices = np.r_[0, np.cumsum(np.maximum(1, np.rint(np.diff(times) / period).astype(int)))]
        close = np.ones(len(times), dtype=bool)
        nominal = round(60 / np.median(np.diff(times)[np.diff(indices) == 1]), 2)
    down_idx = np.clip(np.searchsorted(times, down), 1, len(times) - 1)
    use_prev = abs(times[down_idx - 1] - down) < abs(times[down_idx] - down)
    down_idx -= use_prev
    down_idx = np.unique(down_idx[(abs(times[down_idx] - down) < .06) & close[down_idx]])
    votes = np.bincount(indices[down_idx] % 4, minlength=4)
    bar_class = votes.argmax()
    confidence = votes.max() / max(1, votes.sum())
    if fixed:
        clock = phase + period * indices
        off, strength = attacks_near(attacks, clock[close], .035)
        strong = strength >= .8
        if strong.sum() >= 16:
            phase += float(np.median(off[strong]))
        elapsed_grid = (times - phase) / period
        bar_zero = bar_class + 4 * np.floor((-phase / period - bar_class) / 4)
        start_beat = -phase / period - bar_zero
        first_bar = phase + (bar_zero + 4) * period
        first = float(first_bar)
        if start_beat * period < .028:
            start_beat = 0.
        elif first_bar < .028:
            start_beat = 0.
            bar_zero += 4
            first += 4 * period
        # Use a phase-correct full-file grid. Fractional clip start is retained.
        end_beat = float((duration - phase) / period - bar_zero)
        anchors_b = np.arange(4, end_beat, 32, dtype=float)
        if len(anchors_b) < 2:
            anchors_b = np.linspace(4, end_beat, 3, endpoint=False)
        anchors_s = phase + (anchors_b + bar_zero) * period
        anchor_b = np.r_[start_beat, anchors_b, end_beat]
        anchor_s = np.r_[0., anchors_s, duration]
        # If sample start is close to the projected downbeat, remove the sub-28 ms offset
        # over the intro bar. Otherwise keep the actual pickup phase.
        expected = np.interp(indices - bar_zero, anchor_b, anchor_s)
        use = close & (indices - bar_zero >= anchors_b[0]) & (indices - bar_zero < end_beat)
        test_beats = indices[use] - bar_zero
    else:
        # Keep the earliest supported downbeat after projecting the pickup on the local grid.
        head = int(down_idx[0]) if len(down_idx) else 0
        bar_class = indices[head] % 4
        matched = np.flatnonzero(indices % 4 == bar_class)
        if not len(matched):
            matched = np.array([0])
        start_project = indices[head] - times[head] / period
        bar_zero = bar_class + 4 * np.floor((start_project - bar_class) / 4)
        start_beat = float(start_project - bar_zero)
        if start_beat * period < .028:
            start_beat = 0.
        if (4 - start_beat) * period < .028:
            start_beat = 0.
            bar_zero += 4
        eligible = matched[(indices[matched] - bar_zero > start_beat + .35) & (times[matched] > .12)]
        if not len(eligible):
            eligible = np.array([head])
        selected = eligible[::2]
        if selected[-1] != eligible[-1]:
            selected = np.r_[selected, eligible[-1]]
        a = times[selected]
        offset, strength = attacks_near(attacks, a, .030)
        anchor_s = np.r_[0., a + np.where(strength >= 1.0, offset, 0), duration]
        anchor_b = np.r_[start_beat, indices[selected] - bar_zero,
                         indices[selected[-1]] - bar_zero + (duration - anchor_s[-2]) / period]
        end_beat = float(anchor_b[-1])
        first = float(anchor_s[1])
        expected = np.interp(indices - bar_zero, anchor_b, anchor_s)
        use = (indices - bar_zero > anchor_b[1]) & (indices - bar_zero < anchor_b[-2])
        use[selected] = False
        test_beats = indices[use] - bar_zero
    phase_error = abs(times[use] - expected[use])
    if len(phase_error) < 8:
        raise ValueError("Too few beats available for a timing cross-check.")
    onset_offset, onset_strength = attacks_near(attacks, expected[use], .055)
    usable = onset_strength >= .85
    durations = np.diff(anchor_s) / np.diff(anchor_b)
    if not (np.diff(anchor_s) > 0).all() or not (np.diff(anchor_b) > 0).all():
        raise ValueError(data["source"])
    flags = []
    if not fixed:
        flags.append("tempo or phase varies")
    if fixed and fixed_fraction < .94:
        flags.append("sections disagree with the steady grid")
    if confidence < .88:
        flags.append("ambiguous bar phase")
    if np.mean(phase_error > .04) > .12:
        flags.append("some beats miss grid")
    if usable.sum() < 35 or (usable.any() and np.median(abs(onset_offset[usable])) > .018):
        flags.append("weak transient confirmation")
    max_stretch = float(np.max(abs(durations * nominal / 60 - 1)))
    if max_stretch > .05:
        flags.append("local timing adjustment exceeds 5%")
    return {"audio": data["source"], "duration": duration, "bpm": nominal, "fixed": bool(fixed),
            "fixed_fraction": round(float(fixed_fraction), 3), "bar_agreement": round(float(confidence), 3),
            "bpm_signal": candidates[0]["bpm"], "start_beat": float(start_beat), "first_anchor_s": first,
            "anchors": np.column_stack((anchor_s, anchor_b)).tolist(),
            "beat_median_ms": round(float(np.median(phase_error)) * 1000, 1),
            "beat_p90_ms": round(float(np.quantile(phase_error, .9)) * 1000, 1),
            "attack_median_ms": round(float(np.median(abs(onset_offset[usable]))) * 1000, 1) if usable.any() else None,
            "stretch_pct": round(max_stretch * 100, 2),
            "flags": flags}
