"""
Clawdio Avatar GUI - Modern animated avatar window.

Displays a sleek, modern animated visualization showing the current activity state
of the Clawdio assistant.
"""

import math
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Modern color scheme - Clean and minimal
COLORS = {
    "bg_primary": "#1a1a2e",
    "bg_secondary": "#16213e",
    "bg_card": "#1f2940",
    "bg_elevated": "#253352",
    "accent_primary": "#4facfe",
    "accent_secondary": "#00f2fe",
    "accent_gradient_1": "#667eea",
    "accent_gradient_2": "#764ba2",
    "success": "#00d9a5",
    "warning": "#ffc107",
    "error": "#ff6b6b",
    "text_primary": "#ffffff",
    "text_secondary": "#a0aec0",
    "text_muted": "#5a6a8a",
    "border": "#2d3a5a",
    "glow_blue": "#4facfe",
    "glow_purple": "#a855f7",
    "glow_green": "#10b981",
    "glow_orange": "#f97316",
    "glow_red": "#ef4444",
}

# Avatar states with modern styling
STATES = {
    "idle": {
        "color": COLORS["accent_primary"],
        "glow": COLORS["glow_blue"],
        "animation": "breathe",
        "label": "Ready",
        "icon": "○",
    },
    "thinking": {
        "color": COLORS["glow_purple"],
        "glow": COLORS["glow_purple"],
        "animation": "pulse",
        "label": "Thinking",
        "icon": "◐",
    },
    "reading": {
        "color": COLORS["glow_green"],
        "glow": COLORS["glow_green"],
        "animation": "scan",
        "label": "Reading",
        "icon": "◈",
    },
    "writing": {
        "color": COLORS["glow_orange"],
        "glow": COLORS["glow_orange"],
        "animation": "write",
        "label": "Writing",
        "icon": "◇",
    },
    "executing": {
        "color": COLORS["glow_red"],
        "glow": COLORS["glow_red"],
        "animation": "execute",
        "label": "Executing",
        "icon": "▶",
    },
    "searching": {
        "color": COLORS["accent_secondary"],
        "glow": COLORS["accent_secondary"],
        "animation": "radar",
        "label": "Searching",
        "icon": "◎",
    },
    "web": {
        "color": COLORS["glow_blue"],
        "glow": COLORS["glow_purple"],
        "animation": "orbit",
        "label": "Web Activity",
        "icon": "◉",
    },
    "mcp": {
        "color": COLORS["glow_green"],
        "glow": COLORS["glow_blue"],
        "animation": "connect",
        "label": "MCP Tool",
        "icon": "⬡",
    },
    "working": {
        "color": COLORS["accent_primary"],
        "glow": COLORS["accent_secondary"],
        "animation": "work",
        "label": "Working",
        "icon": "◆",
    },
    "speaking": {
        "color": COLORS["glow_green"],
        "glow": COLORS["glow_green"],
        "animation": "speak",
        "label": "Responding",
        "icon": "●",
    },
    "processing": {
        "color": COLORS["glow_orange"],
        "glow": COLORS["glow_orange"],
        "animation": "process",
        "label": "Processing",
        "icon": "◑",
    },
}

# Map tool names to states
TOOL_TO_STATE = {
    "Bash": "executing",
    "Read": "reading",
    "Write": "writing",
    "Edit": "writing",
    "Glob": "searching",
    "Grep": "searching",
    "WebSearch": "web",
    "WebFetch": "web",
    "Task": "thinking",
}


