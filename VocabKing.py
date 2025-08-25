# -*- coding: utf-8 -*-
# VocabKing.py — Premium UI + Full Feature Integration
# Requirements:
#   pip install customtkinter pyttsx3 pandas openpyxl
#   pyinstaller --onefile --windowed --icon=assets/icon.ico --add-data "assets;assets" --add-data "words_dictionary.json;." VocabKing.py
#
# Notes:
# - Uses a dark navy + gold theme across all screens.
# - Fully wired deck actions: Open, Rename, Copy, Delete, Import, Add Deck.
# - Word Add/Edit, Quiz (scoped), Word List (search/filter/toggle meanings), Excel import (up to 100 rows).
# - Safe fonts (no tkfont.families() call before root).

import customtkinter as ctk
from tkinter import Menu, filedialog
import tkinter as tk
import pyttsx3
import json
import os, sys
from PIL import Image
import random
import pandas as pd
import threading
import queue

# ==============================
# App Constants & Global State
# ==============================

APP_TITLE = "Vocab King"
VOCAB_FILE = "decks.json"

# in-memory state
decks: dict = {}
current_deck = ""
current_word = ""
quiz_index = 0
editing_word = None
shuffle_enabled = False
selected_word = {"text": None}
selected_index = {"idx": None}
filtered_words = []
row_widgets = []
hide_meanings = False
VISIBLE_ROWS = 100
word_entry = pos_entry = meaning_entry = example_entry = None
_tts_queue = queue.Queue()
_tts_thread = None

# ==============================
# Theme (Dark Navy + Royal Gold)
# ==============================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

THEME = {
    "bg":          "#0F1B2A",   # deep navy
    "panel":       "#0F1F31",
    "card":        "#13263A",
    "card_hover":  "#173149",
    "line":        "#2A3C53",
    "text":        "#F1F5F9",
    "muted":       "#97A5B5",
    "gold":        "#E7C46C",
    "gold_dim":    "#CBAE5B",
    "danger":      "#E74C3C",
    "warn":        "#F39C12",
    "success":     "#27AE60",
    "white":       "#F1F5F9",
}

SPACING = {"xs":4,"sm":8,"md":12,"lg":16,"xl":24,"xxl":36}
RADIUS  = {"sm":8,"md":14,"lg":22}

def resource_path(relative_path):
    """ PyInstaller 환경과 개발 환경 모두에서 파일 경로 반환 """
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

icon_unknown_img = ctk.CTkImage(Image.open(resource_path("assets/icon_unknown.png")), size=(24, 24))
icon_partial_img = ctk.CTkImage(Image.open(resource_path("assets/icon_partial.png")), size=(24, 24))
icon_known_img   = ctk.CTkImage(Image.open(resource_path("assets/icon_known.png")), size=(24, 24))

def ui_font(name, size, weight=None):
    # Avoid tkfont.families() before root; CTkFont will fallback automatically if font missing.
    return ctk.CTkFont(name, size, weight)

# ==============================
# Root Window & Menubar
# ==============================

root = ctk.CTk()
root.title(APP_TITLE)
root.configure(fg_color=THEME["bg"])
root.grid_rowconfigure(0, weight=1)
root.grid_columnconfigure(0, weight=1)

FONTS = {
    "title":     ui_font("Inter", 50, "bold"),
    "display":   ui_font("Inter", 36, "bold"),
    "h1":        ui_font("Inter", 24, "bold"),
    "h2":        ui_font("Inter", 18, "bold"),
    "h3":        ui_font("Inter", 16, "bold"),
    "h4":        ui_font("Inter", 12, "normal"),
    "body":      ui_font("Inter", 12),
    "body_bold": ui_font("Inter", 12, "bold"),
    "mono":      ui_font("JetBrains Mono", 11),
}

BTN_SOLID = {
    "corner_radius": RADIUS["sm"],
    "height": 40,
    "fg_color": THEME["gold"],
    "hover_color": THEME["gold_dim"],
    "text_color": "#0E1520",
    "font": FONTS["body_bold"],
}
BTN_GHOST = {
    "corner_radius": RADIUS["sm"],
    "height": 40,
    "fg_color": THEME["panel"],
    "hover_color": THEME["card_hover"],
    "text_color": THEME["text"],
    "font": FONTS["body_bold"],
}
BTN_SMALL = {
    "corner_radius": RADIUS["sm"],
    "height": 28,
    "fg_color": THEME["panel"],
    "hover_color": THEME["card_hover"],
    "text_color": THEME["text"],
    "font": FONTS["body_bold"],
}
# Help Modal
# ==============================

def open_help_modal():
    def build(parent, overlay):
        ctk.CTkLabel(parent, text="Help", font=FONTS["h1"], text_color=THEME["gold"]).pack(
            pady=(SPACING["md"], SPACING["sm"])
        )
        ctk.CTkButton(
            parent,
            text="ℹ️  About",
            width=200,
            **BTN_SOLID,
            command=lambda: (overlay.destroy(), show_about())
        ).pack(pady=SPACING["sm"])

        ctk.CTkButton(
            parent,
            text="♻️  Reset App",
            width=200,
            **BTN_GHOST,
            command=lambda: (overlay.destroy(), reset_app())
        ).pack(pady=SPACING["sm"])

        ctk.CTkButton(
            parent,
            text="Close",
            width=200,
            **BTN_GHOST,
            command=overlay.destroy
        ).pack(pady=(SPACING["md"], 0))

    show_modal("", build, show_close=False)

def _start_tts_worker(voice_index_preferred=1, rate=130):
    """pyttsx3 엔진을 워커 스레드 안에서 생성하고, 큐를 소비하며 speak를 수행"""
    def worker():
        try:
            eng = pyttsx3.init()
            voices = eng.getProperty('voices')
            if voices:
                vi = min(voice_index_preferred, len(voices)-1)
                eng.setProperty('voice', voices[vi].id)
            eng.setProperty('rate', rate)
        except Exception as e:
            try:
                root.after(0, lambda m=f"❌ TTS init error:\n{e}": modal_error(m))
            except Exception:
                pass
            return

        while True:
            text = _tts_queue.get()
            if text is None:
                break
            try:
                # 큐를 비우고 가장 최신 요청만 말하도록 설정 (중복 클릭 대비)
                while True:
                    try:
                        nxt = _tts_queue.get_nowait()
                        if nxt is None:
                            text = None
                            break
                        text = nxt
                    except queue.Empty:
                        break
                if not text:
                    continue

                eng.say(text)
                eng.runAndWait()
            except Exception as e:
                try:
                    root.after(0, lambda m=f"❌ TTS Error:\n{e}": modal_error(m))
                except Exception:
                    pass

    global _tts_thread
    if _tts_thread is None or not _tts_thread.is_alive():
        _tts_thread = threading.Thread(target=worker, daemon=True)
        _tts_thread.start()

# 전역 변수 추가
current_engine = None
current_engine_lock = threading.Lock()

def speak_text(text: str):
    if not text:
        return

    def worker(t):
        global current_engine
        with current_engine_lock:
            try:
                # 이전 재생 중이면 중단
                if current_engine is not None:
                    try:
                        current_engine.stop()
                    except Exception:
                        pass
                    current_engine = None

                # 새 엔진 생성
                eng = pyttsx3.init()
                voices = eng.getProperty('voices')
                if voices:
                    vi = min(1, len(voices)-1)
                    eng.setProperty('voice', voices[vi].id)
                eng.setProperty('rate', 130)

                current_engine = eng
                eng.say(t)
                eng.runAndWait()

            except Exception as e:
                try:
                    root.after(0, lambda m=f"❌ TTS Error:\n{e}": modal_error(m))
                except Exception:
                    pass
            finally:
                current_engine = None

    threading.Thread(target=worker, args=(text,), daemon=True).start()

# ==============================
# Data I/O
# ==============================

def _atomic_write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load_decks():
    global decks
    if os.path.exists(VOCAB_FILE):
        try:
            with open(VOCAB_FILE, "r", encoding="utf-8") as f:
                decks = json.load(f)
        except Exception:
            decks = {}
    if not decks:
        decks = {"Default": {}}

def save_decks():
    try:
        _atomic_write_json(VOCAB_FILE, decks)
    except Exception as e:
        modal_error(f"Deck save failed:\n{e}")

# ===== Random Word Challenge Data =====
import json, random

with open(resource_path("words_dictionary.json"), "r", encoding="utf-8") as f:
    _words_data = json.load(f)

WORD_LIST = list(_words_data.keys())
saved_random_words = []

# ===== Custom Modal Utilities =====

def _modal_template(_title, _message, _color, _on_yes=None, _confirm=False):
    def build(parent, overlay):
        ctk.CTkLabel(parent, text=_message, font=FONTS["body"], text_color=_color,
                     justify="center", wraplength=360).pack(pady=SPACING["md"])
        if _confirm:
            row = ctk.CTkFrame(parent, fg_color="transparent"); row.pack(pady=SPACING["sm"])
            ctk.CTkButton(row, text="Yes", command=lambda: (overlay.destroy(), _on_yes() if _on_yes else None), **BTN_SOLID).pack(side="left", padx=SPACING["sm"])
            ctk.CTkButton(row, text="No", command=overlay.destroy, **BTN_GHOST).pack(side="left", padx=SPACING["sm"])
        else:
            ctk.CTkButton(parent, text="OK", command=overlay.destroy, **BTN_SOLID).pack(pady=SPACING["sm"])
    show_modal(_title, build, show_close=False)

def modal_warn(message):
    _modal_template("Warning", message, THEME["muted"])

def modal_info(message):
    _modal_template("Info", message, THEME["muted"])

def modal_error(message):
    _modal_template("Error", message, THEME["danger"])

def modal_confirm(message, on_yes):
    _modal_template("Confirm", message, THEME["muted"], _on_yes=on_yes, _confirm=True)

    def build(parent, overlay):
        ctk.CTkLabel(parent, text=message, font=FONTS["body"], text_color=THEME["danger"],
                     justify="center", wraplength=360).pack(pady=SPACING["md"])
        ctk.CTkButton(parent, text="OK", command=overlay.destroy, **BTN_SOLID).pack(pady=SPACING["sm"])
    show_modal("Error", build, show_close=False)

    def build(parent, overlay):
        ctk.CTkLabel(parent, text=message, font=FONTS["body"], text_color=THEME["muted"],
                     justify="center", wraplength=360).pack(pady=SPACING["md"])
        row = ctk.CTkFrame(parent, fg_color="transparent"); row.pack(pady=SPACING["sm"])
        ctk.CTkButton(row, text="Yes", command=lambda: (overlay.destroy(), on_yes()), **BTN_SOLID)\
            .pack(side="left", padx=SPACING["sm"])
        ctk.CTkButton(row, text="No", command=overlay.destroy, **BTN_GHOST)\
            .pack(side="left", padx=SPACING["sm"])
    show_modal("Confirm", build, show_close=False)

