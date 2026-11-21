"""Builds Dream-1-Lab-architecture.docx from the diagram PNGs (standard library only).

Run from the repository root, after diagrams.py:
python docs/architecture/make_docx.py docs/architecture/png docs/architecture/Dream-1-Lab-architecture.docx
"""
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

PNG, OUT = Path(sys.argv[1]), Path(sys.argv[2])
FONT = "Arial"
PAGE_W, PAGE_H, MARGIN = 16838, 11906, 1080  # A4 landscape, 0.75 inch margins (twentieths of a point)
TEXT_W = PAGE_W - 2 * MARGIN
IMG_W_IN = 9.6
EMU = 914400

body: list[str] = []
images: list[tuple[str, str]] = []  # (rId, file name)


def run(text, bold=False, italic=False, size=None, color=None):
    props = ""
    if bold:
        props += "<w:b/>"
    if italic:
        props += "<w:i/>"
    if color:
        props += f'<w:color w:val="{color}"/>'
    if size:
        props += f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def para(*runs, style=None, page_break=False, keep_next=False, align=None, after=None):
    ppr = ""
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if keep_next:
        ppr += "<w:keepNext/>"
    if page_break:
        ppr += "<w:pageBreakBefore/>"
    if after is not None:
        ppr += f'<w:spacing w:after="{after}"/>'
    if align:
        ppr += f'<w:jc w:val="{align}"/>'
    content = "".join(r if r.startswith("<w:r>") else run(r) for r in runs)
    return f"<w:p><w:pPr>{ppr}</w:pPr>{content}</w:p>"


def add(*items):
    body.extend(items)


def h1(text, page_break=True):
    add(para(text, style="Heading1", page_break=page_break))


def h2(text, page_break=False):
    add(para(text, style="Heading2", page_break=page_break))


def p(*runs, **kw):
    add(para(*runs, **kw))


def image(file, alt):
    n = len(images) + 1
    rid = f"rIdImg{n}"
    images.append((rid, file))
    cx = int(IMG_W_IN * EMU)
    cy = int(cx * 1350 / 2400)
    add(f"""<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:after="120"/></w:pPr><w:r><w:drawing>
<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>
<wp:docPr id="{n}" name="Diagram {n}" descr="{escape(alt, {'"': '&quot;'})}"/>
<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>
<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
<pic:pic><pic:nvPicPr><pic:cNvPr id="{n}" name="{file}"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>""")


def table(header, rows, widths, new_page=False):
    if new_page:
        add(para("", page_break=True, after=0))
    scale = TEXT_W / sum(widths)
    widths = [int(w * scale) for w in widths]
    border = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="BFC7D1"/>'
                     for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)

    def cell(text, w, head=False):
        shade = '<w:shd w:val="clear" w:color="auto" w:fill="E8EEF5"/>' if head else ""
        return (f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{shade}'
                f'<w:tcMar><w:top w:w="60" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/></w:tcMar></w:tcPr>'
                f'{para(run(text, bold=head), after=0)}</w:tc>')

    head = '<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>' + "".join(
        cell(t, w, True) for t, w in zip(header, widths)) + "</w:tr>"
    body_rows = "".join("<w:tr><w:trPr><w:cantSplit/></w:trPr>" + "".join(cell(t, w) for t, w in zip(r, widths))
                        + "</w:tr>" for r in rows)
    add(f'<w:tbl><w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/><w:tblBorders>{border}</w:tblBorders>'
        f'<w:tblLayout w:type="fixed"/><w:tblCellMar><w:left w:w="100" w:type="dxa"/>'
        f'<w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>{grid}</w:tblGrid>'
        f'{head}{body_rows}</w:tbl>', para("", after=120))


# =====================================================================================================
# Content
# =====================================================================================================
p("Dream-1 Lab: architecture diagrams", style="Title")
p(run("State on 21 November 2026. Code: branch design/minimal-dashboard, commit dfc1d6a (multiplayer, credits, "
      "success rules, report additions, simulated seconds, second brain). The pictures are drawn by "
      "docs/architecture/diagrams.py; run it again after a change.", color="555555"))

