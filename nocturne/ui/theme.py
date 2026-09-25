from __future__ import annotations

# --- semantic colour tokens ---
BG_0 = "#16171a"     # deepest (canvas)
BG_1 = "#1e1f22"     # window
BG_2 = "#26282c"     # panels / toolbar
BG_3 = "#2f3237"     # inputs / raised
BORDER = "#3c4046"
# A rule INSIDE a panel, dimmer than BORDER on purpose. BORDER is a structural
# edge — the boundary of a card; a divider within one is a weaker separation and
# should read as weaker. Andreas, 2026-09-13: at BORDER "the eye tends to be
# drawn to it". share_dialog had already hand-rolled #33373d for exactly this,
# which is the evidence the dimmer value is the right one; it now has a name.
RULE = "#31343a"
ACCENT = "#4a90e2"   # blue — interactive accent (sliders, focus, Next/advance)
ACCENT_HI = "#5fa0ee"
SUCCESS = "#3fb950"  # green — commit/apply hero ("done with this edit")
SUCCESS_HI = "#4cc85e"
WARNING = "#e3b341"  # amber
DANGER = "#f85149"   # red
# Reset step's text, warm but well short of DANGER. Reset is not dangerous in
# the way DANGER marks — it removes ONE step's commit and asks first — but it is
# the only control on a panel that takes something away, and jump_back has no
# redo. A tint says "different kind of action"; the full red would say "careful"
# about a recovery affordance people should feel free to use, and an unused
# recovery affordance is worse than a slightly bland one.
DANGER_DIM = "#c47a72"
TEXT = "#e6e6e6"
TEXT_DIM = "#8a9099"
TEXT_FAINT = "#5e636b"


