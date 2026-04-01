# CloudFlare Analytics Googlebot Archiver

Archiviazione **giornaliera** di metriche aggregate **Cloudflare GraphQL Analytics** (perimetro **Googlebot**), persistenza in **SQLite** e consultazione via **dashboard LAN** — contesto **home lab** (es. Raspberry Pi), uso **diagnostico/direzionale**, non analytics utenti.

Repository: [github.com/martinomh/cf-analytics-googlebot](https://github.com/martinomh/cf-analytics-googlebot)

## Stato

Questo repository contiene la **baseline di progetto** (documentazione e template di configurazione). L’implementazione applicativa è in corso; eventuale prototipo R&D locale resta fuori dal versionamento (cartella `legacy/` in `.gitignore`).

## Documentazione

| File | Contenuto |
|------|-----------|
| [docs/PRD.md](docs/PRD.md) | Requisiti, architettura MVP, vincoli (Docker, LAN, nessuna auth UI, UTC). |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Schema SQLite v1.0: fatto giornaliero, `has_query_string` 0/1, doppia query GraphQL, chiavi e indici. |

## Configurazione (token Cloudflare)

1. Copia `.env.example` in `.env` nella root del clone.
2. Imposta `CLOUDFLARE_ZONE_ID` e `CLOUDFLARE_API_TOKEN` (permessi minimi necessari alle API Analytics in uso).
3. Non committare `.env` (è elencato in `.gitignore`).

## Limiti noti (promemoria)

Le API Analytics aggregate hanno **lookback breve** e **tetti** (es. dimensione risposta); non sostituiscono **Logpush** o log di origine. Dettagli e mitigazioni: PRD e DATA_MODEL.
