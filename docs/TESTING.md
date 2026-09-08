# Verification

## Results

**338 tests passed**, with no failures or skips. The v4 baseline passed its original 303 tests before editing. Existing filename assertions were updated, and 35 tests were added for filenames, application identity, preference migration and repository files.

A separate **55 GUI tests passed at 150% / 144 DPI**, covering filename behavior, log controls and English/Japanese switching.

## Checked

- Actor `PlayerBase` and `APlayerBase` produce the same `APlayerBase` declaration in `PlayerBase.h/.cpp`.
- All 26 templates × four layouts × base/prefixed input forms. Reflected headers use the actual filename for their final `generated.h` include; source includes resolve to the corresponding header. C++ declarations, constructors and type references keep their prefixes.
- Interface `I`/`U` input, plain classes, acronym/word beginnings, single-prefix removal, numeric filenames, Windows device names, extra includes and nested plugin modules.
- Preview/write equality, collisions, overwrite confirmation, backups, undo, and append targets including legacy prefixed filenames. Old prefixed files are not automatically renamed or deleted; duplicate creation is blocked.
- English/Japanese UI and log text, renamed window titles, retained inputs, no duplicate generation, closed-by-default logs and compact geometry.
- New preference and backup paths under `UnrealSourceGenerator`. Missing default preferences can be read from `CppSourceGenerator`; saving uses the new path without modifying the old settings.
- `git check-ignore` excludes settings, logs, caches and backups, but retains Python, C++, translations, README files, project/plugin descriptors and documentation images.
- Real g++ compile/link/run tests for generated **plain C++ types** with a minimal `CoreMinimal.h` stub. These are not UE/UHT builds.
- The existing module/plugin/folder, localization, transactional-write and live child-process logging tests continue to pass. Sources parse with the Python 3.10 grammar.

## Captures

[English](main-en.png) · [Japanese](main-ja.png) · [English log](log-en.png) · [Japanese log](log-ja.png)

These are captures of the running application after generating `APlayerBase` in a temporary example project. At 100% scaling the window is 900 × 510 with the log closed and 900 × 712 with it open. No mock engine-success output is shown.

## Environment and limits

Linux, Python 3.13.5, Tk 8.6, Xvfb and g++ 14.2.0.

**Not verified:** native Windows launch/widgets, MSVC, real Unreal Engine project-file generation, UE/UHT builds, or execution on Python 3.10 itself. Process output is tested using real short-lived test processes, not an installed Unreal Engine.

## Development tests

Run from the repository root with a GUI display available:

```text
python -B -m unittest discover -s tests -v
```

On Linux the tests can use an Xvfb display. C++ compiler-dependent tests are skipped when neither g++ nor clang++ is available. The application remains GUI-only; launch it with `gui.bat` or `gui.pyw`.
