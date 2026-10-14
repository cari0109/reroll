"use strict";
// Browser backend for the static demo (GitHub Pages). It runs the real reroll Python package in
// Pyodide and answers the same routes as `life serve`, so app.js does not know the difference.
// Each visitor's life.json lives in their own browser (localStorage). The narrator is the
// offline one: no API key ever ships with the page.

(() => {
  const STORE = "reroll-demo-life";
  const BOOT_PY = `
import json
from datetime import date
from pathlib import Path

from reroll import ops
from reroll.narrator import MockNarrator
from reroll.observatory import Observatory, ObservatoryError
from reroll.params import default_params
from reroll.storage import RepoError, load_repo, save_repo

PATH = Path("/home/pyodide/life.json")

def boot(saved, lang):
    global OBS
    if saved:
        PATH.write_text(saved)
        try:
            load_repo(PATH)
        except RepoError:
            PATH.unlink()  # unreadable save: start a fresh life rather than a broken page
    if not PATH.exists():
        save_repo(ops.new_repo("my-life", default_params(), date.today(), lang), PATH)
    OBS = Observatory(PATH, narrator=MockNarrator())

def call(method, route, payload):
    try:
        return json.dumps(OBS.dispatch(method, route, json.loads(payload) if payload else None))
    except ObservatoryError as e:
        return json.dumps({"__error__": e.status, "detail": e.detail})

def saved():
    return PATH.read_text()
`;

  const status = (text) => { const el = document.getElementById("loading"); if (el) el.textContent = text; };
  const zh = () => (navigator.language || "").toLowerCase().startsWith("zh");
  const store = {
    get() { try { return localStorage.getItem(STORE); } catch (e) { return null; } },
    set(v) { try { localStorage.setItem(STORE, v); } catch (e) { /* private mode: the life lasts this tab */ } },
    clear() { try { localStorage.removeItem(STORE); } catch (e) {} },
  };

  let py = null;
  const ready = (async () => {
    status(zh() ? "正在加载多重宇宙…（首次访问需要下载约 10 MB）" : "Loading the multiverse… (the first visit downloads about 10 MB)");
    py = await loadPyodide();
    await py.loadPackage(["pydantic", "pyyaml", "micropip"]);
    const micropip = py.pyimport("micropip");
    await micropip.install(new URL(window.REROLL_WHEEL, location.href).href, { deps: false });
    py.runPython(BOOT_PY);
    const wanted = new URLSearchParams(location.search).get("lang");
    py.globals.get("boot")(store.get(), wanted === "zh" || wanted === "en" ? wanted : zh() ? "zh" : "en");
  })();

  window.rerollDemo = {
    /** Start over in the given language. */
    reset(lang) {
      store.clear();
      const url = new URL(location.href);
      url.searchParams.set("lang", lang);
      location.replace(url);
    },
  };

  window.rerollApi = async (path, body) => {
    await ready;
    const method = body ? "POST" : "GET";
    const res = JSON.parse(py.globals.get("call")(method, path, body ? JSON.stringify(body) : null));
    if (res.__error__) throw new Error(res.detail);
    if (method === "POST") store.set(py.globals.get("saved")());
    return res;
  };
})();
