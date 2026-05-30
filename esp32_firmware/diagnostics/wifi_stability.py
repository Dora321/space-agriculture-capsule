"""WiFi 稳定性长时间监测 - 定位"反复掉线"的根因（信号弱 / 供电掉压 / AP 踢人）。

用法：
  py -m mpremote connect COM3 run esp32_firmware/diagnostics/wifi_stability.py

跑几分钟（越久越准），按 Ctrl-C 结束，会打印汇总：
  - RSSI 区间（信号强弱）
  - 掉线次数 + 每次掉线的时刻和当时 RSSI
  - 在线率
  - 若开启 STRESS_ACTUATOR：掉线是否集中在补光灯吸合后 → 供电掉压实锤

诊断思路：
  · RSSI 一直 < -80 且掉线频繁         → 信号弱（挪近 AP / 换信道）
  · RSSI 不错(-60~-70)但仍频繁掉       → AP 踢空闲客户端 或 2.4G 干扰
  · 平时稳，只在 STRESS 脉冲后掉        → 12V 继电器吸合导致 ESP32 掉压 brownout
  · 完全连不上                         → 改用 wifi_diag.py 看连接阶段
"""
import network
import time
import gc

# ── 配置 ────────────────────────────────────────────────
SAMPLE_SEC = 3            # 采样间隔（秒）
PING_HOST = None          # 设为 "43.156.68.157" 做端到端连通测试；None=只看本地连接
PING_PORT = 8790
STRESS_ACTUATOR = False   # True=周期性脉冲水泵继电器，测试供电掉压是否引发掉线
STRESS_TARGET = "pump"    # "pump"=水泵(电机涌流大,需水管已入水) / "light"=补光灯
STRESS_EVERY = 30         # 每 N 秒脉冲一次
STRESS_ON_SEC = 2         # 每次脉冲持续秒数
# ────────────────────────────────────────────────────────


def _rssi_quality(r):
    if r is None:
        return "?"
    if r >= -60:
        return "GOOD"
    if r >= -70:
        return "OK"
    if r >= -80:
        return "WEAK"
    return "BAD"


def _ping(host, port):
    """返回连通延迟 ms，失败返回 None。"""
    import socket
    s = None
    try:
        t0 = time.ticks_ms()
        s = socket.socket()
        s.settimeout(3)
        s.connect((host, port))
        return time.ticks_diff(time.ticks_ms(), t0)
    except Exception:
        return None
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass


