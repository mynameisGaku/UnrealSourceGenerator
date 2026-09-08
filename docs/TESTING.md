# Verification — collapsible log GUI v4

## Results from this revision

The complete suite passed: **303 tests, no failures, no skipped tests**.
This is the previous 241-test suite plus 62 log/streaming tests. Two existing process tests
were updated to exercise the new streaming implementation with real short-lived child processes,
instead of mocking the removed subprocess.run implementation.

An additional **49 GUI tests passed at 150% / 144 DPI**: the 28 new log UI tests and the
21 dedicated language-switching GUI tests. All tests use independent temporary projects and
preferences. The user's Unreal project is not used as a fixture.

`test-results.log` and `high-dpi-tests.log` contain the full test names and results.

## Coverage of the new functionality

- Log closed on every startup, with the previous 900 × 510 default size at 100% scaling.
- Expanding/collapsing, preserving inputs/preview/tab/undo, and not changing a maximized
  window's restore geometry. Compact controls and long status messages stay inside the window.
- Recording while hidden, no automatic opening, no typing/preview spam, copy/clear, read-only
  text selection, bounded history, trimming, and scroll-up without forced return to the bottom.
- Source creation, replacement, appending, backup paths, cancelled overwrite, failures, module /
  plugin / folder additions, undo, and source generation followed by automatic project update.
- English/Japanese switching for existing app log entries; external child output stays untranslated.
- Real child processes emit stdout/stderr through one pipe. Tests check delivery before the child
  finishes, nonzero exits, silent processes, stdin EOF, timeout, cancellation, spawn failure,
  early pipe closure, observer failure cleanup and 12,000-line output without pipe deadlock.
- UTF-8, Japanese CP932, byte-by-byte input, mixed line encodings, CR/CRLF progress, no final newline,
  invalid bytes, ANSI colors, BOM and oversized lines. History has both entry and character limits.
- Closing/destroying the root cancels its timers; forced destruction cancels the update worker
  without letting the worker make Tk calls. The normal close action still asks the user to wait
  for the running project update, as in v3.
- Windows child-tree termination arguments and windowless flags are checked using mocks. Windows
  process-tree behavior itself is not executed on this Linux host.

## Existing behavior retained

`v3-parity.log` verifies byte-for-byte equality with the v3 archive for `internal/model.py`,
`internal/templates.py`, `internal/i18n.py`, `internal/preferences.py`, `internal/launch.py`,
`gui.pyw` and `gui.bat`. Source generation / write protection / undo logic and the entry points
are unchanged. New strings were added to both translation catalogs.

The baseline includes real g++ compile/link/run checks for generated plain C++ types with a
minimal CoreMinimal stub. These are **not** Unreal Engine or UHT builds.

## Captures

`log-closed-en.png`, `log-open-en.png`, `log-closed-ja.png`, and `log-open-ja.png` are captures of
this running application after actually generating ATest in an isolated example project.
The `-150.png` variants are captures at 144 DPI. They are not rendered UI mock-ups, and no fake
engine success is shown in them. The engine is not installed on the verification host.

At 100%: closed 900 × 510, expanded 900 × 712. At 150%: closed 1350 × 765, expanded 1350 × 1068.
The log consumes less extra space when required by the available screen height.
`display-checks.log` records the captured rectangles and open/closed states.

## Environment and limits

Linux; Python 3.13.5; Tk 8.6; Xvfb; g++ 14.2.0. The Python sources also pass parsing using the
Python 3.10 grammar, but Python 3.10 itself was not executed here.

**Not verified here:** native Windows launch/widgets, MSVC, an installed Unreal Engine's project-file
update, or UE/UHT compilation. Process streaming was exercised with real test child processes;
the engine-command resolver was replaced for those tests. This does not demonstrate a real UE build.

External log buffering, encoding and redirection are controlled by the external process. Output becomes
visible after the child flushes a complete line / CR progress record; a final unterminated line is flushed
when it exits. An unusual batch that redirects output elsewhere or detaches another process may not
provide that output to the app's pipe. The previous 120-second project-update timeout is retained.

## Running the tests for development

From the extracted application directory:

```text
python -B -m unittest discover -s tests -v
```

Tk GUI tests require a display; on Linux an Xvfb display can be used. The application itself remains
GUI-only, launched by double-clicking `gui.bat` or `gui.pyw`. No generation CLI was added.