h2("What this document holds")
table(["Part", "Diagram", "The question it answers"], [
    ["1", "Deployment diagram", "On which computer and in which program does each part run, and how are they connected?"],
    ["2.1", "C4 level 1: system context", "Who uses Dream-1 Lab, and which outside systems does it talk to?"],
    ["2.2", "C4 level 2: containers", "Which separate parts make up Dream-1 Lab: page, application, database, files?"],
    ["2.3", "C4 level 3: components", "Which code parts are inside the dashboard application, and who calls whom?"],
    ["3.1", "Architecture: layers", "Which layers does the system have, and what sits in each layer?"],
    ["3.2", "Architecture: teaching loop", "How does an episode move from a Dream-1 try to a fine-tune?"],
    ["3.3", "Architecture: Test Suite", "How does a test campaign run, and where do its results go?"],
    ["4", "Built and planned", "Which parts work today, and which parts are planned?"],
], [600, 3200, 10000])

h2("How to read the diagrams")
table(["Mark", "Meaning"], [
    ["Solid line, filled box", "Built. It works today in the branch."],
    ["Dashed line, white box with dashed border", "Planned. It is not built yet."],
    ["Dark blue box", "A person."],
    ["Blue boxes", "Parts of Dream-1 Lab. A darker blue is a larger part; a lighter blue is a code part."],
    ["Grey box", "A system outside Dream-1 Lab: Dream Labs, GitHub, Cloudflare, the AI agent."],
    ["Cylinder", "A place where data is stored: the database, the episode folders, the second brain folder."],
    ["Arrow", "Points from the part that starts the exchange to the part that answers. Two heads: both directions."],
], [4400, 9400])

# ---------------- 1 deployment ----------------
h1("1. Deployment diagram")
image("1-deployment.png", "Deployment diagram: host laptop with WSL, dashboard process, files, browser; guest laptop, "
      "Cloudflare, Dream Labs, GitHub")
p("One laptop, the host, does all the heavy work: physics, camera pictures, recording. Every other computer only "
  "shows a web page. The host is a teammate's laptop.")
table(["Place", "What runs or lies there", "Status"], [
    ["Host laptop, Windows 11", "The web browser of the operator. Planned: an AI agent (Claude Code or Codex) that "
     "summarizes the team notes and answers questions about the wiki.", "Browser: built. AI agent: planned."],
    ["WSL 2, Ubuntu 24.04 (Linux inside Windows)", "The dashboard process (python start.py); cloudflared, the "
     "program that makes the public link, started from the menu entry Players; the code folders dream-tool (with "
     "the second brain folder brain/) and dreamlabs; the out/ folder with the database, the episodes and the test "
     "reports; the API key file.", "Built."],
    ["Guest laptop", "Only a web browser. The guest opens the public link, types the access code and a name, takes "
     "one arm and moves it. The guest gets a smaller video (12 pictures per second).", "Built."],
    ["Cloudflare", "A quick tunnel: a public web address https://<words>.trycloudflare.com that leads to port 8000 "
     "on the host. It needs no Cloudflare account and changes every time it opens. The host opens the tunnel from "
     "the inside, so no router settings are needed. The access code is checked by the dashboard, not by "
     "Cloudflare.", "Built."],
    ["Dream Labs", "The Dream-1 model (the dashboard sends pictures and arm positions, and gets arm moves back; "
     "each call costs $0.0014). The data service and fine-tuning (receives exported episodes, trains a new model).",
     "Dream-1 calls: built. Upload and fine-tuning: planned."],
    ["GitHub", "The team's repository DreamLabs_Hacklab: the code and the second brain folder brain/ (raw/ notes "
     "and wiki/ pages). The lab database out/lab.db stays on the host and is not in git.", "Built."],
], [3300, 7700, 2800], new_page=True)

