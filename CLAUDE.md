# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

太空农业智能种植舱 — an ESP32 + MicroPython + cloud-AI plant-care system, packaged as a STEM science-competition entry. The narrative framing is "space agriculture" (autonomous, fault-tolerant, comms-tolerant), but the hardware is a ground prototype. Scoring rubric the project targets: 科学性 40 + 创新性 30 + 演讲 20 + 展示力 10.

The repo contains three coupled deliverables:
1. **Firmware** (`esp32_firmware/`) — runs on the ESP32 via MicroPython.
2. **Dashboard + AI proxy** (`tools/`) — Python HTTP servers that run on a PC/cloud box, NOT on the ESP32.
3. **Contest deliverables** (`deliverables/`) — KT board designs, judge-walkthrough scripts, acceptance checklists.

Edits to firmware almost always need a matching edit in `tests/` (PC-side mocks) and frequently in `deliverables/评委展示方案.md` (talking points) or `README.md` (headline numbers). Keep the three in sync.

## Common commands

All commands run from `太空农业种植舱项目/` (the directory containing this file). Shell is PowerShell on Windows; `py` is the Python launcher.

```powershell
# Full test suite (PC-side, uses MicroPython mocks from tests/conftest.py)
py -m pytest

# Single test file or class or method
py -m pytest tests/test_local_decision.py
py -m pytest tests/test_local_decision.py::TestTemperatureSafety
py -m pytest tests/test_local_decision.py::TestTemperatureSafety::test_high_temp_skips_normal_watering

# Quiet / short traceback while iterating
py -m pytest -q --tb=short

# Realtime dashboard (browser opens http://127.0.0.1:8790/)
py tools/dashboard_server.py --host 0.0.0.0 --port 8790
# or, Windows one-liner:
powershell -ExecutionPolicy Bypass -File tools\start_dashboard_server.ps1

# AI proxy (optional — only needed when ESP32 routes via local proxy instead of direct TLS)
py tools/ai_proxy.py
```

There is no build step, no linter config, no CI workflow. Tests are the only automated gate.

### Flashing / running firmware on hardware

```powershell
# Upload all firmware modules (run after editing any *.py in esp32_firmware/)
py -m mpremote connect COM3 cp esp32_firmware/main.py :
py -m mpremote connect COM3 cp esp32_firmware/loop_runtime.py :
# ...repeat for every module — see esp32_firmware/README.md for the full list

# Interrupt a running main.py before re-uploading
py -m mpremote connect COM3 soft-reset

# Per-subsystem smoke tests on device
py -m mpremote connect COM3 exec "import sensors; sensors.init(); sensors.test_all()"
py -m mpremote connect COM3 exec "import actuators; actuators.init(); actuators.test_sequence()"
py -m mpremote connect COM3 exec "import ai_client; ai_client.test_api()"
```

`esp32_firmware/config.py` is gitignored. To set up a new device: `cp config.py.example config.py`, then fill in WiFi / API key / dashboard URL.

## Architecture

### Firmware: dependency-injected runtime modules

`esp32_firmware/main.py` is intentionally thin — it wires shared state and side-effect functions into the runtime modules. It does **not** contain logic. Each `*_runtime.py` module is a pure orchestrator that receives its collaborators as parameters, which is why tests can drive them with mocks without monkey-patching globals.

The runtime layers and where to look for each concern:

| Concern | Module | Notes |
|---|---|---|
| Shared mutable state | `state.py` (`SystemState`) | Single source of truth passed into every runtime |
| Boot sequence | `boot_runtime.py` | OLED bring-up, WiFi connect, first sample |
| Main loop scheduling | `loop_runtime.py` | Read every `READ_INTERVAL`s, decide every `DECISION_INTERVAL`s, reconnect on WiFi drop |
| Sampling + offline degradation | `sensor_runtime.py` → `sensors.py` | Returns `None` on failure; runtime degrades to safe defaults |
| Decision orchestration | `decision.py` | **AI gating lives here**, not in `ai_client.py` |
| Local fallback rules | `utils.local_fallback_decision` | Pure function — easy to test, no I/O |
| AI HTTP + parsing | `ai_client.py` | Builds prompt, posts, parses JSON, returns `None` on any failure |
| Action execution + safety | `action_runtime.py` → `actuators.py` | Single 12V pump (no nutrient pump since 2026-05-27); enforces `PUMP_MAX_RUN_SEC`, `MIN_ACTION_INTERVAL`, hourly cap |
| OLED 3-page rotation | `display_runtime.py` → `display.py` → `sh1106.py` | English-only (built-in ASCII font) |
| Status indicator | `status_strip.py` (WS2812 11 LEDs) | Soil moisture thermometer + system status. `utils.set_led/blink_led` are thin compat wrappers around it. |
| Dashboard upload | `telemetry.py` | One-way POST to dashboard server; no command channel back |

### Decision gating (the key non-obvious piece)

