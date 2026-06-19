// VIP Sim — Trae/VS Code 扩展
// 形态: 扩展自带不可变的项目模板(template/), 用户通过"新建仿真项目"
// 把全部仿真文件复制到自己的项目目录, 所有操作在项目内完成。
const vscode = require('vscode');
const cp = require('child_process');
const fs = require('fs');
const path = require('path');

let extCtx;
let out;             // OutputChannel
let consolePanel;    // 仿真控制台 webview
const dimPanels = {}; // 各分析维度面板

// ---------- 基础工具 ----------

function wsRoot() {
    const f = vscode.workspace.workspaceFolders;
    return f && f.length ? f[0].uri.fsPath : undefined;
}

function isVipProject(root) {
    return !!root &&
        fs.existsSync(path.join(root, 'Makefile')) &&
        fs.existsSync(path.join(root, 'scripts', 'gen_stimulus.py'));
}

function run(cmd, cwd) {
    out.appendLine(`$ ${cmd}`);
    return new Promise((resolve) => {
        const child = cp.spawn(cmd, { shell: true, cwd });
        child.stdout.on('data', (d) => out.append(d.toString()));
        child.stderr.on('data', (d) => out.append(d.toString()));
        child.on('close', resolve);
    });
}

function listIPs(root) {
    const rtl = path.join(root, 'rtl');
    if (!fs.existsSync(rtl)) return [];
    return fs.readdirSync(rtl).filter((d) =>
        fs.statSync(path.join(rtl, d)).isDirectory() &&
        fs.existsSync(path.join(root, 'sim', 'tests', `tb_${d}.v`)));
}

function getState() {
    const s = extCtx.workspaceState;
    return {
        ip: s.get('ip', 'passthrough'),
        width: s.get('width', 64),
        height: s.get('height', 48),
        frames: s.get('frames', 1),
        inputImage: s.get('inputImage', 'sim/testdata/test_input.png'),
    };
}

async function setState(patch) {
    for (const [k, v] of Object.entries(patch)) {
        await extCtx.workspaceState.update(k, v);
    }
}

function readReport(root, ip) {
    const p = path.join(root, 'output', 'reports', `${ip}_report.json`);
    if (!fs.existsSync(p)) return undefined;
    try { return JSON.parse(fs.readFileSync(p, 'utf8')); }
    catch { return undefined; }
}

// 读取 IP 寄存器定义。组合设计可用 includes 引用子 IP 并声明基址,
// 子 IP 寄存器地址自动平移合并成统一寄存器表:
//   {"includes": [{"ip": "auto_white_balance", "base": "0x00", "prefix": "AWB_"},
//                 {"ip": "sharpen", "base": "0x40", "prefix": "SHARP_"}],
//    "registers": [...自有寄存器(可选)...]}
function readRegdef(root, ip, depth = 0) {
    const p = path.join(root, 'rtl', ip, 'regdef.json');
    if (!fs.existsSync(p)) return [];
    let j;
    try { j = JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return []; }
    const out = [];
    if (Array.isArray(j.includes) && depth < 3) {
        for (const inc of j.includes) {
            const base = parseInt(inc.base || '0x0', 16);
            const group = `${inc.ip} (基址 ${inc.base || '0x00'})`;
            for (const r of readRegdef(root, inc.ip, depth + 1)) {
                const addr = parseInt(r.addr, 16) + base;
                out.push({
                    ...r,
                    addr: '0x' + addr.toString(16).toUpperCase().padStart(2, '0'),
                    name: (inc.prefix || '') + r.name,
                    group,
                });
            }
        }
    }
    for (const r of (j.registers || [])) out.push(r);
    return out;
}

// 由寄存器编辑值生成 regcfg.hex (仅 RW 寄存器, 全量写入; 哨兵行结尾)
function writeRegcfg(root, regdef, regs) {
    const lines = [];
    for (const r of regdef) {
        if (r.access !== 'RW') continue;
        const addr = parseInt(r.addr, 16);
        const val = parseInt((regs && regs[r.addr]) || r.default, 16);
        if (Number.isNaN(addr) || Number.isNaN(val)) continue;
        lines.push(addr.toString(16).padStart(2, '0') +
            (val >>> 0).toString(16).padStart(8, '0'));
    }
    lines.push('FFFFFFFFFF');
    fs.writeFileSync(path.join(root, 'sim', 'testdata', 'regcfg.hex'),
        lines.join('\n') + '\n');
}

// ---------- 新建项目 ----------

async function cmdNewProject() {
    const parent = await vscode.window.showOpenDialog({
        canSelectFiles: false, canSelectFolders: true,
        canSelectMany: false, openLabel: '选择项目存放位置',
    });
    if (!parent) return;

    const name = await vscode.window.showInputBox({
        prompt: '项目名称', value: 'my_vip_project',
        validateInput: (v) =>
            /^[A-Za-z0-9_-]+$/.test(v) ? undefined : '仅限字母/数字/下划线/连字符',
    });
    if (!name) return;

    const dest = path.join(parent[0].fsPath, name);
    if (fs.existsSync(dest)) {
        vscode.window.showErrorMessage(`目录已存在: ${dest}`);
        return;
    }

    // 1. 从扩展内置模板复制全部仿真文件 (模板本身只读, 项目可自由修改)
    const template = path.join(extCtx.extensionPath, 'template');
    fs.cpSync(template, dest, { recursive: true });
    for (const d of ['output/images', 'output/reports', 'output/waves']) {
        fs.mkdirSync(path.join(dest, d), { recursive: true });
    }

    // 2. 创建项目内 Python 环境
    out.show(true);
    const ok = await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: `创建 Python 环境 (${name}/.venv, 首次需联网下载)...`,
    }, () => run(
        'python3 -m venv .venv && ' +
        '.venv/bin/pip install -q -r requirements.txt', dest));
    if (ok !== 0) {
        vscode.window.showWarningMessage(
            'Python 环境创建失败(可能无网络), 项目已创建。' +
            '稍后可在项目内手动执行: python3 -m venv .venv && ' +
            '.venv/bin/pip install -r requirements.txt');
    }

    const open = await vscode.window.showInformationMessage(
        `项目 ${name} 创建完成`, '在新窗口打开', '在当前窗口打开');
    if (open) {
        vscode.commands.executeCommand('vscode.openFolder',
            vscode.Uri.file(dest),
            { forceNewWindow: open === '在新窗口打开' });
    }
}

// ---------- 仿真执行 ----------

async function doRun(params) {
    const root = wsRoot();
    const { ip, width, height, frames, inputImage } = params;
    await setState({ ip, width, height, frames, inputImage });
    await extCtx.workspaceState.update(`regs:${ip}`, params.regs || {});
    writeRegcfg(root, readRegdef(root, ip), params.regs);
    out.show(true);

    const video = isVideoPath(inputImage);
    postToConsole({ type: 'status', running: true,
        text: `${video ? '视频' : ''}仿真中: ${ip} ${width}x${height} x${frames}帧 ...` });

    const cmd = video
        ? `make video IP=${ip} WIDTH=${width} HEIGHT=${height} ` +
          `FRAMES=${frames} INPUT_VIDEO="${inputImage}"`
        : `make all IP=${ip} WIDTH=${width} HEIGHT=${height} ` +
          `FRAMES=${frames} INPUT_IMG="${inputImage}"`;
    const code = await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: `VIP Sim: ${video ? '视频' : ''}仿真 ${ip}`,
    }, () => run(cmd, root));

    if (code !== 0) {
        postToConsole({ type: 'status', running: false,
            text: '仿真失败 — 详见 VIP Sim 输出面板' });
        vscode.window.showErrorMessage(`仿真失败: ${ip}`);
        return;
    }

    // 视频模式: 拆帧(供帧级预览/分析) + 时序分析; 跳过金标准(参考模型按 replay 假设)
    if (video) {
        const py = pyExec(root);
        const inDir = `output/video/${ip}_in`, outDir = `output/video/${ip}_out`;
        await run(`${py} scripts/dump_frames.py -i sim/testdata/stimulus.hex ` +
            `-d ${inDir} -W ${width} -H ${height} --frames ${frames}`, root);
        await run(`${py} scripts/dump_frames.py -i sim/testdata/result.hex ` +
            `-d ${outDir} -W ${width} -H ${height} --frames ${frames}`, root);
        await run(`${py} scripts/analyze_video.py ` +
            `--stimulus sim/testdata/stimulus.hex --result sim/testdata/result.hex ` +
            `-W ${width} -H ${height} --frames ${frames} ` +
            `--report output/reports/${ip}_video.json`, root);
        await extCtx.workspaceState.update(`golden:${ip}`, { state: 'video' });
        await extCtx.workspaceState.update(`video:${ip}`, { frames });
        refreshConsole();
        vscode.window.showInformationMessage(
            `视频仿真完成: ${ip} (${frames}帧) — 控制台可逐帧预览/时序分析`);
        return;
    }

    // 金标准比对 (有参考模型的 IP)，结果存入 workspaceState 供控制台显示
    const gv = await runCapture(
        `${pyExec(root)} scripts/verify.py --ip ${ip} -W ${width} -H ${height} ` +
        `--frames ${frames}`, root);
    let golden;
    if (/PASS:|FAIL:/.test(gv.output)) {        // 有明确比对结果
        golden = { state: /PASS:/.test(gv.output) ? 'pass' : 'fail',
                   line: (gv.output.match(/(PASS|FAIL):.*/) || [''])[0].trim() };
    } else if (/invalid choice/i.test(gv.output)) {
        golden = { state: 'na' };               // 该 IP 不在 CONFIG, 无金标准模型
    } else {                                     // 脚本出错 (区别于"无模型")
        golden = { state: 'error',
                   line: (gv.output.trim().split('\n').pop() || '验证出错').slice(0, 140) };
    }
    await extCtx.workspaceState.update(`golden:${ip}`, golden);

    refreshConsole();
    vscode.window.showInformationMessage(
        `仿真完成: ${ip}${golden.state === 'pass' ? ' · 金标准 PASS'
            : golden.state === 'fail' ? ' · 金标准 FAIL' : ''}`);
}

