# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

太空农业智能种植舱 — an ESP32 + MicroPython + cloud-AI plant-care system, packaged as a STEM science-competition entry. The narrative framing is "space agriculture" (autonomous, fault-tolerant, comms-tolerant), but the hardware is a ground prototype. Scoring rubric the project targets: 科学性 40 + 创新性 30 + 演讲 20 + 展示力 10.

The repo contains three coupled deliverables:
1. **Firmware** (`esp32_firmware/`) — runs on the ESP32 via MicroPython.
2. **Pi gateway + dashboard + AI** (`tools/`) — Python that runs on the Raspberry Pi / a PC/cloud box, NOT on the ESP32: `serial_gateway.py` (UART↔Pi gateway), `pi_advisor.py` (DeepSeek advisor), `dashboard_server.py`, `ai_proxy.py`.
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

# Raspberry Pi UART gateway (runs on the Pi; DeepSeek advice + dashboard forward)
python3 tools/serial_gateway.py --port /dev/serial0 --baud 115200 --ai-advice
#   SPACEFARM_AI_API_KEY / SPACEFARM_DASHBOARD env vars supply the DeepSeek key + dashboard URL

# AI proxy (standalone HTTP→DeepSeek relay; legacy, the gateway now calls DeepSeek itself)
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
```

`esp32_firmware/config.py` is gitignored. To set up a new device: `cp config.py.example config.py` (the ESP32 config no longer holds WiFi/AI/dashboard secrets — those moved to the Pi). DeepSeek key/model live on the Raspberry Pi as `SPACEFARM_AI_*` env vars; see `tools/pi_advisor.py` and `tools/serial_gateway.py --ai-advice`.

## Architecture

### Firmware: dependency-injected runtime modules

`esp32_firmware/main.py` is intentionally thin — it wires shared state and side-effect functions into the runtime modules. It does **not** contain logic. Each `*_runtime.py` module is a pure orchestrator that receives its collaborators as parameters, which is why tests can drive them with mocks without monkey-patching globals.

The runtime layers and where to look for each concern:

| Concern | Module | Notes |
|---|---|---|
| Shared mutable state | `state.py` (`SystemState`) | Single source of truth passed into every runtime |
| Boot sequence | `boot_runtime.py` | OLED/sensor/actuator bring-up + first sample. **No WiFi** — the Raspberry Pi handles networking. |
| Main loop scheduling | `loop_runtime.py` | Read every `READ_INTERVAL`s, decide every `DECISION_INTERVAL`s, exchange report/advice with the Pi over UART |
| Sampling + offline degradation | `sensor_runtime.py` → `sensors.py` | Returns `None` on failure; runtime degrades to safe defaults |
| Decision orchestration | `decision.py` | Computes the **local rule fallback**. Online Pi advice is applied in `main.make_decision` and takes priority. Cloud AI (DeepSeek) now lives on the Pi — see `tools/pi_advisor.py`. |
| Local fallback rules | `utils.local_fallback_decision` | Pure function — easy to test, no I/O |
| ESP32↔Pi UART link | `uart_link.py` | JSON-over-Line report/advice/ping/pong; the ESP32's **only** uplink/downlink. Mirrored on CPython by `tools/serial_gateway.py`. |
| Action execution + safety | `action_runtime.py` → `actuators.py` | 12V pump + 12V COB grow light (no nutrient pump since 2026-05-27); enforces `PUMP_MAX_RUN_SEC`, `LIGHT_MAX_RUN_SEC`, `MIN_ACTION_INTERVAL`, hourly cap |
| OLED 3-page rotation | `display_runtime.py` → `display.py` → `sh1106.py` | English-only (built-in ASCII font) |
| Status indicator | `status_strip.py` (WS2812 11 LEDs) | Soil moisture thermometer + system status + **Decision Plane signal animations** (12 signal types). `utils.set_led/blink_led` are thin compat wrappers around it. `utils.play_signal/play_signals` broadcast advisory signals visually. |

### Decision: three-layer degradation (the key non-obvious piece)

Since the 2026-05-30 dual-layer refactor, the cloud AI no longer runs on the ESP32. Decisions degrade across three layers (smartest → most reliable):

1. **DeepSeek** — runs on the **Raspberry Pi** (`tools/pi_advisor.py`, called by `serial_gateway --ai-advice`). The Pi builds the prompt from the ESP32 `report`, calls DeepSeek, and sends the decision back as a UART `advice`.
2. **Pi heuristic** — `serial_gateway._heuristic_advice_from_report` (a tiny soil/light threshold rule). Used automatically when DeepSeek fails.
3. **ESP32 local rules** — `utils.local_fallback_decision`, the resident on-board fallback used whenever no online Pi advice is present.

On the ESP32, `main.make_decision` first takes any online Pi advice (`_take_pi_decision`, guarded by `_guard_pi_decision` for temp/duration safety), otherwise falls back to `decision.make_decision` → `utils.local_fallback_decision`. **There is no cloud-AI call, no AI gating, no TLS heap management on the ESP32 anymore** (all removed with `ai_client.py`/`wifi_client.py`/`telemetry.py`).

If you add a new sensor channel or decision input, you must touch both decision brains:
1. `utils.local_fallback_decision` (ESP32 offline behavior) — and `decision.py`/`tests/test_local_decision.py`
2. `tools/pi_advisor.SYSTEM_PROMPT` + `build_messages` (so the Pi-side DeepSeek uses the same rules)

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
| Plant count phrasing | `plants.json` (8 entries, selectable via HS-S32-L rotary encoder + OLED menu) | `README.md`, `deliverables/评委展示方案.md`, `deliverables/KT板设计文档.md`, `deliverables/KT板展示设计-最新版.md`, `deliverables/KT板打印稿-120x90.html`, `智能种植舱控制器选型报告.md`. Canonical phrasing: **"8 种作物（叶菜 4 + 果菜 4）"**. The earlier 14/8 split has been retired (2026-05-27) to avoid judge confusion. DIP switch replaced by rotary encoder (2026-05-28). |
| Test count | `py -m pytest` output | README badge + `## 📊 数据见证` table + `测试指南.md` |
| BOM / cost | `智能种植舱控制器选型报告.md` BOM table (current: ¥140/套 pump+light) | README badge, KT board, judge script |
| Hardware action set | `action_runtime.py` `valid_actions` tuple (`water`, `light`, `idle`) | `tools/pi_advisor.SYSTEM_PROMPT`+`validate_decision`, `tools/ai_proxy._validate_decision`, `tools/dashboard_server._validate_state`, `deliverables/contest-demo-dashboard.html` action labels, `uart_link._PRIMARY_TO_ACTION`/`VALID_ACTIONS` |
| Signal types | `status_strip.py` signal constants (WATER, LIGHT_LOW, LIGHT_HIGH, TEMP_HIGH, TEMP_LOW, HUMID_LOW, NEED_N, NEED_P, NEED_K, SENSOR_FAIL, OFFLINE_MODE, BREEDING_GEN_UP) | `ai_proxy._validate_decision` signal whitelist, `contest-demo-dashboard.html` SIGNAL_LABELS, `uart_link.VALID_SIGNALS`, `tools/serial_gateway.VALID_SIGNALS`, `tools/pi_advisor.VALID_SIGNALS` (cross-checked by `test_serial_gateway.test_signal_whitelists_match_between_sides` + `test_pi_advisor.test_signal_whitelist_matches_uart_link`) |
| UART link protocol (2026-05-30) | `esp32_firmware/uart_link.py` (JSON-over-Line: report/advice/ping/pong, msg-type constants, `decode_line`/`encode_line`) | `tools/serial_gateway.py` mirrors it on CPython. The two are kept wire-compatible by the cross-side tests in `tests/test_serial_gateway.py`. When you change one side's framing/fields, change the other and run those tests. |
| AI model name | Raspberry Pi env `SPACEFARM_AI_MODEL` (default in `tools/pi_advisor.DeepSeekAdvisor`) | judge Q&A in `deliverables/评委展示方案.md`, KT board tech-spec table |