class AvatarWindow:
    """Modern avatar GUI window that displays Clawdio's activity state."""

    def __init__(self):
        self.root: Optional[tk.Tk] = None
        self.canvas: Optional[tk.Canvas] = None
        self.activity_listbox: Optional[tk.Listbox] = None
        self.status_label: Optional[tk.Label] = None
        self.tool_label: Optional[tk.Label] = None
        self.model_label: Optional[tk.Label] = None
        self.state_indicator: Optional[tk.Label] = None

        # Thread-safe communication
        self._command_queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running = False

        # Animation state
        self._current_state = "idle"
        self._current_details = ""
        self._current_model = "Claude"
        self._animation_frame = 0
        self._blink_timer = 0
        self._next_blink = 90  # Frames until next blink
        self._activities: list[str] = []

    def start(self):
        """Start the GUI in a separate thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_gui, daemon=True)
        self._thread.start()
        logger.info("Avatar GUI started")

    def stop(self):
        """Stop the GUI and clean up."""
        self._running = False
        if self.root:
            try:
                self.root.quit()
            except:
                pass
        logger.info("Avatar GUI stopped")

    def set_state(self, state: str, details: str = ""):
        """Thread-safe state update."""
        if state not in STATES:
            state = "working"
        self._command_queue.put(("set_state", state, details))

    def add_activity(self, activity: str):
        """Add an entry to the activity log."""
        self._command_queue.put(("add_activity", activity, ""))

    def set_model(self, model: str):
        """Set the active model (Claude or Ollama)."""
        self._command_queue.put(("set_model", model, ""))

    def _run_gui(self):
        """Main GUI thread function."""
        try:
            self.root = tk.Tk()
            self.root.title("Clawdio")
            self.root.configure(bg=COLORS["bg_primary"])
            self.root.geometry("500x700")
            self.root.resizable(True, True)
            self.root.minsize(400, 500)

            # Try to remove title bar decorations for modern look (optional)
            try:
                self.root.attributes("-alpha", 0.98)
            except:
                pass

            self._create_widgets()
            self._start_animation_loop()
            self._process_commands()

            self.root.protocol("WM_DELETE_WINDOW", self._on_close)
            self.root.mainloop()

        except Exception as e:
            logger.error(f"Avatar GUI error: {e}")
            self._running = False

    def _on_close(self):
        """Handle window close button."""
        self._running = False
        if self.root:
            self.root.destroy()

    def _create_widgets(self):
        """Create the GUI widgets."""
        # Main container with padding
        main_frame = tk.Frame(self.root, bg=COLORS["bg_primary"])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=24, pady=24)

        # Header section
        header_frame = tk.Frame(main_frame, bg=COLORS["bg_primary"])
        header_frame.pack(fill=tk.X, pady=(0, 20))

        # Logo/Title
        title_font = tkfont.Font(family="Segoe UI", size=28, weight="bold")
        title_label = tk.Label(
            header_frame,
            text="Clawdio",
            font=title_font,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_primary"],
        )
        title_label.pack(side=tk.LEFT)

        # State indicator badge
        self.state_indicator = tk.Label(
            header_frame,
            text="● Ready",
            font=tkfont.Font(family="Segoe UI", size=11),
            fg=COLORS["accent_primary"],
            bg=COLORS["bg_primary"],
        )
        self.state_indicator.pack(side=tk.RIGHT, pady=8)

        # Avatar visualization card
        avatar_card = tk.Frame(
            main_frame,
            bg=COLORS["bg_card"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
        )
        avatar_card.pack(fill=tk.X, pady=(0, 20))

        # Canvas for avatar animation
        self.canvas = tk.Canvas(
            avatar_card,
            width=452,
            height=280,
            bg=COLORS["bg_card"],
            highlightthickness=0,
        )
        self.canvas.pack(padx=0, pady=0)

        # Status section
        status_card = tk.Frame(
            main_frame,
            bg=COLORS["bg_card"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
        )
        status_card.pack(fill=tk.X, pady=(0, 20))

        status_inner = tk.Frame(status_card, bg=COLORS["bg_card"])
        status_inner.pack(fill=tk.X, padx=20, pady=16)

        # Status row
        status_row = tk.Frame(status_inner, bg=COLORS["bg_card"])
        status_row.pack(fill=tk.X, pady=(0, 8))

        status_label_title = tk.Label(
            status_row,
            text="Status",
            font=tkfont.Font(family="Segoe UI", size=10),
            fg=COLORS["text_muted"],
            bg=COLORS["bg_card"],
        )
        status_label_title.pack(side=tk.LEFT)

        self.status_label = tk.Label(
            status_row,
            text="Ready",
            font=tkfont.Font(family="Segoe UI", size=10, weight="bold"),
            fg=COLORS["accent_primary"],
            bg=COLORS["bg_card"],
        )
        self.status_label.pack(side=tk.RIGHT)

        # Model row
        model_row = tk.Frame(status_inner, bg=COLORS["bg_card"])
        model_row.pack(fill=tk.X, pady=(0, 8))

        model_label_title = tk.Label(
            model_row,
            text="Model",
            font=tkfont.Font(family="Segoe UI", size=10),
            fg=COLORS["text_muted"],
            bg=COLORS["bg_card"],
        )
        model_label_title.pack(side=tk.LEFT)

        self.model_label = tk.Label(
            model_row,
            text="Claude",
            font=tkfont.Font(family="Segoe UI", size=10, weight="bold"),
            fg=COLORS["glow_purple"],
            bg=COLORS["bg_card"],
        )
        self.model_label.pack(side=tk.RIGHT)

        # Tool row
        tool_row = tk.Frame(status_inner, bg=COLORS["bg_card"])
        tool_row.pack(fill=tk.X)

        tool_label_title = tk.Label(
            tool_row,
            text="Current Tool",
            font=tkfont.Font(family="Segoe UI", size=10),
            fg=COLORS["text_muted"],
            bg=COLORS["bg_card"],
        )
        tool_label_title.pack(side=tk.LEFT)

        self.tool_label = tk.Label(
            tool_row,
            text="—",
            font=tkfont.Font(family="Segoe UI", size=10),
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_card"],
        )
        self.tool_label.pack(side=tk.RIGHT)

        # Activity log section
        log_card = tk.Frame(
            main_frame,
            bg=COLORS["bg_card"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
        )
        log_card.pack(fill=tk.BOTH, expand=True)

        log_header = tk.Frame(log_card, bg=COLORS["bg_card"])
        log_header.pack(fill=tk.X, padx=20, pady=(16, 8))

        log_title = tk.Label(
            log_header,
            text="Activity Log",
            font=tkfont.Font(family="Segoe UI", size=12, weight="bold"),
            fg=COLORS["text_primary"],
            bg=COLORS["bg_card"],
        )
        log_title.pack(side=tk.LEFT)

        # Activity listbox with scrollbar
        list_frame = tk.Frame(log_card, bg=COLORS["bg_secondary"])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 16))

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        list_font = tkfont.Font(family="Consolas", size=10)
        self.activity_listbox = tk.Listbox(
            list_frame,
            font=list_font,
            fg=COLORS["text_secondary"],
            bg=COLORS["bg_secondary"],
            selectbackground=COLORS["accent_primary"],
            selectforeground=COLORS["text_primary"],
            highlightthickness=0,
            borderwidth=0,
            activestyle="none",
            yscrollcommand=scrollbar.set,
        )
        self.activity_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.activity_listbox.yview)

    def _draw_pixel(self, x: int, y: int, size: int, color: str):
        """Draw a single pixel (rectangle) at grid position."""
        self.canvas.create_rectangle(
            x, y, x + size, y + size,
            fill=color,
            outline="",
        )

    def _draw_avatar(self):
        """Draw retro pixel-art smiley face with solid background."""
        if not self.canvas:
            return

        self.canvas.delete("all")

        width = self.canvas.winfo_width() or 452
        height = self.canvas.winfo_height() or 280
        cx, cy = width // 2, height // 2

        state_info = STATES.get(self._current_state, STATES["idle"])
        color = state_info["color"]
        glow = state_info["glow"]
        anim_type = state_info["animation"]

        # Pixel size for retro look
        px = 10

        # Animation timing
        t = self._animation_frame

        # Natural blinking with variable timing
        self._blink_timer += 1
        if self._blink_timer >= self._next_blink:
            self._blink_timer = 0
            # Random-ish next blink (60-150 frames = 2-5 seconds)
            self._next_blink = 60 + (t * 7) % 90

        # Blink for 6 frames
        is_blinking = self._blink_timer < 6

        # Face size
        face_radius = 90

        # Draw solid circular face background
        self.canvas.create_oval(
            cx - face_radius, cy - face_radius,
            cx + face_radius, cy + face_radius,
            fill=color,
            outline="",
        )

        # Eye and mouth color (dark)
        feature_color = COLORS["bg_primary"]

        # Eye movement based on state
        eye_offset_x = 0
        eye_offset_y = 0

        if anim_type == "scan":  # Reading - eyes move left/right
            eye_offset_x = int(math.sin(t * 0.15) * 3) * px
        elif anim_type == "pulse":  # Thinking - eyes look up
            eye_offset_y = -2 * px
        elif anim_type == "execute":  # Executing - eyes dart around
            eye_offset_x = int(math.sin(t * 0.3) * 2) * px
            eye_offset_y = int(math.cos(t * 0.25) * 1) * px
        elif anim_type == "radar":  # Searching - circular motion
            eye_offset_x = int(math.cos(t * 0.12) * 2) * px
            eye_offset_y = int(math.sin(t * 0.12) * 1) * px
        elif anim_type == "orbit":  # Web - slow drift
            eye_offset_x = int(math.sin(t * 0.08) * 1) * px
        elif anim_type == "work":  # Working - subtle movement
            eye_offset_x = int(math.sin(t * 0.1) * 1) * px

        # Base eye positions
        left_eye_cx = cx - 30
        right_eye_cx = cx + 30
        eye_cy = cy - 15

        # Draw eyes
        if is_blinking:
            # Closed eyes (horizontal lines)
            for i in range(-1, 2):
                self._draw_pixel(left_eye_cx + eye_offset_x + i * px, eye_cy + eye_offset_y, px, feature_color)
                self._draw_pixel(right_eye_cx + eye_offset_x + i * px, eye_cy + eye_offset_y, px, feature_color)
        elif anim_type == "write":
            # Focused/squinting eyes (horizontal slits)
            for i in range(-1, 2):
                self._draw_pixel(left_eye_cx + eye_offset_x + i * px, eye_cy + eye_offset_y, px, feature_color)
                self._draw_pixel(right_eye_cx + eye_offset_x + i * px, eye_cy + eye_offset_y, px, feature_color)
        elif anim_type == "execute":
            # Wide alert eyes (3x3)
            for i in range(-1, 2):
                for j in range(-1, 2):
                    self._draw_pixel(left_eye_cx + eye_offset_x + i * px, eye_cy + eye_offset_y + j * px, px, feature_color)
                    self._draw_pixel(right_eye_cx + eye_offset_x + i * px, eye_cy + eye_offset_y + j * px, px, feature_color)
        else:
            # Normal open eyes (2x2 pixels each)
            for i in range(2):
                for j in range(2):
                    self._draw_pixel(left_eye_cx + eye_offset_x + (i - 1) * px, eye_cy + eye_offset_y + (j - 1) * px, px, feature_color)
                    self._draw_pixel(right_eye_cx + eye_offset_x + (i - 1) * px, eye_cy + eye_offset_y + (j - 1) * px, px, feature_color)

        # Mouth position
        mouth_cy = cy + 30

        # Draw mouth based on state
        if anim_type == "speak":
            # Animated speaking mouth (opens and closes)
            mouth_phase = (t // 6) % 3
            if mouth_phase == 0:
                # Open wide (O shape)
                for i in range(-2, 3):
                    self._draw_pixel(cx + i * px, mouth_cy - 2 * px, px, feature_color)
                    self._draw_pixel(cx + i * px, mouth_cy + 2 * px, px, feature_color)
                for j in range(-1, 2):
                    self._draw_pixel(cx - 3 * px, mouth_cy + j * px, px, feature_color)
                    self._draw_pixel(cx + 3 * px, mouth_cy + j * px, px, feature_color)
            elif mouth_phase == 1:
                # Medium open
                for i in range(-2, 3):
                    self._draw_pixel(cx + i * px, mouth_cy - px, px, feature_color)
                    self._draw_pixel(cx + i * px, mouth_cy + px, px, feature_color)
            else:
                # Nearly closed
                for i in range(-2, 3):
                    self._draw_pixel(cx + i * px, mouth_cy, px, feature_color)

        elif anim_type in ["execute", "process"]:
            # Worried/tense mouth (wavy line)
            wave_offset = (t // 8) % 2
            for i in range(-3, 4):
                y_off = px if (i + wave_offset) % 2 == 0 else 0
                self._draw_pixel(cx + i * px, mouth_cy + y_off, px, feature_color)

        elif anim_type == "pulse":
            # Thinking mouth (small o)
            for i in range(-1, 2):
                self._draw_pixel(cx + i * px, mouth_cy - px, px, feature_color)
                self._draw_pixel(cx + i * px, mouth_cy + px, px, feature_color)
            self._draw_pixel(cx - 2 * px, mouth_cy, px, feature_color)
            self._draw_pixel(cx + 2 * px, mouth_cy, px, feature_color)

        else:
            # Happy smile (curved)
            # Top of smile curve
            self._draw_pixel(cx - 4 * px, mouth_cy - 2 * px, px, feature_color)
            self._draw_pixel(cx + 4 * px, mouth_cy - 2 * px, px, feature_color)
            # Middle parts
            self._draw_pixel(cx - 4 * px, mouth_cy - px, px, feature_color)
            self._draw_pixel(cx + 4 * px, mouth_cy - px, px, feature_color)
            self._draw_pixel(cx - 3 * px, mouth_cy, px, feature_color)
            self._draw_pixel(cx + 3 * px, mouth_cy, px, feature_color)
            # Bottom curve
            for i in range(-2, 3):
                self._draw_pixel(cx + i * px, mouth_cy + px, px, feature_color)

    def _start_animation_loop(self):
        """Start the animation update loop."""
        if not self._running or not self.root:
            return

        self._animation_frame += 1
        self._draw_avatar()

        # Schedule next frame (~30 FPS)
        self.root.after(33, self._start_animation_loop)

    def _process_commands(self):
        """Process commands from the queue."""
        if not self._running or not self.root:
            return

        try:
            while True:
                cmd, arg1, arg2 = self._command_queue.get_nowait()

                if cmd == "set_state":
                    self._current_state = arg1
                    self._current_details = arg2
                    state_info = STATES.get(arg1, STATES["idle"])

                    # Update status label
                    self.status_label.configure(
                        text=state_info["label"],
                        fg=state_info["color"],
                    )

                    # Update state indicator
                    self.state_indicator.configure(
                        text=f"{state_info['icon']} {state_info['label']}",
                        fg=state_info["color"],
                    )

                    # Update tool label if details provided
                    if arg2:
                        # Truncate long tool descriptions
                        display_text = arg2 if len(arg2) <= 40 else arg2[:37] + "..."
                        self.tool_label.configure(
                            text=display_text,
                            fg=state_info["color"],
                        )
                    else:
                        self.tool_label.configure(
                            text="—",
                            fg=COLORS["text_muted"],
                        )

                elif cmd == "add_activity":
                    self._activities.append(arg1)
                    # Keep only last 100 activities
                    if len(self._activities) > 100:
                        self._activities = self._activities[-100:]

                    # Update listbox
                    self.activity_listbox.insert(tk.END, arg1)
                    self.activity_listbox.see(tk.END)

                    # Color the latest entry based on type
                    if arg1.startswith(">"):
                        self.activity_listbox.itemconfig(tk.END, fg=COLORS["accent_primary"])
                    elif "Complete" in arg1:
                        self.activity_listbox.itemconfig(tk.END, fg=COLORS["success"])
                    elif "Error" in arg1:
                        self.activity_listbox.itemconfig(tk.END, fg=COLORS["error"])

                elif cmd == "set_model":
                    self._current_model = arg1
                    # Set color based on model
                    if "ollama" in arg1.lower():
                        model_color = COLORS["glow_green"]
                    else:
                        model_color = COLORS["glow_purple"]
                    self.model_label.configure(text=arg1, fg=model_color)

        except queue.Empty:
            pass

        # Schedule next check
        self.root.after(50, self._process_commands)


def get_state_for_tool(tool_name: str) -> str:
    """Get the avatar state for a given tool name."""
    # Check for MCP tools (contain :: or start with mcp)
    if "::" in tool_name or tool_name.lower().startswith("mcp"):
        return "mcp"

    # Check known tools
    for known_tool, state in TOOL_TO_STATE.items():
        if known_tool.lower() in tool_name.lower():
            return state

    return "working"