// 执行命令并捕获输出 (不流式)，返回 {code, output}
function runCapture(cmd, cwd) {
    out.appendLine(`$ ${cmd}`);
    return new Promise((resolve) => {
        const child = cp.spawn(cmd, { shell: true, cwd });
        let buf = '';
        const cap = (d) => { buf += d.toString(); out.append(d.toString()); };
        child.stdout.on('data', cap);
        child.stderr.on('data', cap);
        child.on('close', (code) => resolve({ code, output: buf }));
    });
}

function pyExec(root) {
    return fs.existsSync(path.join(root, '.venv/bin/python'))
        ? '.venv/bin/python' : 'python3';
}

async function cmdViewWave() {
    const root = wsRoot();
    if (!isVipProject(root)) return noProject();
    const st = getState();
    const vcd = path.join(root, 'output', 'waves', `${st.ip}.vcd`);

    if (!fs.existsSync(vcd)) {
        const code = await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: `重跑仿真生成波形 (${st.ip})...`,
        }, () => run(
            `make sim WAVE=1 IP=${st.ip} WIDTH=${st.width} ` +
            `HEIGHT=${st.height} FRAMES=${st.frames} ` +
            `INPUT_IMG="${st.inputImage}"`, root));
        if (code !== 0 || !fs.existsSync(vcd)) {
            vscode.window.showErrorMessage('波形生成失败');
            return;
        }
    }
    try {
        await vscode.commands.executeCommand(
            'vscode.open', vscode.Uri.file(vcd));
    } catch (e) {
        vscode.window.showErrorMessage(
            `无法打开波形: ${e.message} — 请安装 VCD 查看扩展 (如 VaporView)`);
    }
}

function noProject() {
    vscode.window.showWarningMessage(
        '当前工作区不是 VIP 仿真项目', '新建仿真项目')
        .then((sel) => sel && cmdNewProject());
}

// ---------- 导入 / 导出图像 ----------

async function importImage() {
    const root = wsRoot();
    const pick = await vscode.window.showOpenDialog({
        canSelectMany: false, openLabel: '导入为输入图像',
        filters: { 图像: ['png', 'jpg', 'jpeg', 'bmp'] },
    });
    if (!pick) return;
    const src = pick[0].fsPath;
    const rel = path.join('sim', 'testdata', path.basename(src));
    fs.copyFileSync(src, path.join(root, rel));
    await setState({ inputImage: rel });
    refreshConsole();
}

const VIDEO_EXTS = ['.mp4', '.avi', '.mov', '.mkv'];
function isVideoPath(p) {
    return p && VIDEO_EXTS.includes(path.extname(p).toLowerCase());
}

// 读取视频帧数 (调 python 探测), 存入 state
async function probeVideoFrames(root, rel) {
    const r = await runCapture(
        `${pyExec(root)} -c "import cv2,sys; c=cv2.VideoCapture('${rel}'); ` +
        `print(int(c.get(cv2.CAP_PROP_FRAME_COUNT)))"`, root);
    const n = parseInt((r.output.match(/\d+/) || ['0'])[0], 10);
    return Number.isFinite(n) && n > 0 ? n : 0;
}

async function importVideo() {
    const root = wsRoot();
    const pick = await vscode.window.showOpenDialog({
        canSelectMany: false, openLabel: '导入为输入视频',
        filters: { 视频: ['mp4', 'avi', 'mov', 'mkv'] },
    });
    if (!pick) return;
    const src = pick[0].fsPath;
    const rel = path.join('sim', 'testdata', path.basename(src));
    fs.copyFileSync(src, path.join(root, rel));
    const total = await probeVideoFrames(root, rel);
    // 默认抽取帧数: 视频总帧数与上限(30, iverilog 较慢)取小
    const frames = Math.max(1, Math.min(total || 8, 30));
    await setState({ inputImage: rel, frames });
    vscode.window.showInformationMessage(
        `已导入视频 (${total} 帧), 将仿真前 ${frames} 帧`);
    refreshConsole();
}

// 预处理: 内置算子 (噪声/坏点/模糊) 或 自定义(AI 脚手架)
async function preprocessMedia() {
    const root = wsRoot();
    const st = getState();
    const inRel = st.inputImage;
    const pick = await vscode.window.showQuickPick([
        '高斯噪声 σ=15', '坏点注入 200/帧', '高斯模糊 5×5',
        '噪声+坏点 (组合)',
    ], { placeHolder: '选择内置预处理 (自定义请用"AI预处理"按钮)' });
    if (!pick) return;

    const argMap = {
        '高斯噪声 σ=15': '--noise 15',
        '坏点注入 200/帧': '--dead 200',
        '高斯模糊 5×5': '--blur 5',
        '噪声+坏点 (组合)': '--noise 12 --dead 150',
    };
    return runPreprocess(root, inRel, argMap[pick], 'pp');
}

// 自定义预处理: 文本框收需求 → 写入脚手架 → 复制 AI 提示到剪贴板 → (AI填好后)运行
// 生成自定义算子脚手架 (需求写进顶部, AI 据此填 process 函数体)
function buildPpScaffold(req) {
    return `#!/usr/bin/env python3
# 用户需求: ${req}
# 请据上面的需求实现下方 process() 的函数体 (只改函数体, 保持签名)。
# 约定: frame=H×W×3 BGR uint8 numpy(OpenCV); idx=帧序号(int, 图像恒0);
#       rng=np.random.Generator(用它保证可复现); 返回同形状 uint8(务必 np.clip(x,0,255).astype(np.uint8))。
import cv2          # noqa: F401
import numpy as np


def process(frame, idx, rng):
    # TODO(AI): 在此实现「${req}」
    out = frame
    return out
`;
}

async function customPreprocess(root, inRel) {
    const req = await vscode.window.showInputBox({
        title: 'AI预处理 — 描述要对图像/视频做什么',
        placeHolder: '例: 模拟低光照并加噪声 / 整体调暗30% / 暗角从左扫到右',
        prompt: '回车后: 写入脚手架并复制提示词 → 粘到 Trae 聊天让 AI 实现 → 回来点运行',
        ignoreFocusOut: true,
    });
    if (!req) return;

    const scaffold = path.join(root, 'scripts', 'preprocess_custom.py');
    fs.writeFileSync(scaffold, buildPpScaffold(req));
    const doc = await vscode.workspace.openTextDocument(scaffold);
    await vscode.window.showTextDocument(doc);

    const prompt = `请实现 scripts/preprocess_custom.py 里的 process(frame, idx, rng) 函数体, ` +
        `需求: ${req}`;
    await vscode.env.clipboard.writeText(prompt);

    const go = await vscode.window.showInformationMessage(
        '需求已写入 preprocess_custom.py，提示词已复制到剪贴板。\n' +
        '① 切到 Trae 聊天【粘贴发送】，让 AI 填好 process()  ② 回来点"运行"',
        { modal: false }, '运行 (AI已填好)');
    if (go !== '运行 (AI已填好)') return;
    return runPreprocess(root, inRel, '--custom scripts/preprocess_custom.py', 'custom');
}

