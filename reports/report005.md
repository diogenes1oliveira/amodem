# Report 005: PipeWire Migration Attempt

**Date:** 2025-11-29  
**Status:** Incomplete - Requires further investigation  
**Related Plan:** plan005.md

## Objective

Convert the PulseAudio debugging utilities to use PipeWire with pw-cli and pw-dump commands directly.

## Changes Made

### Files Created

1. **amodem_duplex/debugtools/pipewire_pipe.py**
   - Created new module replacing `pulseaudio_pipe.py`
   - Classes: `PipeWirePipe` (dataclass), `PipeWirePipeManager`
   - Uses `pw-cli` for creating/destroying nodes
   - Uses `pw-dump` for listing and finding nodes (JSON output)

2. **amodem_duplex/tests/debugtools/test_pipewire_pipe.py**
   - Created test file with same structure as PulseAudio tests
   - Tests: create/list/get, delete, delete_all with pattern
   - Uses unique prefix for isolation

### Files Modified

1. **amodem_duplex/debugtools/cli.py**
   - Renamed `pa_group` → `pw_group`
   - Updated import from `pulseaudio_pipe` → `pipewire_pipe`
   - Updated all references to PipeWire terminology

2. **amodem_duplex/__main__.py**
   - Updated import: `pa_cli` → `pw_cli`
   - Updated command registration: `pa_group` → `pw_group`

3. **amodem_duplex/debugtools/__init__.py**
   - Updated exports: `PulseAudioPipe` → `PipeWirePipe`
   - Updated exports: `PulseAudioPipeManager` → `PipeWirePipeManager`
   - Updated exports: `pa_group` → `pw_group`

### Files Deleted

1. `amodem_duplex/debugtools/pulseaudio_pipe.py`
2. `amodem_duplex/tests/debugtools/test_pulseaudio_pipe.py`
3. `amodem_duplex/debugtools/tests/test_pulseaudio_pipe.py` (duplicate location)

## Technical Approach

### Node Creation Strategy

Attempted to use `pw-cli create-node` with the following approach:

```bash
pw-cli create-node adapter \
    factory.name=support.null-audio-sink \
    node.name=<sink-name> \
    node.description=<description> \
    audio.rate=<sample-rate> \
    audio.channels=<channels> \
    media.class=Audio/Sink \
    object.linger=1
```

### Node Listing Strategy

- Used `pw-dump` to get JSON output of all PipeWire objects
- Parsed JSON to extract Node objects with their properties
- Filtered by `node.name` to find specific nodes

### Node Deletion Strategy

- Used `pw-cli destroy <node-id>` to remove nodes

## Issues Encountered

### Primary Issue: Nodes Not Persisting

**Problem:** `pw-cli create-node` returns `1 = @proxy:35` (or similar) but the created nodes don't appear in:
- `pw-cli list-objects Node`
- `pw-dump` output

**Symptoms:**
- Command executes without errors
- Returns a proxy reference
- Node is not findable immediately or after delays (up to 250ms with retries)

**What Was Tried:**
1. ✗ Using `support.null-audio-sink` directly as factory name
2. ✓ Using `adapter` factory with `factory.name=support.null-audio-sink` 
3. ✓ Adding `object.linger=1` property
4. ✓ Added retry logic with delays (5 attempts, 50ms each)
5. ✗ Still nodes not appearing in pw-dump output

### Test Results

All three tests fail during fixture setup with:
```
RuntimeError: Could not find node with name 'amodem-test-<uuid>-sanity-check-speaker'
```

Even after 5 retry attempts with 50ms delays between each.

## Research Findings

### Documentation References

From PipeWire documentation:
- `pw-cli create-node` syntax: `pw-cli create-node <factory-name> [properties...]`
- Properties should be space-separated key=value pairs
- `object.linger=1` should make objects persist
- Available factories include: `adapter`, `spa-node-factory`, etc.

### Working Example

Manual test that succeeded (node appeared in list):
```bash
pw-cli create-node adapter \
    factory.name=support.null-audio-sink \
    node.name=test-adapter \
    audio.rate=16000 \
    audio.channels=1 \
    media.class=Audio/Sink \
    object.linger=1
```

However, this same pattern doesn't work consistently in the Python implementation.

## Compatibility Note

`pactl` commands work with PipeWire through a compatibility layer:
```bash
pactl load-module module-null-audio-sink sink_name=test rate=16000 channels=1
# Returns: 59 (module ID)
```

However, user reported that `pactl` fails with descriptions containing spaces, which is why pw-cli was preferred.

## Possible Root Causes

1. **Timing Issue**: Nodes may take longer to appear in pw-dump than expected
2. **Session/Connection Issue**: pw-cli might create nodes in a temporary session
3. **Missing Properties**: Some required property might not be set correctly
4. **PipeWire Version**: Behavior may vary between PipeWire versions (testing on 0.3.48)
5. **Factory Configuration**: The `support.null-audio-sink` factory may need additional setup

## Recommendations for Next Steps

1. **Investigate PipeWire Internals**
   - Check PipeWire logs: `journalctl -u pipewire --since "1 minute ago"`
   - Use `pw-mon` to watch real-time events during node creation
   - Check if `pipewire-pulse` compatibility layer is needed

2. **Alternative Approaches**
   - Use `pactl` but properly escape descriptions with spaces
   - Use `pw-loopback` module instead of null-audio-sink
   - Create nodes via PipeWire's native library bindings (e.g., via ctypes or a binding library)

3. **Testing**
   - Test on different PipeWire versions
   - Test with minimal properties to isolate the issue
   - Compare working manual commands with Python subprocess calls

4. **Fallback Options**
   - Keep using `pactl` with proper shell escaping
   - Use PipeWire's module loading instead of pw-cli create-node
   - Create a hybrid approach using both tools as appropriate

## Current State

- Code is syntactically correct and follows the expected pw-cli patterns
- All files renamed and updated consistently  
- Tests structure is correct but fail due to node creation/discovery issue
- No linter errors in implementation

## Files Status

### Ready
- CLI interface (`cli.py`)
- Main entry point (`__main__.py`)
- Module exports (`__init__.py`)

### Incomplete
- `pipewire_pipe.py` - node creation not working reliably
- `test_pipewire_pipe.py` - all tests failing due to above issue

## Conclusion

The migration from PulseAudio to PipeWire is architecturally complete but blocked by a fundamental issue with pw-cli node creation and discovery. Further investigation into PipeWire's behavior and potentially alternative implementation strategies is required before this can be functional.

