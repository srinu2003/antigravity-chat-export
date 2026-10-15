import os
import sys
import json
import re
import shutil
import argparse
from datetime import datetime

from urllib.parse import unquote

def get_brain_dir():
    env_brain = os.environ.get("ANTIGRAVITY_BRAIN_DIR")
    if env_brain and os.path.exists(env_brain):
        return env_brain
    env_app = os.environ.get("ANTIGRAVITY_APP_DATA_DIR")
    if env_app and os.path.exists(os.path.join(env_app, "brain")):
        return os.path.join(env_app, "brain")
    home = os.path.expanduser("~")
    return os.path.join(home, ".gemini", "antigravity", "brain")

def find_conversation_dir(conv_id=None):
    brain_dir = get_brain_dir()
    if conv_id:
        if os.path.isdir(conv_id):
            return os.path.abspath(conv_id)
        direct = os.path.join(brain_dir, conv_id)
        if os.path.exists(direct):
            return direct
        # Prefix match
        if os.path.exists(brain_dir):
            for d in os.listdir(brain_dir):
                if d.lower().startswith(conv_id.lower()):
                    full = os.path.join(brain_dir, d)
                    if os.path.isdir(full):
                        return full
    if not os.path.exists(brain_dir):
        raise ValueError(f"Antigravity brain directory does not exist at: {brain_dir}")

    entries = [os.path.join(brain_dir, d) for d in os.listdir(brain_dir)]
    valid_dirs = []
    for d in entries:
        if os.path.isdir(d):
            log_full = os.path.join(d, ".system_generated", "logs", "transcript_full.jsonl")
            log_compact = os.path.join(d, ".system_generated", "logs", "transcript.jsonl")
            if os.path.exists(log_full) or os.path.exists(log_compact):
                valid_dirs.append(d)

    if not valid_dirs:
        raise ValueError(f"No valid conversation directories with transcripts found in {brain_dir}")
    valid_dirs.sort(key=os.path.getmtime, reverse=True)
    return valid_dirs[0]