def main():
    print("=== WiFi Stability Monitor ===")
    print("sample every %ds, Ctrl-C to stop & summarize" % SAMPLE_SEC)
    if STRESS_ACTUATOR:
        print("STRESS mode ON: pulsing %s relay every %ds" % (STRESS_TARGET, STRESS_EVERY))

    # 用项目自己的连接路径，测的就是真实行为
    import wifi_client
    import config
    ok = wifi_client.connect(reset=True)
    print("initial connect:", "OK" if ok else "FAIL")

    w = network.WLAN(network.STA_IF)

    relay = None
    if STRESS_ACTUATOR:
        from machine import Pin
        pin_no = config.RELAY_WATER_PIN if STRESS_TARGET == "pump" else config.RELAY_LIGHT_PIN
        relay = Pin(pin_no, Pin.OUT)
        relay.value(1)  # 低电平触发 → 1=关
        print("STRESS target: %s relay (GPIO%d)" % (STRESS_TARGET, pin_no))

    # ── 统计量 ──
    t_start = time.ticks_ms()
    samples = 0
    online = 0
    drops = 0          # 在线→掉线 的跳变次数
    reconnects = 0
    rssi_min, rssi_max, rssi_sum, rssi_n = 999, -999, 0, 0
    drop_log = []      # [(秒, rssi)]
    ping_fail = 0
    ping_n = 0
    prev_up = ok
    last_stress = -STRESS_EVERY
    last_stress_at = None  # 上次脉冲的秒数，用于关联掉线

    try:
        while True:
            now_s = time.ticks_diff(time.ticks_ms(), t_start) // 1000
            samples += 1

            connected = False
            ip = None
            rssi = None
            try:
                if w.active():
                    ip = w.ifconfig()[0]
                    connected = bool(ip and ip != "0.0.0.0") and w.isconnected()
                    if connected:
                        try:
                            rssi = w.status('rssi')
                        except Exception:
                            rssi = None
            except Exception:
                connected = False

            if connected:
                online += 1
                if rssi is not None:
                    rssi_min = min(rssi_min, rssi)
                    rssi_max = max(rssi_max, rssi)
                    rssi_sum += rssi
                    rssi_n += 1

            # 跳变检测
            if prev_up and not connected:
                drops += 1
                drop_log.append((now_s, rssi))
                tag = ""
                if last_stress_at is not None and now_s - last_stress_at <= STRESS_ON_SEC + SAMPLE_SEC:
                    tag = "  <-- 紧跟%s脉冲(供电掉压?)" % STRESS_TARGET
                print("  ! DROP   @%ds  rssi=%s%s" % (now_s, rssi, tag))
            if not prev_up and connected:
                reconnects += 1
                print("  + UP     @%ds  ip=%s" % (now_s, ip))
            prev_up = connected

            # 连通性测试
            ping_ms = None
            if connected and PING_HOST:
                ping_n += 1
                ping_ms = _ping(PING_HOST, PING_PORT)
                if ping_ms is None:
                    ping_fail += 1

            mem = gc.mem_free()
            line = "  t=%-5ds up=%d rssi=%s(%s) ip=%s mem=%dK" % (
                now_s, 1 if connected else 0, rssi, _rssi_quality(rssi),
                ip or "-", mem // 1024,
            )
            if PING_HOST:
                line += " ping=%s" % ("%dms" % ping_ms if ping_ms is not None else "FAIL")
            print(line)

            # 压力脉冲：开补光灯继电器一小段，看 WiFi 是否随之掉
            if STRESS_ACTUATOR and now_s - last_stress >= STRESS_EVERY:
                last_stress = now_s
                last_stress_at = now_s
                print("  * STRESS pulse: %s relay ON %ds" % (STRESS_TARGET, STRESS_ON_SEC))
                relay.value(0)   # 开
                time.sleep(STRESS_ON_SEC)
                relay.value(1)   # 关

            gc.collect()
            time.sleep(SAMPLE_SEC)

    except KeyboardInterrupt:
        pass
    finally:
        if relay:
            relay.value(1)  # 确保关闭继电器

    # ── 汇总 ──
    elapsed = time.ticks_diff(time.ticks_ms(), t_start) // 1000
    print("\n=== Summary (%ds) ===" % elapsed)
    print("samples:        %d" % samples)
    if samples:
        print("online rate:    %d%% (%d/%d)" % (online * 100 // samples, online, samples))
    print("drops:          %d" % drops)
    print("reconnects:     %d" % reconnects)
    if rssi_n:
        print("rssi min/avg/max: %d / %d / %d  (%s avg)" % (
            rssi_min, rssi_sum // rssi_n, rssi_max,
            _rssi_quality(rssi_sum // rssi_n)))
    if PING_HOST and ping_n:
        print("ping %s:%d  fail %d/%d" % (PING_HOST, PING_PORT, ping_fail, ping_n))
    if drop_log:
        print("drop timeline (sec, rssi):")
        for s, r in drop_log:
            print("   @%-5ds rssi=%s" % (s, r))

    # ── 自动结论 ──
    print("\n=== 诊断 ===")
    if samples and drops == 0:
        print("本次窗口内 0 掉线，连接稳定。若现场仍不稳，延长监测时间或在 STRESS 模式下复测。")
    elif rssi_n and rssi_sum // rssi_n < -80:
        print("信号偏弱(平均 < -80dBm)且有掉线 → 优先解决信号：挪近 AP / 加天线 / 避开 2.4G 干扰。")
    elif STRESS_ACTUATOR and drop_log and any(
        True for (s, _) in drop_log):
        print("有掉线发生。检查上面 DROP 行是否带 '紧跟补光灯脉冲' 标记：")
        print("  带标记 → 12V 继电器吸合导致掉压 brownout，需独立/加大供电、加电容滤波。")
        print("  无标记 → 更可能是 AP 踢人或 2.4G 干扰。")
    else:
        print("RSSI 尚可但仍掉线 → 多半是 AP 踢空闲客户端 或 2.4G 信道拥挤。")
        print("建议：开 STRESS_ACTUATOR=True 复测，排除/坐实供电掉压因素。")


main()
