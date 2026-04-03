# Build Docker per Raspberry Pi / seccomp datati (Debian Buster)

Questa cartella serve **solo** se sul **tuo** host (tipicamente **Raspberry Pi** con OS tipo **Debian Buster**, o kernel con **seccomp** molto restrittivo) compaiono errori del tipo:

- durante **`docker compose build`**: `pip` che fallisce con **`PermissionError`** su **`time.time()`**;
- **dopo** il build, il container che esce subito o crasha su **`import logging`** (stessa causa).

Su **Debian Bookworm**, PC recenti o molti ARM64 **non** serve nulla di tutto ciò: dalla **root del repository** usa il [`Dockerfile`](../Dockerfile) standard e:

```text
docker compose up -d --build
```

## Cosa c’è qui

| File | Ruolo |
|------|--------|
| [`Dockerfile`](Dockerfile) | Come il Dockerfile di root, ma `RUN --security=insecure` **solo** sulla riga `pip install` (workaround BuildKit + seccomp vecchio). |
| [`docker-compose.buster.yml`](docker-compose.buster.yml) | Merge con [`docker-compose.yml`](../docker-compose.yml): punta a questo Dockerfile e imposta **`security_opt: seccomp=unconfined`** sul servizio (runtime). |
| [`build.sh`](build.sh) | Dalla root del repo: **`buildx`** con `--allow security.insecure` + **`compose up`**. |

Tutti i comandi **`docker compose`** vanno eseguiti dalla **root del clone** (dove ci sono `.env`, `docker-compose.yml`, `app/`, `requirements.txt`).

## Procedura consigliata

Dalla root del repository:

```text
chmod +x raspberry-buster/build.sh
./raspberry-buster/build.sh
```

Lo script imposta `IMAGE` di default a `cf-googlebot-archiver:local` (come Compose). Per un’altra tag: `IMAGE=mia:tag ./raspberry-buster/build.sh`.

## Solo Compose (senza lo script)

Con BuildKit attivo:

```text
export DOCKER_BUILDKIT=1
docker compose -f docker-compose.yml -f raspberry-buster/docker-compose.buster.yml up -d --build
```

Se **`security.insecure is not allowed`**, spesso basta Docker 23+ con **buildx** e lo script sopra. In alternativa, sul **daemon** Docker, in **`/etc/docker/daemon.json`** (JSON valido, unisci con le chiavi già presenti):

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

Poi `sudo systemctl restart docker` e rilancia `./raspberry-buster/build.sh` o il `compose` con merge.

## Dopo il primo build

Per riavviare **senza** ricostruire:

```text
docker compose -f docker-compose.yml -f raspberry-buster/docker-compose.buster.yml up -d
```

## Note

- Su molti ARM, `docker build` con `--security-opt seccomp=...` risponde che le security options **non sono supportate** su linux: per questo si usa l’approccio **BuildKit** / **`RUN --security=insecure`** sullo step `pip` e **`seccomp=unconfined`** a **runtime** via Compose.
- Il **`context`** di build resta la **root del repo** (`..` rispetto a questa cartella), così `COPY requirements.txt`, `app/` e `migrations/` funzionano come nel Dockerfile principale.
