"""Compact GUI: one form, always-visible preview, contextual options."""
from __future__ import annotations

from dataclasses import replace
from collections import deque
import time
from pathlib import Path
import json
import os
import queue
import re
import sys
import threading
import traceback
import weakref
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font

from .identity import APP_NAME
from . import model, templates, theme, platform_tools, preferences
from .activity import ActivityLog, format_entry
from .i18n import Message, Translator, LANGUAGES, normalize_language, msg


class UITranslations(Translator):
    def __init__(self, language='en'):
        super().__init__(language)
        self.widgets = weakref.WeakKeyDictionary()
        self.titles = weakref.WeakKeyDictionary()
        self.menus = weakref.WeakKeyDictionary()
        self.tooltips = weakref.WeakSet()

    def bind_text(self, widget, message):
        self.widgets[widget] = message
        widget.configure(text=self.render(message))

    def bind_title(self, widget, message):
        self.titles[widget] = message
        widget.title(self.render(message))

    def bind_menu(self, menu, index, message):
        self.menus.setdefault(menu, {})[index] = message
        menu.entryconfigure(index, label=self.render(message))

    def refresh(self):
        for tip in tuple(self.tooltips):
            tip.hide()
        for widget, message in list(self.widgets.items()):
            if widget.winfo_exists():
                widget.configure(text=self.render(message))
            else:
                del self.widgets[widget]
        for widget, message in list(self.titles.items()):
            if widget.winfo_exists():
                widget.title(self.render(message))
            else:
                del self.titles[widget]
        for menu, items in list(self.menus.items()):
            if menu.winfo_exists():
                for index, message in items.items():
                    menu.entryconfigure(index, label=self.render(message))
            else:
                del self.menus[menu]


def localized_widget(factory, parent, **kwargs):
    message = kwargs.pop('text', '')
    widget = factory(parent, **kwargs)
    parent._root().translations.bind_text(widget, message)
    return widget


def configure_widget(widget, **kwargs):
    if 'text' in kwargs:
        widget._root().translations.bind_text(widget, kwargs.pop('text'))
    if kwargs:
        widget.configure(**kwargs)


def add_menu_item(menu, method, **kwargs):
    message = kwargs.pop('label', '')
    getattr(menu, method)(**kwargs)
    menu._root().translations.bind_menu(menu, menu.index('end'), message)


def localized_messagebox(method, title, message, **kwargs):
    translations = kwargs['parent']._root().translations
    return getattr(messagebox, method)(translations.render(title), translations.render(message), **kwargs)


class ToolTip:
    def __init__(self, widget, text, delay=600):
        self.widget, self.text, self.delay = widget, text, delay
        self.tip = None
        self.timer = None
        widget._root().translations.tooltips.add(self)
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')
        widget.bind('<KeyPress>', self.hide, add='+')
        widget.bind('<F1>', self.show, add='+')
        widget.bind('<Destroy>', self.hide, add='+')

    def schedule(self, event=None):
        self.hide()
        self.timer = self.widget.after(self.delay, self.show)

    def show(self, event=None):
        self.timer = None
        value = self.text() if callable(self.text) else self.text
        text = self.widget._root().translations.render(value)
        if not text or self.tip or not self.widget.winfo_exists():
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.withdraw()
        self.tip.overrideredirect(True)
        self.tip.transient(self.widget.winfo_toplevel())
        tk.Label(self.tip, text=text, background='#ffffe7', foreground='#202020',
                 borderwidth=1, relief='solid', padx=8, pady=5, justify='left',
                 wraplength=420, font='TkDefaultFont').pack()
        self.tip.update_idletasks()
        x, y = self.widget.winfo_rootx() + 12, self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        sw, sh = self.tip.winfo_screenwidth(), self.tip.winfo_screenheight()
        x = max(0, min(x, sw - self.tip.winfo_reqwidth() - 8))
        y = max(0, min(y, sh - self.tip.winfo_reqheight() - 8))
        self.tip.geometry(f'+{x}+{y}')
        self.tip.deiconify()
        return 'break'

    def hide(self, event=None):
        if self.timer:
            try:
                self.widget.after_cancel(self.timer)
            except tk.TclError:
                pass
            self.timer = None
        if self.tip:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


class CodeView(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.content = ''
        self.path = ''
        self.wrap = tk.BooleanVar(self, value=True)
        self.gutter = tk.Canvas(self, width=34, highlightthickness=0, background='#ffffff')
        self.gutter.grid(row=0, column=0, sticky='ns')
        self.text = tk.Text(self, width=1, height=1, font='TkFixedFont', wrap='word',
                            borderwidth=0, highlightthickness=0, background='#ffffff',
                            foreground='#262626', padx=7, pady=9, state='disabled',
                            selectbackground='#cce1f6', selectforeground='#151515',
                            exportselection=False, undo=False)
        self.text.grid(row=0, column=1, sticky='nsew')
        self.vertical = ttk.Scrollbar(self, orient='vertical', command=self._scroll)
        self.vertical.grid(row=0, column=2, sticky='ns')
        self.horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.text.xview)
        self.horizontal.grid(row=1, column=0, columnspan=2, sticky='ew')
        self.horizontal.grid_remove()
        self.text.configure(yscrollcommand=self._yscroll, xscrollcommand=self.horizontal.set)
        self.text.bind('<Configure>', lambda e: self.redraw())
        self.text.bind('<Control-a>', self.select_all)
        self.text.bind('<Control-A>', self.select_all)
        self.gutter.bind('<MouseWheel>', lambda e: self._scroll('scroll', -int(e.delta / 120), 'units'))
        self.menu = tk.Menu(self, tearoff=False)
        add_menu_item(self.menu, 'add_command', label=msg('Copy All'), command=self.copy_all)
        add_menu_item(self.menu, 'add_checkbutton', label=msg('Word Wrap'), variable=self.wrap, command=self.toggle_wrap)
        self.text.bind('<Button-3>', self.context_menu)
        self.text.tag_configure('comment', foreground='#778477')
        self.text.tag_configure('string', foreground='#855a37')
        self.text.tag_configure('directive', foreground='#666178')
        self.text.tag_configure('keyword', foreground='#315b85')
        self.text.tag_configure('macro', foreground='#386862')
        ToolTip(self.gutter, lambda: self.path)

    def context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _scroll(self, *args):
        self.text.yview(*args)
        self.redraw()

    def _yscroll(self, first, last):
        self.vertical.set(first, last)
        self.redraw()

    def redraw(self):
        self.gutter.delete('all')
        if not self.content:
            return
        line = self.text.index('@0,0')
        while True:
            info = self.text.dlineinfo(line)
            if info is None:
                break
            number = line.split('.')[0]
            self.gutter.create_text(self.gutter.winfo_width() - 7, info[1], anchor='ne',
                                    text=number, font='TkFixedFont', fill='#9a9a9a')
            line = f"{int(line.split('.')[0]) + 1}.0"

    def toggle_wrap(self):
        self.text.configure(wrap='word' if self.wrap.get() else 'none')
        if self.wrap.get():
            self.horizontal.grid_remove()
        else:
            self.horizontal.grid()
        self.redraw()

    def select_all(self, event=None):
        self.text.tag_add('sel', '1.0', 'end-1c')
        return 'break'

    def copy_all(self):
        if self.content:
            self.clipboard_clear()
            self.clipboard_append(self.content)

    def set_content(self, text: str, path: str = ''):
        self.path = path
        if text == self.content:
            return
        scroll = self.text.yview()
        same_file = bool(self.content)
        self.content = text
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', text)
        pattern = re.compile(r'(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|'
                             r'(?P<string>"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')|'
                             r'(?P<directive>^\s*#[^\n]*)|'
                             r'(?P<macro>\b(?:UCLASS|USTRUCT|UENUM|UINTERFACE|UPROPERTY|UFUNCTION|GENERATED_BODY|UMETA)\b)|'
                             r'(?P<keyword>\b(?:class|struct|enum|public|protected|private|virtual|override|void|const|return|if|else|static|inline|namespace|template|true|false|bool|int32|uint8|float)\b)', re.M)
        for match in pattern.finditer(text):
            self.text.tag_add(match.lastgroup, f'1.0+{match.start()}c', f'1.0+{match.end()}c')
        self.text.configure(state='disabled')
        if same_file and scroll:
            self.text.yview_moveto(scroll[0])
        else:
            self.text.yview_moveto(0)
        self.redraw()


