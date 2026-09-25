# The Real-Life ATM — browser build

`static/play/atm/` is the ATM game from
[Python_for_IT_Automation/Bank_ATM/The_Real_Life_ATM](https://github.com/spencerawlson/Python_for_IT_Automation/tree/master/Bank_ATM/The_Real_Life_ATM)
compiled to WebAssembly with [pygbag](https://pygame-web.github.io/). The game source is
unchanged; `main.py` here is the only addition — it drives `ATMGame` from an async loop,
which the browser needs.

Rebuild (pygbag 0.9.3 was used):

```bash
mkdir -p /tmp/atm && cd /tmp/atm
cp <ATM repo>/{account,atm_service,atm_game,bank,customer}.py .
cp -r <ATM repo>/{banks,transactions} .
cp <this folder>/main.py .
python -m pip install pygame-ce pygbag
cd .. && python -m pygbag --build --title "The Real-Life ATM" atm
cp atm/build/web/{index.html,atm.apk,atm.tar.gz,favicon.png} <hub>/static/play/atm/
```

Ship **both** `atm.apk` and `atm.tar.gz` — the loader fetches the archive and 404s without it.
The Python runtime itself loads from pygbag's CDN (pygame-web.github.io) at play time.
