# PRD — Tool di archiviazione e consultazione metriche Cloudflare (home lab)

**Versione:** 0.1 (bozza)  
**Data:** 2026-04-01  
**Contesto:** R&D analisi traffico / crawler (es. Googlebot), rete domestica, hardware limitato.

---

## 1. Sintesi

Prodotto: applicazione **web dockerizzata**, estremamente leggera, eseguibile su **Raspberry Pi 3 B+** (o host simile), che **ogni giorno** interroga le **API Cloudflare** (GraphQL Analytics nel caso d’uso attuale), **persiste** snapshot aggregati in **SQLite** e offre una **dashboard** consultabile sulla **LAN**.

Obiettivo primario: **costruire uno storico locale** perché le API non espongono dati oltre una finestra temporale breve (~ordine di una settimana sul dataset `httpRequestsAdaptiveGroups`): senza archiviazione incrementale il dato “scompare” dal punto di vista dell’analisi storica.

Il prodotto è pensato per **monitoraggio diagnostico e direzionale** (crawler, status, trend grossolani), **non** per analytics utenti né per allineamenti fuso-orario da reportistica di business: il **giorno archiviato segue l’UTC** delle API Cloudflare, senza conversione a fuso locale.

---

## 2. Problema e motivazione

- Le API Analytics aggregate hanno **limiti di anzianità** e di ampiezza per query; non sostituiscono i log grezzi Enterprise/Log Explorer.
- Per **monitoraggio e trend** (es. hit per status HTTP, pattern UA) serve comunque una **serie temporale lunga**, ottenibile solo **salvando ogni giorno** (o con frequenza adeguata) ciò che le API restituiscono oggi.
- Il deployment deve convivere con **CPU/RAM/disk** ridotti e preferibilmente **un solo container** o stack minimo.

---

## 3. Obiettivi

| ID | Obiettivo | Misura di successo |
|----|-----------|-------------------|
| O1 | Esecuzione pianificata giornaliera dell’estrazione | Job completato ≥1 volta/24h senza intervento manuale |
| O2 | Persistenza consultabile | Dati leggibili dalla dashboard per qualsiasi giorno archiviato |
| O3 | Footprint ridotto su Pi 3 B+ | Immagine e runtime compatibili con ~512 MB–1 GB RAM disponibili al container (vedi vincoli) |
| O4 | Uso solo rete locale | Dashboard in **LAN** senza esposizione pubblica; **nessuna autenticazione** nell’app (perimetro = rete domestica / firewall) |
| O5 | Ripetibilità del deploy | `docker compose up` (o equivalente) documentato, variabili via env/file |

### 3.1 Non-obiettivi (MVP)

- Autenticazione dell’interfaccia web (login, basic auth, token browser): **fuori scope**; si assume LAN fidata.
- Multi-utente, SSO, ruoli granulari.
- Alta disponibilità, clustering, backup automatici verso cloud (opzionale in fase 2).
- Sostituire Logpush / Log Explorer / log di origine per audit forense.
- Supporto ufficiale a piani Cloudflare diversi oltre a quanto documentato per il token in uso.
- **Export CSV** (o altri download tabellari dalla dashboard): **fuori scope**; per condividere esiti si assume **screenshot** o, se serve il dato grezzo, **copia/backup del file SQLite**.
- **Retention / purge automatica** dei dati storici (per età o quota disco): **fuori scope**. I dati restano **finché il deployment è attivo**; quando non servono più si **smonta Docker** e si **archivia** (immagine/config + volume con SQLite) come si preferisce in archivio personale.
- **Più zone Cloudflare nello stesso database:** **fuori scope** (vedi RF-01).

---

## 4. Utenti e scenari

- **Amministratore domestico:** avvia il container sul Pi, configura credenziali e zona, verifica che il job giornaliero scriva nel DB e apre la dashboard dal laptop in LAN.
- **Analista (stesso soggetto):** consulta grafici/tabelle per intervalli storici (es. ultimi 90 giorni) basati solo su dati effettivamente archiviati.

---

## 5. Vincoli tecnici

### 5.1 Hardware target (MVP)

- **Raspberry Pi 3 B+** (ARMv8, 1 GB RAM tipica sul sistema): il container non deve competere in modo aggressivo con il sistema operativo.
- Storage: SQLite su scheda SD o USB; prevedere crescita modesta (vedi sezione dati).

### 5.2 Leggerezza (requisiti non funzionali vincolanti)