# ---------------- 2 C4 ----------------
h1("2. C4 model")
p("The C4 model shows a software system at four zoom levels, like a map: level 1 shows the system and its "
  "surroundings, level 2 the large parts inside it, level 3 the code parts inside one large part, and level 4 the "
  "code itself. This document shows levels 1 to 3. Level 4 is the source code in the repository.")

h2("2.1 Level 1: system context", page_break=False)
image("2-c4-context.png", "C4 system context: operator, remote operator, Dream-1 Lab, AI agent, Cloudflare, "
      "Dream Labs, GitHub")

h2("2.2 Level 2: containers", page_break=True)
image("3-c4-containers.png", "C4 containers: web page, dashboard application, lab database, episode store, "
      "second brain")
table(["Container", "Technology", "Job"], [
    ["Web page", "HTML, CSS, JavaScript in a web browser", "Shows the view and the cameras, takes tasks, has the "
     "buttons Take over, Save episode, Discard, and the menu panels Control, Scene, Robustness, Episodes, Credits, "
     "Players. Each viewer has an own copy. A guest first sees the join page and then only Control, Scene and "
     "Players."],
    ["Dashboard application", "Python 3.12, FastAPI web server, MuJoCo simulator, one process",
     "Runs the simulation, talks to Dream-1, runs the extensions, records episodes, counts credits, checks guests, "
     "writes notes for the second brain."],
    ["Lab database", "SQLite: one file, out/lab.db, no server program",
     "One row per run, per episode and per export, and the credit settings. Answers: which episodes to train on, "
     "success and cost per model, where a person took over, how much credit is left. Not in GitHub."],
    ["Episode store", "Folders out/episodes and out/exports", "One folder per episode in the LeRobot v2.1 format "
     "that Dream Labs checks: 3 camera videos, a table of arm values, description files."],
    ["Second brain", "Markdown files in the folder brain/, in git", "raw/: notes the dashboard writes by itself "
     "(every Dream-1 run, every robustness test, every export, a daily summary) and notes people write. wiki/: "
     "pages the script brain/build_wiki.py makes from raw/: per task, per model, robustness, exports, notes, "
     "decisions. People read it in Obsidian or on GitHub. An AI agent that adds summaries is planned."],
], [2600, 4200, 7000], new_page=True)

