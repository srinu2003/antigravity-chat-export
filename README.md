# Antigravity Chat Exporter

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8%2B-brightgreen.svg)]()
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero%20(Standard%20Library)-success.svg)]()

> A standalone Python utility and official agent skill to export **Google Antigravity** conversations into a standalone, portable, offline-ready web page.

---

## ✨ Features

- 🌓 **Dual Themes with Theme-Matching Code Blocks:**
  - **Light Mode:** Crisp white palette with GitHub-style light code frames and syntax tokens.
  - **Dark Mode:** Modern dark interface with VS Code Dark+ code frames and syntax tokens.
- 📐 **Direct Draggable Dividers:**
  - Drag the sidebar resizer (`180px` – `500px`) to adjust navigation width.
  - Drag the sticky chat column resizer (`540px` – `1400px`) to adjust your reading width.
  - Preferences persist automatically in `localStorage`.
- 💻 **Compact 26px Code Block Header:**
  - Minimalist header with lowercase language badges (`python`, `latex`, `bash`, `javascript`, etc.).
  - Gutter line numbering with proper tab alignment.
  - One-click copy code button with visual confirmation.
- 🧮 **First-Class Mathematics & Vector Diagrams:**
  - KaTeX rendering for inline and block display LaTeX formulas.
  - Mermaid diagram rendering with container constraints to prevent font blow-up.
- 🧠 **Collapsible Reasoning & Tool Traces:**
  - Thinking processes (`🧠 Thought (11)`) and tool traces (`⚙️ 37 Tools`) collapsed into compact, low-profile pills.
- 💬 **Human-Focused Dialogue:**
  - Automatically cleans internal system harness wrappers (`<USER_REQUEST>`, `<ADDITIONAL_METADATA>`, etc.).
  - Separates raw terminal output, directory listings, and compiler logs into expandable tool traces.
- 📦 **100% Portable & Self-Contained:**
  - Bundles all generated images, diagrams, and uploads into an `./assets/` directory with relative links.
  - Requires **zero external Python packages** (uses standard library: `os`, `sys`, `json`, `re`, `shutil`, `argparse`, `urllib`).

---

## 🚀 Quick Start

### 1. Export Current / Latest Conversation
```bash
python scripts/export_chat.py
```
*Automatically finds and exports the latest active conversation from your Antigravity brain.*

### 2. Export by Conversation ID or Prefix
```bash
python scripts/export_chat.py 3c0c7b56
```

### 3. Custom Output Directory
```bash
python scripts/export_chat.py 3c0c7b56 -o ./my_exported_conversation
```

---

## 🛠️ CLI Options

```text
usage: export_chat.py [-h] [-o OUTPUT] [conv_id]

Export an Antigravity conversation transcript to a standalone HTML web page.

positional arguments:
  conv_id               Conversation ID, prefix, or directory path
                        (defaults to latest active conversation)

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output directory path
```

---

## 📂 Installation as an Antigravity Skill

To make this skill permanently available to your Antigravity agent in any chat:

### Global Installation
Clone or copy this directory into your Antigravity skills configuration:
```bash
git clone https://github.com/srinu2003/antigravity-chat-export.git ~/.gemini/config/skills/antigravity-chat-export
```

Once installed, simply ask Antigravity in any session:
> *"Export our conversation to a web page."*

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
