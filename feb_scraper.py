"""
Extractor setmanal de les competicions femenines de la FEB.
 
Llegeix, per a cada partit d'una jornada:
  - l'acta (línia de cada jugadora, totals, parcials, data),
  - el play-by-play (pestanya "Directo"),
  - el gràfic de tir (pestanya "Gráfico de tiro"),
valida les dades i les desa en JSON a data/<temporada>/<competicio>/J<nn>/<id>.json,
més un informe de la jornada (_jornada.json).
 
Ús:
  python feb_scraper.py --comp lf2a --season 2026 --jornada last
  python feb_scraper.py --comp challenge --season 2025 --jornada 29
  python feb_scraper.py --test            (prova amb una jornada coneguda de 2025-26)
"""
import argparse, json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
 
BASE = "https://www.feb.es"
 
# Competicions: codi FEB (g), text que ha de contenir la fase al desplegable
COMPS = {
    "lf":        {"g": 4,  "slug": "lf",          "fase": "Liga Regular"},
    "challenge": {"g": 67, "slug": "lfchallenge", "fase": "Liga Regular"},
    "lf2a":      {"g": 9,  "slug": "lf2",         "fase": 'Liga Regular "A"'},
    "lf2b":      {"g": 9,  "slug": "lf2",         "fase": 'Liga Regular "B"'},
}
 
# ---------------------------------------------------------------- utilitats
def norm_team(t):
    return re.sub(r"\s+", " ", t or "").strip().upper()
 
def norm_name(n):
    n = re.sub(r"\s+", " ", n or "").strip()
    if "," in n:
        s, f = n.split(",", 1)
        f = f.strip()
        return (f[0].upper() + ". " if f else "") + s.strip().upper()
    return n.upper()
 
def split_made_att(v):
    v = (v or "").split(" ")[0]
    if "/" in v:
        a, b = v.split("/")
        return int(a or 0), int(b or 0)
    return None
 
def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)
 
 
def select_and_wait(page, handle, value):
    """Canvia un desplegable i espera la recàrrega (postback d'ASP.NET) o, si no n'hi ha, que la xarxa es calmi."""
    try:
        with page.expect_navigation(wait_until="load", timeout=20000):
            handle.select_option(value)
    except PWTimeout:
        page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_selector("select", timeout=30000)
 
# ---------------------------------------------------------------- llistat de partits
def list_games(page, comp, season, jornada):
    c = COMPS[comp]
    url = f"{BASE}/competiciones/resultados/{c['slug']}/{c['g']}/{season}"
    page.goto(url, wait_until="load")
    page.wait_for_selector("select", timeout=30000)
 
    def selects():
        return page.query_selector_all("select")
 
    def choose(idx, predicate, label):
        sel = selects()[idx]
        opts = sel.evaluate("s=>[...s.options].map(o=>[o.value,o.text,o.selected])")
        target = next((o for o in opts if predicate(o[1])), None)
        if not target:
            raise RuntimeError(f"No trobo l'opció de {label}. Opcions: {[o[1] for o in opts]}")
        if target[2]:
            return target
        select_and_wait(page, sel, target[0])
        return target
 
    # 1) fase (lliga regular / grup)
    fase = choose(1, lambda t: c["fase"].lower() in t.lower(), "fase")
    # 2) jornada
    jsel = selects()[2]
    jopts = jsel.evaluate("s=>[...s.options].map(o=>[o.value,o.text,o.selected])")
    if jornada == "last":
        # la jornada que la web mostra per defecte és l'actual; si encara no s'ha jugat, l'anterior
        cur = next(o for o in jopts if o[2])
        jn = int(re.search(r"Jornada\s+(\d+)", cur[1]).group(1))
    else:
        jn = int(jornada)
    target = next((o for o in jopts if re.search(rf"Jornada\s+{jn}\b", o[1])), None)
    if not target:
        raise RuntimeError(f"No existeix la jornada {jn}")
    if not target[2]:
        select_and_wait(page, jsel, target[0])
    ids = page.evaluate("""()=>[...new Set([...document.querySelectorAll('a[href*="Partido.aspx"]')]
        .map(a=>+new URL(a.href).searchParams.get('p')))]""")
    date_txt = re.search(r"\((.*?)\)", target[1])
    return {"fase": fase[1], "jornada": jn, "jornada_text": target[1],
            "data": date_txt.group(1) if date_txt else None, "ids": sorted(ids)}
 