# Utilities
# ==============================

def center_root_window(window, width=960, height=680):
    window.update_idletasks()
    sw = window.winfo_screenwidth()
    sh = window.winfo_screenheight()
    x = (sw // 2) - (width // 2)
    y = (sh // 2) - (height // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")

def show_frame(frame):
    frame.tkraise()
    # clear all keybinds that might interfere
    for key in ("<Left>", "<Right>", "<Up>", "<Down>", "<Delete>"):
        try: root.unbind(key)
        except Exception: pass

def get_deck_stats(deck_dict: dict):
    total = len(deck_dict)
    status_count = {"known": 0, "partial": 0, "unknown": 0}
    for w in deck_dict.values():
        status = w.get("status", "unknown")
        if status in status_count:
            status_count[status] += 1
    mastered = status_count["known"]  # ✅ partial 제외
    progress = (mastered / total) if total else 0.0
    return total, status_count, progress, mastered

def build_deck_header(parent, title_text, deck_name):
    """공통 헤더 카드: 제목 + 상태 아이콘/카운트 + 진행바"""
    total, counts, progress, _ = get_deck_stats(decks.get(deck_name, {}))

    # 전역 레퍼런스: Word List 헤더 갱신용
    global header_total_label, header_known_count_label, header_partial_count_label, header_unknown_count_label, header_progress_bar

    status_icons = {
        "unknown": icon_unknown_img,
        "partial": icon_partial_img,
        "known":   icon_known_img
    }

    header_card = ctk.CTkFrame(
        parent,
        fg_color=THEME["panel"],
        corner_radius=RADIUS["lg"],
        border_width=1,
        border_color=THEME["line"]
    )
    header_card.pack(
        pady=(SPACING["xxl"], SPACING["lg"]),
        padx=SPACING["xl"],
        anchor="center",
        fill="x"
    )

    # 제목
    ctk.CTkLabel(
        header_card,
        text=title_text,
        font=FONTS["h1"],
        text_color=THEME["gold"]
    ).pack(pady=(SPACING["md"], 0), padx=SPACING["xl"], anchor="w")

    # 상태 아이콘 + 카운트
    stats_row = ctk.CTkFrame(header_card, fg_color="transparent")
    stats_row.pack(pady=(0, SPACING["md"]), padx=SPACING["xl"], anchor="w")

    # Total
    header_total_label = ctk.CTkLabel(
        stats_row,
        text=f"Total {total}   |   ",
        font=FONTS["body"],
        text_color=THEME["muted"]
    )
    header_total_label.pack(side="left")

    # Known
    ctk.CTkLabel(stats_row, image=status_icons["known"], text="").pack(side="left", padx=(0, 4))
    header_known_count_label = ctk.CTkLabel(
        stats_row, text=str(counts.get("known", 0)), font=FONTS["body"], text_color=THEME["muted"]
    )
    header_known_count_label.pack(side="left", padx=(0, 12))

    # Partial
    ctk.CTkLabel(stats_row, image=status_icons["partial"], text="").pack(side="left", padx=(0, 4))
    header_partial_count_label = ctk.CTkLabel(
        stats_row, text=str(counts.get("partial", 0)), font=FONTS["body"], text_color=THEME["muted"]
    )
    header_partial_count_label.pack(side="left", padx=(0, 12))

    # Unknown
    ctk.CTkLabel(stats_row, image=status_icons["unknown"], text="").pack(side="left", padx=(0, 4))
    header_unknown_count_label = ctk.CTkLabel(
        stats_row, text=str(counts.get("unknown", 0)), font=FONTS["body"], text_color=THEME["muted"]
    )
    header_unknown_count_label.pack(side="left")

    # 진행바
    header_progress_bar = ctk.CTkProgressBar(
        header_card, height=10, fg_color=THEME["card"], progress_color=THEME["gold"]
    )
    header_progress_bar.pack(fill="x", padx=SPACING["xl"], pady=(0, SPACING["lg"]))
    header_progress_bar.set(progress if progress <= 1 else 1)

def refresh_word_list_header():
    cd = current_deck
    deck = decks.get(cd, {})
    total = len(deck)
    known = sum(1 for v in deck.values() if v.get("status") == "known")
    partial = sum(1 for v in deck.values() if v.get("status") == "partial")
    unknown = total - known - partial
    ratio = (known / total) if total else 0

    # 존재할 때만 갱신
    if 'header_total_label' in globals() and header_total_label.winfo_exists():
        header_total_label.configure(text=f"Total {total}   |   ")
    if 'header_known_count_label' in globals() and header_known_count_label.winfo_exists():
        header_known_count_label.configure(text=str(known))
    if 'header_partial_count_label' in globals() and header_partial_count_label.winfo_exists():
        header_partial_count_label.configure(text=str(partial))
    if 'header_unknown_count_label' in globals() and header_unknown_count_label.winfo_exists():
        header_unknown_count_label.configure(text=str(unknown))
    if 'header_progress_bar' in globals() and header_progress_bar.winfo_exists():
        header_progress_bar.set(ratio)

# ==============================
# Modal (overlay + card)
# ==============================

def show_modal(title, build_func, show_close=True):
    overlay = ctk.CTkFrame(root, fg_color="#000000")
    overlay.place(relx=0, rely=0, relwidth=1, relheight=1)

    modal = ctk.CTkFrame(overlay, fg_color="#1E1E1E", corner_radius=20)
    modal.place(relx=0.5, rely=0.5, anchor="center")

    title_label = ctk.CTkLabel(modal, text=title, font=("Arial", 20, "bold"))
    title_label.pack(pady=(10, 5))

    build_func(modal, overlay)  # 내부 UI 빌드

    def close():
        overlay.destroy()

    if show_close:
        close_btn = ctk.CTkButton(modal, text="Close", command=close)
        close_btn.pack(pady=(10, 10))

    overlay.bind("<Button-1>", lambda e: close())
    modal.bind("<Button-1>", lambda e: "break")
    overlay.bind("<Escape>", lambda e: close())

    # target size and subtle grow animation
    root.update_idletasks()
    tw = max(360, modal.winfo_reqwidth() + 24)
    th = max(100, modal.winfo_reqheight() + 24)
    start = 0.9
    steps = 8
    dur = 120
    modal.place_configure(width=int(tw*start), height=int(th*start))
    def animate(step=0):
        scale = start + (1-start) * (step/steps)
        modal.place_configure(width=int(tw*scale), height=int(th*scale))
        if step < steps:
            root.after(dur//steps, lambda: animate(step+1))
        else:
            modal.place_configure(width=tw, height=th)
    animate()

# Click binding utility
# ==============================
def bind_all_children_click(widget, on_click, skip_types=(ctk.CTkButton,)):
    """
    widget과 모든 자식에게 클릭 바인딩을 걸어 row 어디를 눌러도 on_click()이 실행되게 함.
    skip_types에 해당하는 위젯(버튼)은 건너뛰어 기존 command를 보존.
    """
    # 자신에게 바인딩
    widget.bind("<Button-1>", lambda e: on_click())
    # 자식들에게 재귀 바인딩
    for child in widget.winfo_children():
        if isinstance(child, skip_types):
            continue
        bind_all_children_click(child, on_click, skip_types=skip_types)

# Selection Guard Utility
# ==============================

def require_selection(action_func):
    """선택된 단어가 없으면 경고 모달, 있으면 해당 함수 실행"""
    sel = selected_word["text"]
    if not sel:
        modal_warn("⚠️ Please select a word first.")
        return
    action_func(sel)

def speak_selected():
    w = selected_word["text"]
    if not w:
        modal_warn("⚠️ Please select a word first.")
        return
    speak_text(w)

# ==============================
# Frames
# ==============================

deck_select_frame = ctk.CTkFrame(root, fg_color=THEME["bg"])
menu_frame        = ctk.CTkFrame(root, fg_color=THEME["bg"])
add_frame         = ctk.CTkFrame(root, fg_color=THEME["bg"])
quiz_frame        = ctk.CTkFrame(root, fg_color=THEME["bg"])
list_frame        = ctk.CTkFrame(root, fg_color=THEME["bg"])
quiz_filter_frame = ctk.CTkFrame(root, fg_color=THEME["bg"])
random_word_frame = ctk.CTkFrame(root, fg_color=THEME["bg"])
random_word_frame.grid(row=0, column=0, sticky="nsew")

for f in (deck_select_frame, menu_frame, add_frame, quiz_frame, list_frame, quiz_filter_frame):
    f.grid(row=0, column=0, sticky="nsew")

# ==============================
# Deck Management
# ==============================

def select_deck(deck_name):
    global current_deck
    current_deck = deck_name
    build_main_menu()
    show_frame(menu_frame)

def open_deck_popup():
    def build(parent, overlay):
        name = tk.StringVar()
        ctk.CTkLabel(parent, text="Deck Name", font=FONTS["body"]).pack(pady=(0, SPACING["xs"]))
        entry = ctk.CTkEntry(parent, textvariable=name, width=280)
        entry.pack()
        entry.focus_set()

        def create():
            new = name.get().strip()

            if not new:
                modal_warn("⚠️ Please enter a deck name.")
                return
            if new in decks:
                modal_info(f"ℹ️ '{new}' already exists.")
                return

            decks[new] = {}
            save_decks()
            overlay.destroy()
            build_deck_select()

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(pady=SPACING["md"])
        ctk.CTkButton(row, text="Create", command=create, **BTN_SOLID).pack(side="left", padx=SPACING["sm"])
        ctk.CTkButton(row, text="Cancel", command=overlay.destroy, **BTN_GHOST).pack(side="left", padx=SPACING["sm"])
    show_modal("Add New Deck", open_deck_popup_inner := build, show_close=False)

def rename_deck(deck_name):
    def build(parent, overlay):
        name = tk.StringVar(value=deck_name)
        ctk.CTkLabel(parent, text="New Name", font=FONTS["body"]).pack(pady=(0, SPACING["xs"]))
        entry = ctk.CTkEntry(parent, textvariable=name, width=280)
        entry.pack()
        entry.focus_set()
        def apply():
            new = name.get().strip()
            if not new:
                modal_warn("⚠️ Please enter a new deck name.")
                return
            if new in decks:
                modal_info(f"ℹ️ '{new}' already exists.")
                return

            decks[new] = decks.pop(deck_name)
            global current_deck
            if current_deck == deck_name:
                current_deck = new
            save_decks()
            overlay.destroy()
            build_deck_select()
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(pady=SPACING["md"])
        ctk.CTkButton(row, text="Rename", command=apply, **BTN_SOLID).pack(side="left", padx=SPACING["sm"])
        ctk.CTkButton(row, text="Cancel", command=overlay.destroy, **BTN_GHOST).pack(side="left", padx=SPACING["sm"])
    show_modal(f"Rename '{deck_name}'", rename_deck_inner := build, show_close=False)

def confirm_delete_deck(deck_name):
    def build(parent, overlay):
        ctk.CTkLabel(
            parent,
            text=f"Delete deck '{deck_name}'?\nThis cannot be undone.",
            text_color=THEME["muted"], justify="center"
        ).pack(pady=SPACING["sm"])
        def do_delete():
            global current_deck
            decks.pop(deck_name, None)
            if not decks:
                decks["Default"] = {}
            if current_deck == deck_name:
                current_deck = list(decks.keys())[0]
            save_decks()
            overlay.destroy()
            build_deck_select()
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(pady=SPACING["md"])
        ctk.CTkButton(row, text="Delete", command=do_delete, **BTN_SOLID).pack(side="left", padx=SPACING["sm"])
        ctk.CTkButton(row, text="Cancel", command=overlay.destroy, **BTN_GHOST).pack(side="left", padx=SPACING["sm"])
    show_modal("Delete Deck", build, show_close=False)

def copy_deck(deck_name):
    def build(parent, overlay):
        name = tk.StringVar(value=f"{deck_name}_copy")
        ctk.CTkLabel(parent, text="New Deck Name", font=FONTS["body"]).pack(pady=(0, SPACING["xs"]))
        entry = ctk.CTkEntry(parent, textvariable=name, width=280)
        entry.pack()
        entry.focus_set()
        def do_copy():
            new = name.get().strip()
            if not new:
                modal_warn("⚠️ Please enter a new deck name.")
                return
            if new in decks:
                modal_info(f"ℹ️ '{new}' already exists.")
                return
            # deep copy via JSON serialization
            decks[new] = json.loads(json.dumps(decks[deck_name], ensure_ascii=False))
            save_decks()
            overlay.destroy()
            build_deck_select()
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(pady=SPACING["md"])
        ctk.CTkButton(row, text="Copy", command=do_copy, **BTN_SOLID).pack(side="left", padx=SPACING["sm"])
        ctk.CTkButton(row, text="Cancel", command=overlay.destroy, **BTN_GHOST).pack(side="left", padx=SPACING["sm"])
    show_modal(f"Copy '{deck_name}'", build, show_close=False)

# ==============================
# Excel Import
# ==============================

def import_excel_to_deck(filepath, deck_name="Imported"):
    try:
        # 1) 기존 덱 이름 중복 체크
        if deck_name in decks:
            modal_warn(f"⚠️ Deck '{deck_name}' already exists.\nPlease choose a different name.")
            return

        df = pd.read_excel(filepath, header=None)
        if len(df) > 100:
            modal_error("A deck can contain at most 100 words.\nPlease reduce rows in Excel.")
            return

        new_deck = {}
        for _, row in df.iterrows():
            word    = str(row.iloc[0]).strip() if len(row) > 0 and not pd.isna(row.iloc[0]) else ""
            if not word:
                continue
            pos     = str(row.iloc[1]).strip() if len(row) > 1 and not pd.isna(row.iloc[1]) else "null"
            meaning = str(row.iloc[2]).strip() if len(row) > 2 and not pd.isna(row.iloc[2]) else ""
            example = str(row.iloc[3]).strip() if len(row) > 3 and not pd.isna(row.iloc[3]) else ""
            new_deck[word] = {
                "part_of_speech": pos,
                "meaning": meaning,
                "example": example,
                "status": "unknown"
            }

        decks[deck_name] = new_deck
        save_decks()
        global current_deck
        current_deck = deck_name
        build_deck_select()
        show_frame(deck_select_frame)
        modal_info(f"✅ '{deck_name}' deck imported.")

    except Exception as e:
        modal_error(f"Import Error\n{e}")

def open_excel_import_popup():
    def build(parent, overlay):
        path_var = tk.StringVar()
        name_var = tk.StringVar(value="Imported")

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(pady=(SPACING["xs"], 0))
        ctk.CTkEntry(row, textvariable=path_var, width=260, placeholder_text="Select .xlsx").pack(side="left")
        def browse():
            fp = filedialog.askopenfilename(
                title="Select Excel",
                filetypes=[("Excel files","*.xlsx *.xls")]
            )
            if fp: path_var.set(fp)
        ctk.CTkButton(row, text="Browse", command=browse, **BTN_SMALL).pack(side="left", padx=SPACING["sm"])

        ctk.CTkLabel(parent, text="Deck Name", font=FONTS["body"]).pack(pady=(SPACING["sm"], SPACING["xs"]))
        ctk.CTkEntry(parent, textvariable=name_var, width=260).pack()

        hint = "Format: A=Word | B=Part of Speech | C=Meaning | D=Example\n(Up to 100 rows)"
        ctk.CTkLabel(parent, text=hint, text_color=THEME["muted"]).pack(pady=SPACING["sm"])

        def go():
            if not path_var.get().strip() or not name_var.get().strip():
                modal_warn("⚠️ File path and deck name required.")
                return
            overlay.destroy()
            import_excel_to_deck(path_var.get().strip(), name_var.get().strip())

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(pady=SPACING["md"])
        ctk.CTkButton(row, text="Import", command=go, **BTN_SOLID).pack(side="left", padx=SPACING["sm"])
        ctk.CTkButton(row, text="Cancel", command=overlay.destroy, **BTN_GHOST).pack(side="left", padx=SPACING["sm"])
    show_modal("Import Excel Deck", open_excel_import_popup_inner := build, show_close=False)

def show_rank_info():
    rank_info = (
        "🏆 Rank System\n\n"
        "Peasant: 0+\n"
        "Squire: 50+\n"
        "Knight: 150+\n"
        "Baron: 300+\n"
        "Viscount: 600+\n"
        "Count: 1200+\n"
        "Marquis: 2500+\n"
        "Duke: 4000+\n"
        "Prince: 7000+\n"
        "King: 10000+\n\n"
        "Master more words to climb the ranks!"
    )

    def build(parent, overlay):
        ctk.CTkLabel(
            parent,
            text=rank_info,
            font=FONTS["body"],
            text_color=THEME["muted"],
            justify="left"
        ).pack(padx=SPACING["lg"], pady=SPACING["md"])
        ctk.CTkButton(parent, text="Close", command=overlay.destroy, **BTN_SOLID)\
            .pack(pady=SPACING["sm"])

    show_modal("Rank Info", build, show_close=False)

# ==============================
# Deck Select (Hero + Deck List)
# ==============================

def build_deck_select():
    for w in deck_select_frame.winfo_children():
        w.destroy()

    # Help 버튼 (우측 상단)
    help_btn = ctk.CTkButton(
        deck_select_frame,
        text="❓ Help",
        width=80,
        **BTN_GHOST,
        command=open_help_modal
    )
    help_btn.place(relx=1.0, x=-SPACING["xl"], y=SPACING["xl"], anchor="ne")

    # Hero
    hero = ctk.CTkFrame(deck_select_frame, fg_color="transparent")
    hero.pack(pady=(SPACING["xxl"], SPACING["lg"]))

    # 가로 배치 컨테이너
    hero_row = ctk.CTkFrame(hero, fg_color="transparent")
    hero_row.pack(anchor="center")

    logo_img = ctk.CTkImage(Image.open(resource_path("assets/logo.png")), size=(100, 100))
    logo_lbl = ctk.CTkLabel(hero_row, image=logo_img, text="")
    logo_lbl.pack(side="left", padx=(0, SPACING["md"]))

    # 오른쪽: 타이틀 + 서브타이틀
    title_col = ctk.CTkFrame(hero_row, fg_color="transparent")
    title_col.pack(side="left", anchor="w")

    title_label = ctk.CTkLabel(
        title_col,
        text="Vocab King",
        font=FONTS["title"],
        text_color=THEME["white"],
        justify="left"
    )
    title_label.pack(anchor="w", pady=(0, 0))

    subtitle = ctk.CTkLabel(
        title_col,
        text="Master Your Words, Rule Your Mind",
        font=FONTS["h4"],
        text_color=THEME["white"],
        padx=8
    )
    subtitle.pack(anchor="w")

    # Total studied level
    total_mastered = 0
    for deck in decks.values():
        for info in deck.values():
            if info.get("status") == "known":  # ✅ partial 제외
                total_mastered += 1

    level_map = [
        (0, "Peasant"),
        (50, "Squire"),
        (150, "Knight"),
        (300, "Baron"),
        (600, "Viscount"),
        (1200, "Count"),
        (2500, "Marquis"),
        (4000, "Duke"),
        (7000, "Prince"),
        (10000, "King")
    ]
    level = level_map[0][1]
    for t, name in level_map:
        if total_mastered >= t: level = name
    lvl = ctk.CTkLabel(
        deck_select_frame,
        text=f"Mastered: {total_mastered}   •   Rank: {level}",
        font=FONTS["body"],
        text_color=THEME["muted"]
    )

    lvl_row = ctk.CTkFrame(deck_select_frame, fg_color="transparent")
    lvl_row.pack()

    lvl = ctk.CTkLabel(
        lvl_row,
        text=f"Mastered: {total_mastered}   •   Rank: {level}",
        font=FONTS["body"],
        text_color=THEME["muted"]
    )
    lvl.pack(side="left")

    info_btn = ctk.CTkButton(
        lvl_row,
        text="ℹ️",
        width=28,
        height=28,
        command=show_rank_info,
        fg_color=THEME["panel"],
        hover_color=THEME["card_hover"],
        text_color=THEME["text"],
        font=FONTS["body_bold"]
    )
    info_btn.pack(side="left", padx=(SPACING["xs"], 0))

    # Deck list area
    list_card = ctk.CTkFrame(deck_select_frame, fg_color=THEME["panel"],
                             corner_radius=RADIUS["lg"], border_width=1, border_color=THEME["line"])
    list_card.pack(padx=SPACING["xl"], pady=SPACING["xl"], fill="both", expand=True)

    header = ctk.CTkLabel(list_card, text="Decks", font=FONTS["h1"], text_color=THEME["text"])
    header.pack(anchor="w", padx=SPACING["xl"], pady=(SPACING["lg"], SPACING["md"]))

    sf = ctk.CTkScrollableFrame(list_card, fg_color="transparent")
    sf.pack(fill="both", expand=True, padx=SPACING["xl"], pady=(0, SPACING["lg"]))

    # render each deck row
    def deck_row(name):
        total, counts, progress, mastered = get_deck_stats(decks[name])
        row = ctk.CTkFrame(sf, fg_color=THEME["card"], corner_radius=RADIUS["md"])
        row.pack(fill="x", pady=SPACING["sm"])

        # Name & counts
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=SPACING["lg"], pady=SPACING["md"])

        ctk.CTkLabel(left, text=name, font=FONTS["h2"]).pack(anchor="w")

        status_icons = {
            "unknown": icon_unknown_img,
            "partial": icon_partial_img,
            "known": icon_known_img
        }

        stats_row = ctk.CTkFrame(left, fg_color="transparent")
        stats_row.pack(anchor="w", pady=(SPACING["xs"], 0))

        # ✅ mastered 변수 사용
        ctk.CTkLabel(
            stats_row,
            text=f"Mastered {mastered}/{total}  •  ",
            font=FONTS["body"],
            text_color=THEME["muted"]
        ).pack(side="left")

        # Known
        ctk.CTkLabel(stats_row, image=status_icons["known"], text="").pack(side="left", padx=(0, 4))
        ctk.CTkLabel(stats_row, text=str(counts["known"]), font=FONTS["body"], text_color=THEME["muted"]).pack(
            side="left", padx=(0, 8))

        # Partial
        ctk.CTkLabel(stats_row, image=status_icons["partial"], text="").pack(side="left", padx=(0, 4))
        ctk.CTkLabel(stats_row, text=str(counts["partial"]), font=FONTS["body"], text_color=THEME["muted"]).pack(
            side="left", padx=(0, 8))

        # Unknown
        ctk.CTkLabel(stats_row, image=status_icons["unknown"], text="").pack(side="left", padx=(0, 4))
        ctk.CTkLabel(stats_row, text=str(counts["unknown"]), font=FONTS["body"], text_color=THEME["muted"]).pack(
            side="left")

        # progress bar
        pb = ctk.CTkProgressBar(left, height=6, fg_color=THEME["panel"], progress_color=THEME["gold"])
        pb.pack(fill="x", pady=(SPACING["sm"], 0))
        pb.set(progress if progress <= 1 else 1)

        # actions
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right", padx=SPACING["lg"], pady=SPACING["md"])

        ctk.CTkButton(right, text="Open ▶",  command=lambda: select_deck(name), width=90, **BTN_SOLID).pack(pady=2)
        ctk.CTkButton(right, text="Rename",  command=lambda: rename_deck(name), width=90, **BTN_GHOST).pack(pady=2)
        ctk.CTkButton(right, text="Copy",    command=lambda: copy_deck(name), width=90, **BTN_GHOST).pack(pady=2)
        ctk.CTkButton(right, text="Delete",  command=lambda: confirm_delete_deck(name), width=90, **BTN_GHOST).pack(pady=2)

        for child in (row, left):
            child.bind("<Enter>", lambda _e, w=row: w.configure(fg_color=THEME["card_hover"]))
            child.bind("<Leave>", lambda _e, w=row: w.configure(fg_color=THEME["card"]))

        bind_all_children_click(row, lambda: select_deck(name))

    if not decks:
        ctk.CTkLabel(sf, text="No decks yet. Add one!", font=FONTS["body"]).pack(pady=SPACING["lg"])
    else:
        for name in list(decks.keys()):
            deck_row(name)

    # footer buttons
    footer = ctk.CTkFrame(deck_select_frame, fg_color="transparent")
    footer.pack(pady=(0, SPACING["xl"]))
    ctk.CTkButton(footer, text="Import", command=open_excel_import_popup, width=180, **BTN_SOLID).pack(side="left", padx=SPACING["sm"])
    ctk.CTkButton(footer, text="Add Deck", command=open_deck_popup, width=180, **BTN_GHOST).pack(side="left", padx=SPACING["sm"])

# ==============================
# Main Menu (for selected deck)
# ==============================

def build_main_menu():
    for w in menu_frame.winfo_children():
        w.destroy()

    if not decks:
        build_deck_select(); show_frame(deck_select_frame); return

    if not current_deck or current_deck not in decks:
        cd = list(decks.keys())[0]
    else:
        cd = current_deck

    # Help 버튼 (우측 상단)
    help_btn = ctk.CTkButton(
        menu_frame,
        text="❓ Help",
        width=80,
        **BTN_GHOST,
        command=open_help_modal
    )
    help_btn.place(relx=1.0, x=-SPACING["xl"], y=SPACING["xl"], anchor="ne")

    # header card
    card = ctk.CTkFrame(menu_frame, fg_color=THEME["panel"], corner_radius=RADIUS["lg"], border_width=1, border_color=THEME["line"])
    card.pack(padx=SPACING["xl"], pady=(SPACING["xxl"], SPACING["xl"]))

    ctk.CTkLabel(card, text=f"Deck • {cd}", font=FONTS["h1"], text_color=THEME["gold"]).pack(pady=(SPACING["md"],0), padx=SPACING["xl"], anchor="w")
    total, counts, progress, _ = get_deck_stats(decks[cd])

    status_icons = {
        "unknown": icon_unknown_img,
        "partial": icon_partial_img,
        "known": icon_known_img
    }

    stats_row = ctk.CTkFrame(card, fg_color="transparent")
    stats_row.pack(pady=(0, SPACING["md"]), padx=SPACING["xl"], anchor="w")

    # Total
    ctk.CTkLabel(
        stats_row,
        text=f"Total {total}   |   ",
        font=FONTS["body"],
        text_color=THEME["muted"]
    ).pack(side="left")

    # Known
    ctk.CTkLabel(stats_row, image=status_icons["known"], text="").pack(side="left", padx=(0, 4))
    ctk.CTkLabel(stats_row, text=str(counts["known"]), font=FONTS["body"], text_color=THEME["muted"]).pack(side="left",
                                                                                                           padx=(0, 12))

    # Partial
    ctk.CTkLabel(stats_row, image=status_icons["partial"], text="").pack(side="left", padx=(0, 4))
    ctk.CTkLabel(stats_row, text=str(counts["partial"]), font=FONTS["body"], text_color=THEME["muted"]).pack(
        side="left", padx=(0, 12))

    # Unknown
    ctk.CTkLabel(stats_row, image=status_icons["unknown"], text="").pack(side="left", padx=(0, 4))
    ctk.CTkLabel(stats_row, text=str(counts["unknown"]), font=FONTS["body"], text_color=THEME["muted"]).pack(
        side="left")

    pb = ctk.CTkProgressBar(card, height=10, fg_color=THEME["card"], progress_color=THEME["gold"])
    pb.pack(fill="x", padx=SPACING["xl"], pady=(0, SPACING["lg"]))
    pb.set(progress if progress <= 1 else 1)

    # action grid
    actions = ctk.CTkFrame(menu_frame, fg_color="transparent")
    actions.pack(pady=(0, SPACING["xl"]))

    ctk.CTkButton(actions, text="➕  New Vocab", width=240, command=go_to_add_vocab, **BTN_SOLID).grid(row=0, column=0, padx=SPACING["md"], pady=SPACING["sm"])
    ctk.CTkButton(actions, text="🧠  Start Quiz", width=240, command=lambda: (build_quiz_filter(), show_frame(quiz_filter_frame)), **BTN_GHOST).grid(row=1, column=0, padx=SPACING["md"], pady=SPACING["sm"])
    ctk.CTkButton(actions, text="📋  Word List", width=240, command=build_word_list, **BTN_GHOST).grid(row=2, column=0, padx=SPACING["md"], pady=SPACING["sm"])
    ctk.CTkButton(
        actions,
        text="🎲  Random Word",
        width=240,
        command=lambda: (build_random_word_challenge(), show_frame(random_word_frame)),
        **BTN_GHOST
    ).grid(row=3, column=0, padx=SPACING["md"], pady=SPACING["sm"])
    ctk.CTkButton(
        actions,
        text="🔙  Deck Select",
        width=240,
        command=lambda: (build_deck_select(), show_frame(deck_select_frame)),
        **BTN_GHOST
    ).grid(row=4, column=0, padx=SPACING["md"], pady=SPACING["sm"])

# ==============================
# Add / Edit Word
# ==============================

def go_to_add_vocab():
    global editing_word
    editing_word = None
    word_entry.set(""); pos_entry.set(""); meaning_entry.set(""); example_entry.set("")
    build_add_vocab()
    show_frame(add_frame)

def build_add_vocab():
    global word_entry, pos_entry, meaning_entry, example_entry
    word_entry    = tk.StringVar()
    pos_entry     = tk.StringVar()
    meaning_entry = tk.StringVar()
    example_entry = tk.StringVar()

    for w in add_frame.winfo_children():
        w.destroy()

    # 현재 덱
    cd = current_deck if current_deck in decks else (list(decks.keys())[0] if decks else "Default")

    # ===== Hero Header (Choose Quiz 스타일) =====
    header_card = ctk.CTkFrame(
        add_frame,
        fg_color=THEME["panel"],
        corner_radius=RADIUS["lg"],
        border_width=1,
        border_color=THEME["line"]
    )
    header_card.pack(
        pady=(SPACING["xxl"], SPACING["lg"]),
        padx=SPACING["xl"],
        anchor="center"
    )

    # 제목
    ctk.CTkLabel(
        header_card,
        text="➕  Add Word",
        font=FONTS["h1"],
        text_color=THEME["gold"]
    ).pack(pady=(SPACING["md"], 0), padx=SPACING["xl"], anchor="w")

    # 덱 통계 + 진행바 (Choose Quiz처럼)
    total, counts, progress, _ = get_deck_stats(decks.get(cd, {}))

    status_icons = {
        "unknown": icon_unknown_img,
        "partial": icon_partial_img,
        "known":   icon_known_img
    }

    stats_row = ctk.CTkFrame(header_card, fg_color="transparent")
    stats_row.pack(pady=(0, SPACING["md"]), padx=SPACING["xl"], anchor="w")

    ctk.CTkLabel(
        stats_row,
        text=f"Total {total}   |   ",
        font=FONTS["body"],
        text_color=THEME["muted"]
    ).pack(side="left")

    ctk.CTkLabel(stats_row, image=status_icons["known"], text="").pack(side="left", padx=(0, 4))
    ctk.CTkLabel(stats_row, text=str(counts.get("known", 0)), font=FONTS["body"], text_color=THEME["muted"]).pack(side="left", padx=(0, 12))

    ctk.CTkLabel(stats_row, image=status_icons["partial"], text="").pack(side="left", padx=(0, 4))
    ctk.CTkLabel(stats_row, text=str(counts.get("partial", 0)), font=FONTS["body"], text_color=THEME["muted"]).pack(side="left", padx=(0, 12))

    ctk.CTkLabel(stats_row, image=status_icons["unknown"], text="").pack(side="left", padx=(0, 4))
    ctk.CTkLabel(stats_row, text=str(counts.get("unknown", 0)), font=FONTS["body"], text_color=THEME["muted"]).pack(side="left")

    pb = ctk.CTkProgressBar(header_card, height=10, fg_color=THEME["card"], progress_color=THEME["gold"])
    pb.pack(fill="x", padx=SPACING["xl"], pady=(0, SPACING["lg"]))
    pb.set(progress if progress <= 1 else 1)

    # ===== 폼(헤더 밖) =====
    form = ctk.CTkFrame(add_frame, fg_color="transparent")
    form.pack(pady=0)

    def field(lbl, var, placeholder=""):
        ctk.CTkLabel(form, text=lbl, font=FONTS["body_bold"]).pack(anchor="center", padx=SPACING["xl"])
        ent = ctk.CTkEntry(form, textvariable=var, width=240, placeholder_text=placeholder)
        ent.pack(pady=(0, SPACING["md"]))
        return ent

    w_ent = field("Word", word_entry, "ambivalent")
    field("Part of Speech", pos_entry, "adjective / noun / ...")
    field("Meaning", meaning_entry, "having mixed feelings or contradictory ideas")
    field("Example", example_entry, "She felt ambivalent about her new job.")
    w_ent.focus_set()

    # 버튼 영역 (폼 아래)
    row = ctk.CTkFrame(add_frame, fg_color="transparent")
    row.pack(pady=SPACING["md"])

    def save_word():
        global editing_word

        # 현재 덱 확인
        cd2 = current_deck if current_deck in decks else (list(decks.keys())[0] if decks else None)
        if not cd2:
            modal_warn("⚠️ No deck available.")
            return

        # 입력값 가져오기
        w = word_entry.get().strip()
        m = meaning_entry.get().strip()

        # 필수값 체크
        if not w or not m:
            def build_warn(parent, overlay):
                ctk.CTkLabel(
                    parent,
                    text="⚠️ Please enter both word and meaning.",
                    font=FONTS["body"],
                    text_color=THEME["muted"],
                    justify="center",
                    wraplength=360
                ).pack(pady=SPACING["md"])
                ctk.CTkButton(parent, text="OK", command=overlay.destroy, **BTN_SOLID) \
                    .pack(pady=SPACING["sm"])

            show_modal("Warning", build_warn, show_close=False)
            return

        # 수정 모드에서 단어명이 변경된 경우 기존 키 삭제
        if editing_word and editing_word != w:
            decks[cd2].pop(editing_word, None)

        # 단어 수 제한 체크
        if not editing_word and len(decks[cd2]) >= 100:
            def build_full(parent, overlay):
                ctk.CTkLabel(
                    parent,
                    text="⚠️ This deck already has 100 words.",
                    font=FONTS["body"],
                    text_color=THEME["muted"],
                    justify="center"
                ).pack(pady=SPACING["md"])
                ctk.CTkButton(parent, text="OK", command=overlay.destroy, **BTN_SOLID) \
                    .pack(pady=SPACING["sm"])

            show_modal("Warning", build_full, show_close=False)
            return

        # 단어 저장 (status는 기본 unknown)
        decks[cd2][w] = {
            "part_of_speech": pos_entry.get().strip(),
            "meaning": m,
            "example": example_entry.get().strip(),
            "status": decks[cd2].get(w, {}).get("status", "unknown")
        }
        save_decks()
        editing_word = None

        # 입력창 초기화
        word_entry.set("")
        pos_entry.set("")
        meaning_entry.set("")
        example_entry.set("")

        # ✅ 화면 전체 리빌드 → 헤더 통계/진행바 즉시 반영
        build_add_vocab()

        # 저장 완료 모달
        def build_saved(parent, overlay):
            ctk.CTkLabel(
                parent,
                text=f"✅ '{w}' has been saved.",
                font=FONTS["body"],
                text_color=THEME["muted"],
                justify="center"
            ).pack(pady=SPACING["md"])
            ctk.CTkButton(parent, text="OK", command=overlay.destroy, **BTN_SOLID) \
                .pack(pady=SPACING["sm"])

        show_modal("Saved", build_saved, show_close=False)

    ctk.CTkButton(
        row,
        text="💾  Save",
        command=save_word,
        width=240,
        **BTN_SOLID
    ).pack(pady=(0, SPACING["sm"]))  # 위쪽 → 아래쪽 간격

    # Menu 버튼
    ctk.CTkButton(
        row,
        text="🏠  Menu",
        command=lambda: (build_main_menu(), show_frame(menu_frame)),
        width=240,
        **BTN_GHOST
    ).pack()

# ==============================
# Quiz (scope -> quiz)
# ==============================

def build_quiz_filter():
    for w in quiz_filter_frame.winfo_children():
        w.destroy()

    cd = current_deck if current_deck in decks else (list(decks.keys())[0] if decks else None)
    if not cd:
        modal_info("No decks available.")
        return

    # ===== Hero Header (Main Menu 스타일) =====
    header = ctk.CTkFrame(
        quiz_filter_frame,
        fg_color=THEME["panel"],
        corner_radius=RADIUS["lg"],
        border_width=1,
        border_color=THEME["line"]
    )
    header.pack(pady=(SPACING["xxl"], SPACING["lg"]), padx=SPACING["xl"], anchor="center")

    # 제목
    ctk.CTkLabel(
        header,
        text="📜  Choose Quiz",
        font=FONTS["h1"],
        text_color=THEME["gold"]
    ).pack(pady=(SPACING["md"], 0), padx=SPACING["xl"], anchor="w")

    # 덱 통계
    total, counts, progress, _ = get_deck_stats(decks[cd])
    status_icons = {
        "unknown": icon_unknown_img,
        "partial": icon_partial_img,
        "known": icon_known_img
    }

    stats_row = ctk.CTkFrame(header, fg_color="transparent")
    stats_row.pack(pady=(0, SPACING["md"]), padx=SPACING["xl"], anchor="w")

    ctk.CTkLabel(
        stats_row,
        text=f"Total {total}   |   ",
        font=FONTS["body"],
        text_color=THEME["muted"]
    ).pack(side="left")

    ctk.CTkLabel(stats_row, image=status_icons["known"], text="").pack(side="left", padx=(0, 4))
    ctk.CTkLabel(stats_row, text=str(counts["known"]), font=FONTS["body"], text_color=THEME["muted"]).pack(side="left", padx=(0, 12))

    ctk.CTkLabel(stats_row, image=status_icons["partial"], text="").pack(side="left", padx=(0, 4))
    ctk.CTkLabel(stats_row, text=str(counts["partial"]), font=FONTS["body"], text_color=THEME["muted"]).pack(side="left", padx=(0, 12))

    ctk.CTkLabel(stats_row, image=status_icons["unknown"], text="").pack(side="left", padx=(0, 4))
    ctk.CTkLabel(stats_row, text=str(counts["unknown"]), font=FONTS["body"], text_color=THEME["muted"]).pack(side="left")

    # 진행바 (카드 폭에 맞춤)
    pb = ctk.CTkProgressBar(header, height=10, fg_color=THEME["card"], progress_color=THEME["gold"])
    pb.pack(fill="x", padx=SPACING["xl"], pady=(0, SPACING["lg"]))
    pb.set(progress if progress <= 1 else 1)

    # ===== Scope Buttons =====
    scopes = [
        ("📚  All Words", "all", THEME["gold"], None, BTN_SOLID),
        ("", "unknown", THEME["gold"], icon_unknown_img, BTN_GHOST),
        ("", "partial", THEME["gold"], icon_partial_img, BTN_GHOST),
        ("", "known", THEME["gold"], icon_known_img, BTN_GHOST),
    ]

    for label, scope, color, icon, style in scopes:
        btn_text = f"{label}"
        btn = ctk.CTkButton(
            quiz_filter_frame,
            text=btn_text,
            image=icon,
            width=240,
            command=lambda s=scope: start_quiz_mode(s),
            **style  # 여기서 BTN_SOLID 또는 BTN_GHOST 적용
        )
        btn.pack(pady=(SPACING["sm"], 0))

    # ===== Back Button =====
    ctk.CTkButton(
        quiz_filter_frame,
        text="🔙  Back",
        command=lambda: show_frame(menu_frame),
        width=240,
        **BTN_GHOST
    ).pack(pady=SPACING["xl"])

def start_quiz_mode(filter_type="all"):
    cd = current_deck if current_deck in decks else (list(decks.keys())[0] if decks else None)
    if not decks:
        modal_info("No decks available.")
        return
    if not any(decks[d] for d in decks):
        modal_info("No words available.")
        return

    # 필터링
    if filter_type == "all":
        filtered = list(decks[cd].keys())
    else:
        filtered = [w for w, info in decks[cd].items() if info.get("status") == filter_type]

    if not filtered:
        modal_info("No words for this scope.")
        return

    # ✅ 퀴즈 시작 시 단어 순서 섞기
    random.shuffle(filtered)

    # 전역 상태 세팅
    global sorted_words, quiz_index, current_word
    sorted_words = filtered
    quiz_index = 0
    current_word = sorted_words[quiz_index]

    # 퀴즈 화면 빌드 및 전환
    build_quiz()
    show_frame(quiz_frame)

    # 키 바인딩
    root.bind("<Left>",  lambda e: quiz_prev())
    root.bind("<Right>", lambda e: quiz_next())

def update_status(status):
    cd = current_deck
    if cd in decks and current_word in decks[cd]:
        decks[cd][current_word]["status"] = status
        save_decks()
        build_main_menu()

def quiz_next():
    global quiz_index, current_word
    if 'sorted_words' not in globals() or not sorted_words: return
    if quiz_index < len(sorted_words)-1:
        quiz_index += 1
        current_word = sorted_words[quiz_index]
        build_quiz()

def quiz_prev():
    global quiz_index, current_word
    if 'sorted_words' not in globals() or not sorted_words: return
    if quiz_index > 0:
        quiz_index -= 1
        current_word = sorted_words[quiz_index]
        build_quiz()

def build_quiz():
    for w in quiz_frame.winfo_children():
        w.destroy()

    # ===== 말줄임표 + Tooltip 유틸 =====
    def truncate_text(text, max_len=20):
        return text if len(text) <= max_len else text[:max_len-1] + "…"

    def create_tooltip(widget, text):
        tooltip = tk.Toplevel(widget)
        tooltip.withdraw()
        tooltip.overrideredirect(True)
        tooltip.configure(bg="#333333")

        label = tk.Label(
            tooltip,
            text=text,
            bg="#333333",
            fg="white",
            font=("Arial", 10),
            padx=6,
            pady=3,
            wraplength=300,
            justify="left"
        )
        label.pack()

        def enter(event):
            tooltip.deiconify()
            x = event.x_root + 10
            y = event.y_root + 10
            tooltip.geometry(f"+{x}+{y}")

        def leave(event):
            tooltip.withdraw()

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    # ===== 버튼 스타일 =====
    btn_ghost_small = {**BTN_GHOST, "height": 36}
    btn_ghost_icon  = {**BTN_GHOST, "height": 50, "width": 50}

    cd = current_deck
    total = len(sorted_words)
    progress = (quiz_index + 1) / total if total else 0
    word_status = decks[cd][current_word].get("status", "unknown")

    # ===== 상단 카드 (폭 고정) =====
    header_wrap = ctk.CTkFrame(quiz_frame, fg_color="transparent")
    header_wrap.pack(pady=(SPACING["xxl"], 0))

    header = ctk.CTkFrame(
        header_wrap,
        fg_color=THEME["panel"],
        corner_radius=RADIUS["lg"],
        border_width=1,
        border_color=THEME["line"],
        width=600  # 폭 고정
    )
    header.pack(padx=SPACING["xl"])

    # 첫 줄: 상태 아이콘 + 단어(말줄임표) + 발음 버튼
    status_icon_img = {
        "unknown": icon_unknown_img,
        "partial": icon_partial_img,
        "known": icon_known_img,
    }
    top_row = ctk.CTkFrame(header, fg_color="transparent")
    top_row.pack(pady=(SPACING["sm"], SPACING["xs"]))

    ctk.CTkLabel(top_row, image=status_icon_img[word_status], text="").pack(side="left", padx=(0, SPACING["sm"]))

    display_word = truncate_text(current_word, 15)
    word_label = ctk.CTkLabel(
        top_row,
        text=display_word,
        font=FONTS["h2"],
        text_color=THEME["gold"]
    )
    word_label.pack(side="left")
    create_tooltip(word_label, current_word)

    ctk.CTkButton(top_row, text="🔊", width=36, command=lambda: speak_text(current_word), **btn_ghost_small)\
        .pack(side="left", padx=SPACING["sm"])

    # 둘째 줄: 좌/우 이동 버튼
    nav_row = ctk.CTkFrame(header, fg_color="transparent")
    nav_row.pack(pady=(0, SPACING["xs"]))
    ctk.CTkButton(nav_row, text="◀", width=50, command=quiz_prev, **btn_ghost_small).pack(side="left", padx=SPACING["sm"])
    ctk.CTkButton(nav_row, text="▶", width=50, command=quiz_next, **btn_ghost_small).pack(side="left", padx=SPACING["sm"])

    # 진행바
    pb = ctk.CTkProgressBar(header, height=8, fg_color=THEME["card"], progress_color=THEME["gold"])
    pb.pack(fill="x", padx=SPACING["xl"], pady=(0, SPACING["xs"]))
    pb.set(progress if progress <= 1 else 1)

    # ===== 상태 변경 버튼 =====
    st = ctk.CTkFrame(quiz_frame, fg_color="transparent")
    st.pack(pady=8)
    ctk.CTkButton(st, image=icon_unknown_img, text="", command=lambda: (update_status("unknown"), build_quiz()), **btn_ghost_icon)\
        .pack(side="left", padx=SPACING["sm"])
    ctk.CTkButton(st, image=icon_partial_img, text="", command=lambda: (update_status("partial"), build_quiz()), **btn_ghost_icon)\
        .pack(side="left", padx=SPACING["sm"])
    ctk.CTkButton(st, image=icon_known_img, text="", command=lambda: (update_status("known"), build_quiz()), **btn_ghost_icon)\
        .pack(side="left", padx=SPACING["sm"])

    # ===== 정답/예문 표시 =====
    answer = ctk.CTkLabel(
        quiz_frame,
        text="",
        font=FONTS["h3"],
        text_color=THEME["muted"],
        wraplength=640,
        justify="center",
        height=28
    )
    answer.pack(pady=0)

    # ===== 액션 버튼 =====
    actions = ctk.CTkFrame(quiz_frame, fg_color="transparent")
    actions.pack(pady=(SPACING["lg"], SPACING["xl"]))

    ctk.CTkButton(
        actions,
        text="📖  Show Answer",
        width=240,
        command=lambda: answer.configure(
            text=f"({decks[cd][current_word].get('part_of_speech','')}) {decks[cd][current_word].get('meaning','')}"
        ),
        **BTN_SOLID
    ).grid(row=0, column=0, padx=SPACING["md"], pady=SPACING["sm"])

    ctk.CTkButton(
        actions,
        text="💬  Example",
        width=240,
        command=lambda: answer.configure(
            text=f"Ex: {decks[cd][current_word].get('example','').strip() or 'No example saved.'}"
        ),
        **BTN_GHOST
    ).grid(row=1, column=0, padx=SPACING["md"], pady=SPACING["sm"])

    ctk.CTkButton(
        actions,
        text="🔙  Back",
        width=240,
        command=lambda: (build_quiz_filter(), show_frame(quiz_filter_frame)),
        **BTN_GHOST
    ).grid(row=2, column=0, padx=SPACING["md"], pady=SPACING["sm"])

    ctk.CTkButton(
        actions,
        text="🏠  Menu",
        width=240,
        command=lambda: (build_main_menu(), show_frame(menu_frame)),
        **BTN_GHOST
    ).grid(row=3, column=0, padx=SPACING["md"], pady=SPACING["sm"])

# ==============================
# Word List (search / filter / edit)
# ==============================

search_var = tk.StringVar()
filter_vars = {
    "unknown": tk.BooleanVar(value=False),
    "partial": tk.BooleanVar(value=False),
    "known":   tk.BooleanVar(value=False),
}

def update_word_list():
    cd = current_deck if current_deck in decks else (list(decks.keys())[0] if decks else None)
    if not cd: return
    prev_selected = selected_word["text"]

    global filtered_words
    kw = search_var.get().lower().strip()
    statuses = [s for s,v in filter_vars.items() if v.get()]
    items = list(decks[cd].items())
    if statuses:
        items = [(w,i) for w,i in items if i.get("status") in statuses]
    if kw:
        items = [(w,i) for w,i in items if kw in w.lower()]
    if shuffle_enabled:
        random.shuffle(items)
    filtered_words = items
    build_word_list_rows()

    # 선택 복원 (있고, 결과에 남아있으면 하이라이트 포함)

    if prev_selected:
        for idx, (w, _) in enumerate(filtered_words):
            if w == prev_selected:
                set_selection(idx)
                break
        else:
            set_selection(None)

    show_frame(list_frame)

def edit_word(word):
    cd = current_deck
    if word not in decks[cd]:
        return

    d = decks[cd][word]

    # 기존 값 세팅
    w_var  = tk.StringVar(value=word)
    pos_var = tk.StringVar(value=d.get("part_of_speech", ""))
    m_var   = tk.StringVar(value=d.get("meaning", ""))
    ex_var  = tk.StringVar(value=d.get("example", ""))
    status_var = tk.StringVar(value=d.get("status", "unknown"))

    def save_changes():
        new_word = w_var.get().strip()
        if not new_word or not m_var.get().strip():
            overlay.destroy()
            root.after(10, lambda: modal_warn("⚠️ Please enter both word and meaning."))
            return

        # 단어 이름이 바뀌면 기존 키 삭제
        if new_word != word:
            decks[cd].pop(word, None)

        decks[cd][new_word] = {
            "part_of_speech": pos_var.get().strip(),
            "meaning": m_var.get().strip(),
            "example": ex_var.get().strip(),
             "status": status_var.get()
        }
        save_decks()
        refresh_word_list_header()
        update_word_list()
        overlay.destroy()

    def build(parent, overlay_ref):
        nonlocal overlay
        overlay = overlay_ref
        ctk.CTkLabel(parent, text="Edit Word", font=FONTS["h1"], text_color=THEME["gold"]).pack(pady=SPACING["sm"])

        ctk.CTkLabel(parent, text="Word", font=FONTS["body_bold"]).pack(anchor="center", padx=SPACING["xl"])
        ctk.CTkEntry(parent, textvariable=w_var, width=300).pack(pady=(0, SPACING["sm"]))

        ctk.CTkLabel(parent, text="Part of Speech", font=FONTS["body_bold"]).pack(anchor="center", padx=SPACING["xl"])
        ctk.CTkEntry(parent, textvariable=pos_var, width=300).pack(pady=(0, SPACING["sm"]))

        ctk.CTkLabel(parent, text="Meaning", font=FONTS["body_bold"]).pack(anchor="center", padx=SPACING["xl"])
        ctk.CTkEntry(parent, textvariable=m_var, width=300).pack(pady=(0, SPACING["sm"]))

        ctk.CTkLabel(parent, text="Example", font=FONTS["body_bold"]).pack(anchor="center", padx=SPACING["xl"])
        ctk.CTkEntry(parent, textvariable=ex_var, width=300).pack(pady=(0, SPACING["md"]))

        ctk.CTkLabel(parent, text="Status", font=FONTS["body_bold"]).pack(anchor="center")
        status_menu = ctk.CTkOptionMenu(
            parent,
            variable=status_var,
            values=["unknown", "partial", "known"],
            width=300,
            fg_color=THEME["panel"],  # 드롭다운 배경
            button_color=THEME["gold"],  # 선택 버튼 색
            button_hover_color=THEME["gold_dim"],  # 버튼 hover 색
            text_color=THEME["text"]  # 글자 색
        )

        status_menu.pack(pady=(0, SPACING["md"]))

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(pady=SPACING["sm"])
        ctk.CTkButton(row, text="Save", command=save_changes, **BTN_SOLID).pack(side="left", padx=SPACING["sm"])
        ctk.CTkButton(row, text="Cancel", command=overlay.destroy, **BTN_GHOST).pack(side="left", padx=SPACING["sm"])

    overlay = None
    show_modal("", build, show_close=False)

def delete_word(word):
    if not word: return
    cd = current_deck
    modal_confirm(
        f"Delete '{word}'?",
        lambda: (
            decks[current_deck].pop(word, None),
            save_decks(),
            refresh_word_list_header(),  # ← 헤더 즉시 갱신
            update_word_list()
        )
    )

def show_hint_popup(word):
    cd = current_deck
    if word not in decks[cd]: return
    ex = decks[cd][word].get("example","").strip()
    if not ex:
        modal_info("No example sentence saved.")
        return

    def b(parent, overlay):
        ctk.CTkLabel(parent, text=ex, font=FONTS["body"], wraplength=380).pack(pady=SPACING["md"])
        ctk.CTkButton(parent, text="Close", command=overlay.destroy, **BTN_SOLID).pack(pady=SPACING["sm"])
    show_modal(f"Hint • {word}", b, show_close=False)

def toggle_meanings():
    global hide_meanings
    hide_meanings = not hide_meanings
    # 의미 라벨만 업데이트
    for i, (_, _, _, _, meaning_lbl) in enumerate(row_widgets):
        if i < len(filtered_words):
            meaning_lbl.configure(
                text="■"*30 if hide_meanings else filtered_words[i][1].get("meaning","")
            )

def build_word_list():
    for w in list_frame.winfo_children():
        w.destroy()

    global search_var, row_widgets
    row_widgets = []

    cd = current_deck if current_deck in decks else (list(decks.keys())[0] if decks else "Default")
    build_deck_header(list_frame, "📋  Word List", cd)

    # === 선택 액션 버튼 줄 (아이콘+텍스트) ===
    action_row = ctk.CTkFrame(list_frame, fg_color="transparent")
    action_row.pack(pady=(SPACING["xs"], SPACING["sm"]))

    speak_btn = ctk.CTkButton(
        action_row, text="🔊 Speak", width=90,
        command=lambda: require_selection(lambda w: speak_text(w)),
        **BTN_GHOST
    )

    hint_btn = ctk.CTkButton(
        action_row, text="💡 Hint", width=90,
        command=lambda: require_selection(lambda w: show_hint_popup(w)),
        **BTN_GHOST
    )
    edit_btn = ctk.CTkButton(
        action_row, text="✏ Edit", width=90,
        command=lambda: require_selection(lambda w: edit_word(w)),
        **BTN_GHOST
    )
    del_btn = ctk.CTkButton(
        action_row, text="🗑 Delete", width=90,
        command=lambda: require_selection(lambda w: delete_word(w)),
        **BTN_GHOST
    )

    speak_btn.pack(side="left", padx=2)
    hint_btn.pack(side="left", padx=2)
    edit_btn.pack(side="left", padx=2)
    del_btn.pack(side="left", padx=2)

    for b in (speak_btn, hint_btn, edit_btn, del_btn):
        b.configure(state="disabled")
    list_frame._action_buttons = (speak_btn, hint_btn, edit_btn, del_btn)

    # === 필터 카드 (Search + 상태 필터 + Hide/Shuffle) ===
    filter_card = ctk.CTkFrame(list_frame, fg_color=THEME["panel"], corner_radius=RADIUS["md"])
    filter_card.pack(pady=(SPACING["sm"], SPACING["sm"]), padx=SPACING["xl"], fill="x")

    search_var = tk.StringVar()
    ctk.CTkLabel(filter_card, text="Search", font=FONTS["body_bold"]).pack(side="left", padx=(SPACING["md"], SPACING["xs"]))
    se = ctk.CTkEntry(filter_card, textvariable=search_var, width=200, placeholder_text="type a word…")
    se.pack(side="left", padx=(0, SPACING["md"]))

    for status, label in [("unknown", "Don't Know"), ("partial", "Kind of Know"), ("known", "Know")]:
        cb = ctk.CTkCheckBox(
            filter_card,
            text=label,
            variable=filter_vars[status],
            checkbox_width=16,
            checkbox_height=16,
            font=FONTS["body"],
            border_width=2,
            command=update_word_list
        )
        cb.pack(side="left", padx=(SPACING["xs"], 0))

    def toggle_and_update():
        toggle_meanings()
        hide_btn.configure(text=("🙈 Hide Meanings" if not hide_meanings else "👀 Show Meanings"))

    hide_btn = ctk.CTkButton(
        filter_card,
        text=("🙈 Hide Meanings" if not hide_meanings else "👀 Show Meanings"),
        command=toggle_and_update,
        **BTN_GHOST
    )
    hide_btn.pack(side="right", padx=SPACING["sm"])

    def toggle_shuffle():
        global shuffle_enabled
        shuffle_enabled = not shuffle_enabled
        shuffle_btn.configure(text=("🔀 Shuffle ON" if shuffle_enabled else "➡️ Shuffle OFF"))
        update_word_list()

    shuffle_btn = ctk.CTkButton(
        filter_card,
        text=("🔀 Shuffle ON" if shuffle_enabled else "➡️ Shuffle OFF"),
        command=toggle_shuffle,
        **BTN_GHOST
    )
    shuffle_btn.pack(side="right", padx=SPACING["sm"])

    # Search 입력 변경 시 업데이트 (디바운스)
    def debounce(delay=200):
        if hasattr(root, "_search_job"):
            try:
                root.after_cancel(root._search_job)
            except Exception:
                pass
        root._search_job = root.after(delay, update_word_list)
    search_var.trace_add("write", lambda *_: debounce())

    # === 테이블 헤더 ===
    hdr = ctk.CTkFrame(list_frame, fg_color=THEME["panel"], corner_radius=RADIUS["sm"])
    hdr.pack(fill="x", padx=SPACING["xl"], pady=(SPACING["sm"], 0))
    for i, (t, w) in enumerate([("Status", 80), ("Word", 200), ("Part of Speech", 130), ("Meaning", 520)]):
        c = ctk.CTkLabel(hdr, text=t, font=FONTS["body_bold"])
        c.grid(row=0, column=i, sticky="w", padx=(SPACING["lg"], 0), pady=SPACING["xs"])
        hdr.grid_columnconfigure(i, minsize=w, weight=0)

    # === 리스트 영역 ===
    body = ctk.CTkScrollableFrame(list_frame, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=SPACING["xl"], pady=(0, SPACING["lg"]))
    list_frame._rows_container = body

    # 메뉴 버튼
    ctk.CTkButton(
        list_frame, text="🏠  Menu",
        command=lambda: (build_main_menu(), show_frame(menu_frame)),
        width=220, **BTN_GHOST
    ).pack(pady=SPACING["lg"])

    update_word_list()

    # === 키보드 네비게이션 바인딩 ===
    def on_key_up(event=None):
        if selected_index["idx"] is None:
            if filtered_words:
                set_selection(0)  # 아무 것도 선택 안 되어 있으면 첫 행 선택
        else:
            new_idx = max(0, selected_index["idx"] - 1)
            set_selection(new_idx)

    def on_key_down(event=None):
        if selected_index["idx"] is None:
            if filtered_words:
                set_selection(0)
        else:
            new_idx = min(len(filtered_words) - 1, selected_index["idx"] + 1)
            set_selection(new_idx)

    root.bind("<Up>", on_key_up)
    root.bind("<Down>", on_key_down)

def build_random_word_challenge():
    for w in random_word_frame.winfo_children():
        w.destroy()

    # ===== 헤더 카드 =====
    header_card = ctk.CTkFrame(
        random_word_frame,
        fg_color=THEME["panel"],
        corner_radius=RADIUS["lg"],
        border_width=1,
        border_color=THEME["line"],
    )
    header_card.pack(
        pady=(SPACING["xxl"], SPACING["lg"]),
        padx=SPACING["xl"],
        anchor="center",
    )

    # 제목
    ctk.CTkLabel(
        header_card,
        text="🎲  Random Word",
        font=FONTS["h1"],
        text_color=THEME["gold"]
    ).pack(pady=(SPACING["md"], 0), padx=SPACING["xl"], anchor="w")

    # 단어 표시 라벨
    word_label = ctk.CTkLabel(
        header_card,
        text="",
        font=FONTS["h1"],
        text_color=THEME["white"]
    )
    word_label.pack(pady=(SPACING["sm"], SPACING["md"]))

    # ===== 기능 함수 =====
    def show_random_word():
        if not WORD_LIST:
            return
        word_label.configure(text=random.choice(WORD_LIST))

    def save_and_edit_word():
        w = word_label.cget("text")
        if not w:
            return

        cd = current_deck if current_deck in decks else None
        if not cd:
            modal_warn("⚠️ No deck selected.")
            return

        # 🔹 단어 수 제한 체크
        if len(decks[cd]) >= 100:
            modal_warn(f"⚠️ Deck '{cd}' already has 100 words.\nCannot add more.")
            return

        if w in decks[cd]:
            modal_info(f"ℹ️ '{w}' is already in deck '{cd}'.")
            return

        # 기본 데이터로 저장
        decks[cd][w] = {
            "part_of_speech": "",
            "meaning": "",
            "example": "",
            "status": "unknown"
        }
        save_decks()

        # === 저장 후 즉시 편집 모달 ===
        pos_var = tk.StringVar()
        m_var   = tk.StringVar()
        ex_var  = tk.StringVar()

        def apply_changes():
            decks[cd][w]["part_of_speech"] = pos_var.get().strip()
            decks[cd][w]["meaning"] = m_var.get().strip()
            decks[cd][w]["example"] = ex_var.get().strip()
            save_decks()

            # 편집 모달 닫기
            overlay.destroy()

            # 다음 루프에서 새 모달 호출 (중첩 방지)
            root.after(10, lambda: modal_info(f"✅ '{w}' saved & updated."))

            show_random_word()

        def build_edit(parent, overlay_ref):
            nonlocal overlay
            overlay = overlay_ref
            ctk.CTkLabel(parent, text=f"Edit '{w}'", font=FONTS["h2"], text_color=THEME["gold"]).pack(pady=SPACING["sm"])

            ctk.CTkLabel(parent, text="Part of Speech", font=FONTS["body_bold"]).pack(anchor="center")
            ctk.CTkEntry(parent, textvariable=pos_var, width=300).pack(pady=(0, SPACING["sm"]))

            ctk.CTkLabel(parent, text="Meaning", font=FONTS["body_bold"]).pack(anchor="center")
            ctk.CTkEntry(parent, textvariable=m_var, width=300).pack(pady=(0, SPACING["sm"]))

            ctk.CTkLabel(parent, text="Example", font=FONTS["body_bold"]).pack(anchor="center")
            ctk.CTkEntry(parent, textvariable=ex_var, width=300).pack(pady=(0, SPACING["md"]))

            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(pady=SPACING["sm"])
            ctk.CTkButton(row, text="Save", command=apply_changes, **BTN_SOLID).pack(side="left", padx=SPACING["sm"])
            ctk.CTkButton(row, text="Cancel", command=lambda: (overlay.destroy(), show_random_word()), **BTN_GHOST).pack(side="left", padx=SPACING["sm"])

        overlay = None
        show_modal("", build_edit, show_close=False)

    # 1줄: Random Word 버튼
    ctk.CTkButton(
        random_word_frame,
        text="🎲  Random Word",
        command=show_random_word,
        width=240,
        **BTN_SOLID
    ).pack(pady=5)

    # 2줄: Save & Edit 버튼
    ctk.CTkButton(
        random_word_frame,
        text="💾  Save & Edit",
        command=save_and_edit_word,
        width=240,
        **BTN_GHOST
    ).pack(pady=5)

    # 3줄: Menu 버튼
    ctk.CTkButton(
        random_word_frame,
        text="🏠  Menu",
        command=lambda: (build_main_menu(), show_frame(menu_frame)),
        width=240,
        **BTN_GHOST
    ).pack(pady=5)

    # ✅ 화면 진입 시 바로 첫 단어 표시
    show_random_word()
# 공통 선택 헬퍼: 인덱스와(옵션) 행 위젯을 받아 선택/하이라이트/버튼 활성화까지 한 번에
def set_selection(idx, row=None):
    if idx is None or idx < 0 or idx >= len(filtered_words):
        # 범위를 벗어나면 선택 해제
        selected_index["idx"] = None
        selected_word["text"] = None
        for (rf, *_ ) in row_widgets:
            try: rf.configure(fg_color="transparent")
            except: pass
        for b in getattr(list_frame, "_action_buttons", []):
            b.configure(state="disabled")
        return

    selected_index["idx"] = idx
    selected_word["text"] = filtered_words[idx][0]

    # 하이라이트 갱신
    for (rf, *_ ) in row_widgets:
        try: rf.configure(fg_color="transparent")
        except: pass
    if row is None:
        row = row_widgets[idx][0]
    try: row.configure(fg_color=THEME["card_hover"])
    except: pass

    # 액션 버튼 활성화
    for b in getattr(list_frame, "_action_buttons", []):
        b.configure(state="normal")

def build_word_list_rows():
    global row_widgets
    body = list_frame._rows_container

    # 처음 호출 시에만 행 위젯 생성
    if not row_widgets:
        for i in range(VISIBLE_ROWS):
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.grid(row=i, column=0, sticky="w", padx=(0,0))

            status_lbl = ctk.CTkLabel(row, width=60, anchor="w")
            status_lbl.grid(row=0, column=0, sticky="w", padx=(SPACING["lg"],0))

            word_lbl = ctk.CTkLabel(row, font=FONTS["body_bold"], width=180, anchor="w", wraplength=180, justify="left")
            word_lbl.grid(row=0, column=1, sticky="w", padx=(SPACING["lg"],0))

            pos_lbl = ctk.CTkLabel(row, width=120, anchor="w", wraplength=120, justify="left")
            pos_lbl.grid(row=0, column=2, sticky="w", padx=(SPACING["lg"],0))

            meaning_lbl = ctk.CTkLabel(row, width=450, anchor="w", wraplength=450, justify="left")
            meaning_lbl.grid(row=0, column=3, sticky="w", padx=(SPACING["lg"],0))

            row_widgets.append((row, status_lbl, word_lbl, pos_lbl, meaning_lbl))

    # 데이터만 갱신 + 클릭 바인딩 재설정
    for i, (row, status_lbl, word_lbl, pos_lbl, meaning_lbl) in enumerate(row_widgets):
        if i < len(filtered_words):
            w, info = filtered_words[i]
            status_icons = {
                "unknown": icon_unknown_img,
                "partial": icon_partial_img,
                "known": icon_known_img
            }
            status_lbl.configure(
                image=status_icons.get(info.get("status", "unknown")),
                text=""
            )
            word_lbl.configure(text=w)
            pos_lbl.configure(text=info.get("part_of_speech",""))
            meaning_lbl.configure(text="■"*30 if hide_meanings else info.get("meaning",""))
            row.grid()

            # ✅ 클릭 바인딩 재설정
            def on_select(idx=i, rf=row):
                if hasattr(root, "_search_job"):
                    try:
                        root.after_cancel(root._search_job)
                    except:
                        pass
                set_selection(idx, rf)

            for wdg in (row, status_lbl, word_lbl, pos_lbl, meaning_lbl):
                wdg.bind("<Button-1>", lambda e, idx=i, rf=row: on_select(idx, rf=rf))
        else:
            row.grid_remove()

# ==============================
# About / Reset
# ==============================

def show_about():
    def build(parent, overlay):
        ctk.CTkLabel(parent, text="Vocab King", font=FONTS["h1"], text_color=THEME["white"]).pack()
        ctk.CTkLabel(parent, text="Version 1.0 (Optimized)\n"
                                  "Created by Henry Shin\n"
                                  "VocabKin2025@gmail.com\n"
                                  "Designed for intuitive vocabulary learning.", font=FONTS["body"], justify="center").pack(pady=SPACING["xs"])
        ctk.CTkButton(parent, text="Close", command=overlay.destroy, **BTN_SOLID).pack(pady=SPACING["md"])
    show_modal("About", show_about_inner := build, show_close=False)

def reset_app():
    """앱 전체를 초기화하는 커스텀 확인 모달"""
    def build(parent, overlay):
        # 안내 문구
        ctk.CTkLabel(
            parent,
            text="Reset the app?\nAll decks and words will be deleted.",
            font=FONTS["body"],
            text_color=THEME["muted"],
            justify="center"
        ).pack(pady=SPACING["md"])

        # 버튼 영역
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(pady=SPACING["md"])

        def do_reset():
            try:
                # 데이터 파일 삭제
                if os.path.exists(VOCAB_FILE):
                    os.remove(VOCAB_FILE)

                # 메모리 초기화
                global decks, current_deck
                decks = {"Default": {}}
                current_deck = "Default"
                save_decks()

                # UI 갱신
                overlay.destroy()
                build_deck_select()
                show_frame(deck_select_frame)

                # 완료 알림도 커스텀 모달로
                def build_done(parent2, overlay2):
                    ctk.CTkLabel(
                        parent2,
                        text="✅ App has been reset.",
                        font=FONTS["body"],
                        text_color=THEME["muted"],
                        justify="center"
                    ).pack(pady=SPACING["md"])
                    ctk.CTkButton(
                        parent2, text="OK", command=overlay2.destroy, **BTN_SOLID
                    ).pack(pady=SPACING["sm"])

                show_modal("Reset Complete", build_done, show_close=False)

            except Exception as e:
                # 에러도 커스텀 모달로
                def build_error(parent2, overlay2):
                    ctk.CTkLabel(
                        parent2,
                        text=f"❌ Reset failed:\n{e}",
                        font=FONTS["body"],
                        text_color=THEME["muted"],
                        justify="center"
                    ).pack(pady=SPACING["md"])
                    ctk.CTkButton(
                        parent2, text="OK", command=overlay2.destroy, **BTN_SOLID
                    ).pack(pady=SPACING["sm"])

                show_modal("Error", build_error, show_close=False)

        # Reset 버튼
        ctk.CTkButton(
            row, text="Reset", command=do_reset, **BTN_SOLID
        ).pack(side="left", padx=SPACING["sm"])

        # Cancel 버튼
        ctk.CTkButton(
            row, text="Cancel", command=overlay.destroy, **BTN_GHOST
        ).pack(side="left", padx=SPACING["sm"])

    # 커스텀 모달 호출
    show_modal("Confirm Reset", build, show_close=False)

def confirm_reset_app():
    def build(parent, overlay):
        ctk.CTkLabel(
            parent,
            text="Reset the app?\nAll decks and words will be deleted.",
            font=FONTS["body"],
            text_color=THEME["muted"],
            justify="center"
        ).pack(pady=SPACING["md"])

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(pady=SPACING["md"])

        def do_reset():
            try:
                if os.path.exists(VOCAB_FILE):
                    os.remove(VOCAB_FILE)
                global decks, current_deck
                decks = {"Default": {}}
                current_deck = "Default"
                save_decks()
                overlay.destroy()
                build_deck_select()
                show_frame(deck_select_frame)
                modal_info("✅ App reset.")
            except Exception as e:
                modal_error(f"Reset failed:\n{e}")

        ctk.CTkButton(row, text="Reset", command=do_reset, **BTN_SOLID).pack(side="left", padx=SPACING["sm"])
        ctk.CTkButton(row, text="Cancel", command=overlay.destroy, **BTN_GHOST).pack(side="left", padx=SPACING["sm"])

    show_modal("Confirm Reset", build, show_close=False)

# ==============================
# App Boot
# ==============================

def build_all():
    build_deck_select()
    build_main_menu()
    build_add_vocab()
    build_quiz_filter()
    build_word_list()

load_decks()
build_all()
show_frame(deck_select_frame)
center_root_window(root)
root.mainloop()