h2("2.3 Level 3: components of the dashboard application", page_break=True)
image("4-c4-components.png", "C4 components inside the dashboard application")
table(["Component", "File", "Job"], [
    ["Web app", "dashboard/app.py", "Receives every request from the web page; sends the video streams. Its access "
     "check knows a guest by the Cloudflare headers, asks for the access code, lets a guest use only some routes, "
     "and lets a guest move only the arm the guest took."],
    ["Players", "dashboard/multiplayer.py", "The access code (new at each start; 10 wrong codes from one address "
     "wait 10 minutes), the guests, which arm belongs to whom, and the public link (starts and stops cloudflared)."],
    ["Credits", "dashboard/credits.py", "Estimates the cost before a run, asks for a second click above $0.10, "
     "refuses a run that could pass the monthly limit of $100, and computes the balance from the starting balance "
     "of $150. The Dream Labs API does not report the balance, so the dashboard counts calls x price."],
    ["Second brain notes", "dashboard/brain.py", "Writes Markdown notes into brain/raw: one line per Dream-1 run, one "
     "page per robustness test and per export, and a daily summary read from the lab database. After each note it "
     "runs brain/build_wiki.py, which rewrites the wiki pages in brain/wiki."],
    ["Event bus", "dashboard/events.py", "Sends each event (run started, episode state, log line) to every open "
     "browser."],
    ["Sim worker", "dashboard/simulation.py", "The one thread that owns the simulator. Between runs it holds the "
     "arms and keeps drawing pictures; it carries out runs and other jobs one after the other."],
    ["Run loop", "dreamtool/runner.py", "Collects camera pictures, asks Dream-1 for arm moves, carries them out 20 "
     "times per second, stops on success, time limit, monthly credit limit or Stop. The time limit counts "
     "simulated seconds, so waiting for Dream-1 does not use it up. It talks to Dream Labs through the dream "
     "library from the dreamlabs clone."],
    ["Simulator wrapper", "dreamtool/sim.py", "Makes the YAM simulator from the dreamlabs clone usable: physics and "
     "the 3 cameras."],
    ["Success check", "dreamtool/scene.py", "Reads object positions and decides if a task is done. Task types: put "
     "on or in, take out of, next to, stack, push left/right/forward/back, lift, stand upright, all fruit in the "
     "bowl, and two tasks joined by 'then'. Placing tasks are read first by the teammates' sentence reading, so "
     "natural sentences and German work too. A new type is one entry in the list RULES."],
    ["Recorder", "dashboard/episodes.py", "Records episodes, handles Take over, Save and Discard, writes the LeRobot "
     "folders, makes exports."],
    ["Lab database access", "dashboard/lab_db.py", "Writes and reads the rows in lab.db (runs, episodes, exports, "
     "settings) and computes the summary."],
    ["Test Suite", "dashboard/extensions/test_suite/", "The teammates' testing workspace (menu Test Suite): plans "
     "test cases, runs each one on the sim worker with a limit of Dream-1 calls and a deadline, collects evidence "
     "(contacts, joint limits, distance to the target), judges success, failure category and safety, and saves a "
     "report in out/extensions/test_suite/. The Robustness tests appear in it as tiles."],
    ["Extensions", "dashboard/extension.py, dashboard/extensions/",
     "Loads the tools: Control (move the arms by hand, with inverse kinematics), Scene, Robustness tests. The "
     "robustness report shows Dream-1 calls and cost per trial and downloads as one HTML file."],
], [3000, 3800, 7000], new_page=True)

# ---------------- 3 architecture ----------------
h1("3. Architecture diagram")
h2("3.1 Layers", page_break=False)
image("5-architecture-layers.png", "Architecture layers from people to outside services")
p("Each layer uses only the layer below it. The browser never touches the simulator directly: it asks the web "
  "server, and the web server hands the job to the sim worker. This keeps the simulator in one thread, because "
  "MuJoCo is not safe to use from several threads at once.")

h2("3.2 The teaching loop", page_break=True)
image("6-teaching-loop.png", "Teaching loop: task, Dream-1 tries, take over, person finishes, save, export, "
      "fine-tune, compare")
p("Steps 1 to 6 and step 8 work today. Step 7, the upload and the fine-tune at Dream Labs, waits for the answers "
  "to four questions to Dream Labs: is simulated data accepted, what does one training job cost, should "
  "training use the whole episode or only the part after the take-over, and is recording at 10 frames per second "
  "right.")

h2("3.3 The Test Suite", page_break=True)
image("7-test-suite.png", "Test Suite: choose a test, plan the cases, run each case, collect evidence, judge, save "
      "the report, read the results; Breaking Point picks the next strength")
p("The Test Suite was built by teammates and joined into this branch on 21 November 2026. Its runs use the same "
  "simulation thread as the dashboard, so they wait while another run is going, and their Dream-1 calls appear in "
  "the lab database and in Credits. Unlike normal runs, a Test Suite case stops at a deadline in clock time and at "
  "a limit of Dream-1 calls.")

