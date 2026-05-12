<div align="center">

[![PyPI Version](https://img.shields.io/pypi/v/vibravid?logo=pypi&logoColor=white&labelColor=2d3748&color=3182ce&style=for-the-badge)](https://pypi.org/project/vibravid/)
[![Sponsor](https://img.shields.io/badge/💖_Sponsor-ea4aaa?style=for-the-badge&logo=github-sponsors&logoColor=white&labelColor=2d3748)](https://ko-fi.com/arrowar)

[![Windows](https://img.shields.io/badge/🪟_Windows-0078D4?style=for-the-badge&logo=windows&logoColor=white&labelColor=2d3748)](https://github.com/AstraeLabs/VibraVid/releases/latest/download/VibraVid_win_2025_x64.exe)
[![macOS](https://img.shields.io/badge/🍎_macOS-000000?style=for-the-badge&logo=apple&logoColor=white&labelColor=2d3748)](https://github.com/AstraeLabs/VibraVid/releases/latest/download/VibraVid_mac_15_x64)
[![Linux](https://img.shields.io/badge/🐧_Linux_latest-FCC624?style=for-the-badge&logo=linux&logoColor=black&labelColor=2d3748)](https://github.com/AstraeLabs/VibraVid/releases/latest/download/VibraVid_linux_24_04_x64)

_⚡ **Quick Start:** `pip install VibraVid && VibraVid`_

**🌍 Language / Lingua**

[🇬🇧 English](README.md) | [🇮🇹 Italiano](./.github/docs/it/README.md)

</div>

---

## 📖 Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Login](.github/docs/en/login.md)
- [Downloaders](#downloaders)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Global Search](#global-search)
- [Advanced Features](#advanced-features)
- [ARR Integration](#arr-integration)
- [Docker](#docker)
- [Gui](./.github/docs/en/gui.md)
- [Related Projects](#related-projects)

---

## Installation

### Option 1 — PyPI (recommended)

```bash
pip install VibraVid
VibraVid
```

### Option 2 — uv

```bash
uv tool install VibraVid
VibraVid
```

### Option 3 — Manual Clone

```bash
git clone https://github.com/AstraeLabs/VibraVid.git
cd VibraVid
```

Then install and run with either **pip** or **uv**:

**pip:**
```bash
pip install -r requirements.txt   # install
python manual.py                  # run
python update.py                  # update
pip install -r requirements.txt --upgrade  # sync deps
```

**uv:**
```bash
uv sync              # install
uv run manual.py     # run
uv run update.py     # update
uv sync --upgrade    # sync deps
```

### Option 4 — Unraid

```
You can find the app in the Community Application
```

### Additional Documentation

- 📝 [Login Guide](.github/doc/login.md) — Authentication for supported services

---

## Quick Start

```bash
# PyPI or uv install
VibraVid

# Manual clone
python manual.py
```

---

## Downloaders

| Type     | Description                  | Example                                  |
| -------- | ---------------------------- | ---------------------------------------- |
| **HLS**  | HTTP Live Streaming (m3u8)   | [View example](./Test/Downloads/HLS.py)  |
| **MP4**  | Direct MP4 download          | [View example](./Test/Downloads/MP4.py)  |
| **DASH** | MPEG-DASH with DRM bypass\*  | [View example](./Test/Downloads/DASH.py) |
| **ISM** | Smooth Streaming with DRM bypass\*  | [View example](./Test/Downloads/ISM.py) |

> **\*DASH with DRM bypass:** Requires a valid L3\L2\L1\SL3000\SL2000 CDM (Content Decryption Module). This project does not provide or facilitate obtaining CDMs. Users must ensure compliance with applicable laws.

---

## Configuration

All settings live in `config.json`. The sections below cover each configuration block.

### DEFAULT

```json
{
  "DEFAULT": {
    "debug_track_json": false,
    "log_level": "INFO",
    "close_console": true,
    "show_message": false,
    "fetch_domain_online": true,
    "auto_update_check": true,
    "imp_service": ["default"],
    "installation": "essential"
  }
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `close_console` | `true` | Automatically close the console after download completes |
| `debug_track_json` | `false` | Log a `TRACKS_JSON` payload with selected tracks, keys, and manifest metadata — useful for debugging stream selection |
| `log_level` | `"INFO"` | Logging verbosity. Accepts standard Python values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `show_message` | `false` | Show the startup banner and clear the console before printing it |
| `fetch_domain_online` | `true` | Automatically fetch the latest domains from GitHub |
| `auto_update_check` | `true` | Notify you at startup when a new VibraVid version is available |
| `imp_service` | `["default"]` | Service source paths to load site modules from. `"default"` loads all built-in sites. Add absolute paths to directories containing custom site modules — each must have `__init__.py` defining `indice` and `_useFor`. Custom modules take precedence over built-ins with the same name. |
| `installation` | `"essential"` | Controls which bundled binaries are auto-downloaded at setup: `none` skips all, `essential` downloads Bento4, FFmpeg, and Velora, `full` also adds Dovi Tool and MKVToolNix |

**Custom `imp_service` example:**
```json
"imp_service": ["default", "/home/user/my_custom_sites"]
```

---

### OUTPUT

```json
{
  "OUTPUT": {
    "root_path": "Video",
    "movie_folder_name": "Movie",
    "serie_folder_name": "Serie",
    "anime_folder_name": "Anime",
    "movie_format": "%(title_name) (%(title_year))/%(title_name) (%(title_year))",
    "episode_format": "%(series_name)/S%(season:02d)/%(episode_name) S%(season:02d)E%(episode:02d)"
  }
}
```

**`root_path`** — Base directory where videos are saved.
- Windows: `C:\\MyLibrary\\Folder` or `\\\\MyServer\\Share`
- Linux/macOS: `Desktop/MyLibrary/Folder`

**`movie_folder_name`**, **`serie_folder_name`**, **`anime_folder_name`** — Subfolder names for each content type (defaults: `"Movie"`, `"Serie"`, `"Anime"`). All support the `%{site_name}` placeholder:

```
"Movie/%{site_name}"  →  "Movie/Crunchyroll"
"Serie/%{site_name}"  →  "Serie/Crunchyroll"
```

---

#### Movie Format

**Default:** `"%(title_name) (%(title_year))/%(title_name) (%(title_year))"`

```
%(title_name) (%(title_year))/   →  folder    Inception (2010)/
%(title_name) (%(title_year))    →  filename  Inception (2010).mkv
```

| Variable | Description |
|----------|-------------|
| `%(title_name)` | Movie title |
| `%(title_name_slug)` | Movie title as slug |
| `%(title_year)` | Release year (omitted if unavailable) |
| `%(quality)` | Video resolution |
| `%(language)` | Audio languages |
| `%(video_codec)` | Video codec |
| `%(audio_codec)` | Audio codec |

---

#### Episode Format

**Default:** `"%(series_name)/S%(season:02d)/%(episode_name) S%(season:02d)E%(episode:02d)"`

```
%(series_name)/     →  series folder   Breaking Bad/
S%(season:02d)/     →  season folder   S01/
%(episode_name)...  →  filename        Pilot S01E05.mkv
```

| Variable | Description |
|----------|-------------|
| `%(series_name)` | Series name |
| `%(series_name_slug)` | Series name as slug |
| `%(series_year)` | Series release year |
| `%(season:FORMAT)` | Season number with inline padding (see below) |
| `%(episode:FORMAT)` | Episode number with inline padding (see below) |
| `%(episode_name)` | Episode title (sanitized) |
| `%(episode_name_slug)` | Episode title as slug |
| `%(quality)` | Video resolution |
| `%(language)` | Audio languages |
| `%(video_codec)` | Video codec |
| `%(audio_codec)` | Audio codec |

**Inline padding syntax (for `season` and `episode`):**

| Token | Result (n=1) | Description |
|-------|-------------|-------------|
| `%(season:02d)` | `01` | Zero-pad to 2 digits |
| `%(season:03d)` | `001` | Zero-pad to 3 digits |
| `%(season:d)` | `1` | No padding |

---

### DOWNLOAD

```json
{
  "DOWNLOAD": {
    "auto_select": true,
    "delay_after_download": 1,
    "skip_download": false,
    "thread_count": 12,
    "concurrent_download": true,
    "select_video": "1920",
    "select_audio": "ita|Ita",
    "select_subtitle": "ita|eng|Ita|Eng",
    "cleanup_tmp_folder": true
  }
}
```

#### Performance Settings

| Key | Default | Description |
|-----|---------|-------------|
| `auto_select` | `true` | Automatically select streams based on filters. When `false`, enables interactive track selection before download |
| `delay_after_download` | `1` | Delay (seconds) applied after each movie or episode download |
| `skip_download` | `false` | Skip the download step and process existing files |
| `thread_count` | `12` | Number of concurrent segment requests for a single stream |
| `concurrent_download` | `true` | Download video, audio, and subtitles simultaneously |
| `cleanup_tmp_folder` | `true` | Remove temporary files after download |

#### Stream Selection Filters

Use `select_video`, `select_audio`, and `select_subtitle` to control which tracks are downloaded.

**Video (`select_video`):**

| Value | Description |
|-------|-------------|
| `"best"` | Best available resolution |
| `"worst"` | Worst available resolution |
| `"1080"` | Exact height (falls back to worst if not found) |
| `"1080,H265"` | Height + codec constraint |
| `"1080\|best"` | Height with fallback to best |
| `"1080\|best,H265"` | Height + codec with fallback to best |
| `"false"` | Skip video |

**Audio (`select_audio`):**

| Value | Description | If not found |
|-------|-------------|--------------|
| `"best"` | Best bitrate per language | Selects best across all |
| `"worst"` | Worst bitrate per language | Selects worst across all |
| `"all"` | All audio tracks | Downloads all |
| `"default"` | Streams marked as default | DROP |
| `"non-default"` | Streams NOT marked as default | DROP |
| `"ita"` | Italian audio | DROP |
| `"ita\|it"` | Pipe-separated language codes | DROP if none found |
| `"ita,MP4A"` | Language + codec | DROP if combination not found |
| `"ita\|best"` | Language with fallback to best | Fallback to best |
| `"ita\|best,AAC"` | Language + codec with fallback | Fallback to best |
| `"false"` | Skip audio | — |

**Subtitle (`select_subtitle`):**

| Value | Description |
|-------|-------------|
| `"all"` | All subtitles |
| `"default"` | Streams marked as default |
| `"non-default"` | Streams NOT marked as default |
| `"ita\|eng"` | Pipe-separated language codes |
| `"ita_forced"` | Language with flag (`forced`, `cc`, `sdh`) |
| `"ita_forced\|eng_cc"` | Multiple languages with flags |
| `"false"` | Skip subtitles |

---

### PROCESS (Post-Processing)

```json
{
  "PROCESS": {
    "use_gpu": false,
    "param_video": ["-c:v", "libx265", "-crf", "28", "-preset", "medium"],
    "param_audio": ["-c:a", "libopus", "-b:a", "128k"],
    "param_final": ["-c", "copy"],
    "audio_order": ["ita", "eng"],
    "subtitle_order": ["ita", "eng"],
    "merge_audio": true,
    "merge_subtitle": true,
    "subtitle_disposition_language": "ita_forced",
    "extension": "mkv"
  }
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `use_gpu` | `false` | Enable hardware acceleration. GPU type is auto-detected at runtime: `cuda` (NVIDIA), `qsv` (Intel), `vaapi` (AMD) |
| `param_video` | H.265/HEVC | FFmpeg video encoding parameters, e.g. `["-c:v", "libx265", "-crf", "28", "-preset", "medium"]` |
| `param_audio` | Opus 128k | FFmpeg audio encoding parameters, e.g. `["-c:a", "libopus", "-b:a", "128k"]` |
| `param_final` | `["-c", "copy"]` | Final FFmpeg parameters. When set, takes full precedence over `param_video` and `param_audio` |
| `audio_order` | — | Order of audio tracks in the output, e.g. `["ita", "eng"]` |
| `subtitle_order` | — | Order of subtitle tracks in the output, e.g. `["ita", "eng"]` |
| `merge_audio` | `true` | Merge all audio tracks into a single output file |
| `merge_subtitle` | `true` | Merge all subtitle tracks into a single output file |
| `subtitle_disposition_language` | — | Mark a specific subtitle track as default/forced |
| `extension` | `"mkv"` | Output container format: `"mkv"` or `"mp4"` |

**`force_subtitle`** — Controls how subtitles are handled before remuxing:

| Value | Behaviour |
|-------|-----------|
| `"auto"` (default) | Subtitles are renamed/converted based on their detected format. VTT files are sanitized (unmatched `<` replaced) to prevent data loss when muxed as SRT |
| `"copy"` | No conversion or renaming — the original file is muxed as-is. Also skips VTT sanitization |
| `"srt"` / `"vtt"` / `"ass"` | Force-convert all subtitles to the specified format using FFmpeg, with sanitization applied for `vtt` |

See `VibraVid/core/processors/helper/ex_sub.py` for conversion logic.

---

### REQUESTS

```json
{
  "REQUESTS": {
    "timeout": 30,
    "max_retry": 10,
    "use_proxy": false,
    "proxy": {
      "http": "http://localhost:8888",
      "https": "http://localhost:8888"
    }
  }
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `timeout` | `30` | Request timeout in seconds |
| `max_retry` | `10` | Maximum retry attempts for failed requests |
| `use_proxy` | `false` | Enable proxy support for HTTP requests |
| `proxy.http` | — | HTTP proxy URL |
| `proxy.https` | — | HTTPS proxy URL |

---

### ARR

The `ARR` block enables VibraVid to work as an automation layer between **Seerr/Jellyseerr**, **Sonarr**, **Radarr**, and the final media library.

When enabled, VibraVid can:

- read missing episodes from Sonarr;
- read missing movies from Radarr;
- receive webhook events from Seerr/Jellyseerr, Sonarr, and Radarr;
- download the requested media through VibraVid providers;
- ask Sonarr/Radarr to rescan or import the downloaded files;
- optionally mark successfully imported media as unmonitored.

```json
{
  "ARR": {
    "enabled": false,
    "enable_polling": false,
    "enable_seerr_webhook": false,
    "enable_sonarr_webhook": false,
    "enable_radarr_webhook": false,
    "polling_interval": 300,
    "full_resync_interval": 21600,
    "max_concurrent_downloads": 1,
    "webhook_priority_enabled": true,
    "native_webhook_priority_window_seconds": 120,
    "seerr_fallback_delay_seconds": 20,
    "seerr_webhook_secret": "",
    "sonarr_webhook_secret": "",
    "radarr_webhook_secret": "",
    "sonarr": {
      "url": "",
      "api_key": ""
    },
    "radarr": {
      "url": "",
      "api_key": ""
    }
  }
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Enables the ARR integration globally |
| `enable_polling` | `false` | Periodically scans Sonarr/Radarr for missing media |
| `enable_seerr_webhook` | `false` | Enables the Seerr/Jellyseerr webhook endpoint |
| `enable_sonarr_webhook` | `false` | Enables the Sonarr webhook endpoint |
| `enable_radarr_webhook` | `false` | Enables the Radarr webhook endpoint |
| `polling_interval` | `300` | Seconds between incremental polling cycles |
| `full_resync_interval` | `21600` | Seconds between full reconciliation syncs |
| `max_concurrent_downloads` | `1` | Maximum number of ARR-triggered downloads running at the same time |
| `webhook_priority_enabled` | `true` | Gives native Sonarr/Radarr webhook events priority over Seerr events to avoid duplicate processing |
| `native_webhook_priority_window_seconds` | `120` | Time window used to detect near-duplicate native webhook events |
| `seerr_fallback_delay_seconds` | `20` | Delay before processing Seerr webhook events when native Sonarr/Radarr webhooks may arrive |
| `seerr_webhook_secret` | — | Secret expected in the Seerr/Jellyseerr webhook request |
| `sonarr_webhook_secret` | — | Secret expected in the Sonarr webhook request |
| `radarr_webhook_secret` | — | Secret expected in the Radarr webhook request |
| `sonarr.url` | — | Base URL of the Sonarr instance, e.g. `http://sonarr:8989` |
| `sonarr.api_key` | — | Sonarr API key |
| `radarr.url` | — | Base URL of the Radarr instance, e.g. `http://radarr:7878` |
| `radarr.api_key` | — | Radarr API key |

#### Environment variables

The ARR integration can also be configured with environment variables, useful for Docker deployments:

```bash
USE_ARR_SERVICES=true
SONARR_URL=http://sonarr:8989
SONARR_API_KEY=your-sonarr-api-key
RADARR_URL=http://radarr:7878
RADARR_API_KEY=your-radarr-api-key
SEERR_WEBHOOK_SECRET=your-seerr-secret
SONARR_WEBHOOK_SECRET=your-sonarr-secret
RADARR_WEBHOOK_SECRET=your-radarr-secret
```

Environment variables are especially useful when the same container image is deployed across multiple environments.

#### Tag-based filtering and provider selection

ARR processing can be controlled through tags configured in **Sonarr**, **Radarr**, and, when available in the webhook/request metadata, **Seerr/Jellyseerr**.

Besides skip/hold tags, VibraVid can read a provider-selection tag using this format:

```text
provider-<vibravid-site-or-service>
```

The value after `provider-` must match the VibraVid site/service identifier that should be used for the download.

Examples:

```text
provider-streamingcommunity
provider-mycustomsite
```

| Tag | Behaviour |
|-----|-----------|
| `hold` | Skips the item temporarily |
| `pausa` | Skips the item temporarily |
| `skip-s1` | Skips season 1 of a series |
| `skip-s2` | Skips season 2 of a series, and so on |
| `provider-streamingcommunity` | Forces VibraVid to use the `streamingcommunity` provider for that item |
| `provider-<site>` | Forces VibraVid to use the matching site/service provider for that item |

Provider tags can be assigned directly to the movie in Radarr, to the series in Sonarr, or propagated from Seerr/Jellyseerr request metadata when that metadata is available to the webhook flow. If no provider tag is found, VibraVid falls back to the default configured provider.

---

### DRM

```json
{
  "DRM": {
    "use_cdm": true,
    "prefer_remote_cdm": true,
    "vault": {
      "supa": {
        "url": "https://crqczuxpqjmrjvdvqvlx.supabase.co",
        "token": ""
      }
    }
  }
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `use_cdm` | `true` | Enable CDM-based key extraction. When `false`, only database lookups are attempted |
| `prefer_remote_cdm` | `true` | Prefer remote CDM services over local device files |
| `vault` | — | Optional external DRM key store, queried before CDM extraction |

#### Remote CDM Services

When remote CDM services are available, add one or both of the following blocks to `config.json`:

**Widevine:**
```json
"widevine": {
  "device_type": "ANDROID",
  "system_id": 22590,
  "security_level": 3,
  "host": "https://cdrm-project.com/remotecdm/widevine",
  "secret": "CDRM",
  "device_name": "public"
}
```

| Key | Description |
|-----|-------------|
| `device_type` | Device model: `"ANDROID"` or `"CHROME"` |
| `system_id` | Widevine system ID (default `22590` for Android) |
| `security_level` | Security level 1–3 (3 = L3) |
| `host` | Remote CDM server URL |
| `secret` | Authentication secret |
| `device_name` | Device identifier registered on the remote service |

**PlayReady:**
```json
"playready": {
  "device_name": "public",
  "security_level": 3000,
  "host": "https://cdrm-project.com/remotecdm/playready",
  "secret": "CDRM"
}
```

| Key | Description |
|-----|-------------|
| `device_name` | Device identifier registered on the remote service |
| `security_level` | Security level (e.g. `3000` for SL3000) |
| `host` | Remote CDM server URL |
| `secret` | Authentication secret |

#### Local CDM Devices

To use local CDM device files instead of remote services, place them in the project root:

- **Widevine:** `.wvd` file (from pywidevine)
- **PlayReady:** `.prd` file (from pyplayready)

Set `prefer_remote_cdm` to `false` and local devices will be picked up automatically.

---

## Usage Examples

### Basic Commands

```bash
# Show help and available sites
python manual.py -h

# Search and download
python manual.py --site streamingcommunity --search "interstellar"

# Auto-download the first result
python manual.py --site streamingcommunity --search "interstellar" --auto-first

# Use a site by its index number
python manual.py --site 0 --search "interstellar"
```

### Series Selection

Use `--season` and `--episode` to skip interactive prompts:

```bash
# Specific episode
python manual.py --site streamingcommunity --search "breaking bad" --auto-first --season 1 --episode 3

# Range of episodes
python manual.py --site streamingcommunity --search "breaking bad" --auto-first --season 1 --episode "1-5"

# All episodes of a season
python manual.py --site streamingcommunity --search "breaking bad" --auto-first --season 1 --episode "*"

# All episodes of all seasons
python manual.py --site streamingcommunity --search "breaking bad" --auto-first --season "*"

# Multiple seasons
python manual.py --site streamingcommunity --search "breaking bad" --auto-first --season "1-3"
```

### Year Filter

```bash
# Exact year
python manual.py --site streamingcommunity --search "dune" --year 2021

# Year range
python manual.py --site streamingcommunity --search "batman" --year "1990-2015"
```

### Stream Track Overrides

```bash
# Video resolution
python manual.py --site streamingcommunity --search "interstellar" -sv 1080

# Audio language
python manual.py --site streamingcommunity --search "interstellar" -sa "eng"

# Subtitles
python manual.py --site streamingcommunity --search "interstellar" -ss "eng"
```

### Console Behaviour Override

```bash
# Keep console open (loop mode)
python manual.py --close-console false

# Close console after download
python manual.py --site streamingcommunity --search "interstellar" --close-console true
```

### Proxy

```bash
python manual.py --site streamingcommunity --search "interstellar" --use_proxy
```

### Show Dependency Paths

```bash
python manual.py --dep
```

---

## Global Search

```bash
# Global search
python manual.py --global -s "cars"

# Filter by category
python manual.py --category 1    # Anime
python manual.py --category 2    # Movies & Series
python manual.py --category 3    # Series only
```

---

## Advanced Features

### Hook System

Execute custom scripts at specific points in the download lifecycle. Hooks are configured in `config.json` under the `HOOKS` key.

**Available stages:**
- `pre_run` — runs before the main flow starts
- `post_download` — runs after each individual download completes (in the GUI, once per item)
- `post_run` — runs once when the overall execution ends

```json
{
  "HOOKS": {
    "pre_run": [
      {
        "name": "prepare-env",
        "type": "python",
        "path": "scripts/prepare.py",
        "args": ["--clean"],
        "env": { "MY_FLAG": "1" },
        "cwd": "~",
        "os": ["linux", "darwin"],
        "timeout": 60,
        "enabled": true,
        "continue_on_error": true
      }
    ],
    "post_download": [
      {
        "name": "post-download-env",
        "type": "python",
        "path": "/app/script.py",
        "args": ["{download_path}"],
        "env": { "MY_FLAG": "1" },
        "cwd": "~",
        "os": ["linux"],
        "timeout": 60,
        "enabled": true,
        "continue_on_error": true
      }
    ],
    "post_run": [
      {
        "name": "notify",
        "type": "bash",
        "command": "echo 'Download completed'"
      }
    ]
  }
}
```

#### Hook Options

| Key | Description |
|-----|-------------|
| `name` | Descriptive label for the hook |
| `type` | Script type: `python`, `bash`, `sh`, `shell`, `bat`, `cmd` |
| `path` | Path to script file (alternative to `command`) |
| `command` | Inline command to execute (alternative to `path`). Note: `args` are ignored when using `command` |
| `args` | List of arguments passed to the script |
| `env` | Additional environment variables as key-value pairs |
| `cwd` | Working directory for execution (supports `~` and env vars) |
| `os` | Optional OS filter: `["windows"]`, `["darwin"]`, `["linux"]`, or any combination |
| `timeout` | Maximum execution time in seconds (hook fails if exceeded) |
| `enabled` | Enable or disable the hook without removing it |
| `continue_on_error` | If `false`, stops execution when the hook fails |

#### Hook Types

- **Python:** runs with the current Python interpreter
- **Bash / sh / shell:** executed via `/bin/bash -c` on macOS/Linux
- **Bat / cmd / shell:** executed via `cmd /c` on Windows
- **Inline commands:** use `command` instead of `path` for simple one-liners

#### Context Placeholders

| Placeholder | Description |
|-------------|-------------|
| `{download_path}` | Absolute path of the downloaded file |
| `{download_dir}` | Directory containing the downloaded file |
| `{download_filename}` | Filename of the downloaded file |
| `{download_id}` | Internal download identifier |
| `{download_title}` | Download title |
| `{download_site}` | Source site name |
| `{download_media_type}` | Media type |
| `{download_status}` | Final download status |
| `{download_error}` | Error message, if any |
| `{download_success}` | `1` on success, `0` on failure |
| `{stage}` | Current hook stage |

The same values are also exposed as environment variables with the `SC_` prefix (e.g. `SC_DOWNLOAD_PATH`, `SC_DOWNLOAD_SUCCESS`, `SC_HOOK_STAGE`).

---

### Source Code Update (`update.py`)

```bash
# Interactive update
python update.py

# Skip first confirmation prompt
python update.py -y

# Cancel automatically without prompting
python update.py -n

# Preview what would be deleted without deleting anything
python update.py --dry-run

# Combine: skip first prompt + dry run
python update.py -y --dry-run
```

The following are **always preserved** during an update: folders `Video`, `Conf`, `.git` and file `update.py`.

---

## ARR Integration

VibraVid can be used as an automation component in a media-server stack with **Seerr/Jellyseerr**, **Sonarr**, and **Radarr**.

Typical flow:

```text
Seerr / Jellyseerr
    ↓ user requests a movie or series
Sonarr / Radarr
    ↓ media is added and marked as missing
VibraVid ARR
    ↓ detects missing media through polling or webhooks
VibraVid downloader
    ↓ searches and downloads through the configured provider or through the provider selected by tag
Sonarr / Radarr
    ↓ rescans/imports the downloaded file
Media library
    ↓ Jellyfin/Plex can detect the final file
```

### Supported integrations

| Service | Role |
|---------|------|
| **Seerr/Jellyseerr** | Handles user requests and sends approval/pending webhook events |
| **Sonarr** | Manages TV series, missing episodes, episode metadata, rescans and imports |
| **Radarr** | Manages movies, missing movie metadata, rescans and imports |
| **VibraVid** | Searches, downloads and hands files back to Sonarr/Radarr |

### Webhook endpoints

When the GUI/Django server is running, the ARR integration exposes dedicated webhook endpoints:

```text
POST /api/arr/webhook/seerr/
POST /api/arr/webhook/sonarr/
POST /api/arr/webhook/radarr/
```

Each endpoint can be protected with its own webhook secret. Configure the same secret both in VibraVid and in the corresponding external service.

### Manual and automatic sync

ARR can process media in two ways:

1. **Polling** — VibraVid periodically asks Sonarr/Radarr for wanted or missing media.
2. **Webhooks** — VibraVid reacts immediately when Seerr, Sonarr or Radarr sends an event.

Both modes can be enabled together. Native Sonarr/Radarr webhooks can be prioritized over Seerr events to reduce duplicate processing.

### Provider selection with tags

To force VibraVid to use a specific site/service for a movie, series or request, add a tag with the following format in Sonarr, Radarr or Seerr/Jellyseerr:

```text
provider-<vibravid-site-or-service>
```

For example, `provider-streamingcommunity` tells VibraVid ARR to use the `streamingcommunity` provider for that item. This is useful when different media should be downloaded from different VibraVid providers without changing the global configuration.

If multiple provider tags are present, the ARR processor uses the first valid provider tag it resolves from the item metadata. If no provider tag is found, the default provider is used.

### Sonarr workflow

For series, VibraVid ARR can:

- read missing episodes from Sonarr;
- resolve series, season and episode metadata;
- download the requested episode into the expected series path;
- trigger a Sonarr rescan/import;
- verify whether the episode was imported;
- optionally mark the episode as unmonitored after successful import.

### Radarr workflow

For movies, VibraVid ARR can:

- read missing movies from Radarr;
- resolve title, year and TMDB metadata;
- download the requested movie into the expected movie path;
- trigger a Radarr rescan/import;
- verify whether the movie was imported;
- optionally mark the movie as unmonitored after successful import.

### Recommended setup

Use shared volumes so VibraVid and Sonarr/Radarr see the same filesystem paths. If containers use different internal paths for the same media folder, imports may fail because Sonarr/Radarr will not find the downloaded files.

Example Docker path layout:

```text
/media
├── movies
├── series
└── downloads
```

Mount the same media root into VibraVid, Sonarr and Radarr whenever possible.

---

## Docker

### Recommended: Docker Compose

```bash
docker-compose up -d        # Start
docker-compose logs -f      # View logs
docker-compose down         # Stop (data persists)
```

### Private Network Deployment

Uncomment and edit the `environment` section in `docker-compose.yml`:

```yaml
environment:
  DJANGO_DEBUG: "false"
  ALLOWED_HOSTS: "streaming.example.local,localhost,127.0.0.1,192.168.1.50"
  CSRF_TRUSTED_ORIGINS: "https://streaming.example.local"
  USE_X_FORWARDED_HOST: "true"
  SECURE_PROXY_SSL_HEADER_ENABLED: "true"
  CSRF_COOKIE_SECURE: "true"
  SESSION_COOKIE_SECURE: "true"
  DJANGO_SECRET_KEY: "your-secure-secret-key-here"
```

ARR-related variables can be added to the same `environment` block:

```yaml
environment:
  USE_ARR_SERVICES: "true"
  SONARR_URL: "http://sonarr:8989"
  SONARR_API_KEY: "your-sonarr-api-key"
  RADARR_URL: "http://radarr:7878"
  RADARR_API_KEY: "your-radarr-api-key"
  SEERR_WEBHOOK_SECRET: "your-seerr-secret"
  SONARR_WEBHOOK_SECRET: "your-sonarr-secret"
  RADARR_WEBHOOK_SECRET: "your-radarr-secret"
```


### Manual Docker Build

```bash
docker build -t vibravid .

docker run -d \
  --name vibravid \
  -p 8000:8000 \
  -v vibravid_db:/app/GUI \
  -v vibravid_videos:/app/Video \
  -v vibravid_logs:/app/logs \
  -v vibravid_config:/app/Conf \
  --restart unless-stopped \
  vibravid
```

### Binding Local Folders

```bash
# Linux/macOS
docker run -d --name vibravid -p 8000:8000 \
  -v ~/Downloads/Videos:/app/Video \
  vibravid

# Windows (PowerShell)
docker run -d --name vibravid -p 8000:8000 `
  -v "D:\Video:/app/Video" `
  vibravid
```

---

## Related Projects

- **[MammaMia](https://github.com/UrloMythus/MammaMia)** — Stremio addon for Italian streaming (by UrloMythus)
- **[Unit3Dup](https://github.com/31December99/Unit3Dup)** — Torrent automation for Unit3D tracker (by 31December99)
- **[N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE)** — Universal downloader for HLS/DASH/ISM (by nilaoda)
- **[pywidevine](https://github.com/devine-dl/pywidevine)** — Widevine L3 decryption library (by devine-dl)
- **[pyplayready](https://git.gay/ready-dl/pyplayready)** — PlayReady decryption library (by ready-dl)

---

## Disclaimer

> This software is for **educational and research purposes only**. The authors:
>
> - **DO NOT** assume responsibility for illegal use
> - **DO NOT** provide or facilitate DRM circumvention tools, CDMs, or decryption keys
> - **DO NOT** endorse piracy or copyright infringement
>
> By using this software, you agree to comply with all applicable laws and confirm you have rights to any content you process. No warranty is provided.

---

<div align="center">

**Made with ❤️ for streaming lovers**

*If you find this project useful, consider starring it! ⭐*

</div>
