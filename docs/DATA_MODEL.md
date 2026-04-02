# Modello dati — Archivio Googlebot (Cloudflare Analytics → SQLite)

**Versione:** 1.1 (schema aggregato, senza URL; partizione User-Agent **a classi**)  
**Allineamento:** PRD v0.1, granularità **giornaliera (giorno civile UTC)**, come **`datetimeHour`** e filtri `datetime_*` dell’API.

**Changelog:** v1.0 → v1.1 — aggiunta dimensione **`ua_kind`** (Googlebot / Googlebot-Image / altri Googlebot) tramite **filtri** `userAgent_like` sulle richieste GraphQL, **senza** aggiungere la stringa UA come dimensione di raggruppamento lato API.

---

## 0. Contesto e scelta di progetto

Il lavoro di monitoraggio riguarda la **transizione** da percorsi con **query string** verso un crawl più pulito (molti **301** attesi su Googlebot).

**Scelta drastica sull’archivio locale:** **nessun dato a livello URL** nell’output persistito:

- nessun path risorsa, nessuna query string grezza, nessun raggruppamento cartella;
- nessun drill-down per singola URL da questo database.

L’obiettivo dello schema è **tabelle cortissime**, sotto il tetto **10k gruppi/query** Cloudflare, adatte a un **Pi** e a trend giornalieri **diagnostici/direzionali** (non analytics utenti per fuso locale). Per analisi per-URL si usano altre fonti (Search Console, log origine, dashboard Cloudflare, Log Explorer se disponibile).

**v1.1 — User-Agent:** si distingue il traffico per **classi** di crawler Google (immagine vs. generico vs. altri prodotti Googlebot dichiarati), utile a diagnostica senza memorizzare UA completi né alzare la cardinalità delle risposte GraphQL (vedi §5.3 e §7).

---

## 1. Filtro globale (ingest)

| Elemento | Valore | Note |
|----------|--------|------|
| Universo traffico | Perimetro **Googlebot** (e varianti gestite in §3 `ua_kind`) | L’ingest applica **combinazioni di filtri** `userAgent_like` (e composti `and` / `or` / `not` ove supportati) per ottenere partizioni **disgiunte** tra loro. **Non** si usa un singolo `%Googlebot%` come unico filtro su tutte le passate, salvo baseline di test in Explorer. |
| Pattern configurabili | Env / config applicativa (v0.2+) | Default attesi documentati in §3 (`ua_kind`). |
| Zona | `zoneTag` da config | **Una zona per istanza** (stesso SQLite); altro sito = altro deploy / `.env` con token e zone id diversi. **Nessun** multi-zona nello stesso database. |

**Nota:** gli UA sono **spoofabili**; i bucket restano strumenti diagnostici, non prova forense.

---

## 2. Metriche

### 2.1 Hit (`hits`)

- **Definizione:** numero di richieste nel gruppo GraphQL (`count` su `httpRequestsAdaptiveGroups`).
- **Granularità salvata (v1.1):** per ogni combinazione **giorno UTC × `ua_kind` × `has_query_string` (0/1) × status HTTP** (§4).

### 2.2 Metriche non persistite in questo schema

- **URL unici**, **crawl frequency** (hit/URL distinte): **non calcolabili** dall’archivio perché non memorizziamo URL.
- **UA stringa completa**, varianti oltre le tre classi, versioni minori del product token: **non persistite**; solo le classi in §3.
- **Confronto con Search Console:** GSC può mostrare decine di migliaia di richieste/giorno da Googlebot, mentre le API Analytics aggregate hanno **tetto ~10k gruppi** per risposta e campionamento/aggregazione diversi. Per **frequenza reale per URL** o totali “tipo log” l’unica fonte affidabile restano i **log** (origine, Logpush/Enterprise, ecc.); questo prodotto mira solo a **trend grossolani** (hit per status, bucket con/senza query, ripartizione per classe UA).

