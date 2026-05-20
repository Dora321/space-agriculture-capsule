const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const outFile = path.join(root, "deliverables", "KT板展示设计-figma-import.svg");
const assetDir = path.join(root, ".figma-assets");
const deliverables = path.join(root, "deliverables");

const W = 1200;
const H = 900;

const colors = {
  space: "#07110F",
  forest: "#10201C",
  paper: "#F7FBF7",
  text: "#10201C",
  muted: "#5F736D",
  white: "#EDF7F3",
  mist: "#A8C3BA",
  green: "#55D98D",
  cyan: "#58C7E8",
  purple: "#7F77DD",
  pink: "#D4537E",
  amber: "#F2BF5B",
  line: "#BAD5C8",
};

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function imageData(name) {
  const jpg = path.join(assetDir, name.replace(/\.png$/, ".jpg"));
  const png = path.join(deliverables, name);
  const file = fs.existsSync(jpg) ? jpg : png;
  const mime = file.endsWith(".jpg") ? "image/jpeg" : "image/png";
  return `data:${mime};base64,${fs.readFileSync(file).toString("base64")}`;
}

function wrapText(input, maxChars) {
  const parts = [];
  for (const raw of input.split("\n")) {
    let line = "";
    for (const ch of raw) {
      if (line.length >= maxChars && /[，。；、\s]/.test(ch)) {
        parts.push(line.trim());
        line = "";
      } else if (line.length >= maxChars) {
        parts.push(line.trim());
        line = "";
      }
      line += ch;
    }
    if (line.trim()) parts.push(line.trim());
  }
  return parts;
}

function text(x, y, content, opts = {}) {
  const {
    size = 18,
    weight = 500,
    fill = colors.text,
    anchor = "start",
    family = "Noto Sans SC, Microsoft YaHei, Arial, sans-serif",
    opacity = 1,
  } = opts;
  return `<text x="${x}" y="${y}" fill="${fill}" opacity="${opacity}" font-family="${family}" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}" letter-spacing="0">${esc(content)}</text>`;
}

function block(x, y, content, opts = {}) {
  const {
    size = 16,
    line = Math.round(size * 1.35),
    weight = 500,
    fill = colors.text,
    maxChars = 24,
    bullet = false,
  } = opts;
  const lines = Array.isArray(content) ? content : wrapText(content, maxChars);
  return lines
    .map((l, i) => {
      const prefix = bullet ? "• " : "";
      return text(x, y + i * line, `${prefix}${l}`, { size, weight, fill });
    })
    .join("\n");
}

function rect(x, y, w, h, r, fill, stroke = "none", sw = 1, opacity = 1) {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" opacity="${opacity}"/>`;
}

function sectionTitle(x, y, title, subtitle) {
  return [
    text(x, y, title, { size: 22, weight: 900, fill: colors.space }),
    text(x + 210, y, subtitle, { size: 11, weight: 700, fill: colors.muted }),
  ].join("\n");
}

function tag(x, y, label, fill = colors.forest, stroke = colors.cyan) {
  return [
    rect(x, y, label.length * 13 + 22, 28, 14, fill, stroke, 1, 0.92),
    text(x + 11, y + 19, label, { size: 12, weight: 800, fill: colors.white }),
  ].join("\n");
}

function flowNode(x, y, w, h, title, body, note, fill, stroke, titleColor) {
  return [
    rect(x, y, w, h, 14, fill, stroke, 2),
    text(x + 18, y + 32, title, { size: 20, weight: 900, fill: titleColor }),
    block(x + 18, y + 61, body, { size: 13, line: 23, weight: 650, fill: titleColor, maxChars: 16, bullet: true }),
    rect(x + 14, y + h - 42, w - 28, 28, 8, "rgba(255,255,255,0.64)"),
    text(x + 22, y + h - 22, note, { size: 11, weight: 800, fill: titleColor }),
  ].join("\n");
}

function miniCard(x, y, w, h, title, body, accent) {
  return [
    rect(x, y, w, h, 10, "#FFFFFF", accent, 1.5),
    rect(x, y, 6, h, 3, accent),
    text(x + 18, y + 27, title, { size: 17, weight: 900, fill: colors.space }),
    block(x + 18, y + 52, body, { size: 12.5, line: 19, weight: 550, fill: "#344842", maxChars: 22 }),
  ].join("\n");
}

