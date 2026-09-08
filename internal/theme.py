"""Small native controls; no dashboard styling or decorative components."""
import sys
import tkinter as tk
from tkinter import ttk, font


def apply(root):
    available = set(font.families(root))
    family = next((n for n in ('Yu Gothic UI', 'Meiryo UI', 'Noto Sans CJK JP', 'DejaVu Sans') if n in available), 'TkDefaultFont')
    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont', 'TkCaptionFont'):
        font.nametofont(name, root).configure(family=family, size=10)
    mono = next((n for n in ('Consolas', 'Cascadia Mono', 'DejaVu Sans Mono') if n in available), 'TkFixedFont')
    font.nametofont('TkFixedFont', root).configure(family=mono, size=10)
    style = ttk.Style(root)
    if sys.platform == 'win32' and 'vista' in style.theme_names():
        style.theme_use('vista')
    elif sys.platform != 'darwin':
        style.theme_use('clam')
        style.configure('.', background='#f6f6f6', foreground='#242424', font='TkDefaultFont')
        style.configure('TFrame', background='#f6f6f6')
        style.configure('TLabel', background='#f6f6f6')
        style.configure('TEntry', fieldbackground='#ffffff', bordercolor='#c7c7c7',
                        lightcolor='#c7c7c7', darkcolor='#c7c7c7', padding=(6, 4))
        style.configure('TCombobox', fieldbackground='#ffffff', background='#f6f6f6',
                        bordercolor='#c7c7c7', lightcolor='#c7c7c7', darkcolor='#c7c7c7', padding=(6, 4))
        style.map('TCombobox', fieldbackground=[('readonly', '#ffffff'), ('disabled', '#f0f0f0')],
                  foreground=[('disabled', '#888888'), ('!disabled', '#242424')])
        style.configure('TButton', padding=(10, 5), background='#fafafa', relief='flat',
                        bordercolor='#c7c7c7', lightcolor='#c7c7c7', darkcolor='#c7c7c7')
        style.map('TButton', background=[('pressed', '#e6e6e6'), ('active', '#eeeeee')])
        style.configure('TMenubutton', padding=(8, 5), background='#fafafa')
        style.configure('TNotebook', background='#f6f6f6', borderwidth=1, bordercolor='#d0d0d0')
        style.configure('TNotebook.Tab', padding=(12, 5), background='#eeeeee')
        style.map('TNotebook.Tab', background=[('selected', '#ffffff')])
        style.configure('Vertical.TScrollbar', arrowsize=12, background='#dedede', troughcolor='#f8f8f8')
        style.configure('Horizontal.TScrollbar', arrowsize=12, background='#dedede', troughcolor='#f8f8f8')
    style.configure('Error.TLabel', foreground='#ac2020')
    style.configure('Quiet.TLabel', foreground='#606060')
    style.configure('Generate.TButton', padding=(18, 7))
    style.configure('Add.TButton', padding=(3, 0))
    style.configure('Log.TButton', padding=(7, 4))
    style.configure('TCheckbutton', padding=(0, 3))
    root.configure(background=style.lookup('TFrame', 'background') or '#f6f6f6')
    root.option_add('*TCombobox*Listbox.font', 'TkDefaultFont')
    return family, mono
