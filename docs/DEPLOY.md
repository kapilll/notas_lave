# Deploying Notas Lave — Free 24/7 Setup

**Cost: $0/month** (Oracle Cloud free tier + GitHub Actions + Cloudflare free)

---

## Architecture

```
Push to GitHub → GitHub Actions (test + SSH deploy) → Oracle Cloud VM
                                                       ├── Engine (port 8000, internal)
                                                       ├── Dashboard (port 3000, internal)
                                                       └── Cloudflare Tunnel → yourdomain.com
```

## Step 1: Oracle Cloud VM (free forever)

1. Sign up at https://cloud.oracle.com (free tier, no charges)
2. Create a Compute Instance:
   - Shape: **Ampere A1** (ARM) — 4 OCPU, 24 GB RAM
   - Image: **Ubuntu 22.04**
   - Storage: 100 GB (up to 200 GB free)
   - Network: assign a public IP
3. SSH in and install Docker:
   ```bash
   ssh ubuntu@your-vm-ip
   sudo apt update && sudo apt install -y docker.io docker-compose-plugin
   sudo usermod -aG docker $USER
   # Log out and back in
   ```

## Step 2: Clone and Configure

```bash
git clone git@github.com:kapilll/notas_lave.git ~/notas_lave
cd ~/notas_lave

# Create .env with your keys
cat > engine/.env << 'EOF'
BINANCE_TESTNET_KEY=your_key
BINANCE_TESTNET_SECRET=your_secret
BROKER=binance_testnet
TRADING_MODE=personal
CLAUDE_PROVIDER=vertex
GOOGLE_CLOUD_PROJECT=your_project
GOOGLE_CLOUD_REGION=us-east5
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
TWELVEDATA_API_KEY=your_key
EOF

chmod 600 engine/.env
```

## Step 3: Start

```bash
# Local (no tunnel)
docker compose up -d

# With Cloudflare Tunnel
docker compose --profile cloud up -d

# Check status
docker compose ps
docker compose logs -f engine
```

## Step 4: CI/CD (auto-deploy on push)

Add these secrets to your GitHub repo (Settings → Secrets → Actions):

| Secret | Value |
|--------|-------|
| `VPS_HOST` | Your Oracle VM public IP |
| `VPS_USER` | `ubuntu` (or your SSH user) |
| `VPS_SSH_KEY` | Contents of `~/.ssh/id_ed25519` (private key) |

Now every push to `main`:
1. GitHub Actions runs tests
2. If tests pass → SSH into VM → `git pull && docker compose up -d --build`
3. New code is live in ~2 minutes

## Step 5: Cloudflare Tunnel (optional but recommended)

1. Sign up at https://dash.cloudflare.com
2. Add your domain → change nameservers to Cloudflare
3. Go to **Zero Trust → Networks → Tunnels → Create**
4. Name: `notas-lave`
5. Copy the tunnel token
6. Add to your VM's `.env`:
   ```
   CLOUDFLARE_TUNNEL_TOKEN=your_token_here
   ```
7. In Cloudflare dashboard, add a public hostname:
   - Subdomain: `trade` (or whatever you want)
   - Service: `http://dashboard:3000`
8. Start with tunnel: `docker compose --profile cloud up -d`

Your dashboard is now at `https://trade.yourdomain.com` with:
- HTTPS automatic (Cloudflare handles SSL)
- No ports open on the VM
- DDoS protection included

## Step 6: Cloudflare Access (lock it down)

1. In Cloudflare Zero Trust → Access → Applications → Add
2. Application domain: `trade.yourdomain.com`
3. Policy: allow your email only
4. Now only you can access the dashboard (login required)

---

## Useful Commands

```bash
# View logs
docker compose logs -f engine
docker compose logs -f dashboard

# Restart engine only (preserves data)
docker compose restart engine

# Full rebuild (after major changes)
docker compose up -d --build

# Check engine health
curl http://localhost:8000/health

# Verify data integrity
curl http://localhost:8000/api/lab/verify

# Sync balance from Binance
curl -X POST http://localhost:8000/api/lab/sync-balance

# Stop everything (positions stay open on Binance!)
docker compose down

# Stop and remove data (CAREFUL — deletes trade history)
docker compose down -v
```

## What Survives What

| Event | Positions on Binance | Trade history | Engine state |
|-------|---------------------|---------------|--------------|
| Engine restart | Stay open | Preserved (DB) | Reloaded |
| Container rebuild | Stay open | Preserved (volume) | Reloaded |
| VM reboot | Stay open | Preserved (disk) | Auto-starts |
| `docker compose down` | Stay open | Preserved (volume) | Stopped |
| `docker compose down -v` | Stay open | **DELETED** | Stopped |

## Estimated Resources

| Component | RAM | CPU | Disk |
|-----------|-----|-----|------|
| Engine | ~200 MB | ~5% | ~50 MB |
| Dashboard | ~100 MB | ~2% | ~200 MB |
| Tunnel | ~30 MB | ~1% | ~10 MB |
| **Total** | **~330 MB** | **~8%** | **~260 MB** |

Oracle free VM has 24 GB RAM and 4 cores — this uses ~1.4% of it.
