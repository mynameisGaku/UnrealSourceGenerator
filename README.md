# [UnrealSourceGenerator](https://github.com/mynameisGaku/UnrealSourceGenerator)

English | [日本語](README.ja.md)

A standalone GUI for generating Unreal Engine C++ classes, structs, enums and interfaces. Create headers in `Public` and sources in `Private`, or keep them together.

## Start

Requires **Python 3.10+ with tkinter**. No extra packages.
Download the entire repository and double-click **`gui.bat`** on Windows.
The default language is English; select **日本語** at the top right to switch. Your choice is saved.

## Generate

Choose **Project (.uproject) → Module → Type → Name**, set **Folder / Layout**, check the preview and click **Generate**. Use **Options…** for additional settings; hover over a control for help.

**Type names get a prefix; filenames do not.** With Actor, entering `PlayerBase` or `APlayerBase` creates class `APlayerBase` in:

```text
Source/MyGame/Public/PlayerBase.h
Source/MyGame/Private/PlayerBase.cpp
```

The same rule applies to `U`, `F`, `E` and interface `I` / `U` prefixes. `PlainClass` names are unchanged. Structs, enums and interfaces generate headers only. Existing files are not automatically renamed.

## Other actions

| Action | Where |
| --- | --- |
| Add a module or plugin, including a module to an existing plugin | **+** beside Module |
| Add an empty folder | **+** beside Folder |
| Update IDE project files | **Tools → Update Project Files** |
| View generation and UE project-file output; copy or clear it | **▸ Log** at the bottom (closed on startup) |
| Undo the last generation or addition | **Tools → Undo Last Action** |

Project-file updates require Windows and the associated Unreal Engine installation; they do not compile C++. Enable **Options… → Update Project Files After Generation** to update automatically.

Existing-file changes require confirmation and are backed up to `Saved/UnrealSourceGenerator/Backups`. Undo will not overwrite files edited afterward. Logs and undo history last for the current session.

**Shortcuts:** Ctrl+Enter / Ctrl+G — generate; F5 — reload project.

Native Windows launch and Unreal Engine / UHT builds have not been verified. [Test details](docs/TESTING.md).
