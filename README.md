# ⚽ Piala Dunia Live

Mobile-first streaming hub untuk Piala Dunia FIFA & sports lainnya.

## Features

- 🎬 HLS.js player (adaptive bitrate 240p - 1080p)
- 📱 Mobile-optimized (touch-friendly, fullscreen support)
- ⚡ 68 verified live stream dari mflixott.com
- 🌐 Offline-capable PWA
- 🎨 Dark mode UI
- 🏷️ Kategori: ⚽ World Cup, 🏏 Sports, 📺 Other Live

## Stream List

Lihat file [`public/piala_dunia.m3u`](public/piala_dunia.m3u) untuk playlist lengkap (68 stream).

## Run Locally

```bash
cd /home/home/projects/piala-dunia-live
python3 -m http.server 8080
# Buka http://localhost:8080
```

## Deploy ke Vercel

```bash
# Upload ke Vercel project 'piala-dunia-live'
# Auto-deploy on push
```