- **Runtime:** preferenza per linguaggi con footprint contenuto (es. **Go** static binary, o **Python** slim + dipendenze minime); evitare stack pesanti (es. JVM full) salvo motivazione esplicita.
- **Processi:** ideale **un solo processo** che serva HTTP e scheduli il job (es. cron interno o scheduler leggero), oppure **due servizi** (worker + web) solo se il risparmio risorse non peggiora.
- **Immagine Docker:** base **Alpine** o **distroless/slim**; multi-arch **linux/arm/v7** (e opzionalmente arm64/amd64 per CI).
- **Dashboard:** UI statica servita dal backend o **HTMX + template**; evitare build frontend pesante in runtime sul Pi (pre-build asset in CI se necessario).

---

## 6. Architettura logica (MVP)

```
[ Cloudflare GraphQL API ]
           |
           |  HTTPS (token da env/secret)
           v
+----------------------------------+
|  App container                    |
|  - Scheduler (giornaliero)        |
|  - Client API + normalizzazione   |
|  - Scrittura SQLite               |
|  - Server HTTP (dashboard + API)  |
+----------------------------------+
           |
           v
     [ volume: sqlite file ]
```

**Alternativa accettabile:** container `app` + container `caddy`/`nginx` solo se il guadagno in semplicità supera il costo RAM; per MVP preferibile **monolite container**.

---

## 7. Requisiti funzionali

### 7.1 Configurazione

- **RF-01:** Caricamento configurazione tramite variabili d’ambiente (es. `CLOUDFLARE_ZONE_ID`, `CLOUDFLARE_API_TOKEN`) e/o file montato in sola lettura; **mai** committare segreti. **Una zona per istanza**; nessun multi-zona nello stesso SQLite. Altro dominio in futuro = **altro deploy** (o altro volume) con **token e zone id diversi** in `.env`.
- **RF-02:** Orario di esecuzione del job configurabile (default documentato, es. notte UTC). Il **giorno archiviato** nel DB è il **giorno civile UTC** (`YYYY-MM-DD`), allineato a **`datetimeHour`** e ai filtri `datetime_*` dell’API (anch’essi in UTC). Nessuna conversione a fuso locale (vedi [DATA_MODEL.md](./DATA_MODEL.md)).
- **RF-03:** **Lista chiusa** di metriche e dimensioni persistite: **solo** quanto definito in [DATA_MODEL.md](./DATA_MODEL.md) v1.0. Eventuale estensione in v0.2 (es. YAML) non cambia questo vincolo finché lo schema non viene versionato esplicitamente.

### 7.2 Estrazione dati (job)

- **RF-04:** Esecuzione **schedulata** (cron-like) almeno **una volta al giorno**.
- **RF-05:** Chiamata alle API Cloudflare rispettando **limiti noti** (ampiezza finestra, lookback): implementazione con **chunk** laddove necessario, come già emerso in R&D.
- **RF-06:** **Idempotenza per giorno di riferimento:** una seconda esecuzione nello stesso giorno **sovrascrive** o **aggiorna** il record dello stesso bucket (definire chiave univoca, es. `run_date` + `metric_key`).
- **RF-07:** Logging strutturato minimo (testo su stdout): successo/fallimento, durata, righe scritte, errori API.
- **RF-08:** In caso di errore API: **non corrompere** il DB; retry limitato; opzionale notifica (fuori MVP: webhook/email).

### 7.3 Persistenza

- **RF-09:** Database **SQLite 3** in file su volume Docker dedicato.
- **RF-10:** Schema iniziale con tabelle per: **run di ingestione** (metadati), **fatto giornaliero** e relazioni come in [DATA_MODEL.md](./DATA_MODEL.md) v1.0, eventuale tabella **config applicativa** se non solo env.
- **RF-11:** Migrazioni versionate (file SQL o tool minimale) per evolvere lo schema senza perdita dati.

### 7.4 Consultazione (dashboard)

- **RF-12:** Interfaccia web su **porta configurabile** (default es. 8080), bind configurabile (tipicamente LAN); documentare che **non va esposto su Internet** senza altro perimetro.
- **RF-13:** **Nessuna autenticazione** dashboard/API consultativa: il modello di minaccia è **rete locale fidata**; eventuale protezione solo a livello di rete (router, VLAN, VPN) — fuori scope dell’applicazione.
- **RF-14:** Visualizzazione: selezione **intervallo date** (giorni **UTC**, come in DB) su dati **già archiviati**; grafici e/o tabella; nessuna dipendenza da “live” oltre l’ultimo run.
- **RF-15:** Endpoint JSON (es. `/api/...`) senza auth, stesso perimetro LAN degli RF-12/13.

### 7.5 Docker

- **RF-16:** `Dockerfile` multi-stage se utile a ridurre dimensione.
- **RF-17:** `docker-compose.yml` con volume per SQLite, env file esempio `.env.example`, README con comandi ARM.
- **RF-18:** Healthcheck HTTP (es. `/health`) per orchestrazione domestica.