async function runPreprocess(root, inRel, args, tag) {
    const ext = path.extname(inRel);
    const outRel = path.join('sim', 'testdata',
        `pre_${tag}_${Date.now() % 100000}${ext}`);
    out.show(true);
    const code = await run(
        `${pyExec(root)} scripts/preprocess.py -i "${inRel}" -o "${outRel}" ${args}`,
        root);
    if (code !== 0) {
        vscode.window.showErrorMessage('预处理失败 — 详见 VIP Sim 输出面板');
        return;
    }
    let frames = getState().frames;
    if (isVideoPath(outRel)) {
        const total = await probeVideoFrames(root, outRel);
        frames = Math.max(1, Math.min(total || frames, 30));
    }
    await setState({ inputImage: outRel, frames });
    vscode.window.showInformationMessage(`预处理完成 → ${path.basename(outRel)}`);
    refreshConsole();
}

async function exportImage() {
    const root = wsRoot();
    const st = getState();
    // 视频模式导出 MP4
    if (isVideoPath(st.inputImage)) {
        const src = path.join(root, 'output', 'video', `${st.ip}_output.mp4`);
        if (!fs.existsSync(src)) {
            vscode.window.showWarningMessage('暂无输出视频, 请先运行视频仿真');
            return;
        }
        const dest = await vscode.window.showSaveDialog({
            defaultUri: vscode.Uri.file(
                path.join(require('os').homedir(), `${st.ip}_output.mp4`)),
            filters: { MP4: ['mp4'] },
        });
        if (!dest) return;
        fs.copyFileSync(src, dest.fsPath);
        vscode.window.showInformationMessage(`已导出视频: ${dest.fsPath}`);
        return;
    }
    const src = path.join(root, 'output', 'images', `${st.ip}_output.png`);
    if (!fs.existsSync(src)) {
        vscode.window.showWarningMessage('暂无仿真输出图像, 请先运行仿真');
        return;
    }
    const dest = await vscode.window.showSaveDialog({
        defaultUri: vscode.Uri.file(
            path.join(require('os').homedir(), `${st.ip}_output.png`)),
        filters: { PNG: ['png'] },
    });
    if (!dest) return;
    fs.copyFileSync(src, dest.fsPath);
    vscode.window.showInformationMessage(`已导出: ${dest.fsPath}`);
}

// ---------- 测试图卡生成 ----------

const PATTERNS = [
    { label: '灰阶渐变 (Gamma/对比度)', args: '--pattern ramp', file: 'pattern_ramp.png' },
    { label: '彩条 (色彩空间转换)', args: '--pattern colorbar', file: 'pattern_colorbar.png' },
    { label: '低对比度图 (对比度增强)', args: '--pattern lowcontrast', file: 'pattern_lowcontrast.png' },
    { label: '棋盘格 (边界检查)', args: '--pattern checker', file: 'pattern_checker.png' },
    { label: '灰卡·中性 6500K (AWB)', args: '--pattern graycard', file: 'pattern_gray6500.png' },
    { label: '灰卡·偏暖 3000K (AWB)', args: '--pattern graycard --color-temp 3000', file: 'pattern_gray3000.png' },
    { label: '灰卡·偏冷 8500K (AWB)', args: '--pattern graycard --color-temp 8500', file: 'pattern_gray8500.png' },
    { label: '当前输入图 + 高斯噪声 σ=15 (降噪)', base: true, args: '--sigma 15', file: 'pattern_noisy.png' },
    { label: '当前输入图 + 100坏点 (坏点校正)', base: true,
      args: '--dead 100 --table sim/testdata/dpc_table.txt', file: 'pattern_defect.png' },
];

async function genPattern() {
    const root = wsRoot();
    const st = getState();
    const pick = await vscode.window.showQuickPick(
        PATTERNS.map((p) => p.label), { placeHolder: '选择测试图卡类型' });
    if (!pick) return;
    const p = PATTERNS.find((x) => x.label === pick);
    const py = fs.existsSync(path.join(root, '.venv/bin/python'))
        ? '.venv/bin/python' : 'python3';
    const rel = path.join('sim', 'testdata', p.file);
    const baseArg = p.base ? `--base "${st.inputImage}"` : '';
    const code = await run(
        `${py} scripts/gen_pattern.py ${baseArg} ${p.args} ` +
        `-W ${st.width} -H ${st.height} -o "${rel}"`, root);
    if (code !== 0) {
        vscode.window.showErrorMessage('图卡生成失败 — 详见 VIP Sim 输出面板');
        return;
    }
    await setState({ inputImage: rel });
    refreshConsole();
}

// ---------- 环境自检 / 环境同步 ----------

async function cmdCheckEnv() {
    const root = wsRoot();
    const items = [];
    const check = (cmd) => new Promise((res) =>
        cp.exec(cmd, { cwd: root }, (e, so) => res(e ? null : so.trim())));
    const iv = await check('iverilog -V 2>/dev/null | head -1');
    items.push(iv ? `✓ ${iv.split('\n')[0]}` : '✗ iverilog 未安装 (brew install icarus-verilog)');
    const py = root && fs.existsSync(path.join(root, '.venv/bin/python'))
        ? '.venv/bin/python' : null;
    if (py) {
        const ok = await check(`${py} -c "import cv2,numpy,PIL;print(cv2.__version__)"`);
        items.push(ok ? `✓ 项目 venv + opencv ${ok}` : '✗ venv 存在但缺图像库');
    } else {
        items.push('✗ 项目缺 .venv (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)');
    }
    items.push(fs.existsSync(path.join(root || '', 'sim/common/reg_config.v'))
        ? '✓ 环境文件含寄存器配置 BFM' : '✗ 环境文件过旧, 请运行 "VIP Sim: 同步环境文件"');
    vscode.window.showInformationMessage(`VIP Sim 环境自检: ${items.join('  |  ')}`);
}

// 把扩展模板里的环境文件同步到当前项目 (扩展升级后让老项目获得新 BFM/脚本/规则)
async function cmdSyncEnv() {
    const root = wsRoot();
    if (!isVipProject(root)) return noProject();
    const sel = await vscode.window.showWarningMessage(
        '将用扩展内置版本覆盖本项目的环境文件:\n' +
        'sim/common/、scripts/、.trae/rules/、Makefile、requirements.txt\n' +
        '(不会动 rtl/、sim/tests/、sim/testdata/、docs/ 等你自己的文件)',
        { modal: true }, '同步');
    if (sel !== '同步') return;
    const t = path.join(extCtx.extensionPath, 'template');
    for (const d of ['sim/common', 'scripts', '.trae/rules']) {
        fs.cpSync(path.join(t, d), path.join(root, d), { recursive: true });
    }
    for (const f of ['Makefile', 'requirements.txt']) {
        fs.copyFileSync(path.join(t, f), path.join(root, f));
    }
    vscode.window.showInformationMessage('环境文件已同步到扩展当前版本');
}

// ---------- 仿真控制台 ----------

function postToConsole(msg) {
    if (consolePanel) consolePanel.webview.postMessage(msg);
}

function consoleState() {
    const root = wsRoot();
    const st = getState();
    const ips = listIPs(root);
    if (!ips.includes(st.ip) && ips.length) st.ip = ips[0];
    const report = readReport(root, st.ip);
    const webview = consolePanel.webview;
    const imgUri = (rel) => {
        const p = path.join(root, rel);
        return fs.existsSync(p)
            ? webview.asWebviewUri(vscode.Uri.file(p)).toString() +
              '?t=' + fs.statSync(p).mtimeMs
            : undefined;
    };
    // 视频模式: 逐帧 PNG 的 URI 数组 + 时序分析报告
    let video;
    if (isVideoPath(st.inputImage)) {
        const vinfo = extCtx.workspaceState.get(`video:${st.ip}`, undefined);
        if (vinfo && vinfo.frames) {
            const fr = [];
            for (let k = 0; k < vinfo.frames; k++) {
                const fn = `frame_${String(k).padStart(3, '0')}.png`;
                fr.push({
                    in: imgUri(`output/video/${st.ip}_in/${fn}`),
                    out: imgUri(`output/video/${st.ip}_out/${fn}`),
                });
            }
            let vrep;
            const vp = path.join(root, 'output', 'reports', `${st.ip}_video.json`);
            if (fs.existsSync(vp)) {
                try { vrep = JSON.parse(fs.readFileSync(vp, 'utf8')); } catch {}
            }
            video = { frames: vinfo.frames, urls: fr, report: vrep };
        }
    }
    return {
        ...st, ips,
        regdef: readRegdef(root, st.ip),
        regs: extCtx.workspaceState.get(`regs:${st.ip}`, {}),
        inputThumb: imgUri(st.inputImage),
        outputThumb: imgUri(`output/images/${st.ip}_output.png`),
        report: report ? {
            identical: report.identical,
            resolution: report.resolution,
            psnr: report.psnr.overall,
        } : undefined,
        golden: extCtx.workspaceState.get(`golden:${st.ip}`, undefined),
        video,
    };
}