function imageCard(x, y, w, h, title, img) {
  return [
    rect(x, y, w, h, 12, "#FFFFFF", colors.line, 1.2),
    `<clipPath id="clip-${x}-${y}"><rect x="${x + 10}" y="${y + 36}" width="${w - 20}" height="${h - 48}" rx="8"/></clipPath>`,
    text(x + 12, y + 24, title, { size: 15, weight: 900, fill: colors.space }),
    `<image x="${x + 10}" y="${y + 36}" width="${w - 20}" height="${h - 48}" href="${img}" preserveAspectRatio="xMidYMid slice" clip-path="url(#clip-${x}-${y})"/>`,
  ].join("\n");
}

const img1 = imageData("contest-dashboard-live-preview.png");
const img2 = imageData("plant-redesign-live-preview.png");
const img3 = imageData("threshold-dashboard-preview.png");

const stars = Array.from({ length: 38 }, (_, i) => {
  const x = 36 + ((i * 83) % 1100);
  const y = 20 + ((i * 37) % 88);
  const r = [0.8, 1.1, 1.4][i % 3];
  const o = [0.18, 0.26, 0.34][i % 3];
  return `<circle cx="${x}" cy="${y}" r="${r}" fill="#FFFFFF" opacity="${o}"/>`;
}).join("\n");