class LogView(ttk.Frame):
    """Read-only, incrementally updated session log. Called on the Tk thread."""
    def __init__(self, parent, history):
        super().__init__(parent)
        self.history = history
        self._revision = -1
        self._language = ''
        self._last_sequence = 0
        self._rendered = deque()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.text = tk.Text(self, width=1, height=1, font='TkFixedFont', wrap='none',
                            background='#ffffff', foreground='#333333', borderwidth=0,
                            highlightthickness=1, highlightbackground='#d0d0d0',
                            padx=8, pady=7, state='disabled', undo=False,
                            selectbackground='#cce1f6', selectforeground='#151515',
                            exportselection=False)
        self.text.grid(row=0, column=0, sticky='nsew')
        self.vertical = ttk.Scrollbar(self, orient='vertical', command=self.text.yview)
        self.horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.text.xview)
        self.vertical.grid(row=0, column=1, sticky='ns')
        self.horizontal.grid(row=1, column=0, sticky='ew')
        self.text.configure(yscrollcommand=self.vertical.set, xscrollcommand=self.horizontal.set)
        for tag, color in (('error', '#ac2020'), ('warning', '#84610b'), ('success', '#367340')):
            self.text.tag_configure(tag, foreground=color)
        self.text.bind('<Control-a>', self.select_all)
        self.text.bind('<Control-A>', self.select_all)
        self.menu = tk.Menu(self, tearoff=False)
        add_menu_item(self.menu, 'add_command', label=msg('Copy All'), command=self.copy_all)
        add_menu_item(self.menu, 'add_command', label=msg('Clear Log'), command=self.clear)
        self.text.bind('<Button-3>', self.context_menu)
        ToolTip(self.text, msg('Session log. Copy selected text with Ctrl+C. Scroll up to pause automatic scrolling; return to the bottom to follow new output.'))

    def context_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def select_all(self, event=None):
        self.text.tag_add('sel', '1.0', 'end-1c')
        return 'break'

    def copy_all(self):
        _, entries = self.history.snapshot()
        if entries:
            self.clipboard_clear()
            self.clipboard_append(''.join(format_entry(e, self._root().tr) for e in entries))

    def clear(self):
        self.history.clear()
        self.refresh()

    def refresh(self):
        revision, entries = self.history.snapshot()
        language = self._root().tr.language
        if revision == self._revision and language == self._language:
            return
        position = self.text.yview()
        follow = not self._rendered or position[1] >= .995
        reset = language != self._language or not entries
        self.text.configure(state='normal')
        if reset:
            self.text.delete('1.0', 'end')
            self._rendered.clear()
            self._last_sequence = 0
        elif self._rendered:
            removed = 0
            while self._rendered and self._rendered[0][0] < entries[0].sequence:
                removed += self._rendered.popleft()[1]
            if removed:
                self.text.delete('1.0', f'{removed + 1}.0')
        for entry in entries:
            if entry.sequence > self._last_sequence:
                line = format_entry(entry, self._root().tr)
                self.text.insert('end', line, (entry.level,))
                self._rendered.append((entry.sequence, line.count('\n')))
                self._last_sequence = entry.sequence
        self.text.configure(state='disabled')
        if follow:
            self.text.see('end')
        elif reset:
            self.text.yview_moveto(position[0])
        self._revision, self._language = revision, language


def settings_path() -> Path:
    return preferences.settings_path()


