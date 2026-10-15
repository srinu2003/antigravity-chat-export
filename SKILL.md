---
name: antigravity-chat-export
description: >-
  Export any Google Antigravity conversation transcript to a standalone, offline-ready
  interactive web page. Features dual themes (light/dark), draggable width dividers,
  theme-matching VS Code/GitHub code blocks, KaTeX math equations, Mermaid diagrams, and instant search.
---

# Antigravity Chat Exporter

Exports an Antigravity conversation trajectory into a standalone, portable, single-page web application.

## Overview

Antigravity stores conversation trajectories as JSONL logs in its brain directory (`~/.gemini/antigravity/brain/<conv_id>/.system_generated/logs/`). This skill parses those logs and produces an offline-ready HTML viewer replicating modern conversational interfaces (ChatGPT / Antigravity / VS Code).

### Key Features
- **Theme-Adaptive Code Blocks:** 26px compact headers, gutter line numbers, and syntax highlighting matching the active theme (GitHub Light in light mode, VS Code Dark+ in dark mode).
- **Draggable Column Dividers:** Direct mouse-drag handles to adjust sidebar width (180px–500px) and reading column width (540px–1400px), with `localStorage` persistence.
- **Clean Dialogue:** Automatically strips internal harness XML tags (`<USER_REQUEST>`, `<ADDITIONAL_METADATA>`, etc.) from prompts and titles.
- **Mathematics & Vector Graphics:** Renders KaTeX math formulas and Mermaid diagrams in-line without scaling distortion.
- **Collapsible Reasoning:** Keeps reasoning thoughts and tool execution logs packed inside compact pills (`🧠 Thought`, `⚙️ Tools`).
- **Self-Contained Offline Export:** Bundles local images, diagrams, and assets into an `./assets/` directory with relative links.

---

## Quick Start

### Export the Current / Latest Conversation
```bash
python scripts/export_chat.py
```
*Auto-detects the most recently active Antigravity conversation.*

### Export a Specific Conversation
```bash
python scripts/export_chat.py <conversation_id_or_prefix>
```
Example:
```bash
python scripts/export_chat.py 3c0c7b56
```

### Specify a Custom Output Directory
```bash
python scripts/export_chat.py 3c0c7b56 -o ./my_exported_chat
```

---

## Command-Line Arguments

| Argument | Description | Default |
| :--- | :--- | :--- |
| `conv_id` | Conversation UUID, prefix, or direct directory path | Latest active conversation |
| `-o, --output` | Destination directory for HTML and assets | `~/.gemini/antigravity/scratch/antigravity_chat_export_<id>` |

---

## When to Use This Skill
Use this skill when:
- The user asks to "export our chat", "save this conversation", or "convert this chat into a web page".
- A shareable or archival HTML document of an Antigravity coding or research session is required.
- Printing or compiling conversation history to a clean PDF is needed.
