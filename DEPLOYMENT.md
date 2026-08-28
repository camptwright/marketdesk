# reekserver-1 deployment

Clone this repository to `/opt/apps/marketdesk`, create a mode-0600 `.env`
from `.env.example`, then run `docker compose up -d --build`. Configure a
dedicated Cloudflare Tunnel to `http://app:8000` and protect the API with an
app-specific Access policy. This project owns its Postgres volume and all
provider/API credentials; it has no LiteLLM dependency.
