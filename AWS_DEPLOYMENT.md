# AWS Deployment Guide

This guide describes how to deploy Qubitx on AWS while preserving the current Zerodha-native service architecture.

## Recommended AWS Shape

```text
EC2
  -> Docker Compose
  -> api
  -> worker
  -> scheduler
  -> live-engine

RDS PostgreSQL
ElastiCache Redis
ALB or Nginx for HTTPS
```

## Why This Shape Fits

- It matches the current Docker Compose deployment model.
- It keeps the app services separate from PostgreSQL and Redis.
- It supports future evolution without forcing an early Kubernetes or ECS jump.

## Recommended AWS Services

### Database

- Amazon RDS PostgreSQL

### Queue

- Amazon ElastiCache for Redis

### Compute

- EC2 with Docker Engine and Docker Compose

### TLS and routing

- Application Load Balancer with ACM, or
- Nginx on the EC2 host with Let’s Encrypt

## Required Environment Variables

- `DATABASE_URL`
- `REDIS_URL`
- `REDIS_QUEUE_PREFIX`
- `JWT_SECRET`
- `ZERODHA_API_KEY`
- `ZERODHA_API_SECRET`
- `ZERODHA_ACCESS_TOKEN`
- `ZERODHA_REDIRECT_URL`
- `ZERODHA_LIVE_TRADING_ENABLED`
- `PAPER_TRADING_ENABLED`
- `DAILY_SCAN_TIME`
- `MARKET_TIMEZONE`
- `BUY_VOLUME_MULTIPLIER`
- `SELL_VOLUME_MULTIPLIER`
- `ENTRY_BUFFER_TICKS`
- `STOP_BUFFER_TICKS`
- `API_HOST_PORT`
- `API_HOST_BIND`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `SESSION_COOKIE_NAME`
- `SESSION_COOKIE_SECURE`
- `INITIAL_ADMIN_EMAIL`
- `INITIAL_ADMIN_PASSWORD`
- `INITIAL_ADMIN_NAME`
- `TOTP_ISSUER`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `MOCK_DATA`

## PostgreSQL Setup

Recommended SQL:

```sql
CREATE USER qubitx_user WITH PASSWORD 'change-me';
CREATE DATABASE qubitx OWNER qubitx_user;
GRANT ALL PRIVILEGES ON DATABASE qubitx TO qubitx_user;
```

Example URL:

```text
postgresql+psycopg2://qubitx_user:change-me@your-rds-endpoint:5432/qubitx
```

## Redis Setup

Example:

```text
REDIS_URL=redis://your-elasticache-endpoint:6379/2
REDIS_QUEUE_PREFIX=qubitx
```

## EC2 Deployment Steps

### 1. Launch the instance

Use Ubuntu 24.04 LTS or another current Linux distribution.

### 2. Install Docker

Install:

- Docker Engine
- Docker Compose plugin

### 3. Copy the repository

Deploy the code into a stable directory such as:

```bash
mkdir -p ~/qubitx
cd ~/qubitx
```

### 4. Create `.env`

Use `.env.example` as the template and fill in your AWS-specific values.

### 5. Run migrations

```bash
docker compose run --rm migrate
```

### 6. Start the services

```bash
docker compose up --build -d api worker scheduler live-engine
```

### 7. Verify health

```bash
curl http://127.0.0.1:8095/health
```

## Reverse Proxy Examples

### Nginx

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8095;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### ALB

- Listener on `443`
- ACM certificate
- Target group forwarding to the EC2 host on the configured API host port

## Zerodha Token Workflow

This build expects `ZERODHA_ACCESS_TOKEN` to be supplied by the deployment environment.

Recommended daily operations:

1. update the access token in your secret store
2. restart Qubitx services if necessary
3. verify `/system/dependencies`

## Operational Commands

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f scheduler
docker compose logs -f live-engine
docker compose run --rm migrate
```

## Rollback Guidance

If a deployment fails:

1. inspect `docker compose logs api worker scheduler live-engine`
2. verify database and Redis reachability
3. confirm the latest migration completed cleanly
4. redeploy the previous known-good commit
5. rerun migrations only if the previous commit expects the same schema state

## Current Limitation

This repository has local unit coverage for the trading logic, but AWS deployment still depends on valid external PostgreSQL, Redis, and Zerodha credentials at deploy time.
