# iron

A desktop agent harness for small local LLMs (Ollama). Fast, parallel, glass.

## Run

```bash
cd D:\iron
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
python run.py
```

Or double-click `iron.cmd` for the desktop window.

```bash
python run.py          # desktop app
python run.py --web    # browser
python run.py --dev    # vite + reload
```

## Requirements

- Python 3.11+
- Node 20+
- [Ollama](https://ollama.com) running locally

## Config

Settings live in the UI and `~/.iron/config.json`. Default workspace is `D:\iron\workspace`.
