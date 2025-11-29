"""Preamble generation helper for streaming modem."""

import numpy as np
import numpy.typing as npt

import amodem.config
import amodem.equalizer


def generate_preamble_pcm(config: amodem.config.Configuration) -> npt.NDArray[np.float64]:
    """Generate the exact preamble PCM sequence.

    This produces the same PCM output that amodem.send.Sender.start() emits,
    which consists of:
    - Carrier prefix (pilot tone pattern from equalizer.prefix)
    - Training symbols (equalizer.equalizer_length symbols)
    - Silence padding around training

    Note: This does NOT include the initial silence_start padding, which
    is handled separately by the caller.

    Args:
        config: amodem configuration object with Fs, symbols, carriers, etc.

    Returns:
        PCM samples as numpy array (float64, normalized to [-1, 1] * gain)
    """
    # Create components matching amodem.send.Sender.start()
    components = []

    # 1. Carrier prefix (pilot tone on/off pattern)
    # The pilot is complex but needs to be real for PCM output
    pilot = config.carriers[config.carrier_index]
    for value in amodem.equalizer.prefix:
        # Each prefix value multiplies the pilot carrier and takes the real part
        samples = (pilot * value).real
        components.append(samples)

    # 2. Training sequence with silence padding
    equalizer_obj = amodem.equalizer.Equalizer(config)
    train_symbols = equalizer_obj.train_symbols(amodem.equalizer.equalizer_length)
    train_signal = equalizer_obj.modulator(train_symbols)

    silence_samples = np.zeros(amodem.equalizer.silence_length * config.Nsym)
    components.append(silence_samples)
    components.append(train_signal)
    components.append(silence_samples)

    # Concatenate all components
    preamble_pcm = np.concatenate(components)

    # Ensure it's real-valued float64 (matching what Sender outputs)
    result: npt.NDArray[np.float64] = preamble_pcm.real.astype(np.float64)
    return result


def get_preamble_duration(config: amodem.config.Configuration) -> float:
    """Calculate the duration of the preamble in seconds.

    Args:
        config: amodem configuration object

    Returns:
        Duration in seconds (float)
    """
    pcm = generate_preamble_pcm(config)
    return len(pcm) / config.Fs