---

## 8. Modello dati

Definito nel documento **[DATA_MODEL.md](./DATA_MODEL.md)** (v1.0 — aggregato, senza URL):

- **Nessun** path, query grezza o folder nell’output SQLite; drill-down per URL = altre fonti (GSC, log origine, dashboard CF).
- Filtro ingest: **Googlebot** (`userAgent_like`).
- Metriche: **hit**; niente URL unici / crawl frequency nel DB.
- Dimensioni: **giorno civile UTC** (colonna `snapshot_date_utc`), **Percorso con query string** in DB come **`has_query_string` 0/1** (in UI solo etichette **«No»** / **«Sì»**), **status HTTP edge** (301/3xx nel perimetro di monitoraggio). Nessun campo hostname richiesta nel fatto. **Una zona** per istanza (vedi RF-01).
- Ingest: **doppia query** GraphQL (`clientRequestQuery` vuoto vs non vuoto), dimensioni minime; tabelle **piccole**, adatte al tetto **10k** e al Pi.

---

## 9. Sicurezza e privacy

- Token Cloudflare con **permesso minimo**; rotazione documentata (unico segreto “forte” lato app).
- Dashboard **senza login**: la sicurezza si basa sul **non esporre** il servizio oltre la LAN e su buone pratiche di rete domestica (firewall router, segmentazione se necessario).
- SQLite: permessi file solo utente container; backup = copia file a freddo quando il container è fermo (documentare).

---

## 10. Osservabilità e operatività

- Metriche container: uso CPU/RAM via `docker stats` (sufficiente in MVP).
- Rotazione log Docker o limite dimensione log dell’app.
- Procedura di **restore** da backup SQLite.
- **Ciclo di vita dati:** nessuna policy di eliminazione automatica nel prodotto. Lo storico cresce con i giorni di ingest; **fine uso** = stop/rimozione stack Docker e **archiviazione manuale** del tool insieme ai suoi dati (tipicamente il file SQLite sul volume), quando non servono più.

---

## 11. Dipendenze esterne e rischi

| Rischio | Mitigazione |
|---------|-------------|
| Cloudflare cambia limiti/quota GraphQL | Chunk + backoff; messaggi errore chiari; versionare query |
| Pi instabile su SD | SQLite su USB; backup periodici |
| Schema dati in evoluzione | Seguire [DATA_MODEL.md](./DATA_MODEL.md) v1.0 (aggregato); validazione empirica filtri `clientRequestQuery` (§9 DATA_MODEL) |
| Token scaduto/revocato | Fallimento job visibile in log e in dashboard “ultimo run fallito” |

---

## 12. Fasi di consegna suggerite

1. **MVP:** Docker + SQLite + job giornaliero + **doppia query** ingest (bucket DB **0/1**, etichette **«No»/«Sì»** in UI) + dashboard minima (hit per status e confronto con/senza query).
2. **v0.2:** Configurazione operativa via file YAML (es. orario job, pattern UA) **senza** ampliare metriche/dimensioni oltre [DATA_MODEL.md](./DATA_MODEL.md) v1.0 finché lo schema non è versionato; health e pagina stato ultimo ingest.

---

## 13. Criteri di accettazione (MVP)

- [ ] `docker compose up` su Pi 3 B+ (ARM) avvia servizio senza OOM.
- [ ] Dopo 24h e token valido, il DB contiene almeno una riga per l’ingest del giorno.
- [ ] Dashboard mostra i dati archiviati per un intervallo selezionato.
- [ ] README con variabili d’ambiente, backup SQLite, limitazioni API Cloudflare.

---

## 14. Decisioni chiuse (product owner)

1. **Fuso orario del “giorno” archiviato:** **UTC** (stesso calendario delle API Analytics GraphQL; data salvata come **`YYYY-MM-DD` UTC**). Coerente con uso **diagnostico/direzionale**, non con analytics utenti per fuso locale. Dettaglio: [DATA_MODEL.md](./DATA_MODEL.md).
2. **Metriche / dimensioni v1:** **lista chiusa** = solo quanto in [DATA_MODEL.md](./DATA_MODEL.md) v1.0.
3. **Più zone nello stesso DB:** **no**. Un’altra zona in futuro = **riuso del tool con altro `.env`** (token e `ZONE_ID` diversi), non multi-tenant nello stesso SQLite.

---

## 15. Riferimenti interni al repo (R&D esistente)

- Script e web app prototipo: `googlebot_status_daily.py`, `analytics_fetch.py`, `webapp/`.
- Vincoli API emersi: lookback breve su `httpRequestsAdaptiveGroups` → **l’archiviazione giornaliera è requisito funzionale critico**, non optional.

---

*Fine documento PRD v0.1.*
