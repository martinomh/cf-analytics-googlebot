# Modello dati — Archivio Googlebot (Cloudflare Analytics → SQLite)

**Versione:** 1.0 (schema aggregato, senza URL)  
**Allineamento:** PRD v0.1, granularità **giornaliera (giorno civile UTC)**, come **`datetimeHour`** e filtri `datetime_*` dell’API.

---

## 0. Contesto e scelta di progetto

Il lavoro di monitoraggio riguarda la **transizione** da percorsi con **query string** verso un crawl più pulito (molti **301** attesi su Googlebot).

**Scelta drastica sull’archivio locale:** **nessun dato a livello URL** nell’output persistito:

- nessun path risorsa, nessuna query string grezza, nessun raggruppamento cartella;
- nessun drill-down per singola URL da questo database.

L’obiettivo dello schema è **tabelle cortissime**, sotto il tetto **10k gruppi/query** Cloudflare, adatte a un **Pi** e a trend giornalieri **diagnostici/direzionali** (non analytics utenti per fuso locale). Per analisi per-URL si usano altre fonti (Search Console, log origine, dashboard Cloudflare, Log Explorer se disponibile).

---

## 1. Filtro globale (ingest)

| Elemento | Valore | Note |
|----------|--------|------|
| User-Agent | `userAgent_like: "%Googlebot%"` (configurabile) | Uso diagnostico; UA spoofabile. |
| Zona | `zoneTag` da config | **Una zona per istanza** (stesso SQLite); altro sitio = altro deploy / `.env` con token e zone id diversi. **Nessun** multi-zona nello stesso database. |

---

## 2. Metriche

### 2.1 Hit (`hits`)

- **Definizione:** numero di richieste nel gruppo GraphQL (`count` su `httpRequestsAdaptiveGroups`).
- **Granularità salvata:** per ogni combinazione **giorno UTC × has_query_string (0/1) × status HTTP** (§4).

### 2.2 Metriche non persistite in questo schema

- **URL unici**, **crawl frequency** (hit/URL distinte): **non calcolabili** dall’archivio perché non memorizziamo URL.
- **Confronto con Search Console:** GSC può mostrare decine di migliaia di richieste/giorno da Googlebot, mentre le API Analytics aggregate hanno **tetto ~10k gruppi** per risposta e campionamento/aggregazione diversi. Per **frequenza reale per URL** o totali “tipo log” l’unica fonte affidabile restano i **log** (origine, Logpush/Enterprise, ecc.); questo prodotto mira solo a **trend grossolani** (hit per status e bucket con/senza query).

---

## 3. Dimensioni (output)

| Dimensione | Colonna DB | Valori | Note |
|------------|------------|--------|------|
| **Data** | `snapshot_date_utc` | TEXT `YYYY-MM-DD` | **Giorno civile UTC** (mezzanotte UTC → mezzanotte UTC successiva). Derivato da `datetimeHour` (già UTC) o da filtri `datetime_geq` / `datetime_lt` in UTC sulla stessa finestra. |
| **Percorso con query string** | `has_query_string` | **0** \| **1** | **0** = senza query string, **1** = con query string. In UI si mostrano solo le etichette **«No»** / **«Sì»** (o equivalente). Popolamento: §5 (doppia query filtrata). |
| **Codice risposta HTTP (edge)** | `edge_response_status` | INTEGER | Es. 200, 301, 302, 404. I **3xx** restano centrali per il monitoraggio redirect. |

**Niente `request_host`:** in GraphQL spesso compare come dimensione tipo hostname della richiesta; per **MVP una zona = un dominio** non aggiunge informazione e alzerebbe solo cardinalità. Se in futuro servisse spezzare per hostname, si reintroduce come decisione esplicita.

---

## 4. Fatto principale (granularità giornaliera)

Tabella **`fact_googlebot_daily_query_status`** (nome indicativo):

| Colonna | Tipo | Descrizione |
|---------|------|-------------|
| `snapshot_date_utc` | TEXT/DATE | Giorno civile **UTC** (`YYYY-MM-DD`). |
| `has_query_string` | INTEGER | **0** o **1**; `CHECK (has_query_string IN (0, 1))`. |
| `edge_response_status` | INTEGER | Status edge. |
| `hits` | INTEGER | Conteggio richieste. |
| `ingested_at` | TEXT/ISO | Timestamp scrittura. |
| `source_run_id` | INTEGER FK | Run di ingest. |

**Chiave logica (idempotenza per giorno):**  
`(snapshot_date_utc, has_query_string, edge_response_status)`.

**Volume atteso:** per ogni giorno, al massimo **2 × N_status** righe (tipicamente decine: es. 2 × 15 status ≈ 30 righe/giorno). Ordine di grandezza **compatto** con il tetto API.

---

## 5. Logica di export: doppia query GraphQL

Non esiste una dimensione nativa “Sì/No” su query string: si **costruisce** aggregando **due chiamate** identiche per dimensioni e metriche, con **filtri diversi** su `clientRequestQuery`:

| Passata | `has_query_string` da salvare | Filtro (esempio; vedi §9 validazione) |
|---------|----------------------------------|----------------------------------------|
| **A** | **0** | `clientRequestQuery: ""` (query vuota, senza `?` nel valore). |
| **B** | **1** | `clientRequestQuery_like: "%_%"` oppure equivalente per “almeno un carattere nella query”. |