function refreshConsole() {
    if (consolePanel) {
        postToConsole({ type: 'state', state: consoleState() });
    }
}

function cmdConsole() {
    const root = wsRoot();
    if (!isVipProject(root)) return noProject();

    if (consolePanel) { consolePanel.reveal(); refreshConsole(); return; }

    consolePanel = vscode.window.createWebviewPanel(
        'vipsimConsole', 'VIP 仿真控制台', vscode.ViewColumn.One, {
            enableScripts: true,
            retainContextWhenHidden: true,
            localResourceRoots: [vscode.Uri.file(root)],
        });
    consolePanel.onDidDispose(() => { consolePanel = undefined; });
    const persistParams = async (p) => {
        if (!p) return;
        const { ip, width, height, frames, inputImage, regs } = p;
        await setState({ ip, width, height, frames, inputImage });
        if (regs) await extCtx.workspaceState.update(`regs:${ip}`, regs);
    };
    consolePanel.webview.onDidReceiveMessage(async (m) => {
        switch (m.cmd) {
            case 'run': await doRun(m.params); break;
            case 'import': await importImage(); break;
            case 'importVideo': await importVideo(); break;
            case 'preprocess':
                await persistParams(m.params);
                await preprocessMedia();
                break;
            case 'aiPreprocess':
                await persistParams(m.params);
                await customPreprocess(wsRoot(), getState().inputImage);
                break;
            case 'pattern':
                await persistParams(m.params);
                await genPattern();
                break;
            case 'export': await exportImage(); break;
            case 'wave': await cmdViewWave(); break;
            case 'panel':
                await persistParams(m.params);
                await openDimPanel(m.id, m.params && m.params.frame);
                break;
            case 'temporal':
                openTemporalPanel();
                break;
            case 'saveState':
                await persistParams(m.params);
                if (m.refresh) refreshConsole();
                break;
            case 'refresh': refreshConsole(); break;
        }
    });
    consolePanel.webview.html = consoleHtml(consolePanel.webview);
    refreshConsole();
}

