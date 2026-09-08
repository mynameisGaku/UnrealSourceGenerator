"""Code templates adapted from the supplied generator. No command-line interface."""

import re

TEMPLATES = {
    "UObject":                    {"parent": "UObject", "include": "UObject/Object.h", "header_only": False, "desc": "素の UObject"},
    "Actor":                      {"parent": "AActor", "include": "GameFramework/Actor.h", "header_only": False, "desc": "AActor (Tick/BeginPlay 付き)"},
    "ActorComponent":             {"parent": "UActorComponent", "include": "Components/ActorComponent.h", "header_only": False, "desc": "UActorComponent"},
    "SceneComponent":             {"parent": "USceneComponent", "include": "Components/SceneComponent.h", "header_only": False, "desc": "USceneComponent"},
    "Pawn":                       {"parent": "APawn", "include": "GameFramework/Pawn.h", "header_only": False, "desc": "APawn"},
    "Character":                  {"parent": "ACharacter", "include": "GameFramework/Character.h", "header_only": False, "desc": "ACharacter"},
    "PlayerController":           {"parent": "APlayerController", "include": "GameFramework/PlayerController.h", "header_only": False, "desc": "APlayerController"},
    "GameModeBase":               {"parent": "AGameModeBase", "include": "GameFramework/GameModeBase.h", "header_only": False, "desc": "AGameModeBase"},
    "GameStateBase":              {"parent": "AGameStateBase", "include": "GameFramework/GameStateBase.h", "header_only": False, "desc": "AGameStateBase"},
    "PlayerState":                {"parent": "APlayerState", "include": "GameFramework/PlayerState.h", "header_only": False, "desc": "APlayerState"},
    "HUD":                        {"parent": "AHUD", "include": "GameFramework/HUD.h", "header_only": False, "desc": "AHUD"},
    "GameInstanceSubsystem":      {"parent": "UGameInstanceSubsystem", "include": "Subsystems/GameInstanceSubsystem.h", "header_only": False, "desc": "UGameInstanceSubsystem"},
    "WorldSubsystem":             {"parent": "UWorldSubsystem", "include": "Subsystems/WorldSubsystem.h", "header_only": False, "desc": "UWorldSubsystem"},
    "LocalPlayerSubsystem":       {"parent": "ULocalPlayerSubsystem", "include": "Subsystems/LocalPlayerSubsystem.h", "header_only": False, "desc": "ULocalPlayerSubsystem"},
    "EngineSubsystem":            {"parent": "UEngineSubsystem", "include": "Subsystems/EngineSubsystem.h", "header_only": False, "desc": "UEngineSubsystem"},
    "EditorSubsystem":            {"parent": "UEditorSubsystem", "include": "EditorSubsystem.h", "header_only": False, "desc": "UEditorSubsystem (Editorモジュール専用)"},
    "DataAsset":                  {"parent": "UDataAsset", "include": "Engine/DataAsset.h", "header_only": False, "desc": "UDataAsset"},
    "AnimInstance":               {"parent": "UAnimInstance", "include": "Animation/AnimInstance.h", "header_only": False, "desc": "UAnimInstance (追加依存なし)"},
    "SaveGame":                   {"parent": "USaveGame", "include": "GameFramework/SaveGame.h", "header_only": False, "desc": "USaveGame (セーブデータ用)"},
    "BlueprintFunctionLibrary":   {"parent": "UBlueprintFunctionLibrary", "include": "Kismet/BlueprintFunctionLibrary.h", "header_only": False, "desc": "UBlueprintFunctionLibrary"},
    "Interface":                  {"parent": "UInterface", "include": "UObject/Interface.h", "header_only": True, "desc": "UInterface + IInterface (ヘッダオンリー)"},
    "Enum":                       {"parent": None, "include": None, "header_only": True, "desc": "UENUM (ヘッダオンリー, BlueprintType)"},
    "Struct":                     {"parent": None, "include": None, "header_only": True, "desc": "USTRUCT (ヘッダオンリー, BlueprintType)"},
    "PlainStruct":                {"parent": None, "include": None, "header_only": True, "desc": "プレーン struct (USTRUCTなし, ヘッダオンリー)"},
    "PlainEnum":                  {"parent": None, "include": None, "header_only": True, "desc": "プレーン enum class (UENUMなし、名前空間対応)"},
    "PlainClass":                 {"parent": None, "include": None, "header_only": False, "desc": "プレーン C++ class (UCLASSなし)"},
}