class App(tk.Tk):
    UNDO_INDEX = 8
    FOLDER_INDEX = 2

    @property
    def UNDO_ACTION(self):
        return self.tr('Undo Last Action')

    def __init__(self, project_path: Path | None = None, state_path: Path | None = None):
        super().__init__()
        self.withdraw()
        self.title(APP_NAME)
        theme.apply(self)
        self.scale = max(1.0, round(self.winfo_fpixels('1i') / 96.0, 2))
        self.state_path = state_path or settings_path()
        state = self.load_settings()
        self.translations = UITranslations(state.get('language', 'en'))
        self.tr = self.translations
        self.var_language = tk.StringVar(self, LANGUAGES[self.tr.language])
        self.project = None
        self.targets = {}
        self.options = model.default_options('Actor')
        self.template_options = {}
        self.template_before = 'Actor'
        self.plan = None
        self.last_receipt = None
        self.last_output = None
        self.last_signature = None
        self._timer = None
        self._job_timer = None
        self._log_timer = None
        self._update_cancel = threading.Event()
        self.activity = ActivityLog()
        self.log_open = False
        self._loading = True
        self._busy = False
        self._closed = False
        self._error = None
        self._status_message, self._status_error = '', False
        self._dialogs = set()
        self._job_queue = queue.Queue()
        self.var_project = tk.StringVar(self, '')
        self.var_target = tk.StringVar(self, '')
        self.var_template = tk.StringVar(self, 'Actor')
        self.var_name = tk.StringVar(self, '')
        self.var_folder = tk.StringVar(self, '')
        self.var_layout = tk.StringVar(self, self.layout_caption('split'))
        self.var_status = tk.StringVar(self, '')
        self.auto_update = False
        self.make_widgets()
        self._log_timer = self.after(80, self.poll_log)
        self.bind('<Control-g>', lambda e: self.on_generate())
        self.bind('<Control-G>', lambda e: self.on_generate())
        self.bind('<Control-Return>', lambda e: self.on_generate())
        self.bind('<F5>', lambda e: self.reload_project())
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        selected = project_path or model.find_project(Path(__file__).parent.parent, Path.cwd()) or state.get('project')
        if selected:
            try:
                self.set_project(Path(selected), state=state)
            except (model.ValidationError, OSError):
                self.set_status('')
        self._loading = False
        for var in (self.var_name, self.var_folder, self.var_layout):
            var.trace_add('write', self.schedule_preview)
        self.var_template.trace_add('write', self.on_template_changed)
        self.update_enabled()
        self.refresh_preview()
        width, height = self.px(900), self.px(510)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = min(width, sw - 60), min(height, sh - 90)
        self.geometry(f'{width}x{height}+{max(0, (sw-width)//2)}+{max(0, (sh-height)//2-20)}')
        self.minsize(min(self.px(780), width), min(self.px(510), height))
        self.deiconify()
        self.update_idletasks()
        (self.name_entry if self.project and self.project.targets else self.project_button).focus_set()

    def current_layout(self):
        return model.resolve_layout(self.var_layout.get())

    def layout_caption(self, code, translate=True):
        caption = next((label for label, value in model.LAYOUTS.items() if value == code), 'Public / Private')
        return self.tr(caption) if translate else caption

    def on_language_selected(self, event=None):
        language = next((code for code, name in LANGUAGES.items() if name == self.var_language.get()), 'en')
        self.set_language(language)

    def set_language(self, language):
        language = normalize_language(language)
        if language == self.tr.language:
            self.var_language.set(LANGUAGES[language])
            return
        layout = self.current_layout()
        loading, self._loading = self._loading, True
        try:
            self.tr.language = language
            self.var_language.set(LANGUAGES[language])
            self.inputs['layout'].configure(values=tuple(self.layout_caption(code) for code in model.LAYOUTS.values()))
            self.var_layout.set(self.layout_caption(layout))
            self.translations.refresh()
            for dialog in tuple(self._dialogs):
                if hasattr(dialog, 'retranslate'):
                    dialog.retranslate()
            self.set_status(self._status_message, self._status_error)
            if self.log_open:
                self.log_view.refresh()
        finally:
            self._loading = loading
        self.save_settings()

    def px(self, value):
        return round(value * self.scale)

    def make_widgets(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        top = ttk.Frame(self, padding=(14, 12, 14, 10))
        top.grid(row=0, column=0, sticky='ew')
        top.columnconfigure(1, weight=1)
        label = localized_widget(ttk.Label, top, text=msg('Project'))
        label.grid(row=0, column=0, padx=(0, 10))
        self.project_entry = ttk.Entry(top, textvariable=self.var_project, state='readonly', width=12)
        self.project_entry.grid(row=0, column=1, sticky='ew')
        self.project_button = localized_widget(ttk.Button, top, text=msg('Select…'), width=7, command=self.browse_project)
        self.project_button.grid(row=0, column=2, padx=(8, 0))
        self.language_box = ttk.Combobox(top, textvariable=self.var_language, values=tuple(LANGUAGES.values()),
                                        state='readonly', width=9, height=2)
        self.language_box.grid(row=0, column=3, padx=(12, 0))
        self.language_box.bind('<<ComboboxSelected>>', self.on_language_selected)
        ToolTip(self.language_box, msg('Display language. Changes apply immediately and are saved for the next launch.'))
        ToolTip(self.project_entry, lambda: str(self.project.file) if self.project else msg('Select a .uproject file.'))
        ToolTip(label, msg('The Unreal Engine project to generate files in. Your selection is saved for the next launch.'))
        ToolTip(self.project_button, msg('Select a .uproject file.'))

        body = ttk.Frame(self, padding=(14, 0, 14, 0))
        body.grid(row=1, column=0, sticky='nsew')
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        self.form = ttk.Frame(body, width=self.px(276))
        self.form.grid(row=0, column=0, sticky='ns', padx=(0, 14))
        self.form.grid_propagate(False)
        self.form.columnconfigure(0, weight=1)
        rows = (
            (msg('Module'), self.var_target, 'target', msg('The destination module. Modules inside plugins are also listed here.')),
            (msg('Type'), self.var_template, 'template', msg('The C++ type to generate. Type a name to filter the list.')),
            (msg('Name'), self.var_name, 'name', msg('Enter PlayerBase or APlayerBase for Actor. The class is APlayerBase; the files are PlayerBase.h and PlayerBase.cpp. Type prefixes are automatic and omitted from filenames. PlainClass names are unchanged.')),
            (msg('Folder'), self.var_folder, 'folder', msg('A relative folder within the module. Leave blank for the root. Use + to add an empty folder, or enter a new folder to create it with the generated files.')),
            (msg('Layout'), self.var_layout, 'layout', msg('Public / Private: .h in Public, .cpp in Private.\nSame Folder: keep .h and .cpp together under the module root.\nPrivate Only / Public Only: place both files on the selected side.')),
        )
        self.inputs = {}
        for i, (caption, var, key, tip) in enumerate(rows):
            label = localized_widget(ttk.Label, self.form, text=caption)
            label.grid(row=i*2, column=0, sticky='w', pady=(0 if i == 0 else 10, 4))
            container = self.form
            if key in ('target', 'folder'):
                container = ttk.Frame(self.form)
                container.grid(row=i*2+1, column=0, sticky='ew')
                container.columnconfigure(0, weight=1)
            if key == 'name':
                widget = ttk.Entry(container, textvariable=var, width=15)
            else:
                widget = ttk.Combobox(container, textvariable=var, width=15, height=12,
                                      state='normal' if key in ('template', 'folder') else 'readonly')
            widget.grid(row=0 if container is not self.form else i*2+1, column=0, sticky='ew')
            if key == 'target':
                self.target_add_button = localized_widget(ttk.Button, container, text='+', width=3, style='Add.TButton',
                                                     command=self.show_add_menu)
                self.target_add_button.grid(row=0, column=1, sticky='ns', padx=(5, 0))
                self.add_menu = tk.Menu(self.target_add_button, tearoff=False)
                add_menu_item(self.add_menu, 'add_command', label=msg('Add Module…'), command=lambda: self.open_scaffold(False))
                add_menu_item(self.add_menu, 'add_command', label=msg('Add Plugin…'), command=lambda: self.open_scaffold(True))
                self.target_add_button.bind('<Down>', lambda e: self.show_add_menu())
                ToolTip(self.target_add_button, msg('Add a module or plugin.'))
            elif key == 'folder':
                self.folder_add_button = localized_widget(ttk.Button, container, text='+', width=3, style='Add.TButton',
                                                     command=self.open_folder_dialog)
                self.folder_add_button.grid(row=0, column=1, sticky='ns', padx=(5, 0))
                ToolTip(self.folder_add_button, msg('Add an empty folder to the selected module. The selected layout can create matching Public and Private folders.'))
            ToolTip(label, tip)
            ToolTip(widget, lambda k=key, t=tip: self._error if self._error and self._error.field == k else t)
            self.inputs[key] = widget
        self.name_entry = self.inputs['name']
        self.inputs['target'].bind('<<ComboboxSelected>>', self.on_target_changed)
        self.inputs['template'].configure(values=self.template_order())
        self.inputs['template'].configure(postcommand=self.filter_templates)
        self.inputs['template'].bind('<<ComboboxSelected>>', lambda e: self.name_entry.focus_set())
        self.inputs['layout'].configure(values=tuple(self.layout_caption(code) for code in model.LAYOUTS.values()))
        self.inputs['folder'].configure(postcommand=self.refresh_folder_choices)
        bottom_left = ttk.Frame(self.form)
        bottom_left.grid(row=10, column=0, sticky='sw', pady=(10, 0))
        self.advanced_button = localized_widget(ttk.Button, bottom_left, text=msg('Options…'), command=self.open_options)
        self.advanced_button.pack(side='left')
        ToolTip(self.advanced_button, msg('Show only options relevant to the selected type.'))
        self.tools_button = localized_widget(ttk.Menubutton, bottom_left, text=msg('Tools'), width=6)
        self.tools_button.pack(side='left', padx=(8, 0))
        self.tools = tk.Menu(self.tools_button, tearoff=False)
        self.tools_button.configure(menu=self.tools)
        add_menu_item(self.tools, 'add_command', label=msg('Add Module…'), command=lambda: self.open_scaffold(False))
        add_menu_item(self.tools, 'add_command', label=msg('Add Plugin…'), command=lambda: self.open_scaffold(True))
        add_menu_item(self.tools, 'add_command', label=msg('Add Folder…'), command=self.open_folder_dialog)
        self.tools.add_separator()
        add_menu_item(self.tools, 'add_command', label=msg('Reload Project'), command=self.reload_project)
        add_menu_item(self.tools, 'add_command', label=msg('Update Project Files'), command=self.run_update)
        self.tools.add_separator()
        add_menu_item(self.tools, 'add_command', label=msg('Open Output Folder'), command=self.open_output)
        add_menu_item(self.tools, 'add_command', label=msg('Undo Last Action'), command=self.on_undo, state='disabled')

        preview = ttk.Frame(body)
        preview.grid(row=0, column=1, sticky='nsew')
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(1, weight=1)
        localized_widget(ttk.Label, preview, text=msg('Preview')).grid(row=0, column=0, sticky='w', pady=(0, 4))
        self.tabs = ttk.Notebook(preview)
        self.tabs.grid(row=1, column=0, sticky='nsew')
        self.views = {role: CodeView(self.tabs) for role in ('header', 'cpp', 'dependency')}
        self.tabs.add(self.views['header'], text='.h')
        self.tabs.add(self.views['cpp'], text='.cpp')
        self.tabs.add(self.views['dependency'], text='Build.cs')
        self.tabs.hide(self.views['dependency'])
        self.tabs.bind('<<NotebookTabChanged>>', lambda e: self.current_view().redraw())
        ToolTip(self.tabs, lambda: self.current_view().path)

        self.actions = ttk.Frame(self, padding=(14, 12, 14, 12))
        self.actions.grid(row=2, column=0, sticky='ew')
        self.actions.columnconfigure(1, weight=1)
        self.log_controls = ttk.Frame(self.actions)
        self.log_controls.grid(row=0, column=0, sticky='w')
        self.log_toggle = localized_widget(ttk.Button, self.log_controls, text=msg('▸ Log'),
                                           style='Log.TButton', width=0, command=self.toggle_log)
        self.log_toggle.grid(row=0, column=0, sticky='w')
        ToolTip(self.log_toggle, msg('Show or hide the session log. Logging continues while hidden. Starts closed on every launch.'))
        self.log_view = LogView(self, self.activity)
        self.log_copy = localized_widget(ttk.Button, self.log_controls, text=msg('Copy'),
                                         style='Log.TButton', width=0, command=self.log_view.copy_all)
        self.log_clear = localized_widget(ttk.Button, self.log_controls, text=msg('Clear'),
                                          style='Log.TButton', width=0, command=self.log_view.clear)
        self.log_copy.grid(row=0, column=1, padx=(5, 0))
        self.log_clear.grid(row=0, column=2, padx=(3, 0))
        self.log_copy.grid_remove()
        self.log_clear.grid_remove()
        ToolTip(self.log_copy, msg('Copy the full retained session log.'))
        ToolTip(self.log_clear, msg('Clear the session log. This does not delete generated files or backups.'))
        self.status_label = ttk.Label(self.actions, textvariable=self.var_status, style='Quiet.TLabel', width=1)
        self.status_label.grid(row=0, column=1, sticky='ew', padx=(12, 8))
        ToolTip(self.status_label, lambda: self._status_full)
        self.generate_button = localized_widget(ttk.Button, self.actions, text=msg('Generate'), style='Generate.TButton',
                                           width=12, command=self.on_generate)
        self.generate_button.grid(row=0, column=2, sticky='e')
        ToolTip(self.generate_button, lambda: self._error if self._error else msg('Generate the previewed files. Ctrl+Enter / Ctrl+G'))
        self._status_full = ''

    def toggle_log(self):
        if self._closed:
            return
        self.update_idletasks()
        width, height = self.winfo_width(), self.winfo_height()
        x, y = self.winfo_x(), self.winfo_y()
        if not self.log_open:
            self._log_minimum = self.minsize()
            self._log_resize_window = self.state() != 'zoomed'
            for attribute in ('-zoomed', '-fullscreen'):
                try:
                    if self.tk.getboolean(self.attributes(attribute)):
                        self._log_resize_window = False
                except tk.TclError:
                    pass
            room = self.winfo_screenheight() - 70
            panel = min(self.px(202), max(self.px(80), room - self._log_minimum[1]))
            new_height = min(height + panel, max(height, room)) if self._log_resize_window else height
            self._log_added_height = new_height - height
            new_y = max(0, min(y, self.winfo_screenheight() - new_height - 50))
            self._log_original_y, self._log_open_y = y, new_y
            self.log_open = True
            self.rowconfigure(3, minsize=panel)
            self.log_view.grid(row=3, column=0, sticky='nsew', padx=14, pady=(0, 12))
            self.log_copy.grid()
            self.log_clear.grid()
            self.minsize(self._log_minimum[0], min(self._log_minimum[1] + panel, room))
            if self._log_resize_window:
                self.geometry(f'{width}x{new_height}+{x}+{new_y}')
            self.log_view.refresh()
        else:
            self.log_open = False
            self.log_view.grid_remove()
            self.rowconfigure(3, minsize=0)
            self.log_copy.grid_remove()
            self.log_clear.grid_remove()
            self.minsize(*self._log_minimum)
            new_height = max(self._log_minimum[1], height - self._log_added_height)
            new_y = self._log_original_y if y == self._log_open_y else y
            if self._log_resize_window:
                self.geometry(f'{width}x{new_height}+{x}+{new_y}')
        configure_widget(self.log_toggle, text=msg('▾ Log') if self.log_open else msg('▸ Log'))

    def log(self, message, level='info', source='App'):
        # Also safe from the project-update worker: no Tk calls here.
        self.activity.add(message, level, source)

    def poll_log(self):
        self._log_timer = None
        if self._closed:
            return
        if self.log_open:
            self.log_view.refresh()
        self._log_timer = self.after(80, self.poll_log)

    def log_receipt(self, receipt, source):
        plan = receipt.plan
        if receipt.backup:
            self.log(msg('Backup: {path}', path=receipt.backup), source=source)
        for directory in receipt.created_dirs:
            self.log(msg('Created folder: {path}', path=directory.relative_to(plan.root).as_posix()), source=source)
        for change in plan.changes:
            path = change.path.relative_to(plan.root).as_posix()
            if change.before is None:
                message = msg('Created: {path}', path=path)
            elif plan.appended and change.role in ('header', 'cpp'):
                message = msg('Appended: {path}', path=path)
            else:
                message = msg('Updated: {path}', path=path)
            self.log(message, source=source)

    def template_order(self):
        common = ['Actor', 'ActorComponent', 'SceneComponent', 'UObject', 'Struct', 'Enum',
                  'WorldSubsystem', 'GameInstanceSubsystem', 'PlainClass', 'PlainStruct', 'PlainEnum']
        return common + [t for t in templates.TEMPLATES if t not in common]

    def filter_templates(self):
        typed = self.var_template.get().strip()
        values = self.template_order()
        if typed and templates.normalize_template(typed) not in templates.TEMPLATES:
            values = [t for t in values if typed.casefold() in t.casefold()] or self.template_order()
        self.inputs['template'].configure(values=values)

    def current_view(self):
        selected = self.tabs.select()
        return next((v for v in self.views.values() if str(v) == selected), self.views['header'])

    def load_settings(self):
        return preferences.read_settings(self.state_path)

    def save_settings(self):
        target = self.current_target()
        data = dict(language=self.tr.language)
        if self.project:
            data.update(project=str(self.project.file), target=target.key if target else '',
                        template=self.var_template.get(), folder=self.var_folder.get(),
                        layout=self.current_layout())
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.state_path.with_suffix('.tmp')
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temp, self.state_path)
            return True
        except OSError as e:
            # Generating files remains independent from saving preferences.
            self.set_status(msg('Could not save preferences. The language is applied for this session only.\n{error}', error=e), True)
            return False

    def set_project(self, path: Path, state=None):
        project = model.load_project(path)
        state = state or {}
        if state.get('project') and Path(state['project']).resolve() != project.file:
            state = {}
        was_loading, self._loading = self._loading, True
        try:
            self.project = project
            self.var_project.set(project.file.name)
            self.title(f'{APP_NAME} — {project.file.stem}')
            configure_widget(self.project_button, text=msg('Change…'))
            self.targets = {}
            for t in project.targets:
                label = t.label
                if label in self.targets:
                    label = t.folder.relative_to(project.root).as_posix()
                self.targets[label] = t
            self.inputs['target'].configure(values=tuple(self.targets))
            selected = next((label for label, t in self.targets.items() if t.key == state.get('target')), None)
            selected = selected or next((label for label, t in self.targets.items() if t.name == project.file.stem and not t.plugin), None)
            self.var_target.set(selected or next(iter(self.targets), ''))
            self.on_target_changed()
            if model.resolve_layout(state.get('layout', '')):
                self.var_layout.set(self.layout_caption(model.resolve_layout(state['layout'])))
            if isinstance(state.get('folder'), str):
                self.var_folder.set(state['folder'])
            if state.get('template') in templates.TEMPLATES:
                self.var_template.set(state['template'])
            self.options = model.default_options(self.var_template.get())
            self.template_options.clear()
            self.template_before = self.var_template.get()
            self.last_signature = None
            self.last_receipt = None
            self.last_output = None
            self.tools.entryconfigure(self.UNDO_INDEX, state='disabled')
        finally:
            self._loading = was_loading
        self.update_enabled()
        self.refresh_preview()

    def current_target(self):
        return self.targets.get(self.var_target.get())

    def update_enabled(self):
        active = bool(self.project and self.current_target()) and not self._busy
        for key, widget in self.inputs.items():
            state = ('readonly' if key in ('target', 'layout') else 'normal') if active else 'disabled'
            widget.configure(state=state)
        self.advanced_button.configure(state='normal' if active else 'disabled')
        self.tools_button.configure(state='normal' if self.project and not self._busy else 'disabled')
        self.target_add_button.configure(state='normal' if self.project and not self._busy else 'disabled')
        self.folder_add_button.configure(state='normal' if active else 'disabled')
        self.tools.entryconfigure(self.FOLDER_INDEX, state='normal' if active else 'disabled')
        self.project_button.configure(state='disabled' if self._busy else 'normal')
        self.generate_button.configure(state='normal' if active and self.plan else 'disabled')

    def browse_project(self):
        chosen = filedialog.askopenfilename(parent=self, title=self.tr('Select Project'),
                                            initialdir=str(self.project.root if self.project else Path.home()),
                                            filetypes=[(self.tr('Unreal Engine Project'), '*.uproject')])
        if chosen:
            try:
                self.set_project(Path(chosen))
                self.save_settings()
                self.name_entry.focus_set()
            except (model.ValidationError, OSError) as e:
                localized_messagebox('showerror', msg('Project'), e, parent=self)

    def on_target_changed(self, event=None):
        target = self.current_target()
        if target:
            self.var_layout.set(self.layout_caption(target.default_layout))
            self.var_folder.set('')
            self.options['append_to'] = ''
            self.refresh_folder_choices()
        self.last_signature = None
        if not self._loading:
            self.refresh_preview()

    def refresh_folder_choices(self):
        target = self.current_target()
        if target:
            try:
                self.inputs['folder'].configure(values=model.existing_folders(target, self.current_layout()))
            except OSError as e:
                self.set_status(e, True)

    def on_template_changed(self, *args):
        if self._loading:
            return
        new = templates.normalize_template(self.var_template.get())
        if new in templates.TEMPLATES and new != self.template_before:
            old = self.template_before
            # Preserve relevant settings per template only for this session.
            self.template_options[old] = dict(self.options)
            self.options = dict(self.template_options.get(new, model.default_options(new)))
            self.options['append_to'] = ''
            self.template_before = new
        self.schedule_preview()

    def schedule_preview(self, *args):
        if self._loading or self._closed:
            return
        if self._timer:
            self.after_cancel(self._timer)
        self._timer = self.after(140, self.refresh_preview)

    def request(self):
        if not self.project:
            raise model.ValidationError(msg('Please select a project.'), 'project')
        target = self.current_target()
        if not target:
            raise model.ValidationError(msg('Please add a module.'), 'target')
        return model.Request(target, templates.normalize_template(self.var_template.get()), self.var_name.get(),
                             self.var_folder.get(), self.current_layout(), dict(self.options))

    def signature(self):
        template = templates.normalize_template(self.var_template.get())
        try:
            name = model.type_name(self.var_name.get(), template)
        except model.ValidationError:
            name = self.var_name.get().strip()
        return (self.var_target.get(), template, name,
                self.var_folder.get().strip(), self.current_layout(),
                json.dumps(self.options, sort_keys=True))

    def set_status(self, text, error=False):
        self._status_message, self._status_error = text, error
        self._status_full = self.tr.render(text)
        line = self._status_full.splitlines()[0] if self._status_full else ''
        self.var_status.set(line if len(line) < 60 else line[:57] + '…')
        self.status_label.configure(style='Error.TLabel' if error else 'Quiet.TLabel')

    def refresh_preview(self, keep_status=False):
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None
        self.plan, self._error = None, None
        try:
            self.plan = model.build_plan(self.project, self.request())
        except (model.ValidationError, OSError) as e:
            self._error = e if isinstance(e, model.ValidationError) else model.ValidationError(str(e))
        visible = {c.role: c for c in self.plan.changes} if self.plan else {}
        for role, view in self.views.items():
            c = visible.get(role)
            view.set_content(c.content if c else '', str(c.path) if c else '')
            if c:
                # Full filename/path remains available as a tooltip; a long name cannot grow the window.
                tab_name = c.path.name
                if len(tab_name) > 30:
                    tab_name = tab_name[:22] + '…' + c.path.suffix
                self.tabs.tab(view, text=tab_name, state='normal')
            elif role == 'header':
                self.tabs.tab(view, text='.h', state='normal')
            elif role == 'cpp' and not self.plan:
                self.tabs.tab(view, text='.cpp', state='normal')
            else:
                self.tabs.hide(view)
        self.update_enabled()
        generated = self.last_signature == self.signature() and self.last_signature is not None
        configure_widget(self.generate_button, text=msg('Generated') if generated else msg('Generate'),
                                       state='normal' if self.plan and not self._busy and not generated else 'disabled')
        if not keep_status and not self._busy and not generated:
            if self._error and self.var_name.get().strip() and self.project:
                self.set_status(self._error, True)
            else:
                self.set_status('')

    def on_generate(self):
        if self._busy or self._dialogs:
            return
        self.refresh_preview()
        if not self.plan:
            if self._error:
                self.set_status(self._error, True)
                self.log(self._error, 'error', msg('Source'))
                self.inputs.get(self._error.field, self.project_button).focus_set()
            return
        if self.last_signature == self.signature():
            return
        plan = self.plan
        if plan.modified and not self.confirm_changes(plan):
            self.log(msg('Generation cancelled: {name}. No files were changed.', name=plan.name), 'info', msg('Source'))
            return
        started = time.monotonic()
        self.log(msg('Generating {name} ({type})…', name=plan.name, type=self.var_template.get()), source=msg('Source'))
        self.log(msg('Project: {path}', path=self.project.file), source=msg('Source'))
        try:
            self.last_receipt = model.commit(plan, allow_existing=bool(plan.modified))
        except (model.ValidationError, OSError) as e:
            self.set_status(e, True)
            self.log(msg('Generation failed.\n{error}', error=e), 'error', msg('Source'))
            localized_messagebox('showerror', msg('Generation Failed'), e, parent=self)
            self.refresh_preview(keep_status=True)
            return
        self.log_receipt(self.last_receipt, msg('Source'))
        self.log(msg('Generated {name}: {count} file(s), {seconds}s.', name=plan.name,
                     count=len(plan.changes), seconds=f'{time.monotonic() - started:.2f}'), 'success', msg('Source'))
        self.last_signature = self.signature()
        self.last_output = plan.changes[0].path.parent
        self.tools.entryconfigure(self.UNDO_INDEX, state='normal')
        self.save_settings()
        self.refresh_preview(keep_status=True)
        self.set_status(msg('Generated {name}.', name=plan.name))
        self.name_entry.focus_set()
        self.name_entry.selection_range(0, 'end')
        if self.auto_update:
            self.run_update()

    def confirm_changes(self, plan):
        paths = '\n'.join(c.path.relative_to(plan.root).as_posix() for c in plan.modified)
        return localized_messagebox('askyesno', msg('Modify Existing Files'),
                                    msg('{paths}\n\nModify these files?\nTheir current contents will be backed up.', paths=paths),
                                    parent=self, default=messagebox.NO)

    def open_options(self):
        t = templates.normalize_template(self.var_template.get())
        if t not in templates.TEMPLATES or not self.current_target() or self._dialogs:
            return
        OptionsDialog(self, t)

    def show_add_menu(self):
        if not self.project or self._dialogs or self._busy:
            return
        try:
            self.add_menu.tk_popup(self.target_add_button.winfo_rootx(),
                                   self.target_add_button.winfo_rooty() + self.target_add_button.winfo_height())
        finally:
            self.add_menu.grab_release()

    def open_scaffold(self, plugin):
        if self.project and not self._dialogs and not self._busy:
            try:
                ScaffoldDialog(self, plugin)
            except (model.ValidationError, OSError) as e:
                localized_messagebox('showerror', msg('Could Not Add Item'), e, parent=self)

    def open_folder_dialog(self):
        if self.project and self.current_target() and not self._dialogs and not self._busy:
            try:
                FolderDialog(self)
            except (model.ValidationError, OSError) as e:
                localized_messagebox('showerror', msg('Could Not Add Folder'), e, parent=self)

    def reload_project(self):
        if self.project and not self._busy and not self._dialogs:
            state = dict(target=self.current_target().key if self.current_target() else '',
                         layout=self.current_layout(), folder=self.var_folder.get(), template=self.var_template.get())
            options, cache = dict(self.options), dict(self.template_options)
            receipt, signature, output = self.last_receipt, self.last_signature, self.last_output
            try:
                self.set_project(self.project.file, state)
                if self.current_target() and self.current_target().key == state['target']:
                    self.options, self.template_options = options, cache
                self.last_receipt, self.last_signature, self.last_output = receipt, signature, output
                self.tools.entryconfigure(self.UNDO_INDEX, state='normal' if receipt else 'disabled')
                self.refresh_preview()
            except (model.ValidationError, OSError) as e:
                self.set_status(e, True)

    def open_output(self):
        target = self.last_output or (self.current_target().folder if self.current_target() else self.project.root if self.project else None)
        if target:
            try:
                platform_tools.open_folder(target)
            except OSError as e:
                localized_messagebox('showerror', msg('Folder'), e, parent=self)

    def on_undo(self):
        if not self.last_receipt or self._busy or self._dialogs:
            return
        if not localized_messagebox('askyesno', msg('Undo'), msg('Undo the action for {name}?', name=self.last_receipt.plan.name), parent=self, default=messagebox.NO):
            return
        receipt = self.last_receipt
        self.log(msg('Undoing {name}…', name=receipt.plan.name), source=msg('Undo'))
        try:
            model.undo(receipt)
        except (model.ValidationError, OSError) as e:
            self.log(e, 'error', msg('Undo'))
            localized_messagebox('showerror', msg('Could Not Undo'), e, parent=self)
            return
        self.last_receipt = None
        self.last_signature = None
        self.tools.entryconfigure(self.UNDO_INDEX, state='disabled')
        self.reload_project()
        self.refresh_preview(keep_status=True)
        for change in receipt.plan.changes:
            path = change.path.relative_to(receipt.plan.root).as_posix()
            self.log(msg('Removed: {path}', path=path) if change.before is None else msg('Restored: {path}', path=path), source=msg('Undo'))
        for directory in reversed(receipt.created_dirs):
            if not directory.exists():
                self.log(msg('Removed folder: {path}', path=directory.relative_to(receipt.plan.root).as_posix()), source=msg('Undo'))
        self.log(msg('Action undone.'), 'success', msg('Undo'))
        self.set_status(msg('Action undone.'))

    def run_update(self):
        if not self.project or self._busy or self._dialogs:
            return
        self._busy = True
        self._update_cancel = threading.Event()
        self.log(msg('Updating project files…'), source='UE')
        self.set_status(msg('Updating project files…'))
        self.update_enabled()
        project = self.project
        history, cancel = self.activity, self._update_cancel
        def on_log(message, level='info'):
            history.add(message, level, 'UE')
        def work():
            try:
                self._job_queue.put((True, platform_tools.update_project(project, on_log=on_log, cancel=cancel)))
            except Exception as e:
                self._job_queue.put((False, e))
        self._worker = threading.Thread(target=work, name='unrealsourcegen-project-update', daemon=True)
        self._worker.start()
        self._job_timer = self.after(100, self.poll_update)

    def poll_update(self):
        self._job_timer = None
        if self._closed:
            return
        try:
            ok, message = self._job_queue.get_nowait()
        except queue.Empty:
            if not self._closed:
                self._job_timer = self.after(100, self.poll_update)
            return
        self.log(message, 'success' if ok else 'error', 'UE')
        if self.log_open:
            self.log_view.refresh()
        self._busy = False
        self.update_enabled()
        self.refresh_preview(keep_status=True)
        self.set_status(message, not ok)
        if not ok:
            localized_messagebox('showerror', msg('Update Project Files'), message, parent=self)

    def report_callback_exception(self, exc, value, tb):
        detail = ''.join(traceback.format_exception(exc, value, tb))
        if hasattr(self, 'activity'):
            self.log(detail, 'error')
        try:
            log = self.state_path.parent / 'error.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(detail, encoding='utf-8')
        except OSError:
            pass
        localized_messagebox('showerror', msg('Error'), value, parent=self)

    def on_close(self):
        if self._busy:
            localized_messagebox('showinfo', msg('Update in Progress'), msg('Please close the app after the project file update finishes.'), parent=self)
            return
        self.save_settings()
        self.destroy()

    def destroy(self):
        self._closed = True
        self._update_cancel.set()
        # Only cancel callbacks owned by this root. Tooltip callbacks are owned by
        # their widgets and are canceled by each tooltip's <Destroy> handler.
        for timer in (self._timer, self._job_timer, self._log_timer):
            if timer:
                try:
                    self.after_cancel(timer)
                except tk.TclError:
                    pass
        self._timer = self._job_timer = self._log_timer = None
        super().destroy()


