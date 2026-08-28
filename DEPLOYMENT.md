# reekserver-1 deployment

Clone this repository to `/home/reek/apps/marketdesk`, create a mode-0600
`.env` from `.env.example`, then run `docker compose up -d --build`. This
project owns its Postgres volume and all provider/API credentials; it has no
LiteLLM dependency and no `cloudflared` service of its own. Public routing
goes through reekserver-1's shared Cloudflare Tunnel (id
`af0c35fc-ec30-407e-8f9c-56c76e4e8e22`, the same one serving OpenWebUI at
chat.camptwright.com):

1. `docker network connect marketdesk_default cloudflared` so the shared
   tunnel container can reach this stack.
2. In the Zero Trust dashboard, add a Public Hostname route on that tunnel
   pointing at `http://marketdesk-app-1:8000` (the container name, not the
   compose service alias — reachable because step 1 put both containers on
   the same Docker network).
3. Protect the API with an app-specific Access policy (recommended
   alongside `API_BEARER_TOKEN`, not a replacement for it).