Entrambe includono `userAgent_like` tramite `AND` secondo la [grammatica filtri](https://developers.cloudflare.com/analytics/graphql-api/features/filtering/).

**Dimensioni GraphQL (stesse per A e B):** es. `datetimeHour` + `edgeResponseStatus`. Timestamp e filtri API sono in **UTC**; il **`snapshot_date_utc`** è la data (UTC) del bucket giornaliero. **Nessuna** dimensione path/URI nell’output salvato.

**Procedura ingest per il giorno \(D\) (stringa `YYYY-MM-DD` = calendario UTC):**

1. Finestra API: **`D` 00:00:00Z** incluso, **`D+1` 00:00:00Z** escluso (`datetime_geq` / `datetime_lt` o equivalente).
2. Esegui query **A** su quella finestra → righe con `has_query_string = 0`, `snapshot_date_utc = D`; query **B** → `has_query_string = 1`, stesso `snapshot_date_utc`.
3. **Variante equivalente:** solo risposte per `datetimeHour` → da ogni ora estrarre la data UTC (`…Z` → `YYYY-MM-DD`) e sommare in memoria per `(snapshot_date_utc, has_query_string, edge_response_status)`.
4. **Idempotenza:** prima di inserire, `DELETE` dal fatto per `snapshot_date_utc = D` (e run) oppure `UPSERT` sulla chiave logica.

**Chunk temporali:** se la finestra supera `maxDuration` dell’API, suddividere il giorno \(D\) in sotto-finestre UTC e **sommare** i `hits` per la stessa chiave prima di scrivere (preferibile sommare in memoria per `snapshot_date_utc`).

---

## 6. Rollup e dashboard

- **`ingestion_runs`:** metadati job.
- **`fact_googlebot_daily_query_status`:** unica tabella fatto necessaria per il MVP descritto.
- **Viste opzionali:** es. `daily_totals` = `SUM(hits)` per giorno raggruppando o meno per `has_query_string` e/o fascia status (2xx/3xx).

**Esempio — mix crawl con vs senza query (intervallo):**

```sql
SELECT has_query_string, SUM(hits) AS hits
FROM fact_googlebot_daily_query_status
WHERE snapshot_date_utc BETWEEN :start AND :end
GROUP BY has_query_string;
```

**Esempio — 301 su richieste ancora con query (`has_query_string = 1` → etichetta UI «Sì»):**

```sql
SELECT snapshot_date_utc, SUM(hits) AS hits_301_con_query
FROM fact_googlebot_daily_query_status
WHERE has_query_string = 1 AND edge_response_status = 301
GROUP BY snapshot_date_utc;
```

---

## 7. Limiti API (promemoria)

- **`maxPageSize`** (es. 10 000): con questo schema le righe per query sono **pochissime**; il rischio di troncamento si sposta solo su configurazioni errate (dimensioni extra non volute).
- **`maxDuration` / `notOlderThan`:** restano vincoli Cloudflare; ingest **giornaliero** incrementale + tool tipo `graphql_limits.py` nel repo.

---

## 8. Indici SQLite (indicativi)

```sql
CREATE INDEX idx_fact_date ON fact_googlebot_daily_query_status (snapshot_date_utc);
CREATE INDEX idx_fact_date_bucket ON fact_googlebot_daily_query_status (snapshot_date_utc, has_query_string);
CREATE INDEX idx_fact_date_status ON fact_googlebot_daily_query_status (snapshot_date_utc, edge_response_status);
```

---

## 9. Decisioni chiuse (v1.0)

1. **Valori nel DB:** `has_query_string` **0** / **1**; le stringhe **«No»** / **«Sì»** (o **«Sì»** / **«No»** all’asse) sono **solo in UI** (nessun export tabellare previsto nel prodotto; dati grezzi = SQLite).
2. **Nessun `request_host`:** hostname della richiesta non è persistito (una zona, dominio unico nel perimetro MVP).
3. **Validazione empirica dei filtri** — cosa significa: **non** ci si affida solo alla documentazione Cloudflare. Una tantum (e dopo cambiamenti lato CF) si verifica **sul proprio account** che i due filtri partizionino il traffico come atteso, ad esempio:
   - nella **GraphQL API / Explorer**, stessa finestra temporale e stesso filtro Googlebot, si eseguono **A** (solo `clientRequestQuery: ""`) e **B** (solo “query non vuota”);
   - si controlla che **non** ci sia sovrapposizione evidente (stessa richiesta contata in entrambi) e, dove possibile, che **A + B** sia **vicino** al totale della stessa finestra **senza** filtro su query (stesso UA), accettando differenze per campionamento o definizione interna del campo;
   - opzionale: confronto qualitativo con un campione da **log reali** o dashboard CF su “richieste con query”.

Se i filtri non combaciano (es. stringa vuota mal definita), si corregge la coppia di filtri e si aggiorna questo documento.

4. **Fuso del giorno archiviato:** **UTC** (colonna `snapshot_date_utc`; allineato alle API Analytics, uso diagnostico/direzionale).
5. **Metriche e dimensioni v1:** **lista chiusa** = sole tabelle/campi descritti in questo documento v1.0; nessuna estensione ad hoc senza nuova versione dello schema.
6. **Zona Cloudflare:** **una per istanza**; nessun accorpamento di più zone nello stesso DB (riuso del tool = altro `.env`).

---

*Documento di supporto al PRD; schema v1.0 senza persistenza URL.*
