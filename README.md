# Dades FEB setmanals

Extreu cada setmana les actes, el play-by-play i els gràfics de tir de la
Liga Femenina, la LF Challenge i els dos grups de LF-2, i els desa en JSON
dins de la carpeta `data/`. S'executa sol a GitHub, sense cap ordinador encès.

## Posar-ho en marxa (uns 10 minuts, una sola vegada)

1. **Crea un compte a GitHub** (github.com) si no en tens.
2. **Crea un repositori nou**: botó «New», nom per exemple `dades-feb`,
   marca **Public** i crea'l. Ha de ser públic perquè Claude pugui llegir
   les dades; són dades públiques de la FEB.
3. **Puja els fitxers**: a la pàgina del repositori, «Add file» → «Upload files»,
   i arrossega-hi `feb_scraper.py`, `requirements.txt` i `README.md`.
   Confirma amb «Commit changes».
4. **Crea el fitxer del programador**: «Add file» → «Create new file».
   Al nom, escriu exactament `.github/workflows/feb.yml` (les barres creen les
   carpetes). Enganxa-hi el contingut del fitxer `feb.yml` i confirma.
5. **Dona permís d'escriptura a les execucions**: Settings → Actions → General →
   «Workflow permissions» → marca «Read and write permissions» → Save.

## Fer la prova

1. Pestanya **Actions** → a l'esquerra, «Dades FEB setmanals» → botó
   **Run workflow**. Deixa «mode» en `test` i prem «Run workflow».
2. Espera 3-5 minuts i obre l'execució. Al pas «Extreure dades», al final,
   hi ha d'aparèixer:
   `=== RESULTAT DE LA PROVA ===` i `PROVA SUPERADA`.
3. Copia'm l'adreça del repositori (per exemple
   `https://github.com/el-teu-usuari/dades-feb`) i digues-me com ha anat.
   Si ha fallat, copia'm les últimes 30 línies del registre.

La prova extreu la jornada 26 del grup A de LF-2 de la temporada passada,
que ja coneixem, i comprova que els resultats quadren.

## Funcionament normal

- S'executa sol **els dilluns i els dimecres a les 5:00 (UTC)**. El dimecres
  recull els partits ajornats.
- Les dades queden a `data/<temporada>/<competició>/J<jornada>/`: un fitxer
  per partit i un `_jornada.json` amb el control de qualitat.
- Per a una execució manual: Run workflow → mode `run`, i tria competició,
  temporada i jornada.

## Si la FEB bloqueja les connexions des de GitHub

Es veurà a la prova: errors de connexió o pàgines que no carreguen. En aquest
cas es pot executar el mateix script al teu ordinador:

```
pip install -r requirements.txt
python -m playwright install chromium
python feb_scraper.py --test
```

i programar-lo amb el Programador de tasques de Windows.