# ---------------------------------------------------------------- extracció d'un partit
JS_BOX = r"""()=>{
 const tbs=[...document.querySelectorAll('table')].slice(0,2);
 const teams=[...document.querySelectorAll('h1,h2,h3,h4')].map(h=>h.innerText.trim())
   .filter(x=>x&&!/loading|cookies|Personalizar|preferencias/i.test(x)).slice(0,2);
 const lab=[...document.querySelectorAll('.label')].find(e=>/Fecha/.test(e.textContent));
 const fecha=lab?lab.parentElement.textContent.replace(/\s+/g,' ').replace('Fecha','').trim():'';
 const q=[...document.querySelectorAll('span.cuarto')].map(e=>e.nextElementSibling?.textContent.trim()).filter(Boolean);
 const players=[];
 tbs.forEach((t,ti)=>[...t.querySelectorAll('tr')].forEach(tr=>{
   const c=[...tr.querySelectorAll('td')].map(x=>x.innerText.trim());
   if(c.length<22) return;                 // capçaleres i files incompletes
   if(!/^\d+$/.test(c[1]) || !c[2]) return; // la fila de totals no té dorsal ni nom
   if(!/^\d+:\d+$/.test(c[3])) return;      // ha de tenir minuts jugats
   players.push({team:ti,starter:c[0]==='*',dorsal:c[1],name:c[2],min:c[3],cols:c.slice(4,22)});}));
 return {teams,fecha,quarters:q.slice(0,q.length/2),players};}"""
 
COLS = ["PT","T2","T3","TC","TL","RO","RD","RT","AS","BR","BP","TF","TCo","MT","FC","FR","VAL","PM"]
 
def parse_player(p):
    out = {"team": p["team"], "starter": p["starter"], "dorsal": p["dorsal"],
           "name": norm_name(p["name"]), "name_raw": p["name"]}
    mm, _, ss = (p["min"] or "0:0").partition(":")
    out["min"] = round(int(mm or 0) + int(ss or 0) / 60, 2)
    for k, v in zip(COLS, p["cols"]):
        ma = split_made_att(v)
        if ma:
            out[k + "A"], out[k + "I"] = ma
        else:
            try: out[k] = int(v)
            except ValueError: out[k] = 0
    return out
 
def click_tab(page, text):
    page.locator("a.btn-tab", has_text=re.compile(text, re.I)).first.click()
 
def read_pbp(page, timeout_s=40):
    click_tab(page, r"^\s*Directo\s*$")
    last, stable, t0 = -1, 0, time.time()
    while time.time() - t0 < timeout_s:
        n = page.evaluate("()=>{const k=document.querySelector('.widget-keyfacts');return k?k.children.length:0}")
        stable = stable + 1 if (n > 50 and n == last) else 0
        last = n
        if stable >= 3:
            ok = page.evaluate("""()=>[...document.querySelector('.widget-keyfacts').children].slice(-15)
                                   .some(c=>/Comienzo del Cuarto 1/.test(c.textContent))""")
            if ok: break
            stable = 0
        time.sleep(0.8)
    return page.evaluate(r"""()=>{const k=document.querySelector('.widget-keyfacts'); if(!k) return [];
      return [...k.children].reverse().map(c=>{const q=+(c.className.match(/cuarto-(\d+)/)||[])[1];
        const acc=(c.querySelector('.accion')?.textContent||'').replace(/\s+/g,' ').trim();
        const tm=c.textContent.match(/(\d\d):(\d\d)/); return tm?[q,+tm[1]*60+ +tm[2],acc]:null}).filter(Boolean);}""")
 