---

## 3. Dimensioni (output)

| Dimensione | Colonna DB | Valori | Note |
|------------|------------|--------|------|
| **Data** | `snapshot_date_utc` | TEXT `YYYY-MM-DD` | **Giorno civile UTC** (mezzanotte UTC → mezzanotte UTC successiva). Derivato da `datetimeHour` (già UTC) o da filtri `datetime_geq` / `datetime_lt` in UTC sulla stessa finestra. |
| **Classe User-Agent (Googlebot)** | `ua_kind` | TEXT, `CHECK` su valori ammessi | Tre valori chiusi: **`googlebot`** (crawler web “generico”, esclusi image/video/news nel senso di §5.2), **`googlebot_image`** (es. UA che contiene **`Googlebot-Image`** / product token **Googlebot-Image/…**), **`googlebot_other`** (in v1.1: **Video** e **News** e simili dichiarati Googlebot non coperti dalle due classi precedenti — raggruppati volutamente per volumi attesi bassi). In UI etichette leggibili (es. «Googlebot», «Googlebot-Image», «Altri Googlebot»). |
| **Percorso con query string** | `has_query_string` | **0** \| **1** | **0** = senza query string, **1** = con query string. In UI **«No»** / **«Sì»**. Popolamento: §5.1 (doppia query filtrata su `clientRequestQuery`). |
| **Codice risposta HTTP (edge)** | `edge_response_status` | INTEGER | Es. 200, 301, 302, 404. I **3xx** restano centrali per il monitoraggio redirect. |

**Niente `request_host`:** in GraphQL spesso compare come dimensione tipo hostname della richiesta; per **MVP una zona = un dominio** non aggiunge informazione e alzerebbe solo cardinalità. Se in futuro servisse spezzare per hostname, si reintroduce come decisione esplicita.

**Niente colonna UA grezza:** nessuna persistenza della stringa `User-Agent` completa.

---

## 4. Fatto principale (granularità giornaliera)

Tabella **`fact_googlebot_daily_query_status`** (nome conservato per continuità; semanticamente include anche `ua_kind`):

| Colonna | Tipo | Descrizione |
|---------|------|-------------|
| `snapshot_date_utc` | TEXT/DATE | Giorno civile **UTC** (`YYYY-MM-DD`). |
| `ua_kind` | TEXT | Una tra `googlebot`, `googlebot_image`, `googlebot_other`; `CHECK (ua_kind IN (...))`. |
| `has_query_string` | INTEGER | **0** o **1**; `CHECK (has_query_string IN (0, 1))`. |
| `edge_response_status` | INTEGER | Status edge. |
| `hits` | INTEGER | Conteggio richieste. |
| `ingested_at` | TEXT/ISO | Timestamp scrittura. |
| `source_run_id` | INTEGER FK | Run di ingest. |

**Chiave logica (idempotenza per giorno):**  
`(snapshot_date_utc, ua_kind, has_query_string, edge_response_status)`.

**Volume atteso (v1.1):** per ogni giorno, al massimo **3 × 2 × N_status** righe (tre classi UA × due bucket query string × numero di status distinti osservati). Esempio: 3 × 2 × 15 ≈ **90** righe/giorno — ancora **ordini di grandezza sotto** al tetto **10k** gruppi/risposta, **a patto** che nelle query GraphQL restino le sole dimensioni **`datetimeHour`** e **`edgeResponseStatus`** (nessuna dimensione UA).

---

## 5. Logica di export: GraphQL

### 5.1 Partizione query string (invariata)

Non esiste una dimensione nativa “Sì/No” su query string: si **costruisce** con **due** filtri su `clientRequestQuery` combinat i con gli altri filtri della passata:

| Passata | `has_query_string` da salvare | Filtro (esempio; vedi §9 validazione) |
|---------|----------------------------------|----------------------------------------|
| **A** | **0** | `clientRequestQuery: ""`. |
| **B** | **1** | `clientRequestQuery_like: "%_%"` o equivalente per “query non vuota”. |