class Dialog(tk.Toplevel):
    def __init__(self, app, title):
        super().__init__(app)
        self.withdraw()
        self.app = app
        app.translations.bind_title(self, title)
        self.transient(app)
        self.resizable(False, False)
        self.body = ttk.Frame(self, padding=16)
        self.body.pack(fill='both', expand=True)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Escape>', lambda e: self.close())
        self.app._dialogs.add(self)

    def reveal(self):
        self.update_idletasks()
        width, height = self.winfo_reqwidth(), self.winfo_reqheight()
        x = self.app.winfo_rootx() + (self.app.winfo_width()-width)//2
        y = self.app.winfo_rooty() + (self.app.winfo_height()-height)//2
        x = max(0, min(x, self.winfo_screenwidth()-width-16))
        y = max(0, min(y, self.winfo_screenheight()-height-50))
        self.geometry(f'+{x}+{y}')
        self.deiconify()
        self.grab_set()

    def close(self):
        self.app._dialogs.discard(self)
        self.grab_release()
        self.destroy()


class OptionsDialog(Dialog):
    def __init__(self, app: App, template: str):
        super().__init__(app, msg('{template} Options', template=template))
        self.template = template
        self.vars = {}
        self.checks = {}
        self.body.columnconfigure(1, weight=1)
        self.body.columnconfigure(0, minsize=app.px(190))
        self.row = 0
        current = {**model.default_options(template), **app.options}
        for key, value in current.items():
            self.vars[key] = tk.BooleanVar(self, value) if isinstance(value, bool) else tk.StringVar(self, value)
        if template not in ('Enum', 'PlainEnum'):
            self.check('with_api', msg('API Macro'), msg('Add the API macro so other modules can use this type.'))
        if template not in model.PLAIN | {'Enum', 'Struct', 'Interface'}:
            self.check('blueprint_type', msg('Blueprint Support'), msg('Add the BlueprintType and Blueprintable specifiers.'))
        if template in model.ACTORS | model.COMPONENTS | {'UObject', 'AnimInstance'}:
            self.check('with_constructor', msg('Constructor'), msg('Generate the constructor declaration and definition.'))
        if template in model.ACTORS | model.COMPONENTS:
            self.check('with_beginplay', 'BeginPlay', msg('Generate the BeginPlay declaration and definition.'))
            self.check('with_tick', 'TickComponent' if template in model.COMPONENTS else 'Tick',
                       msg('Generate the per-frame update function and the constructor needed to enable ticking.'))
            self.vars['with_tick'].trace_add('write', self.tick_changed)
            self.vars['with_constructor'].trace_add('write', self.ctor_changed)
        if template in model.SUBSYSTEMS:
            self.check('with_initialize', 'Initialize / Deinitialize', msg('Generate initialization and deinitialization functions.'))
            self.check('with_tickable', msg('Tick Support'), msg('Use FTickableGameObject to generate Tick and GetStatId.'))
        if template == 'Enum':
            self.check('with_enum_conversion', msg('FString / FName Conversion'), msg('Add C++ helpers to convert between enum values and strings.'))
        if template == 'Struct':
            for key, label, tip in (
                ('with_struct_datatable', msg('DataTable Support'), msg('Derive from FTableRowBase.')),
                ('with_struct_equality', 'operator== / !=', msg('Generate equality and inequality operators for the struct.')),
                ('with_struct_tostring', 'ToString', msg('Generate a function that converts the struct to a string.')),
                ('with_struct_hash', 'GetTypeHash', msg('Generate a hash function and equality operators.')),
                ('with_struct_netserialize', 'NetSerialize', msg('Generate a network serialization function and the associated type traits.')),
            ):
                self.check(key, label, tip)
            self.vars['with_struct_hash'].trace_add('write', self.hash_changed)
        if template == 'PlainClass':
            self.check('header_only', msg('Header Only'), msg('Define the constructor and destructor in the header without creating a .cpp file.'))
        if template in model.PLAIN:
            self.entry('namespace', msg('Namespace'), msg('For example: MyGame::AI. Namespaces are available only for plain C++ types.'))
        self.entry('extra_includes', msg('Extra Includes'), msg('Enter comma-separated headers. For example: GameplayTagContainer.h, MyHeader.h'))
        self.append_enabled = tk.BooleanVar(self, bool(current['append_to']))
        append_check = localized_widget(ttk.Checkbutton, self.body, text=msg('Append to Existing Header'), variable=self.append_enabled, command=self.toggle_append)
        append_check.grid(row=self.row, column=0, columnspan=2, sticky='w', pady=(10, 4))
        ToolTip(append_check, msg('Add the type to the selected header instead of creating a new one. Changes require confirmation and are backed up.'))
        self.row += 1
        self.append_box = ttk.Combobox(self.body, textvariable=self.vars['append_to'], state='readonly', width=30)
        try:
            hd, _ = model.output_dirs(app.request())
            self.append_box.configure(values=sorted(p.name for p in hd.glob('*.h')))
        except (model.ValidationError, OSError):
            pass
        self.append_box.grid(row=self.row, column=0, columnspan=2, sticky='ew')
        self.row += 1
        self.auto = tk.BooleanVar(self, app.auto_update)
        auto = localized_widget(ttk.Checkbutton, self.body, text=msg('Update Project Files After Generation'), variable=self.auto)
        auto.grid(row=self.row, column=0, columnspan=2, sticky='w', pady=(10, 2))
        ToolTip(auto, msg('Update IDE project files using the engine associated with the selected project.'))
        self.row += 1
        bar = ttk.Frame(self.body)
        bar.grid(row=self.row, column=0, columnspan=2, sticky='ew', pady=(16, 0))
        localized_widget(ttk.Button, bar, text=msg('Reset'), command=self.reset).pack(side='left')
        localized_widget(ttk.Button, bar, text=msg('Apply'), width=7, command=self.apply).pack(side='right')
        localized_widget(ttk.Button, bar, text=msg('Cancel'), width=10, command=self.close).pack(side='right', padx=(8, 8))
        self.toggle_append()
        self.reveal()

    def check(self, key, label, tip):
        check = localized_widget(ttk.Checkbutton, self.body, text=label, variable=self.vars[key])
        check.grid(row=self.row, column=0, columnspan=2, sticky='w', pady=1)
        self.checks[key] = check
        ToolTip(check, tip)
        self.row += 1

    def entry(self, key, caption, tip):
        label = localized_widget(ttk.Label, self.body, text=caption)
        label.grid(row=self.row, column=0, columnspan=2, sticky='w', pady=(10, 4))
        self.row += 1
        entry = ttk.Entry(self.body, textvariable=self.vars[key], width=38)
        entry.grid(row=self.row, column=0, columnspan=2, sticky='ew')
        ToolTip(label, tip)
        ToolTip(entry, tip)
        self.row += 1

    def tick_changed(self, *args):
        if self.vars['with_tick'].get():
            self.vars['with_constructor'].set(True)

    def ctor_changed(self, *args):
        if not self.vars['with_constructor'].get():
            self.vars['with_tick'].set(False)

    def hash_changed(self, *args):
        if self.vars['with_struct_hash'].get():
            self.vars['with_struct_equality'].set(True)

    def toggle_append(self):
        self.append_box.configure(state='readonly' if self.append_enabled.get() else 'disabled')

    def reset(self):
        for key, value in model.default_options(self.template).items():
            self.vars[key].set(value)
        self.append_enabled.set(False)
        self.auto.set(False)
        self.toggle_append()

    def apply(self):
        opts = {key: v.get() for key, v in self.vars.items()}
        opts['with_deinitialize'] = opts['with_initialize']
        if opts['with_struct_hash']:
            opts['with_struct_equality'] = True
        if not self.append_enabled.get():
            opts['append_to'] = ''
        elif not opts['append_to']:
            localized_messagebox('showerror', msg('Append Target'), msg('Please select a header to append to.'), parent=self)
            return
        try:
            # Validate options even while the name field is still empty.
            req = replace(self.app.request(), name=self.app.var_name.get() or model.required_prefix(self.template) + 'Preview', options=opts)
            model.build_plan(self.app.project, req)
        except (model.ValidationError, OSError) as e:
            localized_messagebox('showerror', msg('Options'), e, parent=self)
            return
        self.app.options = opts
        self.app.auto_update = self.auto.get()
        self.app.refresh_preview()
        self.close()


