# UnrealSourceGenerator

English | [日本語](README.ja.md)

A GUI-only C++ source generator for Unreal Engine. Create classes, Components, Subsystems, structs, enums, interfaces and plain C++ types with a live preview. Place `.h` files in `Public` and `.cpp` files in `Private`, or keep them together.

## Getting started

Requires **Python 3.10+ with tkinter**. No extra packages. Download the entire repository, keep the folder structure intact, and double-click **`gui.bat`** on Windows. Unreal Editor does not need to be open.

The default language is **English**. Switch to **日本語** at the top right; the choice is saved.

## Usage

1. Select a `.uproject` under **Project**.
2. Choose **Module** and **Type**, then enter **Name** without a prefix.
3. Set **Folder** and **Layout**.
4. Check **Preview**, then click **Generate**.

For Actor, `Test` becomes `ATest.h` / `ATest.cpp`; entering `ATest` does not add another `A`. UObject-derived types use `U`, structs use `F`, and enums use `E`. PlainClass keeps the entered name.

For module `MyGame`, folder `Actors`, and layout `Public / Private`:

```text
Source/MyGame/Public/Actors/ATest.h
Source/MyGame/Private/Actors/ATest.cpp
```

Folder accepts nested paths such as `AI/Movement`. Layout also supports **Same Folder**, **Private Only**, and **Public Only**.

## Additions and options

- **+ beside Module**: add a Runtime / Editor module or plugin. New plugins include a same-name C++ module; select **Destination** to add a module to an existing plugin. If the project has no modules, add a Runtime module first.
- **+ beside Folder**: add an empty folder. Public / Private creates matching folders on both sides.
- **Options…**: configure generated functions, struct helpers, namespaces for plain C++ types, or appending to an existing header. Tick is off by default. Hover over a control or press **F1** for help.

## Project files and logs

**Tools → Update Project Files** updates IDE project files, not C++ builds. It requires Windows and the project's Unreal Engine installation. Enable **Options… → Update Project Files After Generation** to run it automatically.

Click **▸ Log** at the bottom left. It starts **closed on every launch**, records while hidden, and never opens automatically.

The log shows source generation, file changes, module/plugin/folder additions, undo results, and errors. UE project-file updates stream standard output and errors, with the command, exit code, and elapsed time.

**Copy / Clear** manages the displayed history. Scrolling up pauses automatic scrolling. History is session-only; copy anything needed before closing. UE output stays in its original language.

## Backups and undo

Existing-file changes require confirmation and are backed up to `Saved/CppSourceGenerator/Backups` in the project. **Tools → Undo Last Action** reverses the latest generation or addition without overwriting later edits. Added folders are removed only if nothing else was added to them. Undo history is session-only; backups remain on disk.

## Notes

**Ctrl+Enter / Ctrl+G**: generate. **F5**: reload the project.

Select an Editor module for `EditorSubsystem`. Windows-native launch and Unreal Engine / UHT builds of the generated code have not been verified.