### 5.2 Partizione User-Agent (v1.1) — filtri, non dimensione

Obiettivo: tre flussi **disgiunti** che mappano su `ua_kind`:

| `ua_kind` (DB) | Significato prodotto | Filtro UA (linee guida; da validare in GraphQL Explorer) |
|-----------------|----------------------|-----------------------------------------------------------|
| `googlebot_image` | Googlebot Image | Esempio: `userAgent_like: "%Googlebot-Image%"` (cattura product token tipo **Googlebot-Image/1.0**). |
| `googlebot_other` | Video, News, altri Googlebot dichiarati non “web standard” | Esempio: unione con **`or`** di pattern tipo `%Googlebot-Video%`, `%Googlebot-News%` (nomi esatti da allineare agli UA reali / documentazione Google). Se `or` non è esprimibile in un solo filtro, **due** query per la stessa combinazione (stesso `has_query_string`) e **somma in memoria** per `ua_kind` prima della scrittura. |
| `googlebot` | Crawler web generico Googlebot | Traffico che rientra nel perimetro Googlebot **escludendo** quanto già contato come `googlebot_image` o `googlebot_other`. In implementazione: filtro **`and` / `not`** sui pattern sopra, oppure — solo se empiricamente stabile — baseline `%Googlebot%` con **sottrazione** lato applicazione dei conteggi delle altre due classi (sconsigliato se introduce doppi conteggi; preferire filtri disgiunti lato API). |

Ogni combinazione (**A** o **B** da §5.1) va eseguita **per ogni** `ua_kind` con il filtro UA corrispondente → **6 passate** per giorno \(D\) (3 × 2), salvo fusione query per `googlebot_other` come sopra.

**Dimensioni GraphQL (obbligatorie per tutte le passate):** solo **`datetimeHour`** + **`edgeResponseStatus`**. **Non** aggiungere **`clientRequestUserAgent`** (o equivalente) come dimensione di grouping: moltiplicherebbe i gruppi (cardinalità potenzialmente altissima) e avvicinerebbe il rischio al **maxPageSize**.

### 5.3 Valutazione cardinalità (richiesta esplicita)

| Aspetto | Valutazione |
|---------|-------------|
| **Dimensione UA in query** | **Sconsigliata / fuori schema:** ogni UA distinto = gruppo aggiuntivo; in scenari reali si avvicina o si supera il tetto **10k** con molto meno controllo rispetto a status × ora. |
| **Filtri `userAgent_like` fissi (3 classi)** | **Cardinalità per risposta invariata** rispetto a v1.0: stesso numero di gruppi (~ ore × status) **per singola chiamata**; cresce solo il **numero di chiamate** (×3). |
| **Righe in SQLite** | ~**triplicazione** rispetto a v1.0 sullo stesso traffico (stesso ordine di grandezza: centinaia di righe su intervalli lunghi, non milioni). |
| **Rischio troncamento** | Resta basso se non si aggiungono dimensioni arbitrarie; monitorare log “truncated” come oggi. |

### 5.4 Procedura ingest per il giorno \(D\)

