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

## Security

The API binds to `127.0.0.1` by default and generates a random per-launch token.
All mutating endpoints and the websocket require it; the UI fetches it from
`/api/bootstrap` automatically. CORS is disabled for cross-origin requests, so
other websites cannot drive the local agent. The token is printed to the server
console if you need it for scripting.
