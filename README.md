# Sklio - Backend (Flask + Docker)

## Overview
This repository contains the backend for Sklio — a local skill marketplace. It includes:
- Flask app with JWT auth
- SQLAlchemy models: User, Skill, Booking
- Socket.IO skeleton for chat
- AI endpoints for profile generation & price prediction (stubs)
- Docker + docker-compose for local dev (Postgres + Redis + Web)

---

## Quick start (Docker)

1. Copy `.env.example` to `.env` and edit if needed:
   ```bash
   cp .env.example .env
   # edit .env if you want to set OPENAI_API_KEY etc.