When you change one, grep for the others before committing.

### Known design limits (do not "fix" without asking)

- **Pump execution blocks the main loop** for up to `PUMP_MAX_RUN_SEC` (60s). This is documented in `esp32_firmware/README.md` as an intentional simplification; sampling period is 60s, so the impact is minimal. Don't refactor to async timers without confirming with the user — the test suite assumes synchronous semantics.
- **OLED uses built-in ASCII font only** — plant names are mapped to English in `display._PLANT_NAMES`. Adding a new plant to `plants.json` also requires adding a name there or it falls through to the raw Chinese (which won't render).
- **Dashboard forwarding is the Pi gateway's job** (`serial_gateway` POSTs each ESP32 report to `--dashboard`/`$SPACEFARM_DASHBOARD`); failures are swallowed by design so dashboard outages don't stall the gateway. The ESP32 no longer uploads telemetry itself (`telemetry.py` was removed in the 2026-05-30 refactor).
- **Pump + grow light architecture (2026-05-27)** — there is no nutrient pump. The action set is `{water, light, idle}`. `action_runtime` and `ai_proxy._validate_decision` and `dashboard_server._validate_state` all silently remap any legacy `nutrient` action to `idle` for forward-compat with old recordings/AI hallucinations. Don't reintroduce `nutrient` without first adding hardware back and updating all three sites.
- **WS2812 is the only status indicator on GPIO26** — GPIO27 is free, the old red/green LED pins are gone. If you add new visual signaling, prefer extending `status_strip.py` over re-adding discrete LEDs.
- **Decision Plane / Action Plane separation (2026-05-28)** — The decision output includes `signals[]` (advisory signals for WS2812 broadcast) and `breeding_observation` (growth observation for telemetry). PHYSICAL_SIGNALS = {WATER, LIGHT_LOW} trigger real actuators; all other signals (TEMP_HIGH, NEED_N, etc.) are advisory-only and broadcast via WS2812 animations. This means the system can diagnose conditions even without corresponding hardware (e.g., "缺氮" signal broadcasts without a nutrient pump). When adding new signal types, update: `status_strip.py` signal constants + animation mapping, `ai_proxy._validate_decision` signal whitelist, `contest-demo-dashboard.html` SIGNAL_LABELS.

## Source-of-truth notes

- `deliverables/仓库架构评估.md` is the project's own architecture self-assessment; keep it updated if you do structural refactors.
- `deliverables/实机验收清单.md` is the pre-demo hardware checklist — useful to read before suggesting hardware-touching changes.
- `测试指南.md` documents the four-tier test taxonomy; if you add a new test class, slot it into the table at line 232 onward.
- `智能种植舱控制器选型报告.md` is the hardware BOM and wiring report — when answering hardware questions, prefer it over inferring from code.