function consoleHtml(webview) {
    const nonce = Math.random().toString(36).slice(2);
    return `<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none';
 img-src ${webview.cspSource}; style-src 'unsafe-inline';
 script-src 'nonce-${nonce}';">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:var(--vscode-font-family),system-ui,-apple-system,sans-serif;
  color:var(--vscode-foreground);background:var(--vscode-sideBar-background);
  line-height:1.5;overflow-y:auto;
}

/* ========== HEADER ========== */
.header{
  background:linear-gradient(135deg,#1a73e833,#8e24aa33);
  border:1px solid var(--vscode-panel-border);border-radius:12px;
  padding:20px 24px;margin-bottom:16px;
}
.header .title{
  font-size:1.35em;font-weight:700;letter-spacing:-0.3px;
  color:var(--vscode-foreground);
}
.header .sub{
  font-size:0.82em;opacity:.6;margin-top:2px;
}
.header .project-name{
  font-weight:600;color:var(--vscode-textLink-foreground);
}

/* ========== CARD ========== */
.card{
  background:var(--vscode-editor-background);
  border:1px solid var(--vscode-panel-border);border-radius:10px;
  margin-bottom:14px;overflow:hidden;
  box-shadow:0 1px 3px rgba(0,0,0,.08);
}
.card-head{
  display:flex;align-items:center;gap:8px;
  padding:12px 16px;border-bottom:1px solid var(--vscode-panel-border);
  background:var(--vscode-tab-inactiveBackground,var(--vscode-editor-background));
  font-size:0.88em;font-weight:600;letter-spacing:0.2px;
  text-transform:uppercase;opacity:.8;
}
.card-head .icon{font-size:1.15em;opacity:.55}
.card-body{padding:14px 16px}

/* ========== PARAM ROW ========== */
.param-row{
  display:flex;flex-wrap:wrap;gap:14px;align-items:center;
}
.param-item{
  display:flex;align-items:center;gap:6px;
}
.param-item label{
  font-size:0.83em;font-weight:600;opacity:.7;white-space:nowrap;
}
.param-item input, .param-item select{
  background:var(--vscode-input-background);
  color:var(--vscode-input-foreground);
  border:1px solid var(--vscode-input-border,var(--vscode-panel-border));
  padding:5px 8px;border-radius:6px;font-size:0.88em;
  transition:border-color .15s;
}
.param-item input:focus, .param-item select:focus{
  outline:none;border-color:var(--vscode-focusBorder);
  box-shadow:0 0 0 1px var(--vscode-focusBorder);
}
.param-item input{width:72px}
.param-item select{width:auto;min-width:130px}

/* ========== REG TABLE ========== */
#regbox{max-height:220px;overflow-y:auto}
#regtable{width:100%;border-collapse:collapse;font-size:0.83em}
#regtable th{
  text-align:left;padding:7px 8px;font-weight:600;opacity:.65;
  border-bottom:2px solid var(--vscode-panel-border);
  position:sticky;top:0;background:var(--vscode-editor-background);
}
#regtable td{
  padding:6px 8px;border-bottom:1px solid var(--vscode-panel-border);
  vertical-align:middle;
}
#regtable .regv{
  background:var(--vscode-input-background);
  color:var(--vscode-input-foreground);
  border:1px solid var(--vscode-panel-border);border-radius:5px;
  padding:3px 6px;font-family:monospace;font-size:0.9em;width:105px;
}
#regtable .regv:focus{
  outline:none;border-color:var(--vscode-focusBorder);
}
.reg-hint{
  font-size:0.78em;opacity:.5;margin-top:6px;
  display:flex;align-items:center;gap:10px;
}

/* ========== MEDIA PANELS ========== */
.media-grid{
  display:grid;grid-template-columns:1fr 1fr;gap:14px;
}
.media-card{
  background:var(--vscode-sideBar-background);
  border:1px dashed var(--vscode-panel-border);border-radius:10px;
  padding:16px;text-align:center;
  transition:border-color .2s;
}
.media-card:hover{border-color:var(--vscode-focusBorder)}
.media-card .label{
  font-size:0.8em;font-weight:600;opacity:.55;text-transform:uppercase;
  letter-spacing:0.5px;margin-bottom:8px;
}
.media-card img{
  image-rendering:pixelated;max-height:100px;max-width:100%;
  border-radius:6px;margin-bottom:8px;
  box-shadow:0 2px 8px rgba(0,0,0,.15);
}
.media-card img[src=""]{display:none}
.media-card .placeholder{
  color:var(--vscode-input-placeholderForeground);
  font-size:0.82em;padding:28px 0;
}
.media-actions{
  display:flex;flex-wrap:wrap;gap:5px;justify-content:center;
}

/* ========== BUTTONS ========== */
.btn{
  display:inline-flex;align-items:center;gap:5px;
  padding:5px 14px;cursor:pointer;border:none;border-radius:6px;
  font-size:0.82em;font-weight:500;transition:all .15s;
  background:var(--vscode-button-background);
  color:var(--vscode-button-foreground);
}
.btn:hover{filter:brightness(1.1)}
.btn:active{transform:scale(.97)}
.btn-secondary{
  background:var(--vscode-button-secondaryBackground);
  color:var(--vscode-button-secondaryForeground);
}
.btn-primary{
  background:linear-gradient(135deg,#3b82f6,#7c3aed);
  color:#fff;font-size:0.95em;font-weight:600;
  padding:9px 28px;border-radius:8px;
  box-shadow:0 2px 8px rgba(124,58,237,.3);
}
.btn-primary:hover{box-shadow:0 4px 14px rgba(124,58,237,.4)}
.btn-sm{padding:3px 10px;font-size:0.78em}
.btn-icon{padding:5px;border-radius:6px;min-width:unset}

.btn-group{display:flex;flex-wrap:wrap;gap:6px}

/* ========== TOOLBAR ========== */
.toolbar{
  display:flex;flex-wrap:wrap;align-items:center;gap:10px;
  padding:14px 0;
}
.toolbar .btn-primary{margin-right:auto}

/* ========== STATUS / RESULT ========== */
#status{
  margin:8px 0;min-height:1.4em;font-size:0.85em;
  display:flex;align-items:center;gap:6px;
}
#status .dot{
  width:8px;height:8px;border-radius:50%;display:inline-block;
  animation:pulse 1.5s infinite;
}
.dot.green{background:#2da44e}
.dot.yellow{background:#bf8700}
.dot.red{background:#cf222e}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

#result{margin-top:8px;font-size:0.84em}
#result p{margin:4px 0}
.pill{
  display:inline-flex;align-items:center;gap:4px;
  padding:2px 12px;border-radius:12px;
  font-size:0.82em;font-weight:600;
}
.pill-ok{background:#2da44e22;color:#2da44e}
.pill-warn{background:#bf870022;color:#bf8700}
.pill-fail{background:#cf222e22;color:#cf222e}
.pill-muted{background:var(--vscode-badge-background);color:var(--vscode-badge-foreground)}

/* ========== VIDEO SLIDER ========== */
#videoBox{margin-top:14px}
.slider-row{
  display:flex;align-items:center;gap:10px;margin-bottom:10px;
  font-size:0.85em;font-weight:500;
}
.slider-row input[type=range]{
  flex:1;-webkit-appearance:none;height:6px;
  background:var(--vscode-panel-border);border-radius:3px;
}

/* ========== ANALYSIS GRID ========== */
.analysis-grid{
  display:grid;grid-template-columns:repeat(3,1fr);gap:6px;
}
.analysis-grid .btn{justify-content:center}

/* ========== FOOTER ========== */
.footer{
  margin-top:20px;padding-top:12px;
  border-top:1px solid var(--vscode-panel-border);
  text-align:center;font-size:0.75em;opacity:.35;
}

/* ========== 美化增强 ========== */
body{padding:18px 22px;max-width:1080px;margin:0 auto}
.card{transition:box-shadow .2s,border-color .2s}
.card:hover{box-shadow:0 3px 12px rgba(0,0,0,.14)}
/* 寄存器行悬停高亮 + 斑马纹 */
#regtable tbody tr:hover td{background:var(--vscode-list-hoverBackground,rgba(127,127,127,.08))}
/* 视频滑块拖柄 (默认很丑) */
.slider-row input[type=range]{cursor:pointer}
.slider-row input[type=range]::-webkit-slider-thumb{
  -webkit-appearance:none;width:16px;height:16px;border-radius:50%;
  background:var(--vscode-button-background,#3b82f6);
  border:2px solid var(--vscode-editor-background);cursor:pointer;
  box-shadow:0 1px 4px rgba(0,0,0,.35);transition:transform .12s;
}
.slider-row input[type=range]::-webkit-slider-thumb:hover{transform:scale(1.2)}
/* 滚动条细化 */
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{
  background:var(--vscode-scrollbarSlider-background,rgba(127,127,127,.4));
  border-radius:5px;
}
::-webkit-scrollbar-thumb:hover{background:var(--vscode-scrollbarSlider-hoverBackground,rgba(127,127,127,.6))}
/* 卡片标题渐入下划线点缀 */
.card-head .icon{font-style:normal}
/* 媒体图片悬停轻微放大 */
.media-card img{transition:transform .2s}
.media-card img:hover{transform:scale(1.04)}
</style></head><body>

<!--- HEADER --->
<div class="header">
  <div class="title">&#x1F3AC; VIP 仿真控制台</div>
  <div class="sub">awesom 视频处理IP · 端到端仿真验证平台</div>
</div>

<!--- 仿真参数 --->
<div class="card">
  <div class="card-head"><span class="icon">&#x2699;</span> 仿真参数</div>
  <div class="card-body">
    <div class="param-row">
      <div class="param-item"><label>目标 IP</label><select id="ip"></select></div>
      <div class="param-item"><label>宽</label><input id="width" type="number" placeholder="640"></div>
      <div class="param-item"><label>高</label><input id="height" type="number" placeholder="480"></div>
      <div class="param-item"><label>帧数</label><input id="frames" type="number" placeholder="1"></div>
    </div>
  </div>
</div>

<!--- 寄存器配置 --->
<div class="card">
  <div class="card-head"><span class="icon">&#x1F4CB;</span> 寄存器配置 <span style="font-weight:400;opacity:.5;font-size:.85em;text-transform:none">— 仿真开始时写入 DUT</span></div>
  <div class="card-body">
    <div id="regbox"><table id="regtable"></table></div>
    <div class="reg-hint">
      <span>可写(RW)寄存器可编辑 · 只读(RO)仅展示复位值</span>
      <button class="btn btn-secondary btn-sm" id="btnRegReset">&#x21BA; 恢复缺省值</button>
    </div>
  </div>
</div>

<!--- 媒体输入/输出 --->
<div class="card">
  <div class="card-head"><span class="icon">&#x1F5BC;</span> 媒体输入 / 输出</div>
  <div class="card-body">
    <div class="media-grid">
      <div class="media-card">
        <div class="label" id="inName">&#x1F4E5; 输入图像</div>
        <img id="inThumb" alt="">
        <div class="placeholder" id="inPlaceholder">暂无输入图像</div>
        <div class="media-actions">
          <button class="btn btn-secondary btn-sm" id="btnImport">&#x1F4C2; 导入图像</button>
          <button class="btn btn-secondary btn-sm" id="btnImportVideo">&#x1F3AC; 导入视频</button>
          <button class="btn btn-secondary btn-sm" id="btnPattern">&#x1F3A8; 生成图卡</button>
          <button class="btn btn-secondary btn-sm" id="btnPreprocess">&#x2694; 预处理</button>
          <button class="btn btn-secondary btn-sm" id="btnAiPreprocess">&#x1F916; AI预处理</button>
        </div>
      </div>
      <div class="media-card">
        <div class="label">&#x1F4E4; 仿真输出</div>
        <img id="outThumb" alt="">
        <div class="placeholder" id="outPlaceholder">尚未运行仿真</div>
        <div class="media-actions">
          <button class="btn btn-secondary btn-sm" id="btnExport">&#x1F4BE; 导出图像</button>
        </div>
      </div>
    </div>
    <div id="mediaHint" style="font-size:.8em;opacity:.5;margin-top:8px"></div>
  </div>
</div>

<!--- 操作工具栏 --->
<div class="toolbar">
  <button class="btn btn-primary" id="btnRun">&#x25B6; 运行仿真</button>
  <button class="btn btn-secondary" id="btnWave">&#x1F4C8; 查看波形</button>
</div>

<!--- 状态 & 结果 --->
<div id="status"></div>
<div id="result"></div>

<!--- 视频逐帧预览 --->
<div class="card" id="videoBox" style="display:none">
  <div class="card-head"><span class="icon">&#x1F39E;</span> 视频逐帧预览</div>
  <div class="card-body">
    <div class="slider-row">
      <span>帧</span><span id="frIdx" style="min-width:28px;text-align:right">0</span>
      <span style="opacity:.4">/</span><span id="frMax">0</span>
      <input type="range" id="frSlider" min="0" max="0" value="0">
    </div>
    <div class="media-grid">
      <div class="media-card">
        <div class="label">输入帧</div>
        <img id="vinFrame">
      </div>
      <div class="media-card">
        <div class="label">输出帧</div>
        <img id="voutFrame">
      </div>
    </div>
    <div class="btn-group" style="margin-top:10px">
      <button class="btn btn-secondary btn-sm" id="btnTemporal">&#x1F4CA; 时序分析</button>
      <span style="font-size:.78em;opacity:.45;align-self:center">下方分析按钮对当前选中帧生效</span>
    </div>
  </div>
</div>

<!--- 结果分析 --->
<div class="card">
  <div class="card-head"><span class="icon">&#x1F4CA;</span> 结果分析 <span style="font-weight:400;opacity:.5;font-size:.85em;text-transform:none">— 点击弹出对应面板</span></div>
  <div class="card-body">
    <div class="analysis-grid">
      <button class="btn btn-secondary" data-p="compare">&#x1F4F7; 图像对比</button>
      <button class="btn btn-secondary" data-p="diff">&#x1F525; 差异热力图</button>
      <button class="btn btn-secondary" data-p="sharp">&#x1F50D; 锐度分析</button>
      <button class="btn btn-secondary" data-p="wb">&#x1F321; 白平衡分析</button>
      <button class="btn btn-secondary" data-p="hist">&#x1F4CA; 直方图</button>
      <button class="btn btn-secondary" data-p="psnr">&#x1F4E1; PSNR</button>
    </div>
  </div>
</div>

<div class="footer">VIP Sim v0.9.0 · awesom</div>

<script nonce="${nonce}">
const vscode = acquireVsCodeApi();
let S = {};

function normHex(v) {
  const n = parseInt(String(v).trim().replace(/^0x/i, ''), 16);
  return Number.isNaN(n) ? null
    : '0x' + (n >>> 0).toString(16).toUpperCase().padStart(8, '0');
}
function collectRegs() {
  const regs = {};
  for (const inp of document.querySelectorAll('.regv')) {
    const h = normHex(inp.value);
    if (h !== null) { regs[inp.dataset.addr] = h; inp.value = h; }
  }
  return regs;
}
let curFrame = 0;
function params() {
  return { ip: document.getElementById('ip').value,
    width: +document.getElementById('width').value,
    height: +document.getElementById('height').value,
    frames: +document.getElementById('frames').value,
    inputImage: S.inputImage,
    frame: curFrame,
    regs: collectRegs() };
}
function renderRegs() {
  const tb = document.getElementById('regtable');
  if (!S.regdef || S.regdef.length === 0) {
    tb.innerHTML = '<tr><td style="opacity:.6">该 IP 无寄存器 (未找到 rtl/' +
      (S.ip || '?') + '/regdef.json)</td></tr>';
    return;
  }
  let h = '<tr><th>地址</th><th>名称</th><th>访问</th><th>值</th><th>说明</th></tr>';
  let lastGroup;
  for (const r of S.regdef) {
    if (r.group && r.group !== lastGroup) {
      h += '<tr><td colspan="5" style="opacity:.75;font-weight:bold;' +
        'border-top:2px solid var(--vscode-panel-border)">子 IP: ' +
        r.group + '</td></tr>';
      lastGroup = r.group;
    }
    const cur = (S.regs && S.regs[r.addr]) || r.default;
    const val = r.access === 'RW'
      ? '<input class="regv" data-addr="' + r.addr + '" value="' +
        (normHex(cur) || r.default) + '" style="width:110px;font-family:monospace">'
      : '<span style="font-family:monospace;opacity:.7">' + r.default + '</span>';
    h += '<tr><td style="font-family:monospace">' + r.addr + '</td><td>' +
      r.name + '</td><td>' + r.access + '</td><td>' + val + '</td>' +
      '<td style="opacity:.8">' + r.desc + '</td></tr>';
  }
  tb.innerHTML = h;
  for (const inp of tb.querySelectorAll('.regv')) {
    inp.onchange = () => vscode.postMessage({ cmd: 'saveState', params: params() });
  }
}
document.getElementById('btnRun').onclick =
  () => vscode.postMessage({ cmd: 'run', params: params() });
document.getElementById('btnImport').onclick =
  () => vscode.postMessage({ cmd: 'import' });
document.getElementById('btnImportVideo').onclick =
  () => vscode.postMessage({ cmd: 'importVideo' });
document.getElementById('btnPattern').onclick =
  () => vscode.postMessage({ cmd: 'pattern', params: params() });
document.getElementById('btnPreprocess').onclick =
  () => vscode.postMessage({ cmd: 'preprocess', params: params() });
document.getElementById('btnAiPreprocess').onclick =
  () => vscode.postMessage({ cmd: 'aiPreprocess', params: params() });
document.getElementById('btnExport').onclick =
  () => vscode.postMessage({ cmd: 'export' });
document.getElementById('btnWave').onclick =
  () => vscode.postMessage({ cmd: 'wave' });
for (const b of document.querySelectorAll('[data-p]')) {
  b.onclick = () => vscode.postMessage(
    { cmd: 'panel', id: b.dataset.p, params: params() });
}
// 切换 IP 需重新拉取该 IP 的寄存器表; 其余参数仅保存
document.getElementById('ip').onchange = () => {
  const p = params();
  delete p.regs;          // 切换瞬间的输入框还属于旧 IP, 不写入新 IP
  vscode.postMessage({ cmd: 'saveState', params: p, refresh: true });
};
for (const id of ['width', 'height', 'frames']) {
  document.getElementById(id).onchange =
    () => vscode.postMessage({ cmd: 'saveState', params: params() });
}
document.getElementById('btnRegReset').onclick = () => {
  S.regs = {};
  renderRegs();
  vscode.postMessage({ cmd: 'saveState', params: params() });
};
document.getElementById('frSlider').oninput = (e) => {
  curFrame = +e.target.value;
  showFrame();
};
document.getElementById('btnTemporal').onclick =
  () => vscode.postMessage({ cmd: 'temporal' });

function showFrame() {
  if (!S.video || !S.video.urls) return;
  const f = S.video.urls[curFrame];
  if (!f) return;
  document.getElementById('frIdx').textContent = curFrame;
  if (f.in) document.getElementById('vinFrame').src = f.in;
  if (f.out) document.getElementById('voutFrame').src = f.out;
}

window.addEventListener('message', (e) => {
  const m = e.data;
  if (m.type === 'status') {
    const el = document.getElementById('status');
    if (m.running) {
      el.innerHTML = '<span class="dot green"></span> ' + m.text;
    } else {
      el.innerHTML = m.text;
    }
  }
  if (m.type === 'state') {
    S = m.state;
    const sel = document.getElementById('ip');
    sel.innerHTML = '';
    for (const ip of S.ips) {
      const o = document.createElement('option');
      o.value = o.textContent = ip;
      if (ip === S.ip) o.selected = true;
      sel.appendChild(o);
    }
    document.getElementById('width').value = S.width;
    document.getElementById('height').value = S.height;
    document.getElementById('frames').value = S.frames;
    renderRegs();
    const isVid = /\.(mp4|avi|mov|mkv)$/i.test(S.inputImage || '');
    const inLabel = document.getElementById('inName');
    inLabel.innerHTML = isVid ? '&#x1F3AC; 输入视频' : '&#x1F4E5; 输入图像';
    if (S.inputImage) {
      inLabel.title = S.inputImage;
    }
    document.getElementById('mediaHint').textContent = isVid
      ? '视频模式: 运行将流式仿真前 ' + S.frames + ' 帧并导出 MP4 (帧数可在上方调整)'
      : '';
    const setImg = (id, src) => {
      const el = document.getElementById(id);
      const phId = id === 'inThumb' ? 'inPlaceholder' : 'outPlaceholder';
      const ph = document.getElementById(phId);
      if (src) { el.src = src; el.style.display = ''; if (ph) ph.style.display = 'none'; }
      else { el.removeAttribute('src'); el.style.display = 'none'; if (ph) ph.style.display = ''; }
    };
    setImg('inThumb', isVid ? undefined : S.inputThumb);
    setImg('outThumb', isVid ? undefined : S.outputThumb);
    // 视频逐帧预览
    const vbox = document.getElementById('videoBox');
    if (S.video && S.video.frames > 0) {
      vbox.style.display = '';
      const sl = document.getElementById('frSlider');
      sl.max = S.video.frames - 1;
      document.getElementById('frMax').textContent = S.video.frames - 1;
      if (curFrame > S.video.frames - 1) curFrame = 0;
      sl.value = curFrame;
      showFrame();
    } else {
      vbox.style.display = 'none';
    }
    document.getElementById('status').textContent = '';
    var html = '';
    if (S.golden) {
      var g = S.golden.state;
      if (g === 'video') {
        html += '<p>&#x1F4CB; 金标准 &nbsp;<span class="pill pill-muted">' +
          '视频模式 · 逐帧不做按位比对</span> ' +
          '<span style="opacity:.5;font-size:.85em">用"时序分析"评估时域稳定性</span></p>';
      } else if (g === 'na') {
        html += '<p>&#x1F4CB; 金标准 &nbsp;<span class="pill pill-muted">' +
          '无参考模型 (组合设计/自定义 IP)</span></p>';
      } else if (g === 'error') {
        html += '<p>&#x1F4CB; 金标准 &nbsp;<span class="pill pill-warn">' +
          '验证出错</span> <span style="opacity:.5;font-size:.85em">' + (S.golden.line || '') +
          '</span></p>';
      } else {
        var ok = g === 'pass';
        html += '<p>&#x1F4CB; 金标准 &nbsp;<span class="pill ' +
          (ok ? 'pill-ok' : 'pill-fail') + '">' + (ok ? 'PASS' : 'FAIL') +
          '</span> <span style="opacity:.5;font-size:.85em">' + (S.golden.line || '') +
          '</span></p>';
      }
    }
    if (S.report) {
      html += '<p>&#x1F4CA; 质量分析 &nbsp;' + (S.report.identical
        ? '<span class="pill pill-ok">输出与输入完全一致 (直通验证)</span>'
        : '<span class="pill pill-muted">PSNR ' + (S.report.psnr ?? '∞') + '</span>') + ' · ' + S.report.resolution + '</p>';
    }
    document.getElementById('result').innerHTML =
      html || '<p style="opacity:.35;font-size:.85em">尚无结果，请运行仿真</p>';
  }
});
vscode.postMessage({ cmd: 'refresh' });
</script></body></html>`;
}

