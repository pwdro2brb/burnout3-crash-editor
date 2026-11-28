"""Shared look for the editor windows (plain ttk, no extra dependency).

``apply(root)`` configures the ttk "clam" theme with one palette and a few
named styles used by the windows:

* ``Header.TFrame`` / ``Header.TLabel`` / ``HeaderMuted.TLabel`` / ``Header.TButton``
  for the dark title bar;
* ``Card.TFrame`` + ``Card.TLabel`` / ``CardMuted.TLabel`` / ``Section.TLabel`` for
  white panels, and ``Card.TLabelframe`` for titled panels;
* ``Accent.TButton`` for the main action of a panel;
* ``Muted.TLabel``, ``Info.TLabel``, ``Warning.TLabel``, ``Danger.TLabel`` for notes;
* ``Pill.TLabel``, ``OkPill.TLabel``, ``WarnPill.TLabel`` for small status badges.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

PALETTE = {
    'bg': '#eef1f5',
    'surface': '#ffffff',
    'surface_alt': '#f6f8fa',
    'border': '#d5dbe3',
    'text': '#1b2430',
    'muted': '#5b6878',
    'accent': '#e4570f',
    'accent_hover': '#c94a0b',
    'accent_soft': '#fff0e6',
    'accent_disabled': '#f2c3a6',
    'info': '#1d5fbf',
    'info_soft': '#e8f0fc',
    'ok': '#1a7f37',
    'ok_soft': '#e6f4ea',
    'warn': '#8a5a00',
    'warn_soft': '#fff6d6',
    'danger': '#b42318',
    'danger_soft': '#fdecea',
    'header': '#151c26',
    'header_alt': '#243042',
    'header_text': '#ffffff',
    'header_muted': '#9aa9bb',
    'selection': '#ffe1cc',
    'map_bg': '#f7f9fb',
}
FAMILY = 'Segoe UI'
# Distinct, colour-blind-safe-ish lane colours for maps and the timeline.
LANE_COLOURS = ('#d1495b', '#2e86de', '#2a9d8f', '#e9a03b', '#8e5bd0', '#5d6b7b', '#e76f51', '#3c9d4e')
CATEGORY_COLOURS = {'Car': '#2e86de', 'Taxi': '#e9a03b', 'Tuk-tuk': '#e9a03b', 'Van': '#8e5bd0',
                    'Bus': '#2a9d8f', 'Minibus': '#2a9d8f', 'Articulated truck': '#d1495b',
                    'Pickup': '#5d6b7b', 'Motorhome': '#5d6b7b'}


def apply(root: tk.Misc) -> ttk.Style:
    """Configure the shared styles once per Tk interpreter and return the style."""
    p = PALETTE
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass
    try:
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont'):
            tkfont.nametofont(name, root=root).configure(family=FAMILY, size=10)
        tkfont.nametofont('TkHeadingFont', root=root).configure(family=FAMILY, size=9, weight='bold')
    except (tk.TclError, TypeError):
        pass
    try:
        root.configure(background=p['bg'])
    except tk.TclError:
        pass
    style.configure('.', background=p['bg'], foreground=p['text'], font=(FAMILY, 10),
                    bordercolor=p['border'], lightcolor=p['surface'], darkcolor=p['border'],
                    troughcolor=p['surface_alt'], focuscolor=p['accent'],
                    selectbackground=p['selection'], selectforeground=p['text'],
                    insertcolor=p['text'])
    style.configure('TFrame', background=p['bg'])
    style.configure('Card.TFrame', background=p['surface'], relief='flat')
    style.configure('Header.TFrame', background=p['header'])
    style.configure('Banner.TFrame', background=p['warn_soft'])
    style.configure('TLabel', background=p['bg'], foreground=p['text'])
    style.configure('Muted.TLabel', background=p['bg'], foreground=p['muted'])
    style.configure('Card.TLabel', background=p['surface'], foreground=p['text'])
    style.configure('CardMuted.TLabel', background=p['surface'], foreground=p['muted'])
    style.configure('Section.TLabel', background=p['surface'], foreground=p['text'],
                    font=(FAMILY, 11, 'bold'))
    style.configure('Title.TLabel', background=p['bg'], foreground=p['text'], font=(FAMILY, 15, 'bold'))
    style.configure('Info.TLabel', background=p['surface'], foreground=p['info'])
    style.configure('Warning.TLabel', background=p['surface'], foreground=p['warn'])
    style.configure('Danger.TLabel', background=p['surface'], foreground=p['danger'])
    style.configure('Header.TLabel', background=p['header'], foreground=p['header_text'],
                    font=(FAMILY, 15, 'bold'))
    style.configure('HeaderMuted.TLabel', background=p['header'], foreground=p['header_muted'])
    style.configure('HeaderAccent.TLabel', background=p['header'], foreground=p['accent'],
                    font=(FAMILY, 15, 'bold'))
    for name, fg, bg in (('Pill', p['muted'], p['surface_alt']), ('OkPill', p['ok'], p['ok_soft']),
                         ('WarnPill', p['warn'], p['warn_soft']), ('InfoPill', p['info'], p['info_soft'])):
        style.configure(f'{name}.TLabel', background=bg, foreground=fg, padding=(9, 3),
                        font=(FAMILY, 9, 'bold'))
    style.configure('TButton', background=p['surface'], foreground=p['text'], padding=(12, 5),
                    bordercolor='#c3ccd6', lightcolor=p['surface'], darkcolor='#e3e8ee',
                    focusthickness=1, relief='solid', borderwidth=1)
    style.map('TButton', background=[('disabled', p['surface_alt']), ('pressed', '#e3e8ee'),
                                     ('active', '#f0f3f7')],
              foreground=[('disabled', '#a3adb8')],
              bordercolor=[('focus', p['accent']), ('active', '#b9c3cf')])
    style.configure('Small.TButton', padding=(4, 5))
    style.configure('Accent.TButton', background=p['accent'], foreground='#ffffff',
                    bordercolor=p['accent'], lightcolor=p['accent'], darkcolor=p['accent_hover'],
                    font=(FAMILY, 10, 'bold'))
    style.map('Accent.TButton', background=[('disabled', p['accent_disabled']), ('pressed', p['accent_hover']),
                                            ('active', p['accent_hover'])],
              foreground=[('disabled', '#fff8f3')], bordercolor=[('focus', p['header'])])
    style.configure('Header.TButton', background=p['header_alt'], foreground=p['header_text'],
                    bordercolor=p['header_alt'], lightcolor=p['header_alt'], darkcolor=p['header_alt'])
    style.map('Header.TButton', background=[('disabled', p['header']), ('active', '#31415a')],
              foreground=[('disabled', '#6b7a8c')])
    style.configure('HeaderAccent.TButton', background=p['accent'], foreground='#ffffff',
                    bordercolor=p['accent'], lightcolor=p['accent'], darkcolor=p['accent'],
                    font=(FAMILY, 10, 'bold'))
    style.map('HeaderAccent.TButton', background=[('disabled', '#5a3a2a'), ('active', p['accent_hover'])])
    style.configure('Link.TButton', background=p['surface'], foreground=p['info'], padding=(4, 2),
                    bordercolor=p['surface'], lightcolor=p['surface'], darkcolor=p['surface'])
    style.map('Link.TButton', foreground=[('disabled', '#a3adb8'), ('active', p['accent'])],
              background=[('active', p['surface'])])
    style.configure('TLabelframe', background=p['surface'], bordercolor=p['border'], relief='solid',
                    borderwidth=1, padding=10)
    style.configure('TLabelframe.Label', background=p['surface'], foreground=p['text'],
                    font=(FAMILY, 10, 'bold'))
    style.configure('TNotebook', background=p['bg'], bordercolor=p['border'], tabmargins=(0, 4, 0, 0))
    style.configure('TNotebook.Tab', background='#e2e7ed', foreground=p['muted'], padding=(14, 6),
                    bordercolor=p['border'], font=(FAMILY, 10))
    style.map('TNotebook.Tab', background=[('selected', p['surface']), ('active', '#eaeef3')],
              foreground=[('selected', p['text'])], expand=[('selected', (1, 1, 1, 0))])
    style.configure('Treeview', background=p['surface'], fieldbackground=p['surface'], foreground=p['text'],
                    rowheight=26, bordercolor=p['border'], lightcolor=p['border'], darkcolor=p['border'])
    style.map('Treeview', background=[('selected', p['selection'])], foreground=[('selected', p['text'])])
    style.configure('Treeview.Heading', background=p['surface_alt'], foreground=p['muted'],
                    font=(FAMILY, 9, 'bold'), relief='flat', padding=(6, 5), bordercolor=p['border'])
    style.map('Treeview.Heading', background=[('active', '#e9edf2')])
    for widget in ('TEntry', 'TCombobox', 'TSpinbox'):
        style.configure(widget, fieldbackground=p['surface'], background=p['surface'], foreground=p['text'],
                        bordercolor=p['border'], lightcolor=p['surface'], darkcolor=p['border'],
                        arrowcolor=p['muted'], padding=(6, 4))
        style.map(widget, bordercolor=[('focus', p['accent'])], lightcolor=[('focus', p['accent'])],
                  fieldbackground=[('readonly', p['surface']), ('disabled', p['surface_alt'])],
                  foreground=[('disabled', '#97a2ae')])
    root.option_add('*TCombobox*Listbox.font', (FAMILY, 10))
    root.option_add('*TCombobox*Listbox.selectBackground', p['selection'])
    root.option_add('*TCombobox*Listbox.selectForeground', p['text'])
    for widget in ('TCheckbutton', 'TRadiobutton'):
        style.configure(widget, background=p['bg'], foreground=p['text'], indicatorcolor=p['surface'],
                        indicatorbackground=p['surface'])
        style.map(widget, indicatorcolor=[('selected', p['accent']), ('disabled', p['surface_alt'])],
                  background=[('active', p['bg'])])
        style.configure(f'Card.{widget}', background=p['surface'])
        style.map(f'Card.{widget}', background=[('active', p['surface'])],
                  indicatorcolor=[('selected', p['accent']), ('disabled', p['surface_alt'])])
    style.configure('Horizontal.TProgressbar', troughcolor=p['bg'], background=p['accent'],
                    bordercolor=p['bg'], lightcolor=p['accent'], darkcolor=p['accent'], thickness=4)
    style.configure('TScrollbar', background='#cdd5de', troughcolor=p['surface_alt'], bordercolor=p['surface_alt'],
                    arrowcolor=p['muted'], lightcolor='#cdd5de', darkcolor='#cdd5de', gripcount=0)
    style.map('TScrollbar', background=[('active', '#b6c0cc')])
    style.configure('Horizontal.TScale', background=p['accent'], troughcolor='#dde3ea', bordercolor=p['border'],
                    lightcolor=p['accent'], darkcolor=p['accent'])
    style.configure('TPanedwindow', background=p['bg'])
    style.configure('Sash', sashthickness=8, background=p['bg'], bordercolor=p['bg'])
    return style


class ActivityBar(ttk.Progressbar):
    """Indeterminate while working, empty (no idle block) when stopped."""

    def start(self, interval=None):
        self.configure(mode='indeterminate')
        super().start(interval)

    def stop(self):
        super().stop()
        self.configure(mode='determinate', value=0)


def section(parent, title, *, row, padding=14, pady=(12, 0), subtitle=None) -> ttk.Frame:
    """A card with a bold title; returns the inner frame (title occupies row 0)."""
    inner = card(parent, padding=padding, row=row, column=0, sticky='ew', pady=pady)
    inner.columnconfigure(0, weight=1)
    ttk.Label(inner, text=title, style='Section.TLabel').grid(row=0, column=0, columnspan=4, sticky='w')
    if subtitle:
        ttk.Label(inner, text=subtitle, style='CardMuted.TLabel', wraplength=320).grid(
            row=1, column=0, columnspan=4, sticky='w', pady=(2, 0))
    return inner


def card(parent, *, padding=14, **grid) -> ttk.Frame:
    """A white panel with a hairline border, gridded when grid options are given."""
    outer = tk.Frame(parent, background=PALETTE['border'], borderwidth=0, highlightthickness=0)
    inner = ttk.Frame(outer, style='Card.TFrame', padding=padding)
    inner.pack(fill='both', expand=True, padx=1, pady=1)
    inner.outer = outer
    if grid:
        outer.grid(**grid)
    return inner


def banner(parent, textvariable, *, kind='warn', **options) -> tk.Label:
    """A full-width coloured message line (pending creation, density warning...)."""
    colours = {'warn': ('warn_soft', 'warn'), 'info': ('info_soft', 'info'),
               'danger': ('danger_soft', 'danger'), 'ok': ('ok_soft', 'ok')}[kind]
    return tk.Label(parent, textvariable=textvariable, background=PALETTE[colours[0]],
                    foreground=PALETTE[colours[1]], font=(FAMILY, 10, 'bold'), anchor='w',
                    justify='left', padx=14, pady=10, **options)