def read_shots(page, fga, timeout_s=25):
    click_tab(page, r"Gr.{1,2}fico de tiro")
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        n = page.evaluate("()=>document.querySelectorAll('.court-shoots .shoot').length")
        if n >= fga: break
        time.sleep(0.8)
    return page.evaluate(r"""()=>[...document.querySelectorAll('.court-shoots .shoot')].map(e=>{
        const st=e.getAttribute('style')||''; const c=e.className.split(/\s+/);
        const g=p=>(c.find(x=>x.startsWith(p))||'').slice(p.length);
        return {team:+g('t'),dorsal:g('p-'),made:g('success')==='1',q:+g('q-'),
                left:+(st.match(/left:\s*([\d.]+)%/)||[])[1],top:+(st.match(/top:\s*([\d.]+)%/)||[])[1]};})""")
 
PBP_RE = re.compile(r"^\((.+?)\) (?:(.+?): )?(.+)$")
 
def pbp_points(raw):
    pts = {}
    for q, rem, acc in raw:
        m = PBP_RE.match(acc)
        if not m: continue
        team, act = norm_team(m.group(1)), m.group(3)
        p = 2 if act.startswith("TIRO DE 2 ANOTADO") else 3 if act.startswith("TIRO DE 3 ANOTADO") else 1 if act.startswith("TIRO DE 1 ANOTADO") else 0
        pts[team] = pts.get(team, 0) + p
    return pts
 
def extract_game(page, gid, tries=2):
    for attempt in range(1, tries + 1):
        try:
            page.goto(f"{BASE}/competiciones/partido/{gid}", wait_until="load", timeout=60000)
            page.wait_for_function("()=>{const t=document.querySelectorAll('table');return t.length>=2&&t[1].querySelectorAll('tr').length>3}", timeout=40000)
            box = page.evaluate(JS_BOX)
            players = [parse_player(p) for p in box["players"]]
            teams = [norm_team(t) for t in box["teams"]]
            box_pts = [sum(p.get("PT", 0) for p in players if p["team"] == i) for i in (0, 1)]
            fga = sum(p.get("T2I", 0) + p.get("T3I", 0) for p in players)
            raw = read_pbp(page)
            pp = pbp_points(raw)
            pbp_ok = all(pp.get(t) == box_pts[i] for i, t in enumerate(teams))
            shots = read_shots(page, fga)
            # validació de tirs per jugadora (dorsal numèric per evitar "00" vs "0")
            by = {}
            for s in shots:
                k = (s["team"], int(s["dorsal"]) if str(s["dorsal"]).isdigit() else s["dorsal"])
                by[k] = by.get(k, 0) + 1
            pl_keys = {(p["team"], int(p["dorsal"]) if p["dorsal"].isdigit() else p["dorsal"]): p for p in players}
            fga_p = lambda p: p.get("T2I", 0) + p.get("T3I", 0)
            mism = [f'{p["name"]} {by.get(k,0)}/{fga_p(p)}' for k, p in pl_keys.items() if by.get(k, 0) != fga_p(p)]
            orphans = [f"t{k[0]}|{k[1]}:{n}" for k, n in by.items() if k not in pl_keys]
            game = {"id": gid, "teams": teams, "teams_raw": box["teams"], "date": box["fecha"],
                    "quarters": box["quarters"], "score": box_pts, "players": players,
                    "pbp": raw, "shots": shots,
                    "checks": {"pbp_ok": pbp_ok, "pbp_points": pp, "pbp_events": len(raw),
                               "shots": len(shots), "fga": fga, "shots_ok": len(shots) == fga,
                               "shot_mismatch": mism, "shot_orphans": orphans}}
            if pbp_ok or attempt == tries:
                return game
            log(f"  {gid}: play-by-play incomplet, reintent")
        except PWTimeout as e:
            log(f"  {gid}: temps d'espera esgotat ({attempt}/{tries}): {e}")
            if attempt == tries:
                return {"id": gid, "error": "timeout"}
    return {"id": gid, "error": "unknown"}
 