class ScaffoldDialog(Dialog):
    def __init__(self, app, plugin):
        plugins = model.available_plugins(app.project)
        super().__init__(app, msg('Add Plugin') if plugin else msg('Add Module'))
        self.plugin = plugin
        self.name = tk.StringVar(self, '')
        self.kind = tk.StringVar(self, 'Runtime')
        self.split = tk.BooleanVar(self, True)
        self.plugin_choices = plugins
        self.parents = {}
        self.parent_label = tk.StringVar(self, '')
        self.parent_box = None
        self.retranslate()
        current = app.current_target()
        if not plugin and current and current.plugin:
            self.parent_label.set(next((label for label, path in self.parents.items() if path == current.descriptor), app.tr('Project')))
        self.body.columnconfigure(1, weight=1)
        localized_widget(ttk.Label, self.body, text=msg('Name')).grid(row=0, column=0, sticky='w', padx=(0, 12))
        ent = ttk.Entry(self.body, textvariable=self.name, width=28)
        ent.grid(row=0, column=1, sticky='ew', pady=5)
        ToolTip(ent, msg('Start with a letter and use letters, digits or underscores. The plugin includes a C++ module with the same name.') if plugin else msg('Start with a letter and use letters, digits or underscores.'))
        ent.bind('<Return>', lambda e: self.apply())
        localized_widget(ttk.Label, self.body, text=msg('Type')).grid(row=1, column=0, sticky='w')
        ttk.Combobox(self.body, textvariable=self.kind, values=('Runtime', 'Editor'), state='readonly').grid(row=1, column=1, sticky='ew', pady=5)
        if not plugin:
            localized_widget(ttk.Label, self.body, text=msg('Destination')).grid(row=2, column=0, sticky='w')
            self.parent_box = ttk.Combobox(self.body, textvariable=self.parent_label, values=tuple(self.parents), state='readonly')
            self.parent_box.grid(row=2, column=1, sticky='ew', pady=5)
        check = localized_widget(ttk.Checkbutton, self.body, text=msg('Split Public / Private'), variable=self.split)
        check.grid(row=3, column=0, columnspan=2, sticky='w', pady=(8, 6))
        ToolTip(check, msg('Generate headers in Public and source files in Private.'))
        bar = ttk.Frame(self.body)
        bar.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(14, 0))
        localized_widget(ttk.Button, bar, text=msg('Add'), width=8, command=self.apply).pack(side='right')
        localized_widget(ttk.Button, bar, text=msg('Cancel'), command=self.close).pack(side='right', padx=8)
        self.reveal()
        ent.focus_set()

    def retranslate(self):
        selected = self.parents.get(self.parent_label.get())
        parents = {self.app.tr('Project'): None}
        for label, path in self.plugin_choices.items():
            display = label
            if display in parents:
                display = self.app.tr('{name} (Plugin)', name=label)
            while display in parents:
                display += ' / ' + path.stem
            parents[display] = path
        self.parents = parents
        self.parent_label.set(next((label for label, path in parents.items() if path == selected), self.app.tr('Project')))
        if self.parent_box is not None:
            self.parent_box.configure(values=tuple(parents))

    def apply(self):
        app = self.app
        source = msg('Plugin') if self.plugin else msg('Module')
        try:
            plan = model.scaffold_plan(app.project, self.name.get(), self.kind.get(), plugin=self.plugin,
                                       split=self.split.get(), plugin_descriptor=self.parents[self.parent_label.get()])
            if plan.modified:
                paths = '\n'.join(c.path.name for c in plan.modified)
                if not localized_messagebox('askyesno', msg('Modify Project Settings'), msg('{paths}\n\nAdd the registration entries to these files?', paths=paths), parent=self, default=messagebox.NO):
                    app.log(msg('Addition cancelled: {name}. No files were changed.', name=plan.name), source=source)
                    return
            app.log(msg('Adding {name}…', name=plan.name), source=source)
            app.log(msg('Project: {path}', path=app.project.file), source=source)
            receipt = model.commit(plan, allow_existing=True)
            app.log_receipt(receipt, source)
            app.log(msg('Added {name}.', name=plan.name), 'success', source)
            # Keep the class input/type/options; only the destination changes.
            state = dict(template=templates.normalize_template(app.var_template.get()))
            options, cache = dict(app.options), dict(app.template_options)
            app.set_project(app.project.file, state)
            app.options, app.template_options = options, cache
            match = next((label for label, t in app.targets.items() if t.folder == plan.changes[0].path.parent), '')
            app.var_target.set(match)
            app.on_target_changed()
            app.last_receipt = receipt
            app.last_output = plan.changes[0].path.parent
            app.tools.entryconfigure(app.UNDO_INDEX, state='normal')
            app.save_settings()
            app.set_status(msg('Added {name}.', name=plan.name))
            self.close()
            app.name_entry.focus_set()
            if app.auto_update:
                app.run_update()
        except (model.ValidationError, OSError) as e:
            app.log(e, 'error', source)
            localized_messagebox('showerror', msg('Could Not Add Item'), e, parent=self)