// ---------- 分析维度面板 ----------

const DIMS = {
    compare: '图像对比',
    diff: '差异热力图',
    sharp: '锐度分析',
    wb: '白平衡分析',
    hist: '直方图',
    psnr: 'PSNR',
};

async function openDimPanel(id, frame) {
    const root = wsRoot();
    const st = getState();
    const video = isVideoPath(st.inputImage);
    let report, imgDir, imgBase;

    if (video) {
        // 视频: 对选中帧的 in/out PNG 现跑 analyze.py 生成该帧的报告 + 差异图
        const k = String(frame || 0).padStart(3, '0');
        const inP = `output/video/${st.ip}_in/frame_${k}.png`;
        const outP = `output/video/${st.ip}_out/frame_${k}.png`;
        if (!fs.existsSync(path.join(root, outP))) {
            vscode.window.showWarningMessage('该帧无数据, 请先运行视频仿真');
            return;
        }
        const rep = `output/reports/${st.ip}_frame${k}.json`;
        const diff = `output/video/${st.ip}_out/diff_${k}.png`;
        const code = await run(`${pyExec(root)} scripts/analyze.py ` +
            `--input ${inP} --output ${outP} --report ${rep} --diff ${diff}`, root);
        if (code !== 0) { vscode.window.showErrorMessage('帧分析失败'); return; }
        report = JSON.parse(fs.readFileSync(path.join(root, rep), 'utf8'));
        imgDir = path.join(root, 'output', 'video', `${st.ip}_out`);
        imgBase = { input: path.join(root, inP), output: path.join(root, outP),
                    diff: path.join(root, diff) };
    } else {
        report = readReport(root, st.ip);
        if (!report) {
            vscode.window.showWarningMessage('尚无分析报告, 请先运行仿真');
            return;
        }
        const d = path.join(root, 'output', 'images');
        imgBase = { input: path.join(d, `${st.ip}_input.png`),
                    output: path.join(d, `${st.ip}_output.png`),
                    diff: path.join(d, `${st.ip}_diff.png`) };
    }

    if (dimPanels[id]) dimPanels[id].dispose();
    const title = video ? `${DIMS[id]}: ${st.ip} 帧${frame || 0}` : `${DIMS[id]}: ${st.ip}`;
    const panel = vscode.window.createWebviewPanel(
        `vipsim.${id}`, title, vscode.ViewColumn.Beside, {
            enableScripts: true,
            localResourceRoots: [vscode.Uri.file(path.join(root, 'output'))],
        });
    dimPanels[id] = panel;
    panel.onDidDispose(() => { delete dimPanels[id]; });

    const u = (p) => panel.webview.asWebviewUri(vscode.Uri.file(p)).toString();
    const imgs = { input: u(imgBase.input), output: u(imgBase.output),
                   diff: u(imgBase.diff) };
    panel.webview.html = dimHtml(panel.webview, id, st.ip, report, imgs);
}

