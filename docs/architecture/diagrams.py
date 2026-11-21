"""Draws the six architecture diagrams of Dream-1 Lab as PNG files (needs only Pillow).

Run from the repository root:  python docs/architecture/diagrams.py docs/architecture/png
Then build the Word file:     python docs/architecture/make_docx.py docs/architecture/png docs/architecture/Dream-1-Lab-architecture.docx

Solid lines and filled boxes: built. Dashed lines and white boxes: planned.
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "png")
W, H = 2400, 1350

PERSON = ("#08427B", "#FFFFFF")
SYSTEM = ("#1168BD", "#FFFFFF")
CONTAINER = ("#438DD5", "#FFFFFF")
COMPONENT = ("#85BBF0", "#0B2545")
EXTERNAL = ("#8A8A8A", "#FFFFFF")
LINE = "#4A4A4A"
TEXT = "#1B1B1B"

# Segoe UI on Windows (also seen from WSL); DejaVu Sans on plain Linux.
FONT_FILES = {
    "r": ["/mnt/c/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeui.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "b": ["/mnt/c/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeuib.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "i": ["/mnt/c/Windows/Fonts/segoeuii.ttf", "C:/Windows/Fonts/segoeuii.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"],
}


def font(size, style="r"):
    for path in FONT_FILES[style]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


F_TITLE, F_KIND, F_BODY, F_LABEL, F_HEAD = font(32, "b"), font(25, "i"), font(27), font(25), font(40, "b")


class Diagram:
    def __init__(self, title, w=W, h=H):
        self.img = Image.new("RGB", (w, h), "white")
        self.d = ImageDraw.Draw(self.img)
        self.d.text((40, 24), title, font=F_HEAD, fill=TEXT)

    # ---------- text ----------
    def wrap(self, text, fnt, width):
        lines = []
        for part in text.split("\n"):
            words, line = part.split(), ""
            for word in words:
                trial = f"{line} {word}".strip()
                if self.d.textlength(trial, font=fnt) <= width or not line:
                    line = trial
                else:
                    lines.append(line)
                    line = word
            lines.append(line)
        return lines

    def block(self, x, y, w, items, color, align="center", gap=4):
        """items: list of (text, font). Returns the height used."""
        cy = y
        for text, fnt in items:
            if not text:
                cy += 10
                continue
            for line in self.wrap(text, fnt, w):
                tw = self.d.textlength(line, font=fnt)
                tx = x + (w - tw) / 2 if align == "center" else x
                self.d.text((tx, cy), line, font=fnt, fill=color)
                cy += fnt.size + gap + 4
        return cy - y

    def measure(self, w, items, gap=4):
        return sum(10 if not text else len(self.wrap(text, fnt, w)) * (fnt.size + gap + 4) for text, fnt in items)

    # ---------- shapes ----------
    def dashed_line(self, a, b, color, width=3, dash=16, gapl=10):
        (x1, y1), (x2, y2) = a, b
        length = math.hypot(x2 - x1, y2 - y1)
        if length == 0:
            return
        dx, dy = (x2 - x1) / length, (y2 - y1) / length
        pos = 0
        while pos < length:
            end = min(pos + dash, length)
            self.d.line([(x1 + dx * pos, y1 + dy * pos), (x1 + dx * end, y1 + dy * end)], fill=color, width=width)
            pos += dash + gapl

    def rect(self, x, y, w, h, fill, edge, dashed=False, width=3, radius=16):
        if dashed:
            if fill:
                self.d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill)
            pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
            for a, b in zip(pts, pts[1:]):
                self.dashed_line(a, b, edge, width)
        else:
            self.d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=fill, outline=edge, width=width)

    def box(self, x, y, w, h, title, kind=None, body=None, style=CONTAINER, planned=False):
        fill, color = style
        if planned:
            self.rect(x, y, w, h, "#FFFFFF", fill, dashed=True, width=4)
            color = TEXT
        else:
            self.rect(x, y, w, h, fill, fill)
        items = [(title, F_TITLE)]
        if kind:
            items.append((f"[{kind}]", F_KIND))
        if body:
            items += [("", None), (body, F_BODY)]
        inner = w - 36
        used = self.measure(inner, items)
        self.block(x + 18, y + max(14, (h - used) / 2), inner, items, color)

    def person(self, x, y, w, h, title, body, planned=False):
        fill = PERSON[0]
        r = 34
        cx = x + w / 2
        if planned:
            self.d.ellipse([cx - r, y, cx + r, y + 2 * r], outline=fill, width=4, fill="white")
        else:
            self.d.ellipse([cx - r, y, cx + r, y + 2 * r], fill=fill)
        self.box(x, y + 2 * r - 6, w, h - 2 * r + 6, title, "Person" + (", planned" if planned else ""), body,
                 style=PERSON, planned=planned)

    def cylinder(self, x, y, w, h, title, kind, body, style=CONTAINER):
        fill, color = style
        e = 34
        self.d.rectangle([x, y + e / 2, x + w, y + h - e / 2], fill=fill)
        self.d.ellipse([x, y + h - e, x + w, y + h], fill=fill)
        self.d.ellipse([x, y, x + w, y + e], fill=fill, outline="white", width=3)
        items = [(title, F_TITLE), (f"[{kind}]", F_KIND)] + ([("", None), (body, F_BODY)] if body else [])
        used = self.measure(w - 36, items)
        self.block(x + 18, y + e + max(4, (h - e - used) / 2), w - 36, items, color)

    def boundary(self, x, y, w, h, label, color="#5A5A5A"):
        self.rect(x, y, w, h, None, color, dashed=True, width=3, radius=4)
        self.d.text((x + 18, y + h - 46), label, font=font(27, "b"), fill=color)

    def node(self, x, y, w, h, label, depth=18, fill="#F3F6FA", dashed=False):
        """A UML deployment node: a box with a 3D top and side."""
        edge = "#2E4057"
        top = [(x, y), (x + depth, y - depth), (x + w + depth, y - depth), (x + w, y)]
        side = [(x + w, y), (x + w + depth, y - depth), (x + w + depth, y + h - depth), (x + w, y + h)]
        if dashed:
            for poly in (top, side):
                for a, b in zip(poly, poly[1:] + poly[:1]):
                    self.dashed_line(a, b, edge, 3)
            self.rect(x, y, w, h, "#FFFFFF", edge, dashed=True, radius=2)
        else:
            self.d.polygon(top, fill="#DCE3EC", outline=edge)
            self.d.polygon(side, fill="#C9D3DF", outline=edge)
            self.d.rectangle([x, y, x + w, y + h], fill=fill, outline=edge, width=3)
        self.block(x + 16, y + 12, w - 32, [(label, font(28, "b"))], TEXT, align="left")

    def artifact(self, x, y, w, h, title, body, planned=False):
        self.rect(x, y, w, h, "#FFFFFF", "#2E4057", dashed=planned, width=3, radius=6)
        self.block(x + 16, y + 12, w - 32, [(title, font(27, "b")), (body, F_BODY)], TEXT, align="left")

    # ---------- arrows ----------
    def arrow(self, pts, label=None, at=None, planned=False, both=False, lw=380):
        for a, b in zip(pts, pts[1:]):
            if planned:
                self.dashed_line(a, b, LINE, 3)
            else:
                self.d.line([a, b], fill=LINE, width=3)
        self.head(pts[-2], pts[-1])
        if both:
            self.head(pts[1], pts[0])
        if label:
            if at is None:
                (x1, y1), (x2, y2) = pts[len(pts) // 2 - 1], pts[len(pts) // 2]
                at = ((x1 + x2) / 2, (y1 + y2) / 2)
            self.label(at, label, lw)

    def head(self, a, b):
        (x1, y1), (x2, y2) = a, b
        ang = math.atan2(y2 - y1, x2 - x1)
        size = 20
        p1 = (x2 - size * math.cos(ang - 0.45), y2 - size * math.sin(ang - 0.45))
        p2 = (x2 - size * math.cos(ang + 0.45), y2 - size * math.sin(ang + 0.45))
        self.d.polygon([(x2, y2), p1, p2], fill=LINE)

    def label(self, at, text, width=380):
        lines = self.wrap(text, F_LABEL, width)
        lh = F_LABEL.size + 6
        tw = max(self.d.textlength(line, font=F_LABEL) for line in lines)
        x, y = at[0] - tw / 2, at[1] - lh * len(lines) / 2
        self.d.rectangle([x - 8, y - 4, x + tw + 8, y + lh * len(lines) + 4], fill="white")
        for i, line in enumerate(lines):
            lx = at[0] - self.d.textlength(line, font=F_LABEL) / 2
            self.d.text((lx, y + i * lh), line, font=F_LABEL, fill="#333333")

    def legend(self, x, y):
        self.d.line([(x, y + 16), (x + 56, y + 16)], fill=LINE, width=3)
        self.head((x, y + 16), (x + 56, y + 16))
        self.d.text((x + 72, y + 1), "built: works today", font=F_LABEL, fill=TEXT)
        x2 = x + 380
        self.dashed_line((x2, y + 16), (x2 + 56, y + 16), LINE, 3)
        self.head((x2, y + 16), (x2 + 56, y + 16))
        self.d.text((x2 + 72, y + 1), "planned: not built yet", font=F_LABEL, fill=TEXT)

    def save(self, name):
        path = OUT / name
        self.img.save(path, dpi=(240, 240))
        print("wrote", path)


# =====================================================================================================
# 1. Deployment diagram
# =====================================================================================================
def deployment():
    g = Diagram("Deployment: where each part runs")
    g.legend(1640, 36)
    g.node(40, 120, 1560, 1080, "«device» Host laptop: a teammate's laptop, Windows 11")
    g.node(80, 200, 1090, 970, "«execution environment» WSL 2: Ubuntu 24.04 Linux", fill="#FFFFFF")
    g.artifact(110, 290, 640, 380, "«process» Dashboard: python start.py",
               "Python 3.12 in ~/Hacklab/.venv\nWeb server (FastAPI), port 8000\nSim worker: MuJoCo, 3 cameras, "
               "Dream-1 runs\nRecorder, credits, players, brain notes\nExtensions: Control, Scene, Robustness")
    g.artifact(790, 290, 350, 170, "«program» cloudflared", "~/Hacklab/bin/\nstarted from Players\n"
               "forwards to port 8000")
    g.artifact(110, 720, 500, 200, "«source» dreamlabs clone", "~/Hacklab/dreamlabs\nYAM simulator, dream client")
    g.artifact(640, 720, 500, 200, "«source» dream-tool", "~/Hacklab/dream-tool: the code\nbrain/raw: notes "
               "the dashboard writes\nbrain/wiki: pages the AI agent writes")
    g.artifact(110, 950, 500, 190, "«files» dream-tool/out/",
               "lab.db: SQLite database\nepisodes/, exports/: LeRobot folders\nextensions/: test reports")
    g.artifact(640, 950, 500, 190, "«file» API key", "~/.dreamlabs/credentials\nonly on this laptop, never in git")
    g.artifact(1210, 480, 360, 150, "«program» Web browser", "Opens http://localhost:8000")
    g.artifact(1210, 700, 360, 160, "«program» AI agent", "Claude Code or Codex: 'ingest' in brain/")

    g.node(1700, 110, 650, 150, "«device» Guest laptop")
    g.artifact(1730, 160, 590, 85, "«program» Web browser", "Controls the one arm the guest took")
    g.node(1700, 350, 650, 130, "«cloud» Cloudflare")
    g.block(1716, 400, 610, [("Quick tunnel: https://<words>.trycloudflare.com; no account, a new address each "
                              "time", F_BODY)], TEXT, align="left")
    g.node(1700, 580, 650, 330, "«cloud» Dream Labs")
    g.artifact(1730, 650, 590, 110, "API gateway: api.dreamlabs.ai", "Dream-1 model: get_action")
    g.artifact(1730, 775, 590, 110, "Data service and fine-tuning", "Datasets and training jobs", planned=True)
    g.node(1700, 1000, 650, 170, "«cloud» GitHub")
    g.block(1716, 1060, 610, [("Repository DreamLabs_Hacklab: the code and brain/", F_BODY)], TEXT, align="left")

    g.arrow([(790, 375), (750, 375)])  # cloudflared -> dashboard
    g.arrow([(1140, 400), (1700, 400)], "tunnel, opened from inside the host", at=(1420, 400), both=True, lw=300)
    g.arrow([(2025, 260), (2025, 332)], "HTTPS + access code", at=(2215, 296), lw=260)
    g.arrow([(1210, 555), (750, 555)], "HTTP, WebSocket, video", at=(980, 555), both=True, lw=360)
    g.arrow([(750, 640), (1680, 640), (1680, 705), (1730, 705)],
            "HTTPS: camera frames + arm state; back: arm moves", at=(965, 640), lw=380)
    g.arrow([(700, 670), (700, 720)])  # dashboard -> brain/raw
    g.arrow([(1210, 780), (1140, 780)])  # AI agent -> brain/
    g.arrow([(1140, 890), (1660, 890), (1660, 1085), (1700, 1085)], "git: pull and push (code and brain/)",
            at=(1400, 890), both=True, lw=480)
    g.arrow([(360, 1140), (360, 1300), (2385, 1300), (2385, 830), (2320, 830)], planned=True)
    g.label((1200, 1300), "upload of exported episodes (planned)", 600)
    g.save("1-deployment.png")


# =====================================================================================================
# 2. C4 level 1: system context
# =====================================================================================================
def context():
    g = Diagram("C4 level 1, system context: who and what uses Dream-1 Lab")
    g.person(120, 110, 560, 340, "Operator", "A team member at the host laptop. Gives Dream-1 tasks, takes over, "
             "saves episodes.")
    g.person(1720, 110, 560, 340, "Remote operator or judge", "Uses another laptop and a public link. Controls "
             "one arm.")
    g.box(820, 520, 760, 330, "Dream-1 Lab", "Software system",
          "Runs the YAM robot simulation. Lets Dream-1 try tasks, lets people take over, records episodes, counts "
          "credits.", style=SYSTEM)
    g.box(120, 560, 560, 250, "AI agent", "External system", "Claude Code or Codex. Keeps the wiki of the second "
          "brain up to date.", style=EXTERNAL)
    g.box(1720, 560, 560, 250, "Cloudflare", "External system", "A public link to the host laptop. No account "
          "needed.", style=EXTERNAL)
    g.box(1720, 960, 560, 270, "Dream Labs platform", "External system",
          "Dream-1 model: robot moves from pictures and arm positions. Datasets and fine-tuning (planned).",
          style=EXTERNAL)
    g.box(120, 960, 560, 270, "GitHub", "External system",
          "Team repository: the code and the second brain folder brain/.", style=EXTERNAL)

    g.arrow([(680, 300), (1100, 300), (1100, 520)], "gives tasks, takes over, in a web browser", at=(1100, 420),
            lw=320)
    g.arrow([(2000, 450), (2000, 560)], "opens the link, types the access code", at=(2000, 505), lw=420)
    g.arrow([(1720, 685), (1580, 685)], "forwards", at=(1650, 640), lw=200)
    g.arrow([(1200, 850), (1200, 1095), (1720, 1095)], "asks for arm moves (HTTPS); uploads episodes (planned)",
            at=(1460, 1095), lw=360)
    g.arrow([(1000, 850), (1000, 1095), (680, 1095)], "code and notes of every run (git)", at=(840, 1095), lw=270)
    g.arrow([(400, 810), (400, 960)], "reads the notes, writes the wiki", at=(400, 885), lw=420)
    g.legend(830, 1260)
    g.save("2-c4-context.png")


# =====================================================================================================
# 3. C4 level 2: containers
# =====================================================================================================
def containers():
    g = Diagram("C4 level 2, containers: the parts inside Dream-1 Lab")
    g.person(160, 80, 480, 230, "Operator", None)
    g.person(1760, 80, 520, 230, "Remote operator or judge", None)
    g.boundary(60, 380, 1560, 950, "Dream-1 Lab [software system, on the host laptop]")
    g.box(120, 420, 640, 230, "Web page", "Container: HTML, CSS, JavaScript",
          "View, cameras, Take over, menu panels. Guests: join page, fewer panels.")
    g.box(120, 760, 640, 360, "Dashboard application", "Container: Python 3.12, FastAPI, MuJoCo",
          "Web server with access check, simulation thread, recorder, credits, players, extensions. One process.")
    g.cylinder(900, 420, 660, 220, "Lab database", "Container: SQLite file out/lab.db",
               "Runs, episodes, exports, settings.")
    g.cylinder(900, 680, 660, 200, "Episode store", "Container: out/episodes, out/exports",
               "LeRobot v2.1 folders.")
    g.cylinder(900, 960, 660, 200, "Second brain", "Container: Markdown folder brain/, in git",
               "raw/: notes. wiki/: pages.")
    g.box(1760, 400, 520, 190, "Cloudflare", "External system", "Public link", style=EXTERNAL)
    g.box(1760, 650, 520, 220, "Dream Labs", "External system", "Dream-1 API. Fine-tuning: planned.",
          style=EXTERNAL)
    g.box(1760, 930, 520, 200, "AI agent", "External system", "Claude Code or Codex", style=EXTERNAL)
    g.box(1760, 1180, 520, 140, "GitHub", "External system", None, style=EXTERNAL)

    g.arrow([(400, 310), (400, 420)], "uses", at=(470, 365), lw=120)
    g.arrow([(2020, 310), (2020, 400)], "opens the link", at=(2170, 355), lw=220)
    g.arrow([(1760, 495), (1690, 495), (1690, 345), (680, 345), (680, 420)], "the guest's copy, through the tunnel",
            at=(1180, 345), lw=520)
    g.arrow([(440, 650), (440, 760)], "HTTP JSON, WebSocket events, MJPEG video", at=(440, 705), both=True, lw=560)
    g.arrow([(760, 790), (830, 790), (830, 530), (900, 530)], "SQL", at=(830, 660), lw=100)
    g.arrow([(760, 835), (900, 835)])
    g.label((830, 860), "writes", 100)
    g.arrow([(760, 920), (1650, 920), (1650, 760), (1760, 760)], "HTTPS: frames and arm state; back: arm moves",
            at=(1230, 920), lw=700)
    g.arrow([(760, 1060), (900, 1060)], "notes", at=(830, 1060), lw=100)
    g.arrow([(1760, 1030), (1560, 1030)], "ingest", at=(1660, 1030), lw=120)
    g.arrow([(1230, 1160), (1230, 1250), (1760, 1250)], "git push", at=(1500, 1250), lw=200)
    g.save("3-c4-containers.png")


# =====================================================================================================
# 4. C4 level 3: components of the dashboard application
# =====================================================================================================
def components():
    g = Diagram("C4 level 3, components: inside the dashboard application")
    g.boundary(430, 100, 1540, 1220, "Dashboard application [one Python process]")
    cols, rows, cw, ch = (460, 847, 1233, 1620), (140, 510, 880), 320, 290

    def comp(c, r, title, kind, body):
        g.box(cols[c], rows[r], cw, ch, title, kind, body, style=COMPONENT)

    comp(0, 0, "Lab database access", "lab_db.py", "Rows: runs, episodes, exports, settings")
    comp(1, 0, "Event bus", "events.py", "Every event to every open browser")
    comp(2, 0, "Credits", "credits.py", "Estimate, ask, monthly limit, balance")
    comp(3, 0, "Web app", "app.py, FastAPI", "Routes, video, /ws; access check for guests")
    comp(0, 1, "Recorder", "episodes.py", "Take over, LeRobot folders, export")
    comp(1, 1, "Extensions", "extension.py, extensions/", "Control, Scene, Robustness")
    comp(2, 1, "Sim worker", "simulation.py", "One thread owns MuJoCo and does the jobs")
    comp(3, 1, "Players", "multiplayer.py", "Access code, arm owners, public link")
    comp(0, 2, "Success check", "dreamtool/scene.py", "Task rules: on, in, next to, lift, push ...")
    comp(1, 2, "Second brain notes", "brain.py", "Notes on runs, tests, exports; daily summary")
    comp(2, 2, "Simulator wrapper", "dreamtool/sim.py", "Physics and the 3 cameras")
    comp(3, 2, "Run loop", "dreamtool/runner.py", "Dream-1 calls, 20 steps per second")

    g.cylinder(40, 150, 330, 260, "Lab database", "SQLite", "out/lab.db")
    g.cylinder(40, 520, 330, 260, "Episode store", "LeRobot folders", "out/episodes")
    g.cylinder(40, 900, 330, 250, "Second brain", "Markdown", "brain/raw")
    g.box(2030, 160, 330, 250, "Web page", "Container", "Sends requests; gets video and events")
    g.box(2030, 530, 330, 250, "Cloudflare", "External system", "Tunnel made by cloudflared", style=EXTERNAL)
    g.box(2030, 900, 330, 250, "Dream-1 API", "External system", "Through the dream library", style=EXTERNAL)

    # web side
    g.arrow([(1940, 285), (2030, 285)], both=True)
    g.arrow([(1007, 140), (1007, 118), (2195, 118), (2195, 160)], "events", at=(1600, 118), lw=120)
    g.arrow([(1620, 285), (1553, 285)])  # web app -> credits
    g.arrow([(1780, 430), (1780, 510)])  # web app -> players
    g.arrow([(1940, 655), (2030, 655)])  # players -> Cloudflare
    g.arrow([(1620, 390), (1587, 390), (1587, 600), (1553, 600)], "jobs", at=(1587, 545), lw=80)
    # simulation side
    g.arrow([(1167, 655), (1233, 655)])  # extensions -> sim worker
    g.arrow([(1553, 750), (1587, 750), (1587, 1000), (1620, 1000)], "runs", at=(1587, 880), lw=80)
    g.arrow([(1620, 1100), (1553, 1100)])  # run loop -> simulator wrapper
    g.arrow([(1940, 1025), (2030, 1025)])  # run loop -> Dream-1 API
    # data side
    g.arrow([(1393, 430), (1393, 455), (680, 455), (680, 430)], "spending so far", at=(1240, 455), lw=260)
    g.arrow([(1360, 510), (1360, 488), (720, 488), (720, 510)], "every step", at=(900, 488), lw=200)
    g.arrow([(560, 510), (560, 430)], "rows", at=(560, 470), lw=80)
    g.arrow([(460, 285), (370, 285)], "SQL", at=(415, 285), lw=80)
    g.arrow([(460, 650), (370, 650)])
    g.arrow([(620, 800), (620, 880)], "is the task done?", at=(620, 840), lw=260)
    g.arrow([(1360, 800), (1360, 840), (1007, 840), (1007, 880)], "after each run", at=(1180, 840), lw=220)
    g.arrow([(1007, 1170), (1007, 1215), (400, 1215), (400, 1100), (370, 1100)], "writes notes", at=(700, 1215),
            lw=200)
    g.save("4-c4-components.png")


# =====================================================================================================
# 5. Architecture: layers
# =====================================================================================================
def layers():
    g = Diagram("Architecture: the layers and what is in each one")
    bands = [("People and access", 100, 150), ("Browser", 255, 140), ("Web server", 400, 140),
             ("Application", 545, 220), ("Simulation", 770, 140), ("Data on disk", 915, 160),
             ("Outside services", 1080, 170)]
    for i, (name, y, h) in enumerate(bands):
        g.d.rectangle([40, y, 2360, y + h], fill="#F5F7FA" if i % 2 == 0 else "#FFFFFF", outline="#D5DCE4")
        g.block(56, y + h / 2 - 22, 300, [(name, font(30, "b"))], TEXT, align="left")

    def row(y, h, items, x0=380, x1=2340, gap=20):
        w = (x1 - x0 - gap * (len(items) - 1)) / len(items)
        for i, (title, body, style, *planned) in enumerate(items):
            g.box(x0 + i * (w + gap), y, w, h, title, None, body, style=style, planned=bool(planned))

    row(112, 126, [("Operator", "browser at localhost:8000", PERSON),
                   ("Remote operator or judge", "browser, public link", PERSON),
                   ("Cloudflare tunnel", "public link + access code", EXTERNAL),
                   ("AI agent", "keeps brain/wiki up to date", EXTERNAL)])
    row(265, 120, [("Core page", "index.html, app.js", COMPONENT),
                   ("Join page", "join.html: code and name", COMPONENT),
                   ("Menu panels", "Episodes, Credits, Players", COMPONENT),
                   ("Extension panels", "Control, Scene, Robustness", COMPONENT)])
    row(410, 120, [("HTTP JSON API", "/api/run, /api/credits ...", COMPONENT),
                   ("Access check", "guests: code, routes, own arm", COMPONENT),
                   ("Video streams", "smaller for guests", COMPONENT),
                   ("Event bus", "WebSocket /ws", COMPONENT)])
    row(560, 190, [("Sim worker", "one thread owns the simulation", COMPONENT),
                   ("Run loop", "Dream-1 calls, 20 steps per second", COMPONENT),
                   ("Recorder", "episodes, take over, export", COMPONENT),
                   ("Credits", "estimate, limit, balance", COMPONENT),
                   ("Players", "access code, arm owners", COMPONENT),
                   ("Brain notes", "notes for brain/raw", COMPONENT),
                   ("Extensions", "teleop, robustness tests", COMPONENT)], gap=16)
    row(782, 116, [("YAM simulator: MuJoCo physics", "two arms, 3 cameras at 640 x 360, fruit, bowl, plate",
                    CONTAINER),
                   ("Success check", "task rules decide success, time counted in simulated seconds", CONTAINER)])
    row(930, 130, [("lab.db (SQLite)", "runs, episodes, exports, settings", CONTAINER),
                   ("episodes/ and exports/", "LeRobot v2.1 folders", CONTAINER),
                   ("extensions/ results", "robustness reports, one-file report", CONTAINER),
                   ("brain/", "raw/ and wiki/, in git", CONTAINER)])
    row(1095, 140, [("Dream-1 API (Dream Labs)", "frames + arm state in, arm moves out", EXTERNAL),
                    ("Dream Labs fine-tuning", "upload, train, new model id", EXTERNAL, True),
                    ("GitHub", "code and brain/", EXTERNAL)])
    g.legend(380, 1285)
    g.save("5-architecture-layers.png")


# =====================================================================================================
# 6. Architecture: the teaching loop
# =====================================================================================================
def teaching_loop():
    g = Diagram("Architecture: the teaching loop, step by step")
    y1, y2, w, h = 200, 760, 470, 330
    xs = [60, 640, 1220, 1800]

    def step(i, x, y, title, body, planned=False, style=CONTAINER):
        g.box(x, y, w, h, f"{i}. {title}", None, body, style=style, planned=planned)

    step(1, xs[0], y1, "Task", "The operator types a task, for example 'put banana on the plate', sees the cost "
         "estimate and presses Run.", style=PERSON)
    step(2, xs[1], y1, "Dream-1 tries", "The run loop sends pictures and arm positions to Dream-1 and moves the "
         "arms. The recorder records.")
    step(3, xs[2], y1, "Take over", "Dream-1 fails, or the operator presses Take over. Dream-1 stops; the scene "
         "stays.", style=PERSON)
    step(4, xs[3], y1, "Person finishes", "The operator, or a guest on another laptop, moves the arms with "
         "Control. The recorder keeps recording.", style=PERSON)
    step(5, xs[3], y2, "Save", "The success check marks the episode. A LeRobot folder and a database row are "
         "written.")
    step(6, xs[2], y2, "Export", "All unused successful episodes of one task go into one folder. Dream Labs' "
         "check runs.")
    step(7, xs[1], y2, "Fine-tune", "Upload to Dream Labs, a training job, a new model id dream-1-ft:...",
         planned=True, style=EXTERNAL)
    step(8, xs[0], y2, "Compare", "Run the task with the new model. Episodes and Credits show success and cost per "
         "model; the second brain gets the notes.")

    mid1, mid2 = y1 + h / 2, y2 + h / 2
    g.arrow([(xs[0] + w, mid1), (xs[1], mid1)])
    g.arrow([(xs[1] + w, mid1), (xs[2], mid1)], "fails", at=(xs[1] + w + 55, mid1 - 40), lw=110)
    g.arrow([(xs[2] + w, mid1), (xs[3], mid1)])
    g.arrow([(xs[3] + w / 2, y1 + h), (xs[3] + w / 2, y2)], "Save episode", at=(xs[3] + w / 2, (y1 + h + y2) / 2),
            lw=220)
    g.arrow([(xs[3], mid2), (xs[2] + w, mid2)])
    g.arrow([(xs[2], mid2), (xs[1] + w, mid2)], None, planned=True)
    g.arrow([(xs[1], mid2), (xs[0] + w, mid2)], None, planned=True)
    g.arrow([(xs[0] + w / 2, y2), (xs[0] + w / 2, y1 + h)], "next round", at=(xs[0] + w / 2, (y1 + h + y2) / 2),
            lw=200)
    g.arrow([(xs[1] + w / 2, y1 + h), (xs[1] + w / 2, 640), (xs[3] + 60, 640), (xs[3] + 60, y2)],
            "success: saved at once", at=(xs[2] + w / 2, 640), lw=320)
    g.legend(60, 1180)
    g.save("6-teaching-loop.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in (deployment, context, containers, components, layers, teaching_loop):
        fn()