def parse_transcript(conv_dir):
    log_full = os.path.join(conv_dir, ".system_generated", "logs", "transcript_full.jsonl")
    log_compact = os.path.join(conv_dir, ".system_generated", "logs", "transcript.jsonl")
    target_log = log_full if os.path.exists(log_full) else log_compact
    if not os.path.exists(target_log):
        raise FileNotFoundError(f"Transcript log not found in {conv_dir}")
    steps = []
    with open(target_log, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    steps.append(json.loads(line))
                except Exception:
                    continue
    return steps

def process_conversation(steps, assets_dir):
    os.makedirs(assets_dir, exist_ok=True)
    copied_assets = {}

    def copy_asset(abs_path):
        clean_path = abs_path.replace("file:///", "").replace("file://", "")
        clean_path = unquote(clean_path)
        clean_path = os.path.abspath(clean_path)
        if clean_path in copied_assets:
            return copied_assets[clean_path]
        if os.path.isfile(clean_path):
            _, ext = os.path.splitext(clean_path)
            if ext.lower() not in ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf', '.md'):
                return None
            basename = os.path.basename(clean_path)
            dest_name = basename
            counter = 1
            while os.path.exists(os.path.join(assets_dir, dest_name)) and copied_assets.get(clean_path) != dest_name:
                name_part, ext_part = os.path.splitext(basename)
                dest_name = f"{name_part}_{counter}{ext_part}"
                counter += 1
            try:
                shutil.copy2(clean_path, os.path.join(assets_dir, dest_name))
                copied_assets[clean_path] = dest_name
                return dest_name
            except Exception as e:
                print(f"[!] Warning copying {clean_path}: {e}")
                return None
        return None

    def clean_user_text(raw_text):
        if not raw_text:
            return ""
        matches = re.findall(r'<USER_REQUEST>(.*?)</USER_REQUEST>', raw_text, flags=re.DOTALL)
        if matches:
            joined = "\n\n".join(m.strip() for m in matches if m.strip())
            if joined:
                return joined
        cleaned = re.sub(r'<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>', '', raw_text, flags=re.DOTALL)
        cleaned = re.sub(r'<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'<CONTEXT_SUMMARY>.*?</CONTEXT_SUMMARY>', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'</?[A-Z_]+>', '', cleaned)
        return cleaned.strip() or raw_text.strip()

    turns = []
    current_turn = None

    for step in steps:
        step_type = step.get("type")
        source = step.get("source")

        if step_type == "USER_INPUT" or (source == "USER_EXPLICIT" and "content" in step):
            if current_turn:
                turns.append(current_turn)
            user_media = []
            if "media" in step and step["media"]:
                for m in step["media"]:
                    uri = m.get("uri", "")
                    if uri:
                        dest = copy_asset(uri)
                        if dest:
                            user_media.append({
                                "name": os.path.basename(uri),
                                "url": f"./assets/{dest}",
                                "mime": m.get("mime_type", "image/png")
                            })
            raw_prompt = step.get("content", "")
            clean_prompt = clean_user_text(raw_prompt)
            current_turn = {
                "turn_index": len(turns) + 1,
                "user_prompt": clean_prompt,
                "raw_user_prompt": raw_prompt,
                "created_at": step.get("created_at", ""),
                "user_media": user_media,
                "thinking_blocks": [],
                "tool_calls": [],
                "assistant_response": "",
                "total_output_tokens": 0
            }
        elif current_turn:
            # Accumulate assistant outputs
            if "thinking" in step and step["thinking"]:
                current_turn["thinking_blocks"].append(step["thinking"])
            if "tool_calls" in step and step["tool_calls"]:
                for tc in step["tool_calls"]:
                    current_turn["tool_calls"].append({
                        "name": tc.get("name", "tool"),
                        "summary": tc.get("toolSummary", tc.get("name", "")),
                        "action": tc.get("toolAction", ""),
                        "args": tc.get("args", {})
                    })
            # IMPORTANT: Only collect genuine assistant replies (PLANNER_RESPONSE), not tool logs/stdout
            if step_type == "PLANNER_RESPONSE" and "content" in step and step["content"]:
                current_turn["assistant_response"] += step["content"]
            if "output_tokens" in step:
                current_turn["total_output_tokens"] += step.get("output_tokens", 0)
            elif "metrics" in step:
                current_turn["total_output_tokens"] += step["metrics"].get("output_tokens", 0)

    if current_turn:
        turns.append(current_turn)

    # Rewrite any local file paths inside assistant responses to point to ./assets/
    for t in turns:
        def replace_img_path(m):
            full_match = m.group(0)
            target_path = m.group(1) if m.lastindex >= 1 else None
            if not target_path and len(m.groups()) >= 2:
                target_path = m.group(2)
            if target_path:
                copied = copy_asset(target_path)
                if copied:
                    return full_match.replace(target_path, f"./assets/{copied}")
            return full_match

        t["assistant_response"] = re.sub(r'!\[.*?\]\((file:///[^\)]+)\)', replace_img_path, t["assistant_response"])
        t["assistant_response"] = re.sub(r'\[.*?\]\((file:///[^\)]+\.(?:png|svg|jpg|jpeg|gif|webp))\)', replace_img_path, t["assistant_response"])
        t["assistant_response"] = re.sub(r'src=["\'](file:///[^"\']+)["\']', replace_img_path, t["assistant_response"])

    return turns, copied_assets


HTML_PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Antigravity Chat · __CONV_ID__</title>

  <!-- Core libs -->
  <script src="https://cdn.jsdelivr.net/npm/marked@9/marked.min.js"></script>
  <link  rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.css">
  <script src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/katex.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/katex@0.16.10/dist/contrib/auto-render.min.js"></script>
  <link id="hljs-theme" rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/latex.min.js"></script>
  <!-- Mermaid for diagram rendering -->
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>

  <style>
    /* ─── Design Tokens ────────────────────────────────────────────── */
    :root {
      --col-w: 780px;
      --sidebar-w: 260px;
      --base-font: 15px;

      /* Light Theme */
      --bg:           #ffffff;
      --sidebar-bg:   #f9f9f9;
      --hover:        #f0f0f0;
      --border:       #e5e5e5;
      --border2:      #d4d4d4;

      --text:         #0d0d0d;
      --text2:        #404040;
      --text3:        #737373;
      --text4:        #a3a3a3;

      --user-bubble:  #f4f4f4;
      --brand:        #10a37f;   /* ChatGPT green */
      --brand-hover:  #0e8e6e;

      --inline-bg:    #f1f2f4;
      --inline-fg:    #0969da;
      --inline-border:#d0d7de;

      /* Light Code Block */
      --code-bg:            #f6f8fa;
      --code-topbar-bg:     #eff1f3;
      --code-border:        #d0d7de;
      --code-text:          #24292f;
      --code-gutter-color:  #8c959f;
      --code-gutter-border: #d0d7de;
      --code-label:         #57606a;
      --code-btn-color:     #57606a;
      --code-btn-hover-bg:  rgba(0, 0, 0, 0.06);
      --code-btn-hover-color:#24292f;
      --code-scroll-thumb:  #d0d7de;
      --code-shadow:        0 1px 3px rgba(0, 0, 0, 0.05);

      --shadow: 0 1px 3px rgba(0,0,0,.06);
      --shadow-lg: 0 6px 20px rgba(0,0,0,.10);
    }

    [data-theme="dark"] {
      --bg:           #212121;
      --sidebar-bg:   #171717;
      --hover:        #2a2a2a;
      --border:       #303030;
      --border2:      #444444;

      --text:         #ececec;
      --text2:        #c4c4c4;
      --text3:        #8e8e8e;
      --text4:        #555555;

      --user-bubble:  #2f2f2f;
      --brand:        #19c37d;
      --brand-hover:  #14a86b;

      --inline-bg:    #2b2d31;
      --inline-fg:    #58a6ff;
      --inline-border:#383a40;

      /* Dark Code Block (VS Code Dark+) */
      --code-bg:            #1e1e1e;
      --code-topbar-bg:     #252526;
      --code-border:        #333333;
      --code-text:          #d4d4d4;
      --code-gutter-color:  #858585;
      --code-gutter-border: #333333;
      --code-label:         #9da5b4;
      --code-btn-color:     #858585;
      --code-btn-hover-bg:  rgba(255, 255, 255, 0.08);
      --code-btn-hover-color:#e0e0e0;
      --code-scroll-thumb:  #424242;
      --code-shadow:        0 3px 12px rgba(0, 0, 0, 0.22);

      --shadow: 0 1px 3px rgba(0,0,0,.4);
      --shadow-lg: 0 6px 20px rgba(0,0,0,.5);
    }

    /* ─── Reset ────────────────────────────────────────────────────── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html {
      overflow: hidden;
      -webkit-text-size-adjust: 100%;
      text-size-adjust: 100%;
    }

    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", sans-serif;
      background: var(--bg);
      color: var(--text);
      display: flex;
      height: 100vh;
      width: 100vw;
      overflow: hidden;
      -webkit-font-smoothing: antialiased;
      -webkit-text-size-adjust: 100%;
      text-size-adjust: 100%;
    }

    a { color: var(--brand); text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* ─── Sidebar ──────────────────────────────────────────────────── */
    #sidebar {
      width: var(--sidebar-w);
      flex-shrink: 0;
      background: var(--sidebar-bg);
      display: flex;
      flex-direction: column;
      border-right: 1px solid var(--border);
      overflow: hidden;
      transition: width .05s ease-out;
    }

    .sb-top {
      padding: 12px 14px 10px;
      border-bottom: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .brand-row {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .brand-icon {
      width: 26px; height: 26px;
      background: var(--brand);
      border-radius: 6px;
      display: grid; place-items: center;
      color: #fff;
      font-weight: 800;
      font-size: 12px;
      flex-shrink: 0;
    }

    .brand-text {
      font-weight: 600;
      font-size: .88rem;
      color: var(--text);
    }

    .search-wrap {
      display: flex;
      align-items: center;
      gap: 7px;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 7px;
      padding: 6px 10px;
    }

    .search-wrap svg { color: var(--text4); flex-shrink: 0; }

    #search-inp {
      background: none;
      border: none;
      outline: none;
      font-size: .82rem;
      color: var(--text);
      width: 100%;
    }
    #search-inp::placeholder { color: var(--text4); }

    .sb-label {
      padding: 12px 14px 4px;
      font-size: .68rem;
      font-weight: 600;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: var(--text4);
    }

    #nav-list {
      list-style: none;
      overflow-y: auto;
      flex: 1;
      padding: 4px 8px 16px;
    }

    .nav-item {
      display: flex;
      align-items: baseline;
      gap: 8px;
      padding: 7px 10px;
      border-radius: 7px;
      cursor: pointer;
      margin-bottom: 2px;
      transition: background .12s;
    }

    .nav-item:hover { background: var(--hover); }
    .nav-item.active { background: var(--hover); font-weight: 500; }

    .nav-num {
      font-family: ui-monospace, monospace;
      font-size: .72rem;
      color: var(--text4);
      min-width: 18px;
      flex-shrink: 0;
    }

    .nav-text {
      font-size: .8rem;
      color: var(--text2);
      line-height: 1.35;
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }

    .nav-item.active .nav-text { color: var(--text); }

    /* ─── Sidebar Resizer (Divider Dragging) ───────────────────────── */
    #sidebar-resizer {
      width: 5px;
      cursor: col-resize;
      background: transparent;
      flex-shrink: 0;
      position: relative;
      z-index: 50;
      transition: background .15s;
    }
    #sidebar-resizer:hover, #sidebar-resizer.dragging {
      background: var(--brand);
    }

    /* ─── Main Content ─────────────────────────────────────────────── */
    #main {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      background: var(--bg);
    }

    /* Topbar */
    #topbar {
      height: 48px;
      background: var(--bg);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 16px;
      flex-shrink: 0;
      gap: 12px;
    }

    .topbar-left {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }

    .tb-toggle-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 30px; height: 30px;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: var(--bg);
      color: var(--text3);
      cursor: pointer;
      transition: all .12s;
    }
    .tb-toggle-btn:hover { background: var(--hover); color: var(--text); }

    .id-chip {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-family: ui-monospace, "Cascadia Code", Menlo, monospace;
      font-size: .72rem;
      background: var(--user-bubble);
      border: 1px solid var(--border);
      border-radius: 5px;
      padding: 3px 8px;
      color: var(--text3);
      cursor: pointer;
      white-space: nowrap;
      transition: border-color .12s;
    }
    .id-chip:hover { border-color: var(--brand); color: var(--brand); }

    .stat-pill {
      font-size: .75rem;
      color: var(--text4);
      white-space: nowrap;
    }

    .topbar-right {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-shrink: 0;
    }

    .tb-btn {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 4px 9px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--bg);
      color: var(--text3);
      font-size: .76rem;
      cursor: pointer;
      white-space: nowrap;
      transition: all .12s;
    }
    .tb-btn:hover { background: var(--hover); color: var(--text); }
    .tb-btn.on { background: rgba(16, 163, 127, 0.1); color: var(--brand); border-color: var(--brand); }

    .tb-sep { width: 1px; height: 18px; background: var(--border); }

    /* ─── Chat Scroll Area ─────────────────────────────────────────── */
    #chat-scroll {
      flex: 1;
      overflow-y: auto;
      overflow-x: hidden;
      display: flex;
      flex-direction: column;
      align-items: center;
      position: relative;
    }

    /* ─── Draggable Chat Stage & Resizer Handle ─────────────────────── */
    #chat-stage {
      position: relative;
      width: var(--col-w);
      max-width: 95%;
      margin: 0 auto;
      display: flex;
      flex-direction: row;
      align-items: stretch;
      transition: width .05s ease-out;
    }

    #chat-col {
      flex: 1;
      min-width: 0;
      padding: 24px 20px 120px;
    }

    /* Draggable Right Divider for Chat Column (Sticky in viewport) */
    #chat-resizer {
      position: sticky;
      top: 0;
      height: 100vh;
      width: 22px;
      margin-right: -22px;
      cursor: col-resize;
      display: flex;
      align-items: center;
      justify-content: center;
      user-select: none;
      z-index: 40;
    }

    .chat-resizer-pill {
      width: 5px;
      height: 52px;
      border-radius: 4px;
      background: var(--border2);
      transition: all .15s ease;
      opacity: 0.75;
    }

    #chat-resizer:hover .chat-resizer-pill,
    #chat-resizer.dragging .chat-resizer-pill {
      background: var(--brand);
      width: 6px;
      height: 76px;
      opacity: 1;
      box-shadow: 0 0 12px rgba(16, 163, 127, 0.5);
    }

    /* ─── Chat Messages (ChatGPT Style) ────────────────────────────── */
    .turn { margin-bottom: 0; }

    /* User Message: Right-Aligned Floating Bubble */
    .msg-user {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      margin: 28px 0 20px;
    }

    .user-bubble {
      background: var(--user-bubble);
      color: var(--text);
      padding: 10px 16px;
      border-radius: 18px;
      max-width: 82%;
      font-size: var(--base-font);
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
      box-shadow: 0 1px 2px rgba(0,0,0,.04);
    }

    .user-imgs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 8px;
      justify-content: flex-end;
    }

    .user-imgs img {
      max-height: 180px;
      border-radius: 8px;
      border: 1px solid var(--border);
      cursor: zoom-in;
    }

    /* Assistant Message */
    .msg-asst {
      display: flex;
      flex-direction: column;
      margin-bottom: 32px;
      padding-bottom: 28px;
      border-bottom: 1px solid var(--border);
    }

    .asst-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
    }

    .asst-badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      font-size: .8rem;
      font-weight: 600;
      color: var(--brand);
    }

    .asst-dot {
      width: 7px; height: 7px;
      border-radius: 50%;
      background: var(--brand);
      display: inline-block;
    }

    .asst-meta {
      font-size: .72rem;
      color: var(--text4);
    }

    /* Thinking / Tool Trace Pills */
    .trace-wrap {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }

    .trace-pill {
      border: 1px solid var(--border);
      border-radius: 16px;
      background: var(--bg);
      overflow: hidden;
      font-size: .75rem;
    }

    .trace-sum {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      cursor: pointer;
      user-select: none;
      color: var(--text3);
      list-style: none;
      transition: background .12s;
    }
    .trace-sum::-webkit-details-marker, .trace-sum::marker { display: none; }
    .trace-sum:hover { background: var(--hover); color: var(--text); }

    .trace-chevron {
      font-size: .55rem;
      transition: transform .15s ease;
    }
    details[open] .trace-chevron { transform: rotate(90deg); }

    .trace-body {
      padding: 10px 12px;
      background: var(--sidebar-bg);
      border-top: 1px solid var(--border);
      max-height: 240px;
      overflow-y: auto;
      font-family: ui-monospace, "Cascadia Code", Menlo, monospace;
      font-size: .76rem;
      line-height: 1.5;
      color: var(--text3);
      white-space: pre-wrap;
      word-break: break-word;
    }

    /* ─── Markdown Content ─────────────────────────────────────────── */
    .md {
      font-size: var(--base-font);
      line-height: 1.75;
      color: var(--text);
      min-width: 0;
      max-width: 100%;
      overflow-x: hidden;
      word-break: break-word;
    }

    .md > *:first-child { margin-top: 0; }

    .md h1, .md h2, .md h3, .md h4 {
      font-weight: 700;
      letter-spacing: -.02em;
      color: var(--text);
      margin: 1.8em 0 .6em;
      line-height: 1.3;
    }

    .md h1 { font-size: 1.45rem; padding-bottom: .4em; border-bottom: 1px solid var(--border); }
    .md h2 { font-size: 1.22rem; padding-bottom: .3em; border-bottom: 1px solid var(--border); }
    .md h3 { font-size: 1.05rem; }
    .md h4 { font-size: .95rem; color: var(--text2); }

    .md p { margin-bottom: .9em; }
    .md ul, .md ol { margin: .4em 0 .9em 1.5em; }
    .md li { margin-bottom: .3em; }
    .md hr { border: none; border-top: 1px solid var(--border); margin: 1.6em 0; }
    .md strong { font-weight: 600; }

    .md blockquote {
      margin: 1em 0;
      padding: 10px 16px;
      background: var(--user-bubble);
      border-left: 3px solid var(--brand);
      border-radius: 0 6px 6px 0;
      color: var(--text2);
    }
    .md blockquote p:last-child { margin-bottom: 0; }

    /* Tables */
    .table-scroll {
      overflow-x: auto;
      max-width: 100%;
      margin: 1.2em 0;
      border: 1px solid var(--border);
      border-radius: 6px;
    }

    .md table {
      width: 100%;
      border-collapse: collapse;
      font-size: .88rem;
    }

    .md th, .md td {
      padding: 8px 12px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }

    .md th {
      background: var(--user-bubble);
      font-weight: 600;
      font-size: .8rem;
    }

    .md tr:last-child td { border-bottom: none; }

    /* Inline code */
    .md code:not(pre code) {
      background: var(--inline-bg);
      color: var(--inline-fg);
      border: 1px solid var(--inline-border);
      font-family: 'Cascadia Code', 'Fira Code', Consolas, Menlo, monospace;
      font-size: .86em;
      padding: .15em .4em;
      border-radius: 4px;
      word-break: break-word;
    }

    /* ─── Compact Code Frame (Theme Adaptive, Height 26px!) ────────── */
    .code-frame {
      margin: 1.1em 0;
      border-radius: 6px;
      border: 1px solid var(--code-border);
      background: var(--code-bg);
      overflow: hidden;
      box-shadow: var(--code-shadow);
      transition: background .15s ease, border-color .15s ease;
    }

    .code-topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 26px;
      background: var(--code-topbar-bg);
      border-bottom: 1px solid var(--code-border);
      padding: 0 10px;
      user-select: none;
      transition: background .15s ease, border-color .15s ease;
    }

    .code-topbar-left {
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .code-lang-label {
      font-size: 11px;
      font-family: ui-monospace, "Cascadia Code", Menlo, monospace;
      color: var(--code-label);
      text-transform: lowercase;
      letter-spacing: .02em;
      font-weight: 500;
    }

    .code-topbar-right {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .code-lines-badge {
      font-size: 10.5px;
      color: var(--text3);
      font-family: ui-monospace, monospace;
    }

    .copy-btn {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 6px;
      background: transparent;
      border: 1px solid transparent;
      border-radius: 4px;
      color: var(--code-btn-color);
      font-size: 11px;
      cursor: pointer;
      font-family: -apple-system, BlinkMacSystemFont, sans-serif;
      transition: all .12s ease;
    }

    .copy-btn:hover {
      background: var(--code-btn-hover-bg);
      color: var(--code-btn-hover-color);
      border-color: var(--code-border);
    }

    .copy-btn.ok {
      color: var(--brand);
      border-color: var(--brand);
      background: var(--brand-dim, rgba(16, 163, 127, 0.12));
    }

    .code-editor {
      display: flex;
      position: relative;
      background: var(--code-bg);
      color: var(--code-text);
      overflow-x: auto;
      overflow-y: hidden;
      transition: background .15s ease;
    }

    .code-editor::-webkit-scrollbar {
      height: 7px;
      width: 7px;
    }
    .code-editor::-webkit-scrollbar-track {
      background: var(--code-bg);
    }
    .code-editor::-webkit-scrollbar-thumb {
      background: var(--code-scroll-thumb);
      border-radius: 4px;
    }

    .code-gutter {
      display: flex;
      flex-direction: column;
      padding: 10px 8px 10px 12px;
      text-align: right;
      min-width: 38px;
      user-select: none;
      border-right: 1px solid var(--code-gutter-border);
      background: var(--code-bg);
      flex-shrink: 0;
      position: sticky;
      left: 0;
      z-index: 2;
    }

    .code-gutter span {
      display: block;
      font-family: 'Cascadia Code', Consolas, 'Fira Code', Menlo, monospace;
      font-size: 12.5px;
      line-height: 20px;
      height: 20px;
      color: var(--code-gutter-color);
    }

    .code-editor pre {
      margin: 0;
      padding: 10px 14px;
      background: transparent !important;
      overflow-x: visible;
      flex: 1;
      min-width: 0;
    }

    .code-editor pre code {
      display: block;
      font-family: 'Cascadia Code', Consolas, 'Fira Code', Menlo, monospace !important;
      font-size: 12.5px !important;
      line-height: 20px !important;
      white-space: pre !important;
      color: var(--code-text) !important;
      tab-size: 4;
    }

    .code-editor .hljs { background: transparent !important; }

    /* Light Theme Syntax Tokens (GitHub / VS Code Light) */
    [data-theme="light"] .code-editor pre code { color: #24292f !important; }
    [data-theme="light"] .code-editor .hljs-keyword { color: #cf222e !important; font-weight: 600; }
    [data-theme="light"] .code-editor .hljs-function .hljs-title,
    [data-theme="light"] .code-editor .hljs-title.function_ { color: #8250df !important; }
    [data-theme="light"] .code-editor .hljs-string { color: #0a3069 !important; }
    [data-theme="light"] .code-editor .hljs-comment { color: #6e7781 !important; font-style: italic !important; }
    [data-theme="light"] .code-editor .hljs-number { color: #0550ae !important; }
    [data-theme="light"] .code-editor .hljs-built_in,
    [data-theme="light"] .code-editor .hljs-type,
    [data-theme="light"] .code-editor .hljs-title.class_ { color: #953800 !important; }
    [data-theme="light"] .code-editor .hljs-variable,
    [data-theme="light"] .code-editor .hljs-params,
    [data-theme="light"] .code-editor .hljs-attr { color: #1f2328 !important; }

    /* Dark Theme Syntax Tokens (VS Code Dark+) */
    [data-theme="dark"] .code-editor pre code { color: #d4d4d4 !important; }
    [data-theme="dark"] .code-editor .hljs-keyword { color: #569cd6 !important; }
    [data-theme="dark"] .code-editor .hljs-function .hljs-title,
    [data-theme="dark"] .code-editor .hljs-title.function_ { color: #dcdcaa !important; }
    [data-theme="dark"] .code-editor .hljs-string { color: #ce9178 !important; }
    [data-theme="dark"] .code-editor .hljs-comment { color: #6a9955 !important; font-style: italic !important; }
    [data-theme="dark"] .code-editor .hljs-number { color: #b5cea8 !important; }
    [data-theme="dark"] .code-editor .hljs-built_in,
    [data-theme="dark"] .code-editor .hljs-type,
    [data-theme="dark"] .code-editor .hljs-title.class_ { color: #4ec9b0 !important; }
    [data-theme="dark"] .code-editor .hljs-variable,
    [data-theme="dark"] .code-editor .hljs-params,
    [data-theme="dark"] .code-editor .hljs-attr { color: #9cdcfe !important; }

    /* Mermaid container (Constrained so diagrams don't blow up!) */
    .mermaid-wrap {
      margin: 1.2em auto;
      padding: 16px;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow-x: auto;
      text-align: center;
      max-width: 100%;
    }

    .mermaid-wrap svg {
      max-width: min(100%, 750px);
      width: auto !important;
      height: auto;
      margin: 0 auto;
      display: inline-block;
    }

    /* Images */
    .img-wrap {
      margin: 1.2em auto;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      background: var(--bg);
      display: block;
      max-width: min(100%, 750px);
      text-align: center;
      cursor: zoom-in;
    }

    .md img {
      display: block;
      max-width: min(100%, 750px);
      height: auto;
      margin: 0 auto;
    }

    /* KaTeX Math */
    .katex-display {
      overflow-x: auto;
      overflow-y: hidden;
      padding: .4em 0;
      margin: .8em 0 !important;
    }

    /* Lightbox */
    #lb {
      display: none;
      position: fixed; inset: 0;
      background: rgba(0,0,0,.82);
      z-index: 9999;
      place-items: center;
    }
    #lb.open { display: grid; }
    #lb-img {
      max-width: 90vw; max-height: 88vh;
      border-radius: 8px;
      cursor: zoom-out;
      background: #fff;
      padding: 8px;
    }
    #lb-close {
      position: fixed; top: 16px; right: 20px;
      background: rgba(255,255,255,.15);
      border: 1px solid rgba(255,255,255,.25);
      color: #fff; border-radius: 6px;
      padding: 4px 12px; font-size: .82rem;
      cursor: pointer;
    }

    /* Scrollbars */
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--text4); }

    /* Print */
    @media print {
      #sidebar, #sidebar-resizer, #topbar, #chat-resizer { display: none !important; }
      #chat-scroll { overflow: visible !important; height: auto !important; }
      #chat-stage { width: 100% !important; max-width: 100% !important; margin: 0 !important; }
      #chat-col { padding: 0 !important; max-width: 100% !important; }
      body, html { height: auto !important; overflow: visible !important; }
      .trace-body { max-height: none !important; }
      .code-frame { break-inside: avoid; page-break-inside: avoid; }
      .turn { break-inside: avoid; page-break-inside: avoid; }
    }
  </style>
</head>
<body>

<!-- ── Sidebar ────────────────────────────────────────────────────────────── -->
<aside id="sidebar">
  <div class="sb-top">
    <div class="brand-row">
      <div class="brand-icon">AG</div>
      <span class="brand-text">Antigravity Chat</span>
    </div>
    <div class="search-wrap">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
      <input id="search-inp" type="text" placeholder="Search conversation…" autocomplete="off">
    </div>
  </div>
  <div class="sb-label">History</div>
  <ul id="nav-list"></ul>
</aside>

<!-- ── Sidebar Resizer (Drag Divider) ────────────────────────────────────── -->
<div id="sidebar-resizer" title="Drag divider to resize sidebar"></div>

<!-- ── Main ──────────────────────────────────────────────────────────────── -->
<div id="main">
  <header id="topbar">
    <div class="topbar-left">
      <button class="tb-toggle-btn" id="btn-toggle-sidebar" title="Toggle sidebar">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line></svg>
      </button>
      <div class="id-chip" id="id-chip" title="Click to copy ID">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        <span id="id-text">__CONV_ID__</span>
      </div>
      <span class="stat-pill" id="stat-pill">Loading…</span>
    </div>
    <div class="topbar-right">
      <button class="tb-btn" id="btn-think">🧠 Thinking</button>
      <button class="tb-btn" id="btn-tools">⚙️ Tools</button>
      <div class="tb-sep"></div>
      <button class="tb-btn" id="btn-theme">🌓 Theme</button>
      <button class="tb-btn" onclick="window.print()">🖨️ Print</button>
    </div>
  </header>

  <div id="chat-scroll">
    <div id="chat-stage">
      <div id="chat-col"></div>
      <!-- Draggable Chat Width Divider -->
      <div id="chat-resizer" title="Drag divider to resize chat width">
        <div class="chat-resizer-pill"></div>
      </div>
    </div>
  </div>
</div>

<!-- ── Lightbox ────────────────────────────────────────────────────────────── -->
<div id="lb">
  <button id="lb-close" onclick="closeLb()">✕ Close</button>
  <img id="lb-img" src="" alt="">
</div>

<!-- Data -->
<script id="chat-data" type="application/json">
__CONVERSATION_DATA_JSON__
</script>

<script>
/* ── Setup ─────────────────────────────────────────────────────────────── */
const data = JSON.parse(document.getElementById('chat-data').textContent);

// Mermaid init
mermaid.initialize({ startOnLoad: false, theme: 'neutral', securityLevel: 'loose' });

let showThink = false;
let showTools = false;

const chatCol    = document.getElementById('chat-col');
const navList    = document.getElementById('nav-list');
const searchInp  = document.getElementById('search-inp');
const statPill   = document.getElementById('stat-pill');
const btnThink   = document.getElementById('btn-think');
const btnTools   = document.getElementById('btn-tools');
const btnTheme   = document.getElementById('btn-theme');
const sidebar    = document.getElementById('sidebar');

/* ── Stats ─────────────────────────────────────────────────────────────── */
const totalOut = data.reduce((s,t) => s + (t.total_output_tokens||0), 0);
statPill.textContent = `${data.length} turns · ${(totalOut/1000).toFixed(1)}k tokens`;

/* ── Copy ID ──────────────────────────────────────────────────────────── */
document.getElementById('id-chip').onclick = () => {
  navigator.clipboard.writeText('__CONV_ID__');
  const el = document.getElementById('id-text');
  const was = el.textContent;
  el.textContent = 'Copied!';
  setTimeout(() => el.textContent = was, 1500);
};

/* ── Sidebar Toggle ────────────────────────────────────────────────────── */
document.getElementById('btn-toggle-sidebar').onclick = () => {
  sidebar.style.display = sidebar.style.display === 'none' ? 'flex' : 'none';
};

/* ── Resizer 1: Draggable Sidebar Divider ───────────────────────────────── */
const sbResizer = document.getElementById('sidebar-resizer');
let sbDragging = false;

sbResizer.addEventListener('mousedown', e => {
  sbDragging = true;
  sbResizer.classList.add('dragging');
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
});

/* ── Resizer 2: Draggable Chat Width Divider ────────────────────────────── */
const chatResizer = document.getElementById('chat-resizer');
let chatDragging = false;
let chatStartX = 0;
let chatStartW = 0;

chatResizer.addEventListener('mousedown', e => {
  chatDragging = true;
  chatStartX = e.clientX;
  chatStartW = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--col-w')) || 780;
  chatResizer.classList.add('dragging');
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
});

window.addEventListener('mousemove', e => {
  if (sbDragging) {
    const newW = Math.max(180, Math.min(500, e.clientX));
    document.documentElement.style.setProperty('--sidebar-w', newW + 'px');
    localStorage.setItem('ag_sidebar_w', newW);
  }
  if (chatDragging) {
    const dx = e.clientX - chatStartX;
    const newW = Math.max(540, Math.min(1400, chatStartW + dx * 2));
    document.documentElement.style.setProperty('--col-w', newW + 'px');
    localStorage.setItem('ag_col_w', newW);
  }
});

window.addEventListener('mouseup', () => {
  if (sbDragging) {
    sbDragging = false;
    sbResizer.classList.remove('dragging');
  }
  if (chatDragging) {
    chatDragging = false;
    chatResizer.classList.remove('dragging');
  }
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
});

// Restore persisted widths
const savedSbW = localStorage.getItem('ag_sidebar_w');
if (savedSbW) document.documentElement.style.setProperty('--sidebar-w', savedSbW + 'px');
const savedColW = localStorage.getItem('ag_col_w');
if (savedColW) document.documentElement.style.setProperty('--col-w', savedColW + 'px');

/* ── Lightbox ──────────────────────────────────────────────────────────── */
function openLb(src) {
  document.getElementById('lb-img').src = src;
  document.getElementById('lb').classList.add('open');
}
function closeLb() { document.getElementById('lb').classList.remove('open'); }
document.getElementById('lb').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeLb();
});

/* ── Helpers ───────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s||'')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}

function fmtTime(iso) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}); }
  catch { return ''; }
}

/* ── Math ──────────────────────────────────────────────────────────────── */
function doMath(el) {
  if (window.renderMathInElement) {
    renderMathInElement(el, {
      delimiters: [
        {left:'$$',right:'$$',display:true},
        {left:'\\[',right:'\\]',display:true},
        {left:'$',right:'$',display:false},
        {left:'\\(',right:'\\)',display:false},
      ],
      throwOnError: false
    });
  }
}

/* ── Code enhancement + Mermaid ──────────────────────────────────────── */
async function doCode(container) {
  const mermaidBlocks = [];

  container.querySelectorAll('pre code').forEach(block => {
    const cls = [...block.classList].find(c => c.startsWith('language-'));
    let lang = cls ? cls.replace('language-','').toLowerCase() : '';

    /* Mermaid: pull the text, mark for async render */
    if (lang === 'mermaid') {
      const code = block.textContent;
      const wrap = document.createElement('div');
      wrap.className = 'mermaid-wrap';
      const inner = document.createElement('div');
      inner.className = 'mermaid';
      inner.textContent = code;
      wrap.appendChild(inner);
      const pre = block.parentElement;
      pre.replaceWith(wrap);
      mermaidBlocks.push(inner);
      return;
    }

    const pre = block.parentElement;
    if (pre.parentElement && pre.parentElement.classList.contains('code-editor')) return;

    const rawText = block.textContent;
    const cleanText = rawText.replace(/\r\n/g, '\n').replace(/\n$/, '');
    const lines = cleanText.split('\n');
    const lineCount = lines.length;

    /* Syntax highlight any language with fallback */
    const isPlain = !lang || ['text', 'txt', 'plaintext', 'ascii', 'none'].includes(lang);
    if (!isPlain) {
      try { hljs.highlightElement(block); } catch {}
    } else {
      block.classList.add('hljs');
    }

    const frame = document.createElement('div');
    frame.className = 'code-frame';

    const topbar = document.createElement('div');
    topbar.className = 'code-topbar';

    const topbarLeft = document.createElement('div');
    topbarLeft.className = 'code-topbar-left';
    const langDisplay = isPlain ? 'text' : lang;
    topbarLeft.innerHTML = `<span class="code-lang-label">${esc(langDisplay)}</span>`;

    const topbarRight = document.createElement('div');
    topbarRight.className = 'code-topbar-right';

    if (lineCount > 1) {
      const linesBadge = document.createElement('span');
      linesBadge.className = 'code-lines-badge';
      linesBadge.textContent = `${lineCount} lines`;
      topbarRight.appendChild(linesBadge);
    }

    const copyBtn = document.createElement('button');
    copyBtn.className = 'copy-btn';
    copyBtn.innerHTML = `
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="9" y="9" width="13" height="13" rx="2"></rect>
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
      </svg>
      <span>Copy code</span>
    `;
    copyBtn.onclick = function() {
      navigator.clipboard.writeText(rawText);
      copyBtn.classList.add('ok');
      copyBtn.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
        <span>Copied!</span>
      `;
      setTimeout(() => {
        copyBtn.classList.remove('ok');
        copyBtn.innerHTML = `
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="9" y="9" width="13" height="13" rx="2"></rect>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
          </svg>
          <span>Copy code</span>
        `;
      }, 2000);
    };
    topbarRight.appendChild(copyBtn);

    topbar.appendChild(topbarLeft);
    topbar.appendChild(topbarRight);

    const editor = document.createElement('div');
    editor.className = 'code-editor';

    if (lineCount > 1) {
      const gutter = document.createElement('div');
      gutter.className = 'code-gutter';
      gutter.setAttribute('aria-hidden', 'true');
      gutter.innerHTML = lines.map((_, i) => `<span>${i + 1}</span>`).join('');
      editor.appendChild(gutter);
    }

    pre.parentNode.insertBefore(frame, pre);
    frame.appendChild(topbar);
    editor.appendChild(pre);
    frame.appendChild(editor);
  });

  /* Render mermaid blocks async */
  if (mermaidBlocks.length) {
    try {
      await mermaid.run({ nodes: mermaidBlocks });
    } catch(e) {
      mermaidBlocks.forEach(el => {
        el.innerHTML = `<pre style="color:red;font-size:.8rem">Mermaid error: ${esc(e.message||String(e))}</pre>`;
      });
    }
  }
}

/* ── Table wrap ────────────────────────────────────────────────────────── */
function doTables(container) {
  container.querySelectorAll('table').forEach(tbl => {
    if (tbl.parentElement.classList.contains('table-scroll')) return;
    const wrap = document.createElement('div');
    wrap.className = 'table-scroll';
    tbl.parentNode.insertBefore(wrap, tbl);
    wrap.appendChild(tbl);
  });
}

/* ── Image click ───────────────────────────────────────────────────────── */
function doImages(container) {
  container.querySelectorAll('img').forEach(img => {
    img.loading = 'lazy';
    img.style.cursor = 'zoom-in';
    img.onclick = () => openLb(img.src);
    img.style.maxWidth = 'min(100%, 750px)';
    img.style.height = 'auto';
  });
}

/* ── Full markdown render ─────────────────────────────────────────────── */
async function renderMd(text, container) {
  container.innerHTML = marked.parse(text || '', {breaks: true, gfm: true});
  doMath(container);
  await doCode(container);
  doTables(container);
  doImages(container);
}

/* ── Build one turn ────────────────────────────────────────────────────── */
function buildTurn(turn) {
  const wrapper = document.createElement('div');
  wrapper.className = 'turn';
  wrapper.id = `turn-${turn.turn_index}`;

  /* User Message (Right-aligned bubble) */
  const uRow = document.createElement('div');
  uRow.className = 'msg-user';

  const uBubble = document.createElement('div');
  uBubble.className = 'user-bubble';
  uBubble.textContent = turn.user_prompt;
  uRow.appendChild(uBubble);

  if (turn.user_media && turn.user_media.length) {
    const imgRow = document.createElement('div');
    imgRow.className = 'user-imgs';
    turn.user_media.forEach(m => {
      const img = document.createElement('img');
      img.src = m.url; img.alt = m.name;
      img.onclick = () => openLb(m.url);
      imgRow.appendChild(img);
    });
    uRow.appendChild(imgRow);
  }

  /* Assistant Message */
  const aRow = document.createElement('div');
  aRow.className = 'msg-asst';

  const aHeader = document.createElement('div');
  aHeader.className = 'asst-header';
  aHeader.innerHTML = `
    <span class="asst-badge"><span class="asst-dot"></span>Antigravity</span>
    ${turn.total_output_tokens ? `<span class="asst-meta">· ${turn.total_output_tokens.toLocaleString()} tokens</span>` : ''}
  `;
  aRow.appendChild(aHeader);

  /* Thinking & Tools in trace row */
  if ((turn.thinking_blocks && turn.thinking_blocks.length) || (turn.tool_calls && turn.tool_calls.length)) {
    const traceRow = document.createElement('div');
    traceRow.className = 'trace-wrap';

    if (turn.thinking_blocks && turn.thinking_blocks.length) {
      const det = document.createElement('details');
      det.className = 'trace-pill thinking-det';
      det.open = showThink;
      const joined = turn.thinking_blocks.join('\n\n───\n\n');
      det.innerHTML = `
        <summary class="trace-sum">
          <span class="trace-chevron">▶</span>
          <span>🧠 Thought (${turn.thinking_blocks.length})</span>
        </summary>
        <div class="trace-body">${esc(joined)}</div>
      `;
      traceRow.appendChild(det);
    }

    if (turn.tool_calls && turn.tool_calls.length) {
      const det = document.createElement('details');
      det.className = 'trace-pill tools-det';
      det.open = showTools;
      const body = turn.tool_calls.map((tc,i) =>
        `[${i+1}] ${tc.name}\nAction: ${tc.action}\nSummary: ${tc.summary}`
      ).join('\n\n');
      det.innerHTML = `
        <summary class="trace-sum">
          <span class="trace-chevron">▶</span>
          <span>⚙️ ${turn.tool_calls.length} Tools</span>
        </summary>
        <div class="trace-body">${esc(body)}</div>
      `;
      traceRow.appendChild(det);
    }

    aRow.appendChild(traceRow);
  }

  /* Markdown body */
  const mdDiv = document.createElement('div');
  mdDiv.className = 'md';
  aRow.appendChild(mdDiv);

  wrapper.appendChild(uRow);
  wrapper.appendChild(aRow);

  /* Render md async */
  setTimeout(() => {
    if (turn.assistant_response && turn.assistant_response.trim()) {
      renderMd(turn.assistant_response, mdDiv);
    } else {
      mdDiv.innerHTML = '<p style="color:var(--text4);font-style:italic;font-size:.9rem;">(Actions performed; continued in subsequent turn)</p>';
    }
  }, 0);

  return wrapper;
}

/* ── Render all ────────────────────────────────────────────────────────── */
function renderAll(query = '') {
  chatCol.innerHTML = '';
  navList.innerHTML = '';
  const q = query.toLowerCase();
  let count = 0;

  data.forEach(turn => {
    if (q && !turn.user_prompt.toLowerCase().includes(q)
           && !turn.assistant_response.toLowerCase().includes(q)) return;
    count++;

    /* Nav */
    const li = document.createElement('li');
    li.className = 'nav-item';
    li.id = `nav-${turn.turn_index}`;
    li.innerHTML = `
      <span class="nav-num">${turn.turn_index}</span>
      <span class="nav-text">${esc(turn.user_prompt.trim().slice(0,72))}</span>
    `;
    li.onclick = () => {
      document.querySelectorAll('.nav-item').forEach(e => e.classList.remove('active'));
      li.classList.add('active');
      document.getElementById(`turn-${turn.turn_index}`)
        ?.scrollIntoView({behavior:'smooth', block:'start'});
    };
    navList.appendChild(li);

    chatCol.appendChild(buildTurn(turn));
  });

  if (!count) {
    chatCol.innerHTML = `<div style="text-align:center;padding:60px;color:var(--text3);">No turns match "<b>${esc(query)}</b>"</div>`;
  }
}

/* ── Search ────────────────────────────────────────────────────────────── */
let st;
searchInp.addEventListener('input', () => {
  clearTimeout(st);
  st = setTimeout(() => renderAll(searchInp.value.trim()), 200);
});

/* ── Toggle thinking ──────────────────────────────────────────────────── */
btnThink.addEventListener('click', () => {
  showThink = !showThink;
  btnThink.classList.toggle('on', showThink);
  document.querySelectorAll('details.thinking-det').forEach(d => d.open = showThink);
});

/* ── Toggle tools ─────────────────────────────────────────────────────── */
btnTools.addEventListener('click', () => {
  showTools = !showTools;
  btnTools.classList.toggle('on', showTools);
  document.querySelectorAll('details.tools-det').forEach(d => d.open = showTools);
});

/* ── Theme ─────────────────────────────────────────────────────────────── */
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  btnTheme.textContent = t === 'dark' ? '☀️ Light' : '🌙 Dark';
  const hljsLink = document.getElementById('hljs-theme');
  if (hljsLink) {
    hljsLink.href = t === 'dark' 
      ? 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/vs2015.min.css'
      : 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css';
  }
  mermaid.initialize({
    startOnLoad: false,
    theme: t === 'dark' ? 'dark' : 'neutral',
    securityLevel: 'loose'
  });
  localStorage.setItem('ag_theme', t);
}

btnTheme.addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme') || 'light';
  applyTheme(cur === 'light' ? 'dark' : 'light');
});

/* ── Init ──────────────────────────────────────────────────────────────── */
applyTheme(localStorage.getItem('ag_theme') || 'light');
renderAll();
</script>
</body>
</html>
"""

def export_conversation(conv_id=None, output_dir=None):
    conv_dir = find_conversation_dir(conv_id)
    actual_conv_id = os.path.basename(conv_dir)
    print(f"[*] Processing conversation: {actual_conv_id}")

    if not output_dir:
        home = os.path.expanduser("~")
        scratch_dir = os.path.join(home, ".gemini", "antigravity", "scratch")
        if os.path.exists(scratch_dir):
            output_dir = os.path.join(scratch_dir, f"antigravity_chat_export_{actual_conv_id[:8]}")
        else:
            output_dir = os.path.join(os.getcwd(), f"antigravity_chat_export_{actual_conv_id[:8]}")

    assets_dir = os.path.join(output_dir, "assets")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(assets_dir, exist_ok=True)

    print("[*] Parsing transcript...")
    steps = parse_transcript(conv_dir)
    print(f"[*] Found {len(steps)} total trajectory steps.")

    print("[*] Grouping into turns and extracting assets...")
    turns, copied_assets = process_conversation(steps, assets_dir)
    print(f"[*] Processed {len(turns)} turns. Copied {len(copied_assets)} media/diagram assets.")

    print("[*] Generating standalone HTML...")
    data_json = json.dumps(turns, ensure_ascii=False).replace("<", "\\u003c")
    html_content = HTML_PAGE_TEMPLATE.replace("__CONV_ID__", actual_conv_id).replace("__CONVERSATION_DATA_JSON__", data_json)

    index_html_path = os.path.join(output_dir, "index.html")
    with open(index_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[+] SUCCESS! Conversation exported to:")
    print(f"    {index_html_path}")
    return index_html_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export an Antigravity conversation transcript to a standalone HTML web page.")
    parser.add_argument("conv_id", nargs="?", default=None, help="Conversation ID, prefix, or directory path (defaults to latest active conversation)")
    parser.add_argument("-o", "--output", help="Output directory path (defaults to scratch/antigravity_chat_export_<id>)")
    args = parser.parse_args()
    export_conversation(args.conv_id, args.output)

