# Archivio Googlebot da Cloudflare Analytics

Archiviazione **giornaliera** di metriche aggregate **Cloudflare GraphQL Analytics** (perimetro **Googlebot**), persistenza in **SQLite** e consultazione via **dashboard LAN** — contesto **home lab** (es. Raspberry Pi), uso **diagnostico/direzionale**, non analytics utenti.

---

### ⚠️ Disclaimer — sicurezza e perimetro d’uso ⚠️

**Nessuna autenticazione.** L’app **non** espone login né protezione sulle API: chi raggiunge host e porta può **consultare la dashboard** e, con il servizio configurato (token Cloudflare nel `.env` / container), **chiamare ingest e backfill** come previsto dal codice.

**Docker non è un confine di sicurezza.** Non installarla su **macchine o reti pubbliche** senza ulteriori controlli. È pensata per **LAN e ambienti fidati** che gestisci tu (casa, lab, VLAN amministrativa). Se ti serve accesso da fuori, usa almeno una **VPN** oppure metti davanti **reverse proxy, firewall e autenticazione** (e ogni altro accorgimento) di tua scelta e **tua responsabilità**.

---

Repository: [github.com/martinomh/cf-analytics-googlebot](https://github.com/martinomh/cf-analytics-googlebot)

## Stato

MVP implementato secondo [docs/PRD.md](docs/PRD.md) e [docs/DATA_MODEL.md](docs/DATA_MODEL.md): app Python (`app/`), SQLite con migrazioni (`migrations/`), ingest giornaliero (cron UTC) con **query GraphQL partizionate** (con/senza query string e **classi** `ua_kind`), dashboard su dati **solo da DB**. Il prototipo R&D in `legacy/` resta fuori dal flusso principale (vedi `.gitignore`).

## Avvio rapido

**Locale (sviluppo):**

```text
pip install -r requirements.txt
copy .env.example .env   # Windows; su Linux/macOS: cp .env.example .env
python -m app.server
```

Apri `http://127.0.0.1:8080` se non imposti altro: il default in codice è la porta **8080** (`HTTP_PORT` in `.env` per cambiarla). Health: `GET /health`.

**Docker (consigliato su Raspberry Pi):**

Sul Pi (o altro host Linux con Docker / Docker Compose) serve prima il codice sul disco, poi l’avvio:

1. **Clona il repository** (installa `git` se manca), ad esempio in `~/src`:

   ```text
   git clone https://github.com/martinomh/cf-analytics-googlebot.git
   cd cf-analytics-googlebot
   ```

2. **Configura e avvia:** copia `.env.example` in `.env`, compila `CLOUDFLARE_ZONE_ID` e `CLOUDFLARE_API_TOKEN`, poi dalla stessa cartella:

   ```text
   cp .env.example .env
   docker compose up -d --build
   ```

   (Modifica `.env` con l’editor che preferisci prima del `compose up`.)

Dashboard raggiungibile su **`http://<host>:418`** con la configurazione predefinita del repo.

- **Porta 418:** richiamo allo status **HTTP 418 I’m a teapot**. Non è assegnata a servizi standard dalla **IANA** ma rientra nel range *registered*.
- **Conflitti:** rimappa l’host, ad esempio in `docker-compose.yml` con `ports: - "TUA_PORTA:418"`, oppure imposta **`HTTP_PORT`** nel `.env` nella root del progetto: Compose lo usa per la **porta sull’host** nella riga `ports` (`${HTTP_PORT:-418}:418`). Il processo **nel container** resta in ascolto sulla **418** (come definito nel servizio in `docker-compose.yml`).

Build multi-arch (es. da PC verso Pi 3 armv7):

```text
docker buildx build --platform linux/arm/v7 -t cf-googlebot-archiver:armv7 --load .
```

Il volume Compose `cf_googlebot_sqlite` contiene il file SQLite in `/data`.

**Raspberry / build:** immagine **`python:3.12-slim-bookworm`**: su **Pi armv7**, **Alpine** poteva far crashare `pip` (es. **139** / SIGSEGV). Su macchine recenti basta `docker compose up -d --build` (BuildKit consigliato).

**Solo Debian Buster (o seccomp datato):** se `pip` in build fallisce con **`PermissionError` su `time.time()`** oppure BuildKit risponde che **`security.insecure` non è consentita**, il daemon va autorizzato alle **entitlements** BuildKit, poi si usa il file overlay **`docker-compose.buster.yml`** (che imposta `build.privileged` solo lì).

1. Modifica **`/etc/docker/daemon.json`** (JSON valido: se il file esiste già, **unisci** le chiavi senza duplicare l’oggetto radice). Esempio minimo se parti da zero:

   ```json
   {
     "builder": {
       "entitlements": {
         "network-host": true,
         "security-insecure": true
       }
     }
   }
   ```

2. Riavvia Docker: **`sudo systemctl restart docker`**.

3. Build e avvio con **BuildKit** e doppio compose file:

   ```text
   export DOCKER_BUILDKIT=1
   docker compose -f docker-compose.yml -f docker-compose.buster.yml up -d --build
   ```

   In seguito, senza ricostruire: `docker compose -f docker-compose.yml -f docker-compose.buster.yml up -d` (oppure solo `docker compose up -d` se l’immagine è già presente con lo stesso tag).

**Nota:** su molti daemon Linux **`docker build --security-opt seccomp=...` non è supportato** (errore *security options are not supported on linux*): non è una soluzione affidabile su Pi; l’overlay + entitlements è il percorso previsto per Buster. Init a runtime: `init: true`. Per **TLS**, NTP e DNS.

## API e operatività

| Endpoint | Ruolo |
|----------|--------|
| `GET /health` | Healthcheck (orchestrazione / Docker) |
| `GET /api/facts?start=&end=` | JSON per intervallo date UTC (`YYYY-MM-DD`): `facts` (righe granulari `d`, `uk`, `b`, `s`, `h`), `rows`, `start`/`end` — aggregazione e filtri in dashboard |
| `GET /api/last-run` | Ultimo run di ingest (metadati) |
| `POST /api/trigger-ingest` | Avvio ingest in background (default: **ieri UTC**; body opzionale `{"date":"YYYY-MM-DD"}`) |
| `POST /api/trigger-backfill` | Backfill sequenziale in background: default **8 giorni** UTC (da `oggi−8` a **ieri**), come tipica finestra 7+1 API; body opzionale `{"days":8}` (1–14). Se un backfill è già in corso → HTTP 409 |

**Backup / restore:** con il container fermo, copia il file puntato da `SQLITE_PATH` (in Compose: volume su `cf_googlebot_sqlite`).

**Limiti Cloudflare:** l’ingest può fallire se la data richiesta è oltre il lookback del dataset (`httpRequestsAdaptiveGroups`); messaggio in log e in dashboard sull’ultimo run.

## Documentazione

| File | Contenuto |
|------|-----------|
| [docs/PRD.md](docs/PRD.md) | Requisiti, architettura MVP, vincoli (Docker, LAN, nessuna auth UI, UTC). |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Schema SQLite v1.1: fatto giornaliero, `ua_kind` (Googlebot / Image / altri), `has_query_string`, partizioni query string + filtri UA (nessuna dimensione UA in GraphQL). |

## Configurazione (token Cloudflare)

1. Copia `.env.example` in `.env` nella root del clone.
2. Imposta `CLOUDFLARE_ZONE_ID` e `CLOUDFLARE_API_TOKEN` (permessi minimi necessari alle API Analytics in uso).
3. Opzionale: `HTTP_PORT`, pattern UA (`USER_AGENT_LIKE`, `UA_GOOGLEBOT_*`), ingest, chunk GraphQL — vedi commenti in `.env.example`.
4. Non committare `.env` (è elencato in `.gitignore`).

## Limiti noti (promemoria)

Le API Analytics aggregate hanno **lookback breve** e **tetti** (es. dimensione risposta); non sostituiscono **Logpush** o log di origine. Dettagli e mitigazioni: PRD e DATA_MODEL.

## Licenza

Distribuito sotto licenza **MIT**: regalo alla community; vedi il file [LICENSE](LICENSE).
