/**
 * 小红书直播流地址提取器
 * 使用 puppeteer-core + 系统 Chrome 打开直播页面，拦截网络请求获取真实流地址
 *
 * 用法: node stream_extractor.js <直播链接> [--headless] [--timeout 30]
 * 输出: 提取到的流地址（stdout），错误信息（stderr）
 */

const puppeteer = require('puppeteer-core');
const path = require('path');
const fs = require('fs');

// Chrome 路径（macOS）
const CHROME_PATHS = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
];

// 用户数据目录（持久化登录状态）
const USER_DATA_DIR = path.join(__dirname, '.chrome-profile');

function findChrome() {
  for (const p of CHROME_PATHS) {
    if (fs.existsSync(p)) return p;
  }
  return null;
}

function isStreamUrl(url) {
  const lower = url.toLowerCase();

  // 排除 API/网页请求（这些不是流地址）
  if (
    lower.includes('/api/') ||
    lower.includes('room_id=') ||
    lower.includes('user_id=') ||
    lower.includes('request_user_id=') ||
    lower.includes('current_room_info') ||
    lower.includes('room/') ||
    lower.includes('web_live') ||
    lower.includes('client_type=')
  ) {
    return false;
  }

  // 真实流媒体地址
  return (
    lower.includes('.m3u8') ||
    lower.includes('.flv') ||
    lower.includes('/hls/') ||
    lower.includes('m3u8') ||
    lower.includes('hls-') ||
    lower.includes('-hls.') ||
    lower.includes('live-hls') ||
    lower.includes('live.flv') ||
    lower.includes('pull-flv') ||
    lower.includes('pull-hls') ||
    (lower.includes('playlist') && lower.includes('m3u8')) ||
    (lower.includes('.ts?') || lower.includes('.ts&'))  // HLS 切片
  );
}

