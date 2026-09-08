from pathlib import Path
import json


def fixture(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'Demo.uproject').write_text(json.dumps({'FileVersion': 3, 'EngineAssociation': '5.6', 'Modules': [
        {'Name': 'Game', 'Type': 'Runtime'}, {'Name': 'EditorTools', 'Type': 'Editor'},
        {'Name': 'Flat', 'Type': 'Runtime'}], 'Plugins': []}), encoding='utf-8')
    for name in ('Game', 'EditorTools', 'Flat'):
        p = root / 'Source' / name
        p.mkdir(parents=True)
        (p / f'{name}.Build.cs').write_text(f'''using UnrealBuildTool;
public class {name} : ModuleRules {{
    public {name}(ReadOnlyTargetRules Target) : base(Target) {{
        PublicDependencyModuleNames.AddRange(new string[] {{ "Core", "CoreUObject", "Engine" }});
        PrivateDependencyModuleNames.AddRange(new string[] {{ }});
    }}
}}
''', encoding='utf-8')
        if name != 'Flat':
            (p / 'Public').mkdir()
            (p / 'Private').mkdir()
    for suffix, kind in (('', 'Game'), ('Editor', 'Editor')):
        (root / 'Source' / f'Demo{suffix}.Target.cs').write_text(f'''using UnrealBuildTool;
public class Demo{suffix}Target : TargetRules {{
    public Demo{suffix}Target(TargetInfo Target) : base(Target) {{
        Type = TargetType.{kind};
        ExtraModuleNames.AddRange(new string[] {{ "Game", "Flat" }});
    }}
}}
''', encoding='utf-8')
    return root / 'Demo.uproject'


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
