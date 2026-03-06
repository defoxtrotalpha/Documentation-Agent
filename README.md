# Documentation Agent

Automated documentation generator for backend and frontend codebases.

---

## Quick Start

1. **Copy the agent folder**
   - Place the entire `documentation_agent` folder inside your project’s backend directory (or wherever you want to document).

2. **Install dependencies**
   - Create a virtual environment (recommended):
     ```sh
     python -m venv .venv
     .venv\Scripts\activate  # Windows
     # or
     source .venv/bin/activate  # Linux/macOS
     ```
   - Install required packages:
     ```sh
     pip install -r requirements-docs.txt
     ```

3. **Configure LLM provider**
   - Copy `.env.example` to `.env` and fill in your API keys for one provider (Azure OpenAI, Foundry, OpenAI, Claude, or Gemini):
     ```sh
     cp .env.example .env  # or use Copy-Item on Windows
     ```
   - Edit `.env` and set only one provider block.

4. **Set up the commit hook (auto-run on commit)**
   - From the root of your repo, run:
     ```sh
     cp documentation_agent/hooks/pre-commit.sample .git/hooks/pre-commit
     chmod +x .git/hooks/pre-commit  # Linux/macOS only
     ```
   - This hook will run the documentation agent before every commit, updating docs only for changed files.

5. **Manual full scan (regenerate all docs)**
   - From the repo root:
     ```sh
     python documentation_agent/doc_orchestrator.py --repo-root . --full-scan
     ```
   - This will regenerate all backend and frontend documentation.

---

## How it works
- On every commit (with the hook), only changed files are scanned and their docs updated.
- On a full scan, all docs are regenerated regardless of changes.
- Docs are written as `documentation.md` files alongside source code, with `_doc_metadata.json` for change tracking.

---

## Requirements
- Python 3.10+
- API key for your chosen LLM provider (see `.env.example`)

---

## FAQ

**Q: Where do I copy the agent?**
- Place the `documentation_agent` folder inside your backend or project root.

**Q: What if I want to run it manually?**
- Use the full scan command above, or run `doc_orchestrator.py` with `--from-ref`/`--to-ref` for incremental scans.

**Q: How do I change providers?**
- Edit `.env` and set only one provider block at a time.

**Q: What if I don’t want the hook?**
- You can run the agent manually as needed.

---

## Contributing
- Fork, branch, and submit PRs as usual.
- The agent is self-contained and can be copied into any compatible Python project.