let temporalPanel;
function openTemporalPanel() {
    const root = wsRoot();
    const st = getState();
    const vp = path.join(root, 'output', 'reports', `${st.ip}_video.json`);
    if (!fs.existsSync(vp)) {
        vscode.window.showWarningMessage('尚无视频时序报告, 请先运行视频仿真');
        return;
    }
    const rep = JSON.parse(fs.readFileSync(vp, 'utf8'));
    if (temporalPanel) temporalPanel.dispose();
    temporalPanel = vscode.window.createWebviewPanel(
        'vipsim.temporal', `时序分析: ${st.ip}`, vscode.ViewColumn.Beside,
        { enableScripts: true });
    temporalPanel.onDidDispose(() => { temporalPanel = undefined; });
    const nonce = Math.random().toString(36).slice(2);
    const pf = rep.per_frame;
    const series = {
        idx: pf.map((f) => f.idx),
        sharp_in: pf.map((f) => f.sharp_in), sharp_out: pf.map((f) => f.sharp_out),
        luma_in: pf.map((f) => f.luma_in), luma_out: pf.map((f) => f.luma_out),
        psnr: pf.map((f) => f.psnr === null ? null : f.psnr),
    };
    temporalPanel.webview.html = `<!DOCTYPE html><html lang="zh"><head>
<meta charset="UTF-8"><meta http-equiv="Content-Security-Policy"
 content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);
 padding:12px 20px}h2{margin:6px 0}canvas{border:1px solid var(--vscode-panel-border);
 background:var(--vscode-editor-background);margin:8px 0}
 .lg{font-size:.85em;opacity:.8}</style></head><body>
<h2>时序分析: ${st.ip} (${rep.frames} 帧, ${rep.resolution})</h2>
<div class="lg">每帧指标随时间变化; 评估帧间一致性与时域稳定性</div>
<h3>锐度 Laplacian 方差 <span class="lg">蓝=输入 橙=输出</span></h3>
<canvas id="cSharp" width="640" height="180"></canvas>
<h3>亮度 (平均 luma) <span class="lg">蓝=输入 橙=输出</span></h3>
<canvas id="cLuma" width="640" height="180"></canvas>
<h3>逐帧 PSNR (输出 vs 输入, dB)</h3>
<canvas id="cPsnr" width="640" height="180"></canvas>
<script nonce="${nonce}">
const S = ${JSON.stringify(series)};
function draw(id, seriesList) {
  const cv = document.getElementById(id), ctx = cv.getContext('2d');
  const W = cv.width, H = cv.height, pad = 30;
  const all = [].concat(...seriesList.map(s => s.data.filter(v => v !== null)));
  if (!all.length) return;
  let mn = Math.min(...all), mx = Math.max(...all);
  if (mn === mx) { mn -= 1; mx += 1; }
  const n = S.idx.length;
  const xx = i => pad + (n <= 1 ? 0 : i / (n - 1) * (W - 2 * pad));
  const yy = v => H - pad - (v - mn) / (mx - mn) * (H - 2 * pad);
  ctx.strokeStyle = '#666'; ctx.beginPath();
  ctx.moveTo(pad, H-pad); ctx.lineTo(W-pad, H-pad); ctx.stroke();
  ctx.fillStyle = '#999'; ctx.font = '10px sans-serif';
  ctx.fillText(mx.toFixed(0), 2, pad+4); ctx.fillText(mn.toFixed(0), 2, H-pad);
  for (const s of seriesList) {
    ctx.strokeStyle = s.color; ctx.fillStyle = s.color; ctx.beginPath();
    let first = true;
    s.data.forEach((v, i) => {
      if (v === null) return;
      const x = xx(i), y = yy(v);
      first ? (ctx.moveTo(x, y), first = false) : ctx.lineTo(x, y);
    });
    ctx.stroke();
    s.data.forEach((v, i) => { if (v !== null) {
      ctx.beginPath(); ctx.arc(xx(i), yy(v), 2.5, 0, 7); ctx.fill(); } });
  }
}
draw('cSharp', [{data:S.sharp_in,color:'#5577ee'},{data:S.sharp_out,color:'#e08a2b'}]);
draw('cLuma', [{data:S.luma_in,color:'#5577ee'},{data:S.luma_out,color:'#e08a2b'}]);
draw('cPsnr', [{data:S.psnr,color:'#4cba4c'}]);
</script></body></html>`;
}