def build_stylesheet() -> str:
    return f"""
* {{ color: {TEXT}; font-size: 14px; }}
QMainWindow, QWidget {{ background-color: {BG_1}; }}
/* Inside a step card everything lets the card colour through. The global rule
   above paints EVERY widget BG_1, which put a darker rectangle behind every
   label on the BG_2 card (his screenshot, 2026-09-25). Buttons, dropdowns,
   inputs and sliders keep their own surfaces — only plain text and containers
   go transparent. */
QWidget#stepCard QLabel, QWidget#stepCard QWidget#panelBody,
QWidget#stepCard QCheckBox, QWidget#stepCard QRadioButton,
QWidget#stepCard QFrame#panelRule {{ background: transparent; }}
QToolBar {{ background: {BG_2}; border: none; spacing: 4px; padding: 6px; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 4px 6px; }}
QToolBar QToolButton {{ padding: 6px 10px; border-radius: 8px; color: {TEXT_DIM}; }}
QToolBar QToolButton:hover {{ background: {BG_3}; color: {TEXT}; }}
QToolBar QToolButton:pressed {{ background: {BORDER}; }}
QToolBar QToolButton:checked {{ background: {BG_3}; color: {ACCENT}; }}
QToolBar QToolButton:disabled {{ color: {TEXT_FAINT}; }}

QLabel#stageTitle {{ font-size: 20px; font-weight: 600; color: #ffffff; padding-bottom: 8px; }}

QListWidget {{ background: {BG_2}; border: none; outline: 0; padding: 8px; }}
QListWidget::item {{ padding: 2px; border-radius: 8px; margin: 1px 0; }}
QListWidget::item:selected {{ background: transparent; }}

QComboBox, QLineEdit {{ background: {BG_3}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 6px 10px; }}
QComboBox:focus, QLineEdit:focus {{ border: 1px solid {ACCENT}; }}

QPushButton {{ background: {BG_3}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 8px 14px; }}
QPushButton:hover {{ background: #3e4248; }}
QPushButton:pressed {{ background: {BG_2}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: #2a2c30; }}
QPushButton#primary {{ background: {SUCCESS}; color: #052611; font-weight: 600; border: none; }}
QPushButton#primary:hover {{ background: {SUCCESS_HI}; }}
/* SUCCESS is documented above as "there is an edit to commit". A step with
   nothing pending has no edit to commit, and a colour that is always on carries
   no information — so the hero green is spent only when it is true. Set ONLY on
   the step-panel apply buttons (see _sync_step_controls); everything else keeps
   the default above. */
QPushButton#primary[pending="false"] {{ background: {BG_3}; color: {TEXT};
                                        border: 1px solid {BORDER}; }}
QPushButton#primary[pending="false"]:hover {{ background: #383b41; }}
QPushButton#primary:pressed {{ background: #37a247; }}
QPushButton#primary:disabled {{ background: #2a2c30; color: {TEXT_FAINT}; }}
QPushButton#nav {{ background: {ACCENT}; color: #041427; font-weight: 600; border: none; }}
QPushButton#nav:hover {{ background: {ACCENT_HI}; }}
QPushButton#nav:pressed {{ background: #3f80cc; }}
QPushButton#nav:disabled {{ background: #2a2c30; color: {TEXT_FAINT}; }}

QGraphicsView {{ background: {BG_0}; border: 1px solid #2c2f34; }}

QSlider::groove:horizontal {{ height: 6px; background: {BG_3}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 3px; }}
QSlider::add-page:horizontal {{ background: {BG_3}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 16px; height: 16px;
    margin: -6px 0; border-radius: 8px; }}
QSlider::handle:horizontal:hover {{ background: {ACCENT_HI}; }}

QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px;
    border: 1px solid {BORDER}; background: {BG_3}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT}; border: 1px solid {ACCENT}; }}

QProgressBar {{ background: {BG_3}; border: none; border-radius: 6px; height: 10px;
    text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 6px; }}

QHeaderView::section {{ background: {BG_3}; color: {TEXT_DIM}; border: none;
    padding: 6px 8px; }}
QTableWidget {{ background: {BG_2}; gridline-color: {BORDER};
    border: 1px solid {BORDER}; border-radius: 8px; }}
QTableWidget::item:hover {{ background: {BG_3}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #4a4f56; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

QWidget#stepCard {{ background: {BG_2}; border-radius: 10px; }}
/* The side panel's ONE step card (Ruling R6): the rounded frame holds the
   fixed header and the scrolling controls, and every plain container inside
   it lets the frame colour through — the inner step card included, so there
   is one visible surface, not a card inside a card. */
QFrame#stepFrame {{ background: {BG_2}; border-radius: 10px; }}
QFrame#stepFrame QWidget#stepHeaderSlot, QFrame#stepFrame QWidget#stepHeader,
QFrame#stepFrame QWidget#stepHeader QLabel, QFrame#stepFrame QScrollArea,
QFrame#stepFrame QScrollArea > QWidget, QFrame#stepFrame QScrollArea > QWidget > QWidget,
QFrame#stepFrame QWidget#stepCard, QFrame#stepFrame QWidget#solvePanel,
QFrame#stepFrame QLabel#stepExplainer, QFrame#stepFrame QLabel#fullHelpLink
{{ background: transparent; }}
/* "How this works" on the title line: the link is drawn in ACCENT with no
   underline by MainWindow's rich text; this sizes it to sit on the title. */
QLabel#helpHeader {{ font-size: 12px; }}
QLabel#stepDesc {{ color: {TEXT_DIM}; font-size: 12px; padding-bottom: 6px; }}
/* The answer to "did that apply?" — so NOT stepDesc's muted help-text grey, which
   is the styling people skim past. Full-strength text, above the button. */
QLabel#pendingNote {{ color: {TEXT}; font-size: 13px; font-weight: 600;
                      padding: 2px 0 6px 0; }}
QLabel#importMeta {{ color: {TEXT}; font-size: 13px; padding-bottom: 6px; }}
QWidget#welcome {{ background: transparent; }}
QLabel#welcomeTitle {{ font-size: 40px; font-weight: 700; color: #ffffff; }}
QLabel#welcomeTag {{ font-size: 15px; color: {TEXT_DIM}; }}
QLabel#welcomeHint {{ font-size: 13px; color: {TEXT_FAINT}; }}
QWidget#zoomPill {{ background: {BG_2}; border: 1px solid {BORDER}; border-radius: 14px; }}
QWidget#zoomPill QPushButton {{ background: transparent; border: none; color: {TEXT};
    font-size: 15px; padding: 0; }}
QWidget#zoomPill QPushButton:hover {{ color: {ACCENT}; }}
QWidget#zoomPill QPushButton:pressed {{ background: transparent; color: {ACCENT_HI}; }}
/* No font-variant-numeric here: Qt Style Sheets implement a SUBSET of CSS and
   reject it with 'Unknown property font-variant-numeric' on every widget the
   sheet is applied to. The label carries a fixed width instead, which is what
   actually stops the pill jittering.

   And these are C-style comments, not '#'. Qt has no '#' comment syntax: it
   parses such a line as a SELECTOR, which silently swallows every rule after it
   until the rule block closes. That is not hypothetical: the '#' version of
   this very comment ate QLabel#zoomLevel, QFrame#panelRule and all three
   QPushButton#resetStep rules for several hours on 2026-09-13, which is why the
   panel divider looked "too bright": it was falling back to Qt's default frame
   colour, not to ours. */
QLabel#zoomLevel {{ color: {TEXT_DIM}; font-size: 12px; }}
QFrame#panelRule {{ color: {RULE}; }}
/* Tinted TEXT and border, never a filled red: this button is disabled most of
   the time (main_window enables it only when the step has something to undo),
   and a filled danger colour would make the quietest control on the panel the
   loudest thing on it — beside an Apply button that is meant to be the hero.
   The disabled state deliberately keeps the ordinary muted grey. */
QPushButton#resetStep {{ color: {DANGER_DIM}; border-color: {DANGER_DIM}; }}
QPushButton#resetStep:hover {{ color: {DANGER}; border-color: {DANGER}; }}
QPushButton#resetStep:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; }}
/* The visual stretch picker: the PICTURE is the button, so it must not look
   like one. Flat and transparent at rest, with the accent appearing on hover
   and focus — the only cue that the six previews are clickable, since the
   "Use this one" buttons that used to say so were removed on 2026-09-14. */
QPushButton#pickPanel {{ background: transparent; border: 2px solid transparent;
    border-radius: 6px; padding: 0; }}
QPushButton#pickPanel:hover {{ border-color: {ACCENT}; }}
QPushButton#pickPanel:focus {{ border-color: {ACCENT_HI}; }}
/* A consequence, not a scolding: an unlinked stretch annihilates a photometric
   calibration (measured 0.0004 of a level), so the panel that would discard it
   says so. Amber, not red — it is a real cost, not a mistake. */
QLabel#pickCaveat {{ color: {WARNING}; font-size: 11px; }}
QLabel#panelSectionLabel {{ color: {TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QFrame#objectListPanel {{ background: rgba(16, 22, 33, 0.94); border: 1px solid {BORDER};
    border-radius: 10px; }}
QLabel#objectListTitle {{ color: {TEXT}; font-size: 12px; font-weight: 600; }}
QPushButton#objectListClose {{ color: {TEXT_DIM}; border: none; background: transparent;
    font-size: 13px; }}
QPushButton#objectListClose:hover {{ color: {TEXT}; }}
QListWidget#objectList {{ background: transparent; color: {TEXT}; font-size: 12px;
    border: none; outline: none; }}
QListWidget#objectList::item {{ padding: 4px 10px; border-radius: 4px; }}
QListWidget#objectList::item:hover {{ background: {BG_2}; }}
QListWidget#objectList::item:selected {{ background: {BORDER}; color: {TEXT}; }}
QLabel#readoutPill {{ background: {BG_2}; border: 1px solid {BORDER}; border-radius: 12px;
    color: {TEXT}; font-size: 12px; padding: 4px 10px; }}
QPushButton#solveHeader {{ background: transparent; border: none; text-align: left;
    font-weight: 600; padding: 6px 2px; }}
QPushButton#solveHeader:hover {{ color: {ACCENT}; background: transparent; }}
QPushButton#solveHeader:pressed {{ background: transparent; }}
QLabel#solveResultCard {{ color: {TEXT_DIM}; font-size: 12px; padding: 4px 0 8px 0; }}
QLabel#aboutWordmark {{ font-size: 34px; font-weight: 700; color: #ffffff; padding: 10px; }}
QLabel#aboutBody {{ font-size: 13px; color: {TEXT}; padding: 4px 12px; }}
QScrollArea {{ border: none; background: {BG_1}; }}
"""


def apply_dark_theme(app) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet())