async function extractStreamUrl(liveUrl, options = {}) {
  const { headless = false, timeout = 30 } = options;
  const chromePath = findChrome();

  if (!chromePath) {
    console.error('错误: 未找到 Chrome 浏览器，请安装 Google Chrome');
    process.exit(1);
  }

  console.error(`[INFO] 启动 Chrome...`);
  console.error(`[INFO] 用户数据目录: ${USER_DATA_DIR}`);

  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: headless ? 'new' : false,
    userDataDir: USER_DATA_DIR,
    args: [
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-blink-features=AutomationControlled',
      '--mute-audio',
      '--window-size=1280,800',
    ],
    defaultViewport: { width: 1280, height: 800 },
  });

  const page = await browser.newPage();

  // 设置 User-Agent 避免被检测
  await page.setUserAgent(
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ' +
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
  );

  const streamUrls = new Set();
  let foundUrl = null;

  // 拦截网络请求
  page.on('request', (request) => {
    const url = request.url();
    if (isStreamUrl(url)) {
      console.error(`[FOUND] 检测到流地址: ${url.substring(0, 120)}...`);
      streamUrls.add(url);
      if (!foundUrl) {
        foundUrl = url;
      }
    }
  });

  // 也监听 response，有些流地址只在 response 中出现
  page.on('response', (response) => {
    const url = response.url();
    if (isStreamUrl(url)) {
      console.error(`[FOUND] 检测到流响应: ${url.substring(0, 120)}...`);
      streamUrls.add(url);
      if (!foundUrl) {
        foundUrl = url;
      }
    }
  });

  console.error(`[INFO] 正在打开直播页面: ${liveUrl}`);

  try {
    // 用 domcontentloaded 而非 networkidle2 —— 直播页面网络永远不空闲，networkidle2 会一直超时
    await page.goto(liveUrl, {
      waitUntil: 'domcontentloaded',
      timeout: timeout * 1000,
    });
  } catch (err) {
    console.error(`[WARN] 页面加载超时或出错: ${err.message}`);
  }

  // 轮询等待流地址出现（最多等 20 秒，每 500ms 检查一次）
  console.error(`[INFO] 等待流地址加载...`);
  const maxWaitMs = 20000;
  const pollIntervalMs = 500;
  const startTime = Date.now();

  while (Date.now() - startTime < maxWaitMs) {
    if (foundUrl) {
      break;
    }
    // 尝试从页面 JS 变量中提取
    try {
      const pageData = await page.evaluate(() => {
        const results = [];
        // 检查 __INITIAL_STATE__
        if (window.__INITIAL_STATE__) {
          try {
            const stateStr = JSON.stringify(window.__INITIAL_STATE__);
            const m3u8Matches = stateStr.match(/https?:\/\/[^"'\s]+\.m3u8[^"'\s]*/g);
            const flvMatches = stateStr.match(/https?:\/\/[^"'\s]+\.flv[^"'\s]*/g);
            if (m3u8Matches) results.push(...m3u8Matches);
            if (flvMatches) results.push(...flvMatches);
          } catch (e) {}
        }
        // 检查 video 标签
        const videos = document.querySelectorAll('video');
        videos.forEach((v) => {
          if (v.src) results.push(v.src);
          v.querySelectorAll('source').forEach((s) => {
            if (s.src) results.push(s.src);
          });
        });
        // 检查页面 HTML
        const html = document.documentElement.innerHTML;
        const m3u8InHtml = html.match(/https?:\/\/[^"'\s<>]+\.m3u8[^"'\s<>]*/g);
        const flvInHtml = html.match(/https?:\/\/[^"'\s<>]+\.flv[^"'\s<>]*/g);
        if (m3u8InHtml) results.push(...m3u8InHtml);
        if (flvInHtml) results.push(...flvInHtml);
        return results;
      });

      if (pageData && pageData.length > 0) {
        for (const url of pageData) {
          if (isStreamUrl(url)) {
            streamUrls.add(url);
            if (!foundUrl) foundUrl = url;
          }
        }
        if (pageData.length > 0) {
          console.error(`[FOUND] 从页面数据中提取到 ${pageData.length} 个候选地址`);
        }
      }
    } catch (e) {
      // 页面可能还在跳转，忽略
    }

    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }

  console.error(`[INFO] 流地址检测完成，等待了 ${((Date.now() - startTime) / 1000).toFixed(1)} 秒`);

  // 输出结果
  if (foundUrl) {
    // 优先选择 m3u8（HLS 更稳定）
    const m3u8Urls = [...streamUrls].filter((u) => u.toLowerCase().includes('.m3u8'));
    const finalUrl = m3u8Urls.length > 0 ? m3u8Urls[0] : foundUrl;

    // stdout 输出流地址（供 Python 脚本读取）
    console.log(finalUrl);
    console.error(`[SUCCESS] 流地址提取成功`);
    console.error(`[INFO] 共发现 ${streamUrls.size} 个候选地址`);

    // 关闭浏览器
    await browser.close();
    return;
  }

  // 没有找到流地址
  console.error('[ERROR] 未检测到流媒体地址');
  console.error('[INFO] 可能的原因:');
  console.error('  1. 直播已结束或未开始');
  console.error('  2. 需要登录才能观看（请在弹出的浏览器中登录后重试）');
  console.error('  3. 页面结构变化，需要更新提取逻辑');

  // 关闭浏览器并退出，让 Python 脚本的 wait_for_stream() 重试
  await browser.close();
  process.exit(1);
}

// 解析命令行参数
const args = process.argv.slice(2);
const liveUrl = args.find((a) => !a.startsWith('--'));
const headless = args.includes('--headless');
const timeoutArg = args.find((a) => a.startsWith('--timeout'));
const timeout = timeoutArg ? parseInt(timeoutArg.split('=')[1] || args[args.indexOf(timeoutArg) + 1]) : 30;

if (!liveUrl) {
  console.error('用法: node stream_extractor.js <直播链接> [--headless] [--timeout 30]');
  process.exit(1);
}

extractStreamUrl(liveUrl, { headless, timeout }).catch((err) => {
  console.error(`[FATAL] ${err.message}`);
  process.exit(1);
});