`decision.make_decision` does **not** unconditionally call the cloud AI. It always computes a local fallback first, then `_should_request_ai` checks three triggers — threshold event, sensor delta exceeds `AI_*_DELTA`, or periodic recheck — and additionally rate-limits via `AI_MIN_REQUEST_INTERVAL`. Even when allowed, it gates on free heap (`AI_MIN_FREE_MEM`) because TLS handshake on ESP32 needs ~110 KB free. When the proxy is configured (`AI_PROXY_URL`), the heap gate and OLED release step are skipped (proxy uses plain HTTP).

If you add a new sensor channel or decision input, you must touch all three:
1. `decision._sensor_snapshot` and `_ai_input_changed` (for AI gating)
2. `utils.local_fallback_decision` (for offline behavior)
3. `ai_client.SYSTEM_PROMPT` + `_build_payload` (so cloud AI uses the same rules)

The temperature safety rule (added 2026-05) is the worked example — see `TestTemperatureSafety` in `tests/test_local_decision.py`.

### Self-imposed autonomy boundary

The mermaid diagram in `README.md` calls out that the dashboard is **read-only telemetry** — there is no command channel from PC back to ESP32. This is deliberate (it maps to the "deep space delay" narrative). Do not add a downstream control path without first asking; it breaks the story.

### Testing harness

`tests/conftest.py` injects mock modules for `machine`, `network`, `dht`, `sh1106`, `urequests`, `ujson`, `gc` into `sys.modules` **at import time**, then adds `esp32_firmware/` to `sys.path`. It also loads `config.py` if present, otherwise falls back to `config.py.example` (this is how CI-style runs work without a real device config). `open('plants.json')` is monkey-patched to find the file regardless of CWD.

Consequences:
- Any new MicroPython-only API (anything from `machine`, `network`, `dht`, `urequests`, etc.) needs a matching mock in `conftest.py` or tests will fail at import.
- Adding a new config constant: it must exist in **both** `config.py.example` and the developer's local `config.py`, otherwise the test that exercises it will skip the constant via `getattr(config, "X", default)` and silently use defaults. Prefer `getattr(config, "X", default)` in firmware code for forward compatibility.

### Cross-document invariants

These pieces of data are duplicated across files and must move together:

| Datum | Authoritative source | Mirrors to update |
|---|---|---|
| Plant count phrasing | `plants.json` (14 entries) + 3-bit DIP (8 selectable) | `README.md`, `deliverables/评委展示方案.md`, `deliverables/KT板设计文档.md`, `deliverables/KT板展示设计-最新版.md`, `deliverables/KT板打印稿-120x90.html`, `智能种植舱控制器选型报告.md`. Canonical phrasing: **"库内 14 种 / 现场拨码 8 种"**. |
| Test count | `py -m pytest` output | README badge + `## 📊 数据见证` table + `测试指南.md` |
| BOM / cost | `智能种植舱控制器选型报告.md` BOM table (current: ¥122/套 single-pump) | README badge, KT board, judge script |
| Hardware action set | `action_runtime.py` `valid_actions` tuple | `ai_client.SYSTEM_PROMPT`, `tools/ai_proxy._validate_decision`, `tools/dashboard_server._validate_state`, `deliverables/contest-demo-dashboard.html` action labels |
| AI model name | `config.py` `AI_MODEL` | judge Q&A in `deliverables/评委展示方案.md`, KT board tech-spec table |

When you change one, grep for the others before committing.

### Known design limits (do not "fix" without asking)

- **Pump execution blocks the main loop** for up to `PUMP_MAX_RUN_SEC` (60s). This is documented in `esp32_firmware/README.md` as an intentional simplification; sampling period is 60s, so the impact is minimal. Don't refactor to async timers without confirming with the user — the test suite assumes synchronous semantics.
- **OLED uses built-in ASCII font only** — plant names are mapped to English in `display._PLANT_NAMES`. Adding a new plant to `plants.json` also requires adding a name there or it falls through to the raw Chinese (which won't render).
- **Telemetry is fire-and-forget** with a short timeout (`DASHBOARD_TIMEOUT=2`); failures are swallowed by design so dashboard outages don't stall the control loop.
- **Single-pump architecture (2026-05-27)** — there is no nutrient pump. The action set is `{water, idle}`. `action_runtime` and `ai_proxy._validate_decision` and `dashboard_server._validate_state` all silently remap any legacy `nutrient` action to `idle` for forward-compat with old recordings/AI hallucinations. Don't reintroduce `nutrient` without first adding hardware back and updating all three sites.
- **WS2812 is the only status indicator on GPIO26** — GPIO27 is free, the old red/green LED pins are gone. If you add new visual signaling, prefer extending `status_strip.py` over re-adding discrete LEDs.

## Source-of-truth notes

- `deliverables/仓库架构评估.md` is the project's own architecture self-assessment; keep it updated if you do structural refactors.
- `deliverables/实机验收清单.md` is the pre-demo hardware checklist — useful to read before suggesting hardware-touching changes.
- `测试指南.md` documents the four-tier test taxonomy; if you add a new test class, slot it into the table at line 232 onward.
- `智能种植舱控制器选型报告.md` is the hardware BOM and wiring report — when answering hardware questions, prefer it over inferring from code.