class FolderDialog(Dialog):
    def __init__(self, app):
        target = app.current_target()
        layout = app.current_layout()
        folders = model.existing_folders(target, layout)
        super().__init__(app, msg('Add Folder'))
        self.target, self.layout = target, layout
        self.parent_folder = tk.StringVar(self, app.var_folder.get())
        self.name = tk.StringVar(self, '')
        self.body.columnconfigure(1, weight=1)
        localized_widget(ttk.Label, self.body, text=msg('Parent Folder')).grid(row=0, column=0, sticky='w', padx=(0, 12))
        parent = ttk.Combobox(self.body, textvariable=self.parent_folder, values=folders, width=26)
        parent.grid(row=0, column=1, sticky='ew', pady=5)
        ToolTip(parent, msg('A relative folder within {target}. Leave blank for the root. Uses the main window layout: {layout}.', target=target.label, layout=msg(app.layout_caption(app.current_layout(), translate=False))))
        localized_widget(ttk.Label, self.body, text=msg('Name')).grid(row=1, column=0, sticky='w')
        ent = ttk.Entry(self.body, textvariable=self.name, width=26)
        ent.grid(row=1, column=1, sticky='ew', pady=5)
        ToolTip(ent, msg('The folder to add. Nested paths such as AI/Movement are supported. No files are created.'))
        ent.bind('<Return>', lambda e: self.apply())
        bar = ttk.Frame(self.body)
        bar.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(14, 0))
        localized_widget(ttk.Button, bar, text=msg('Add'), width=8, command=self.apply).pack(side='right')
        localized_widget(ttk.Button, bar, text=msg('Cancel'), command=self.close).pack(side='right', padx=8)
        self.reveal()
        ent.focus_set()

    def apply(self):
        app = self.app
        try:
            name = model.normalized_folder(self.name.get())
            if not name:
                raise model.ValidationError(msg('Please enter a folder name.'), 'folder')
            parent = model.normalized_folder(self.parent_folder.get())
            folder = '/'.join(filter(None, (parent, name)))
            plan = model.folder_plan(app.project, self.target, folder, self.layout)
            app.log(msg('Adding folder: {path}', path=folder), source=msg('Folder'))
            app.log(msg('Project: {path}', path=app.project.file), source=msg('Folder'))
            receipt = model.commit(plan)
            app.log_receipt(receipt, msg('Folder'))
            app.log(msg('Added {name}.', name=folder) if receipt.created_dirs else msg('Selected existing folder: {path}', path=folder), 'success' if receipt.created_dirs else 'info', msg('Folder'))
            if receipt.created_dirs:
                app.last_receipt = receipt
                app.tools.entryconfigure(app.UNDO_INDEX, state='normal')
            app.last_output = plan.directories[0]
            app.var_folder.set(folder)
            app.refresh_folder_choices()
            app.refresh_preview()
            app.save_settings()
            app.set_status(msg('Added {name}.', name=folder) if receipt.created_dirs else msg('Selected {name}.', name=folder))
            self.close()
            app.name_entry.focus_set()
        except (model.ValidationError, OSError) as e:
            app.log(e, 'error', msg('Folder'))
            localized_messagebox('showerror', msg('Could Not Add Folder'), e, parent=self)


def main():
    App().mainloop()