1. Finestra API: **`D` 00:00:00Z** incluso, **`D+1` 00:00:00Z** escluso.
2. Per ogni `ua_kind` e per ogni passata **A**/**B** (§5.1), eseguire la query con filtri combinati (`datetime`, UA, `clientRequestQuery`).
3. Aggregare in memoria per `(snapshot_date_utc, ua_kind, has_query_string, edge_response_status)` sommando i `count`.
4. **Idempotenza:** `DELETE` dal fatto per `snapshot_date_utc = D` (tutti i `ua_kind`) poi inserimento con nuovo `source_run_id`, oppure `UPSERT` sulla chiave logica estesa.

**Chunk temporali:** come v1.0; sommare per chiave prima di scrivere.

---

## 6. Rollup e dashboard

- **`ingestion_runs`:** metadati job.
- **`fact_googlebot_daily_query_status`:** tabella fatto con dimensione **`ua_kind`** (v1.1).

**Esempio — hit per classe UA (intervallo):**

```sql
SELECT ua_kind, SUM(hits) AS hits
FROM fact_googlebot_daily_query_status
WHERE snapshot_date_utc BETWEEN :start AND :end
GROUP BY ua_kind;
```

**Esempio — mix crawl con vs senza query (invariato concettualmente, con `ua_kind`):**

```sql
SELECT ua_kind, has_query_string, SUM(hits) AS hits
FROM fact_googlebot_daily_query_status
WHERE snapshot_date_utc BETWEEN :start AND :end
GROUP BY ua_kind, has_query_string;
```

**Esempio — 301 con query su Googlebot “generico”:**

```sql
SELECT snapshot_date_utc, SUM(hits) AS hits
FROM fact_googlebot_daily_query_status
WHERE ua_kind = 'googlebot' AND has_query_string = 1 AND edge_response_status = 301
GROUP BY snapshot_date_utc;
```

---

## 7. Limiti API (promemoria)

- **`maxPageSize`** (es. 10 000): con **sole** dimensioni `datetimeHour` + `edgeResponseStatus` le righe per risposta restano **pochissime**; il rischio di troncamento aumenta solo se si aggiungono dimensioni ad alta cardinalità (es. UA completo).
- **`maxDuration` / `notOlderThan`:** invariati; ingest giornaliero incrementale.
- **Quota chiamate:** v1.1 moltiplica le passate per giorno per un fattore **~3** rispetto a v1.0 (a parità di chunk); accettabile per job giornaliero + backfill entro lookback; in caso di limiti si può serializzare con breve pausa tra passate (come già pratica sul chunking).

---

## 8. Indici SQLite (indicativi, v1.1)

```sql
CREATE INDEX idx_fact_date ON fact_googlebot_daily_query_status (snapshot_date_utc);
CREATE INDEX idx_fact_date_ua ON fact_googlebot_daily_query_status (snapshot_date_utc, ua_kind);
CREATE INDEX idx_fact_date_ua_bucket ON fact_googlebot_daily_query_status (snapshot_date_utc, ua_kind, has_query_string);
CREATE INDEX idx_fact_date_status ON fact_googlebot_daily_query_status (snapshot_date_utc, edge_response_status);
```

*(Aggiornare la migrazione SQL reale del repo quando si implementa lo schema.)*

---

## 9. Decisioni chiuse

### v1.0 (ancora valide salvo dove sostituite da v1.1)

1. `has_query_string` **0** / **1**; etichette **«No»** / **«Sì»** solo in UI.
2. **Nessun `request_host`** nel fatto.
3. **Validazione empirica dei filtri** (query string **e**, in v1.1, **UA**): verificare in Explorer che le partizioni siano **disgiunte** o che la somma delle classi sia coerente con una baseline `%Googlebot%` sulla stessa finestra, accettando campionamento CF.
4. **Fuso del giorno archiviato:** **UTC**.
5. **Zona Cloudflare:** **una per istanza**.

### v1.1 (aggiunte)

6. **Tre valori chiusi `ua_kind`:** `googlebot`, `googlebot_image`, `googlebot_other` (Video + News + simili in `googlebot_other`); nessun altro valore senza bump di versione documento.
7. **Nessuna persistenza UA grezza**; nessuna dimensione GraphQL su stringa UA piena — solo **filtri** per classe.
8. **Lista chiusa dimensioni/metriche v1.1** = quanto in questo documento **§2–§4**; estensioni future = **v1.2+** o **2.0** con migrazione esplicita.

---

*Documento di supporto al PRD; schema v1.1 senza persistenza URL, con partizione User-Agent a classi.*