KIND_GROUPS = {
    "Normal": ["Actor", "Pawn", "Character", "PlayerController",
               "GameModeBase", "GameStateBase", "PlayerState", "HUD",
               "ActorComponent", "SceneComponent", "UObject",
               "DataAsset", "AnimInstance", "SaveGame", "BlueprintFunctionLibrary", "PlainClass"],
    "Subsystem": ["GameInstanceSubsystem", "WorldSubsystem",
                  "LocalPlayerSubsystem", "EngineSubsystem", "EditorSubsystem"],
    "Data": ["Enum", "PlainEnum", "Struct", "PlainStruct", "Interface"],
}

TEMPLATE_ALIASES = {
    "aactor": "Actor", "actor": "Actor",
    "uobject": "UObject", "object": "UObject",
    "actorcomponent": "ActorComponent", "component": "ActorComponent",
    "scenecomponent": "SceneComponent",
    "apawn": "Pawn", "pawn": "Pawn",
    "acharacter": "Character", "character": "Character",
    "playercontroller": "PlayerController", "controller": "PlayerController",
    "gamemode": "GameModeBase", "gamemodebase": "GameModeBase",
    "gamestate": "GameStateBase", "gamestatebase": "GameStateBase",
    "playerstate": "PlayerState",
    "hud": "HUD", "ahud": "HUD",
    "gameinstancesubsystem": "GameInstanceSubsystem", "gis": "GameInstanceSubsystem",
    "gameinstance": "GameInstanceSubsystem",
    "worldsubsystem": "WorldSubsystem", "wss": "WorldSubsystem", "world": "WorldSubsystem",
    "localplayersubsystem": "LocalPlayerSubsystem", "localplayer": "LocalPlayerSubsystem",
    "enginesubsystem": "EngineSubsystem", "engine": "EngineSubsystem",
    "editorsubsystem": "EditorSubsystem", "editor": "EditorSubsystem",
    "dataasset": "DataAsset", "udataasset": "DataAsset",
    "animinstance": "AnimInstance", "uaniminstance": "AnimInstance", "anim": "AnimInstance",
    "savegame": "SaveGame", "usavegame": "SaveGame", "save": "SaveGame",
    "bfl": "BlueprintFunctionLibrary", "blueprintfunctionlibrary": "BlueprintFunctionLibrary",
    "uenum": "Enum", "enum": "Enum",
    "ustruct": "Struct", "struct": "Struct",
    "plainstruct": "PlainStruct", "fstruct": "PlainStruct",
    "plainenum": "PlainEnum", "enumclass": "PlainEnum",
    "plainclass": "PlainClass", "class": "PlainClass",
    "interface": "Interface", "uinterface": "Interface", "iinterface": "Interface",
}

def normalize_template(name: str) -> str:
    if not name:
        return ""
    key = name.strip()
    if key in TEMPLATES:
        return key
    low = key.lower()
    if low in TEMPLATE_ALIASES:
        return TEMPLATE_ALIASES[low]
    # 大文字小文字無視で検索
    for k in TEMPLATES:
        if k.lower() == low:
            return k
    return key

def sanitize_class_name(name: str) -> str:
    return re.sub(r'\s+', '', (name or '').strip())

def normalize_namespace(s) -> str:
    if not s or not isinstance(s, str):
        return ""
    return re.sub(r'\s*::\s*', '::', s.strip())