const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <defs>
    <linearGradient id="hero" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="${colors.space}"/>
      <stop offset="100%" stop-color="${colors.forest}"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="5" stdDeviation="8" flood-color="#0D211B" flood-opacity="0.15"/>
    </filter>
  </defs>

  ${rect(0, 0, W, H, 0, "#D9E2DC")}
  ${rect(24, 24, 1152, 852, 0, colors.paper)}
  ${rect(24, 24, 1152, 112, 0, colors.space)}
  ${stars}

  <g filter="url(#shadow)">
    ${rect(42, 38, 1116, 86, 14, "url(#hero)", "rgba(85,217,141,0.36)", 2)}
    ${text(60, 66, "SPACE AGRICULTURE · SMART PLANTING CABIN", { size: 15, weight: 800, fill: colors.mist })}
    ${text(60, 103, "太空农业智能种植舱", { size: 41, weight: 900, fill: colors.white })}
    ${text(470, 99, "ESP32 + MicroPython + 云端 AI + 本地规则兜底的植物自主养护系统", { size: 18, weight: 700, fill: "#D9F1E8" })}
    ${tag(880, 55, "环境感知")}
    ${tag(1004, 55, "自动浇水")}
    ${tag(880, 90, "实时大屏")}
    ${tag(1004, 90, "离线安全")}
  </g>

  <g filter="url(#shadow)">
    ${rect(42, 150, 1116, 260, 14, "#FFFFFF", colors.line, 1.2)}
    ${sectionTitle(62, 184, "系统链路图", "SENSE → THINK → ACT → DISPLAY")}
    ${flowNode(62, 210, 236, 176, "感知层 SENSE", ["土壤湿度 ADC", "环境光照反向标定", "DHT11/DHT22 可配置", "3 位拨码切换 8 种作物"], "把现场环境变成可靠数据", "#E9E7FF", colors.purple, "#312B78")}
    ${text(320, 305, "→", { size: 34, weight: 900, fill: "#55746A", anchor: "middle" })}
    ${flowNode(342, 210, 236, 176, "决策层 THINK", ["ESP32 主控循环", "本地规则常驻兜底", "阈值事件触发 AI", "自动匹配生长阶段"], "AI 辅助，本地规则保底", "#FFEAF2", colors.pink, "#72243E")}
    ${text(600, 305, "→", { size: 34, weight: 900, fill: "#55746A", anchor: "middle" })}
    ${flowNode(622, 210, 236, 176, "执行层 ACT", ["水泵继电器浇水", "营养液泵按周期补充", "LED 标识运行状态", "限频、限时、防抖"], "能动作，也能自我约束", "#EAF6DF", "#639922", "#27500A")}
    ${text(880, 305, "→", { size: 34, weight: 900, fill: "#55746A", anchor: "middle" })}
    ${flowNode(902, 210, 236, 176, "展示层 DISPLAY", ["OLED 三页轮播", "动作覆盖提示", "Web LIVE 大屏", "120 秒无数据回 DEMO"], "让评委看到系统跑通", "#E8F8FF", colors.cyan, "#07384B")}
  </g>

  <g filter="url(#shadow)">
    ${rect(42, 424, 548, 190, 14, "#F4FAFD", "#85B7EB", 1.2)}
    ${sectionTitle(62, 458, "核心亮点", "让评委快速读懂价值")}
    ${miniCard(62, 480, 246, 54, "AI + 本地规则双决策", "云端 AI 做综合判断，本地规则保证 WiFi 或 API 不可用时仍能完成基本养护。", colors.purple)}
    ${miniCard(324, 480, 246, 54, "14 种作物参数库", "库内 14 种作物；现场通过 3 位拨码快速切换 8 种核心作物。", colors.green)}
    ${miniCard(62, 548, 246, 48, "按生长阶段调整策略", "依据种植天数匹配苗期、营养期、花期、果期和采收期。", colors.amber)}
    ${miniCard(324, 548, 246, 48, "全链路安全机制", "传感器离线降级、动作限时限频、连续错误触发看门狗重启。", "#EF6F6C")}

    ${rect(610, 424, 548, 190, 14, "#FFF7F4", "#F0997B", 1.2)}
    ${sectionTitle(630, 458, "作物数据库与策略", "库内 14 种 / 现场 8 种")}
    ${text(630, 490, "分类", { size: 13, weight: 900, fill: "#4A1B0C" })}
    ${text(725, 490, "作物", { size: 13, weight: 900, fill: "#4A1B0C" })}
    ${text(975, 490, "策略特点", { size: 13, weight: 900, fill: "#4A1B0C" })}
    ${rect(626, 500, 512, 1, 0, "#F0997B")}
    ${text(630, 525, "叶菜", { size: 13, weight: 800, fill: "#4A1B0C" })}
    ${block(725, 525, "生菜、小白菜、菠菜、韭菜、葱", { size: 12.5, line: 18, weight: 550, fill: "#49322A", maxChars: 18 })}
    ${block(975, 525, "看土壤湿度和氮肥需求", { size: 12.5, line: 18, weight: 550, fill: "#49322A", maxChars: 14 })}
    ${text(630, 562, "果菜", { size: 13, weight: 800, fill: "#4A1B0C" })}
    ${block(725, 562, "番茄、辣椒、黄瓜、茄子、豆角、西葫芦", { size: 12.5, line: 18, weight: 550, fill: "#49322A", maxChars: 18 })}
    ${block(975, 562, "花期控水，果期重视钾肥", { size: 12.5, line: 18, weight: 550, fill: "#49322A", maxChars: 14 })}
    ${text(630, 599, "根茎", { size: 13, weight: 800, fill: "#4A1B0C" })}
    ${block(725, 599, "萝卜、大蒜、生姜", { size: 12.5, line: 18, weight: 550, fill: "#49322A", maxChars: 18 })}
    ${block(975, 599, "按膨大阶段调整水肥", { size: 12.5, line: 18, weight: 550, fill: "#49322A", maxChars: 14 })}
  </g>

  <g filter="url(#shadow)">
    ${rect(42, 628, 1116, 196, 14, "#FFFFFF", colors.line, 1.2)}
    ${sectionTitle(62, 662, "现场展示区", "实物 / OLED / Web 实时大屏 / 运行日志")}
    ${imageCard(62, 676, 330, 128, "LIVE Web 大屏：实时遥测与决策来源", img1)}
    ${imageCard(412, 676, 330, 128, "动态植物与生长阶段展示", img2)}
    ${imageCard(762, 676, 206, 128, "阈值策略面板", img3)}
    ${rect(990, 676, 148, 128, 10, "#10201C", "#55D98D", 1.2)}
    ${text(1008, 703, "技术参数", { size: 16, weight: 900, fill: colors.white })}
    ${block(1008, 728, ["主控 ESP32 DevKit", "固件 MicroPython", "采样 60 秒/次", "安全 12 次/小时上限"], { size: 12, line: 20, weight: 650, fill: "#D9F1E8", maxChars: 16 })}
    ${text(1008, 804, "[Sensor] [Growth] [AI] [Action] [Telemetry]", { size: 10, weight: 700, fill: colors.green, family: "Consolas, monospace" })}
  </g>

  <g>
    ${rect(42, 838, 1116, 30, 8, colors.forest)}
    ${text(62, 859, "科技竞赛现场展示 · 120cm × 90cm 横版 KT 板", { size: 13, weight: 800, fill: colors.white })}
    ${text(1138, 859, "团队 / 学校 / 指导老师", { size: 13, weight: 700, fill: colors.mist, anchor: "end" })}
  </g>
</svg>`;

fs.writeFileSync(outFile, svg, "utf8");
console.log(outFile);