# ---------------------------------------------------------------- execució
def run(comp, season, jornada, outdir):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="es-ES",
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
        page = ctx.new_page()
        info = list_games(page, comp, season, jornada)
        log(f"{comp} {season} {info['jornada_text']}: {len(info['ids'])} partits {info['ids']}")
        folder = Path(outdir) / str(season) / comp / f"J{info['jornada']:02d}"
        folder.mkdir(parents=True, exist_ok=True)
        report = {"comp": comp, "season": season, **info, "generated": datetime.now(timezone.utc).isoformat(), "games": []}
        for gid in info["ids"]:
            g = extract_game(page, gid)
            (folder / f"{gid}.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
            ch = g.get("checks", {})
            line = {"id": gid, "teams": g.get("teams"), "score": g.get("score"), "error": g.get("error"),
                    "pbp_ok": ch.get("pbp_ok"), "shots_ok": ch.get("shots_ok"),
                    "shot_mismatch": ch.get("shot_mismatch"), "shot_orphans": ch.get("shot_orphans")}
            report["games"].append(line)
            log(f"  {gid} {g.get('teams')} {g.get('score')} pbp_ok={ch.get('pbp_ok')} tirs={ch.get('shots')}/{ch.get('fga')}")
        (folder / "_jornada.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        browser.close()
        return report
 
def self_test(outdir):
    """Prova amb una jornada coneguda: LF-2 grup A 2025-26, J26 (partits 2479858-2479864)."""
    rep = run("lf2a", 2025, 26, outdir)
    expected = {2479859: [69, 45],   # CB Claret 69 - 45 Spar Gran Canaria
                2479861: [71, 63]}   # Alcorcón 71 - 63 GMASB (acta amb una fila extra)
    problems = []
    if len(rep["ids"]) != 7: problems.append(f"S'esperaven 7 partits i n'he trobat {len(rep['ids'])}")
    for g in rep["games"]:
        if g.get("error"): problems.append(f"{g['id']}: {g['error']}")
        if g["id"] in expected and g.get("score") != expected[g["id"]]:
            problems.append(f"{g['id']}: marcador {g.get('score')} i s'esperava {expected[g['id']]}")
    for g in rep["games"]:
        if g.get("pbp_ok") is False: problems.append(f'{g["id"]}: el play-by-play no quadra amb l\'acta')
        if g.get("shot_orphans"): problems.append(f'{g["id"]}: tirs amb dorsal desconegut {g["shot_orphans"]}')
    ok_pbp = sum(1 for g in rep["games"] if g.get("pbp_ok"))
    ok_sh = sum(1 for g in rep["games"] if g.get("shots_ok"))
    print("\n=== RESULTAT DE LA PROVA ===")
    print(f"Partits: {len(rep['games'])} | play-by-play correcte: {ok_pbp} | tirs correctes: {ok_sh}")
    print("PROVA SUPERADA" if not problems else "PROBLEMES:\n - " + "\n - ".join(problems))
    return 0 if not problems else 1
 
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--comp", choices=list(COMPS) + ["all"], default="all")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--jornada", default="last", help="número o 'last'")
    ap.add_argument("--out", default="data")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        sys.exit(self_test(a.out))
    comps = list(COMPS) if a.comp == "all" else [a.comp]
    failed = []
    for c in comps:
        try:
            run(c, a.season, a.jornada, a.out)
        except Exception as e:
            log(f"ERROR a {c}: {e}")
            failed.append(c)
    sys.exit(1 if failed and len(failed) == len(comps) else 0)