def build_header_content(req: dict, info: dict, api_macro: str) -> str:
    cls = sanitize_class_name(req["class_name"])
    header_stem = req["header_stem"]
    api = f"{api_macro} " if req.get("with_api") and api_macro else ""
    bp_type = "BlueprintType, " if req.get("blueprint_type") else ""
    extra_includes = (req.get("extra_includes") or "").strip()
    tmpl = req["template"]
    # 基本関数の有無 (デフォルトは True、明示的に False の場合のみ無効)
    with_ctor = req.get("with_constructor", True)
    with_bp = req.get("with_beginplay", True)
    with_tick = req.get("with_tick", True)
    with_init = req.get("with_initialize", True)
    with_deinit = req.get("with_deinitialize", True)

    # --- Enum ---
    if tmpl == "Enum":
        enum_name = cls if cls.startswith("E") else "E" + cls
        with_conv = req.get("with_enum_conversion", False)
        base = f'''#pragma once

#include "CoreMinimal.h"
#include "{header_stem}.generated.h"

UENUM(BlueprintType)
enum class {enum_name} : uint8
{{
    None    UMETA(DisplayName="None"),
    ItemA   UMETA(DisplayName="Item A"),
    ItemB   UMETA(DisplayName="Item B"),
    MAX     UMETA(Hidden)
}};
'''
        if with_conv:
            base += f'''
// Helpers for {enum_name} <-> FString/FName conversion
namespace {enum_name}_Helper
{{
    inline FString ToString({enum_name} Value)
    {{
        const UEnum* Enum = StaticEnum<{enum_name}>();
        return Enum ? Enum->GetNameStringByValue((int64)Value) : TEXT("Invalid");
    }}
    inline FName ToName({enum_name} Value)
    {{
        const UEnum* Enum = StaticEnum<{enum_name}>();
        return Enum ? Enum->GetNameByValue((int64)Value) : NAME_None;
    }}
    inline bool FromString(const FString& Str, {enum_name}& Out)
    {{
        const UEnum* Enum = StaticEnum<{enum_name}>();
        if (!Enum) return false;
        int64 V = Enum->GetValueByName(FName(*Str));
        if (V == INDEX_NONE) return false;
        Out = static_cast<{enum_name}>(V);
        return true;
    }}
    inline bool FromName(FName Name, {enum_name}& Out)
    {{
        const UEnum* Enum = StaticEnum<{enum_name}>();
        if (!Enum) return false;
        int64 V = Enum->GetValueByName(Name);
        if (V == INDEX_NONE) return false;
        Out = static_cast<{enum_name}>(V);
        return true;
    }}
    // Blueprint-callable via inline helpers (no BFL needed)
}}
'''
        return base

    # --- Struct (USTRUCT) ---
    if tmpl == "Struct":
        struct_name = cls if cls.startswith("F") else "F" + cls
        with_eq = req.get("with_struct_equality", False)
        with_tostring = req.get("with_struct_tostring", False)
        with_net = req.get("with_struct_netserialize", False)
        with_dt = req.get("with_struct_datatable", False)
        with_hash = req.get("with_struct_hash", False)
        parent = " : public FTableRowBase" if with_dt else ""
        dt_include = '#include "Engine/DataTable.h"\n' if with_dt else ""
        out = f'''#pragma once

#include "CoreMinimal.h"
{dt_include}#include "{header_stem}.generated.h"

'''
        out += f'''USTRUCT(BlueprintType)
struct {api}{struct_name}{parent}
{{
    GENERATED_BODY()

public:
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Config")
    int32 Value = 0;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Config")
    FString Name;
'''
        if with_eq:
            out += f'''
    bool operator==(const {struct_name}& Other) const
    {{
        return Value == Other.Value && Name == Other.Name;
    }}
    bool operator!=(const {struct_name}& Other) const
    {{
        return !(*this == Other);
    }}
'''
        if with_tostring:
            out += f'''
    FString ToString() const
    {{
        return FString::Printf(TEXT("%s: %d"), *Name, Value);
    }}
'''
        if with_net:
            out += f'''
    bool NetSerialize(FArchive& Ar, class UPackageMap* Map, bool& bOutSuccess)
    {{
        Ar << Value;
        Ar << Name;
        bOutSuccess = !Ar.IsError();
        return bOutSuccess;
    }}
'''
        out += '};\n'
        if with_hash:
            out += f'''
FORCEINLINE uint32 GetTypeHash(const {struct_name}& S)
{{
    return HashCombine(GetTypeHash(S.Value), GetTypeHash(S.Name));
}}
'''
        if with_net:
            out += f'\ntemplate<> struct TStructOpsTypeTraits<{struct_name}> : public TStructOpsTypeTraitsBase2<{struct_name}>\n{{\n    enum {{ WithNetSerializer = true, WithNetSharedSerialization = true }};\n}};\n'
        return out

    # --- PlainStruct ---
    if tmpl == "PlainStruct":
        struct_name = cls if cls.startswith("F") else "F" + cls
        out = '#pragma once\n\n#include "CoreMinimal.h"\n'
        if extra_includes:
            for inc in [s.strip() for s in extra_includes.split(",") if s.strip()]:
                out += f'#include "{inc}"\n' if "#include" not in inc else inc + "\n"
        out += f'''
struct {api}{struct_name}
{{
public:
    int32 Value = 0;
    FString Name;
}};
'''
        return out

    if tmpl == "PlainEnum":
        return f'''#pragma once

#include "CoreMinimal.h"

// 状態を表す列挙型。用途に合わせて列挙値を追加する。
enum class {cls} : uint8
{{
    // 状態がまだ選ばれていない。
    None = 0
}};
'''

    # --- PlainClass ---
    if tmpl == "PlainClass":
        out = '#pragma once\n\n#include "CoreMinimal.h"\n'
        if extra_includes:
            for inc in [s.strip() for s in extra_includes.split(",") if s.strip()]:
                out += f'#include "{inc}"\n' if "#include" not in inc else inc + "\n"
        special_members = f'{cls}() = default;\n    ~{cls}() = default;' if req.get("header_only") else f'{cls}();\n    ~{cls}();'
        out += f'''
class {api}{cls}
{{
public:
    {special_members}

private:
    int32 Value = 0;
}};
'''
        return out

    # --- Interface ---
    if tmpl == "Interface":
        if cls.startswith("I"):
            iname = cls
            uname = "U" + cls[1:]
        elif cls.startswith("U"):
            uname = cls
            iname = "I" + cls[1:]
        else:
            uname = "U" + cls
            iname = "I" + cls
        # generated.h follows the actual header filename, not the C++ type name.
        return f'''#pragma once

#include "CoreMinimal.h"
#include "UObject/Interface.h"
#include "{header_stem}.generated.h"

UINTERFACE(MinimalAPI, BlueprintType)
class {uname} : public UInterface
{{
    GENERATED_BODY()
}};

class {api}{iname}
{{
    GENERATED_BODY()

public:
    // Add interface functions here
    UFUNCTION(BlueprintNativeEvent, BlueprintCallable, Category="Interface")
    void DoSomething();
}};
'''

    # --- 通常 UCLASS 系 ---
    out = '#pragma once\n\n#include "CoreMinimal.h"\n'
    if info.get("include"):
        out += f'#include "{info["include"]}"\n'
    if tmpl in ("GameInstanceSubsystem", "WorldSubsystem", "LocalPlayerSubsystem", "EngineSubsystem", "EditorSubsystem") and req.get("with_tickable", False):
        out += '#include "Tickable.h"\n'
    if extra_includes:
        for inc in [s.strip() for s in extra_includes.split(",") if s.strip()]:
            out += f'#include "{inc}"\n' if "#include" not in inc else inc + "\n"
    out += f'#include "{header_stem}.generated.h"\n\n'

    # UCLASS 指定子
    uclass_spec = ""
    if req.get("blueprint_type"):
        uclass_spec = "BlueprintType, Blueprintable"
    if uclass_spec:
        out += f'UCLASS({uclass_spec})\n'
    else:
        out += 'UCLASS()\n'

    parent_decl = info["parent"]
    if tmpl in ("GameInstanceSubsystem", "WorldSubsystem", "LocalPlayerSubsystem", "EngineSubsystem", "EditorSubsystem") and req.get("with_tickable", False):
        parent_decl = f'{info["parent"]}, public FTickableGameObject'

    out += f'class {api}{cls} : public {parent_decl}\n{{\n    GENERATED_BODY()\n\npublic:\n'

    if tmpl in ("Actor", "Pawn", "Character", "PlayerController", "GameModeBase", "GameStateBase", "PlayerState", "HUD"):
        decls = []
        if with_ctor:
            decls.append(f'    {cls}();')
        # protected の BeginPlay/Tick
        prot = []
        if with_bp:
            prot.append('    virtual void BeginPlay() override;')
        if with_tick:
            prot.append('    virtual void Tick(float DeltaSeconds) override;')
        if decls:
            out += '\n'.join(decls) + '\n'
        if prot:
            out += '\nprotected:\n' + '\n'.join(prot) + '\n'
        if not decls and not prot:
            out += '    // Add members here\n'
    elif tmpl in ("ActorComponent", "SceneComponent"):
        decls = []
        if with_ctor:
            decls.append(f'    {cls}();')
        prot = []
        if with_bp:
            prot.append('    virtual void BeginPlay() override;')
        if with_tick:
            prot.append('    virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;')
        if decls:
            out += '\n'.join(decls) + '\n'
        if prot:
            out += '\nprotected:\n' + '\n'.join(prot) + '\n'
        if not decls and not prot:
            out += '    // Add members here\n'
    elif tmpl in ("GameInstanceSubsystem", "WorldSubsystem", "LocalPlayerSubsystem", "EngineSubsystem", "EditorSubsystem"):
        # 先頭の public: と重複しないように
        out = out.replace("public:\n", "", 1)
        decls = []
        if with_init:
            decls.append('    virtual void Initialize(FSubsystemCollectionBase& Collection) override;')
        if with_deinit:
            decls.append('    virtual void Deinitialize() override;')
        with_tickable = req.get("with_tickable", False)
        if with_tickable:
            # FTickableGameObject併用パターン (USubsystem系にTickは無いため)
            decls.append('    // FTickableGameObject')
            decls.append('    virtual void Tick(float DeltaTime) override;')
            decls.append('    virtual TStatId GetStatId() const override;')
            decls.append('    virtual bool IsTickable() const override { return !IsTemplate(); }')
            decls.append('    virtual bool IsTickableWhenPaused() const override { return false; }')
        if decls:
            out += 'public:\n' + '\n'.join(decls) + '\n'
            out = out.replace("GENERATED_BODY()\n\npublic:\npublic:\n", "GENERATED_BODY()\n\npublic:\n")
        else:
            out += 'public:\n    // Add subsystem members here\n'
            out = out.replace("GENERATED_BODY()\n\npublic:\npublic:\n", "GENERATED_BODY()\n\npublic:\n")
    elif tmpl in ("UObject", "AnimInstance"):
        if with_ctor:
            out += f'    {cls}();\n'
        else:
            out += '    // Add members here\n'
    elif tmpl == "DataAsset":
        out += '    // Add UPROPERTY members here\n'
    elif tmpl == "SaveGame":
        out += '    UPROPERTY(VisibleAnywhere, Category="Save")\n'
        out += '    FString SlotName = TEXT("Slot1");\n\n'
        out += '    UPROPERTY(VisibleAnywhere, Category="Save")\n'
        out += '    int32 UserIndex = 0;\n'
    elif tmpl == "BlueprintFunctionLibrary":
        out += '    UFUNCTION(BlueprintCallable, Category="Util")\n    static void SampleFunction();\n'

    out += '};\n'
    return out