# ---------------- 4 status ----------------
h1("4. Built and planned")
table(["Part", "Status", "Where"], [
    ["Dashboard: view, cameras, camera swap, task bar, menu, status dot", "Built", "dashboard/static/"],
    ["Dream-1 runs with success check and reply times", "Built", "dreamtool/runner.py, dreamtool/scene.py"],
    ["Control: move the arms by hand (teammate's extension)", "Built", "dashboard/extensions/teleop/"],
    ["Take over, episode recording in LeRobot format, Save, Discard", "Built", "dashboard/episodes.py"],
    ["Lab database: runs, episodes, exports, cost", "Built", "dashboard/lab_db.py, out/lab.db"],
    ["Export with Dream Labs' own dataset check", "Built", "dashboard/episodes.py"],
    ["Multiplayer: second person controls one arm from another laptop", "Built", "dashboard/multiplayer.py"],
    ["Cloudflare quick tunnel with access code", "Built", "dashboard/multiplayer.py, ~/Hacklab/bin/cloudflared"],
    ["Second brain: notes and wiki pages made by a script, in the team repository", "Built",
     "dashboard/brain.py, brain/build_wiki.py"],
    ["Second brain: AI agent that summarizes notes and answers questions", "Planned", "rules in brain/AGENTS.md"],
    ["Credits: balance, estimate, ask above $0.10, monthly limit", "Built", "dashboard/credits.py"],
    ["More success rules (lift, push, next to, stack, ...)", "Built", "dreamtool/scene.py"],
    ["Report additions: cost per trial, one-file report", "Built", "dashboard/extensions/robustness/"],
    ["Time limit in simulated seconds", "Built", "dreamtool/runner.py"],
    ["Test Suite: quick test, repeated runs, sweeps, safety, A/B, failure reproduction (teammates)", "Built",
     "dashboard/extensions/test_suite/"],
    ["Robustness: breaking-point search, inside the Test Suite (teammates)", "Built",
     "dashboard/extensions/robustness/adaptive.py"],
    ["Task recognition for natural sentences and German (teammates)", "Built", "dreamtool/scene.py"],
    ["Upload of exports and fine-tuning at Dream Labs", "Planned", "waits for 4 answers from Dream Labs"],
], [7800, 1600, 4400])

# =====================================================================================================
# Package
# =====================================================================================================
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
sect = (f'<w:sectPr><w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}" w:orient="landscape"/>'
        f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" w:header="500" '
        f'w:footer="500" w:gutter="0"/></w:sectPr>')
document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}><w:body>{"".join(body)}{sect}</w:body></w:document>'


def style(sid, name, size, bold=False, before=0, after=120, color=None, keep=False, outline=None):
    rpr = f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/>' + ("<w:b/>" if bold else "") + \
          (f'<w:color w:val="{color}"/>' if color else "") + f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
    ppr = (f'<w:spacing w:before="{before}" w:after="{after}"/>' + ("<w:keepNext/>" if keep else "")
           + (f'<w:outlineLvl w:val="{outline}"/>' if outline is not None else ""))
    return (f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/><w:basedOn w:val="Normal"/>'
            f'<w:next w:val="Normal"/><w:qFormat/><w:pPr>{ppr}</w:pPr><w:rPr>{rpr}</w:rPr></w:style>')


styles = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}" w:eastAsia="{FONT}"/>
<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>
<w:rPr><w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:cs="{FONT}"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
{style("Title", "Title", 44, True, 0, 160, "1B1B1B", True)}
{style("Heading1", "heading 1", 32, True, 0, 160, "0B3D6E", True, 0)}
{style("Heading2", "heading 2", 26, True, 240, 120, "1168BD", True, 1)}
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:uiPriority w:val="99"/>
<w:semiHidden/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/>
<w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>"""

content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            + "".join(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{f}"/>'
                      for rid, f in images) + "</Relationships>")

core = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>Dream-1 Lab: architecture diagrams</dc:title>
<dcterms:created xsi:type="dcterms:W3CDTF">2026-11-21T00:00:00Z</dcterms:created>
</cp:coreProperties>"""

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("[Content_Types].xml", content_types)
    z.writestr("_rels/.rels", root_rels)
    z.writestr("docProps/core.xml", core)
    z.writestr("word/document.xml", document)
    z.writestr("word/styles.xml", styles)
    z.writestr("word/_rels/document.xml.rels", doc_rels)
    for _, f in images:
        z.write(PNG / f, f"word/media/{f}")
print("wrote", OUT)