function page(webview, nonce, body, script = '') {
    return `<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none';
 img-src ${webview.cspSource}; style-src 'unsafe-inline';
 script-src 'nonce-${nonce}';">
<style>
 body { font-family: var(--vscode-font-family);
        color: var(--vscode-foreground); padding: 12px 20px; }
 table { border-collapse: collapse; margin: 10px 0; }
 td, th { border: 1px solid var(--vscode-panel-border); padding: 5px 14px; }
 .imgrow { display: flex; gap: 16px; flex-wrap: wrap; margin: 10px 0; }
 .imgrow img { image-rendering: pixelated; border: 1px solid #888;
   width: calc(var(--w) * var(--zoom) * 1px); }
 .imgbox { text-align: center; }
 canvas { border: 1px solid var(--vscode-panel-border); }
 .probe { font-family: var(--vscode-editor-font-family);
   min-height: 1.4em; margin: 6px 0; }
 .swatch { display: inline-block; width: 48px; height: 24px;
   border: 1px solid #888; vertical-align: middle; }
 .note { opacity: .7; }
</style></head><body>${body}
<script nonce="${nonce}">${script}</script></body></html>`;
}

function zoomBar() {
    return `缩放: <select id="zoom">
      <option value="1">1x</option><option value="2">2x</option>
      <option value="4" selected>4x</option><option value="8">8x</option>
    </select>`;
}

const zoomScript = `
document.body.style.setProperty('--zoom', 4);
document.getElementById('zoom').onchange =
  (e) => document.body.style.setProperty('--zoom', e.target.value);`;

function dimHtml(webview, id, ip, report, imgs) {
    const nonce = Math.random().toString(36).slice(2);
    const [W, H] = report.resolution.split('x').map(Number);
    const wStyle = `style="--w:${W}"`;
    const p = (v) => (v === null ? '∞ (完全一致)' : v);

    if (id === 'compare') {
        return page(webview, nonce, `
<h2>图像对比 — ${ip} (${report.resolution})</h2>
<div>${zoomBar()}</div>
<div class="imgrow" ${wStyle}>
 <div class="imgbox"><div>输入 (DUT 激励)</div><img id="a" src="${imgs.input}"></div>
 <div class="imgbox"><div>输出 (仿真结果)</div><img id="b" src="${imgs.output}"></div>
</div>
<div class="probe" id="probe">鼠标悬停图像查看像素值</div>`,
        zoomScript + `
const W=${W}, H=${H};
const off={};
function load(k, el){ const c=document.createElement('canvas');
  c.width=W; c.height=H;
  const d=()=>c.getContext('2d').drawImage(el,0,0);
  el.complete?d():el.addEventListener('load',d); off[k]=c; }
load('a',document.getElementById('a'));
load('b',document.getElementById('b'));
function px(k,x,y){ const d=off[k].getContext('2d')
  .getImageData(x,y,1,1).data; return [d[0],d[1],d[2]]; }
for (const id of ['a','b']) {
 document.getElementById(id).addEventListener('mousemove',(e)=>{
  const r=e.target.getBoundingClientRect();
  const x=Math.min(W-1,Math.floor((e.clientX-r.left)/r.width*W));
  const y=Math.min(H-1,Math.floor((e.clientY-r.top)/r.height*H));
  try { const a=px('a',x,y), b=px('b',x,y);
   document.getElementById('probe').textContent =
    '('+x+','+y+')  输入 RGB('+a.join(',')+')  输出 RGB('+b.join(',')+
    ')  Δ('+a.map((v,i)=>b[i]-v).join(',')+')';
  } catch(err){} }); }`);
    }

    if (id === 'diff') {
        return page(webview, nonce, `
<h2>差异热力图 — ${ip} (×8 放大)</h2>
<p class="note">蓝=无差异, 红=差异大。${report.identical
        ? '本次输出与输入完全一致, 全图应为纯蓝。' : ''}</p>
<div>${zoomBar()}</div>
<div class="imgrow" ${wStyle}><img src="${imgs.diff}"></div>`,
        zoomScript);
    }

    if (id === 'sharp') {
        const s = report.sharpness;
        const delta = (a, b) => (b - a >= 0 ? '+' : '') +
            (((b - a) / (a || 1)) * 100).toFixed(1) + '%';
        return page(webview, nonce, `
<h2>锐度分析 — ${ip}</h2>
<table><tr><th>指标</th><th>输入</th><th>输出</th><th>变化</th></tr>
<tr><td>Laplacian 方差</td><td>${s.input.laplacian_variance}</td>
 <td>${s.output.laplacian_variance}</td>
 <td>${delta(s.input.laplacian_variance, s.output.laplacian_variance)}</td></tr>
<tr><td>Tenengrad</td><td>${s.input.tenengrad}</td>
 <td>${s.output.tenengrad}</td>
 <td>${delta(s.input.tenengrad, s.output.tenengrad)}</td></tr></table>
<p class="note">数值越大锐度越高。锐化 IP 应提升, 降噪 IP 略降为正常。</p>`);
    }

    if (id === 'wb') {
        const w = report.white_balance;
        const sw = (x) => `<span class="swatch" style="background:rgb(${
            Math.round(x.avg_r)},${Math.round(x.avg_g)},${
            Math.round(x.avg_b)})"></span>`;
        return page(webview, nonce, `
<h2>白平衡分析 — ${ip}</h2>
<table><tr><th>指标</th><th>输入</th><th>输出</th></tr>
<tr><td>平均色 (R/G/B)</td>
 <td>${w.input.avg_r} / ${w.input.avg_g} / ${w.input.avg_b} ${sw(w.input)}</td>
 <td>${w.output.avg_r} / ${w.output.avg_g} / ${w.output.avg_b} ${sw(w.output)}</td></tr>
<tr><td>灰度世界增益 (R/G/B)</td>
 <td>${w.input.r_gain} / ${w.input.g_gain} / ${w.input.b_gain}</td>
 <td>${w.output.r_gain} / ${w.output.g_gain} / ${w.output.b_gain}</td></tr></table>
<p class="note">增益偏离 1.0 表示偏色: R 增益 &gt; 1 偏冷(需补红), B 增益 &gt; 1 偏暖(需补蓝)。
AWB IP 的目标是让输出增益更接近 1.0。</p>`);
    }

    if (id === 'hist') {
        return page(webview, nonce, `
<h2>直方图 — ${ip}</h2>
<div class="imgrow">
 <div class="imgbox"><div>输入</div>
   <canvas id="hi" width="360" height="180"></canvas></div>
 <div class="imgbox"><div>输出</div>
   <canvas id="ho" width="360" height="180"></canvas></div>
</div>
<p class="note"><span style="color:#e05555">— R</span>
 <span style="color:#4cba4c">— G</span>
 <span style="color:#5577ee">— B</span></p>`, `
const hist = ${JSON.stringify(report.histograms)};
function draw(id, h) {
 const cv=document.getElementById(id), ctx=cv.getContext('2d');
 const max=Math.max(...h.r,...h.g,...h.b,1);
 const colors={r:'#e05555',g:'#4cba4c',b:'#5577ee'};
 for (const ch of ['r','g','b']) {
  ctx.strokeStyle=colors[ch]; ctx.beginPath();
  h[ch].forEach((v,i)=>{
   const x=i/255*(cv.width-2)+1;
   const y=cv.height-1-(v/max)*(cv.height-10);
   i===0?ctx.moveTo(x,y):ctx.lineTo(x,y); });
  ctx.stroke(); } }
draw('hi', hist.input); draw('ho', hist.output);`);
    }

    if (id === 'psnr') {
        const ps = report.psnr;
        return page(webview, nonce, `
<h2>PSNR — ${ip}</h2>
<table><tr><th>通道</th><th>PSNR (dB)</th></tr>
<tr><td>整体</td><td>${p(ps.overall)}</td></tr>
<tr><td>R</td><td>${p(ps.channel_r)}</td></tr>
<tr><td>G</td><td>${p(ps.channel_g)}</td></tr>
<tr><td>B</td><td>${p(ps.channel_b)}</td></tr></table>
<p class="note">经验参考: &gt;40dB 差异几乎不可见; 30~40dB 良好;
 &lt;30dB 差异明显。直通/查表类 IP 应为 ∞。</p>`);
    }

    return page(webview, nonce, `<h2>未知面板: ${id}</h2>`);
}

// ---------- 入口 ----------

function activate(context) {
    extCtx = context;
    out = vscode.window.createOutputChannel('VIP Sim');
    context.subscriptions.push(
        out,
        vscode.commands.registerCommand('vipsim.newProject', cmdNewProject),
        vscode.commands.registerCommand('vipsim.console', cmdConsole),
        vscode.commands.registerCommand('vipsim.viewWave', cmdViewWave),
        vscode.commands.registerCommand('vipsim.checkEnv', cmdCheckEnv),
        vscode.commands.registerCommand('vipsim.syncEnv', cmdSyncEnv),
    );
}

function deactivate() { }

module.exports = { activate, deactivate };