def build_cpp_content(req: dict, info: dict, header_include: str) -> str:
    cls = sanitize_class_name(req["class_name"])
    tmpl = req["template"]
    out = f'#include "{header_include}"\n\n'
    with_ctor = req.get("with_constructor", True)
    with_bp = req.get("with_beginplay", True)
    with_tick = req.get("with_tick", True)
    with_init = req.get("with_initialize", True)
    with_deinit = req.get("with_deinitialize", True)

    if tmpl == "PlainClass":
        out += f'{cls}::{cls}()\n{{\n}}\n\n{cls}::~{cls}()\n{{\n}}\n'
        return out
    if tmpl == "Interface":
        return out

    if tmpl in ("Actor", "Pawn", "Character", "PlayerController", "GameModeBase", "GameStateBase", "PlayerState", "HUD"):
        if with_ctor:
            tick_line = "\n    PrimaryActorTick.bCanEverTick = true;" if with_tick else ""
            out += f'''{cls}::{cls}()
{{{tick_line}
}}

'''
        if with_bp:
            out += f'''void {cls}::BeginPlay()
{{
    Super::BeginPlay();
}}

'''
        if with_tick:
            # もしコンストラクタが無くても Tick は定義可能
            out += f'''void {cls}::Tick(float DeltaSeconds)
{{
    Super::Tick(DeltaSeconds);
}}

'''
        if not with_ctor and not with_bp and not with_tick:
            out += '// Add implementation here\n'
    elif tmpl in ("ActorComponent", "SceneComponent"):
        if with_ctor:
            tick_line = "\n    PrimaryComponentTick.bCanEverTick = true;" if with_tick else ""
            out += f'''{cls}::{cls}()
{{{tick_line}
}}

'''
        if with_bp:
            out += f'''void {cls}::BeginPlay()
{{
    Super::BeginPlay();
}}

'''
        if with_tick:
            out += f'''void {cls}::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
}}

'''
        if not with_ctor and not with_bp and not with_tick:
            out += '// Add implementation here\n'
    elif tmpl in ("GameInstanceSubsystem", "WorldSubsystem", "LocalPlayerSubsystem", "EngineSubsystem", "EditorSubsystem"):
        if with_init:
            out += f'''void {cls}::Initialize(FSubsystemCollectionBase& Collection)
{{
    Super::Initialize(Collection);
}}

'''
        if with_deinit:
            out += f'''void {cls}::Deinitialize()
{{
    Super::Deinitialize();
}}

'''
        if req.get("with_tickable", False):
            out += f'''void {cls}::Tick(float DeltaTime)
{{
    // Per-frame logic here
}}

TStatId {cls}::GetStatId() const
{{
    RETURN_QUICK_DECLARE_CYCLE_STAT({cls}, STATGROUP_Tickables);
}}

'''
        if not with_init and not with_deinit and not req.get("with_tickable", False):
            out += '// Add subsystem implementation here\n'
    elif tmpl in ("UObject", "AnimInstance"):
        if with_ctor:
            out += f'{cls}::{cls}()\n{{\n}}\n'
        else:
            out += '// Add implementation here\n'
    elif tmpl == "BlueprintFunctionLibrary":
        out += f'void {cls}::SampleFunction()\n{{\n}}\n'
    elif tmpl == "DataAsset":
        out += '// DataAsset implementation\n'
    elif tmpl == "SaveGame":
        out += '// SaveGame: UPROPERTY members are auto-serialized by the engine\n'
    else:
        out += '// Add implementation here\n'
    return out

NS_PLAIN_TEMPLATES = ("PlainStruct", "PlainClass", "PlainEnum")

def _apply_namespace(header: str, cpp: str, ns: str):
    """生成内容を namespace で包む。先頭のinclude部は外に残す。
    呼び出し側でプレーン型のみに制限済み (UCLASS等はUHTが処理できない)。"""
    lines = header.splitlines(keepends=True)
    idx = None
    for i, ln in enumerate(lines):
        if 'CoreMinimal.h' in ln:
            idx = i + 1
        elif ln.lstrip().startswith('#include'):
            idx = i + 1
    if idx is None:
        idx = 0
    head = "".join(lines[:idx])
    body = "".join(lines[idx:]).strip("\n")
    header = head + f"\nnamespace {ns}\n{{\n" + body + f"\n}} // namespace {ns}\n"
    if cpp:
        clines = cpp.splitlines(keepends=True)
        cidx = 1 if clines and clines[0].startswith("#include") else 0
        chead = "".join(clines[:cidx])
        cbody = "".join(clines[cidx:]).strip("\n")
        cpp = chead + (f"\nnamespace {ns}\n{{\n" + cbody + f"\n}} // namespace {ns}\n" if cbody else "")
    return header, cpp
