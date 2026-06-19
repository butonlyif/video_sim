#!/usr/bin/env python3
"""将 USER_GUIDE.md 中的 Mermaid 图替换为图片引用，并生成排版精美的 PDF。"""

import re
import markdown
from weasyprint import HTML
import base64
from pathlib import Path

BASE = Path("/Users/wangxin/Documents/trae_projects/video_sim")
OUTPUT_DIR = BASE / "output"
DOCS_DIR = BASE / "docs"

# 读取原始 Markdown
md_path = DOCS_DIR / "USER_GUIDE.md"
with open(md_path, "r", encoding="utf-8") as f:
    md_content = f.read()

# 定义 3 个 Mermaid 图与对应 PNG 的映射
mermaid_replacements = [
    # 图1: 核心能力流程图 (Section 一)
    {
        "pattern": r'```mermaid\nflowchart LR\n    A\[📷 图像/视频\].*?```',
        "replacement": f'![核心能力流程图]({OUTPUT_DIR}/diagram1_pipeline.png)\n\n*图1：VIP 仿真验证系统核心处理流程*',
    },
    # 图2: 系统架构图 (Section 三)
    {
        "pattern": r'```mermaid\nflowchart LR\n    subgraph Python.*?```',
        "replacement": f'![系统架构图]({OUTPUT_DIR}/diagram2_arch.png)\n\n*图2：Python 工具链与 Verilog 仿真层双层架构*',
    },
    # 图3: 仿真过程序列图 (Section 四)
    {
        "pattern": r'```mermaid\nsequenceDiagram\n    participant TB.*?```',
        "replacement": f'![仿真过程序列图]({OUTPUT_DIR}/diagram3_seq.png)\n\n*图3：Gamma 校正 IP 仿真全流程时序图*',
    },
]

# 逐项替换
for repl in mermaid_replacements:
    md_content = re.sub(repl["pattern"], repl["replacement"], md_content, count=1, flags=re.DOTALL)

# 保存新的 Markdown 文件
new_md_path = OUTPUT_DIR / "USER_GUIDE_for_pdf.md"
with open(new_md_path, "w", encoding="utf-8") as f:
    f.write(md_content)

print(f"✅ 已生成替换后的 Markdown: {new_md_path}")

# ====== 转换为 HTML 并生成 PDF ======

# 自定义 CSS 样式（专业排版）
css_style = """
@page {
    size: A4;
    margin: 2.2cm 2.5cm 2.2cm 2.5cm;
    @bottom-center {
        content: "— " counter(page) " —";
        font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
        font-size: 9pt;
        color: #999;
    }
}

body {
    font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "Helvetica Neue", sans-serif;
    font-size: 11pt;
    line-height: 1.8;
    color: #333;
}

h1 {
    font-size: 22pt;
    color: #1a365d;
    border-bottom: 3px solid #3B82F6;
    padding-bottom: 8px;
    margin-top: 0;
    margin-bottom: 12px;
}

h2 {
    font-size: 16pt;
    color: #2c5282;
    border-bottom: 1.5px solid #93C5FD;
    padding-bottom: 5px;
    margin-top: 28px;
    margin-bottom: 14px;
}

h3 {
    font-size: 13pt;
    color: #2d3748;
    margin-top: 22px;
    margin-bottom: 10px;
}

h4 {
    font-size: 11.5pt;
    color: #4a5568;
    margin-top: 18px;
    margin-bottom: 8px;
}

p {
    margin: 8px 0;
    text-align: justify;
}

code {
    font-family: "SF Mono", "Fira Code", "Consolas", monospace;
    font-size: 9.5pt;
    background: #f7fafc;
    padding: 2px 5px;
    border-radius: 3px;
    border: 1px solid #e2e8f0;
}

pre {
    background: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 5px;
    padding: 14px 16px;
    overflow-x: auto;
    font-size: 9pt;
    line-height: 1.5;
}

pre code {
    background: none;
    border: none;
    padding: 0;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 14px 0;
    font-size: 10.5pt;
}

table th {
    background: #EBF4FF;
    color: #2c5282;
    font-weight: 600;
    padding: 10px 12px;
    border: 1px solid #BEE3F8;
    text-align: left;
}

table td {
    padding: 8px 12px;
    border: 1px solid #E2E8F0;
}

table tr:nth-child(even) {
    background: #F7FAFC;
}

blockquote {
    border-left: 4px solid #F59E0B;
    background: #FFFBEB;
    padding: 10px 16px;
    margin: 12px 0;
    color: #92400E;
    border-radius: 0 5px 5px 0;
}

hr {
    border: none;
    border-top: 1px solid #E2E8F0;
    margin: 24px 0;
}

img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 18px auto;
    border-radius: 6px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}

img + p em {
    display: block;
    text-align: center;
    color: #718096;
    font-size: 10pt;
    margin-top: 4px;
}

a {
    color: #3B82F6;
    text-decoration: none;
}

strong {
    color: #1a365d;
}

em {
    color: #4a5568;
}

/* 封面样式 */
.cover-title {
    text-align: center;
    padding: 60px 0 30px 0;
}

.cover-title h1 {
    border-bottom: none;
    font-size: 28pt;
    margin-bottom: 10px;
}

.cover-meta {
    text-align: center;
    color: #718096;
    font-size: 10pt;
    margin: 20px 0 40px 0;
}
"""

# 将 Markdown 转换为 HTML
md = markdown.Markdown(extensions=['tables', 'fenced_code', 'codehilite', 'toc'])
html_body = md.convert(md_content)

html_doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>VIP 仿真验证系统 - 使用说明书</title>
<style>{css_style}</style>
</head>
<body>
{html_body}
</body>
</html>"""

# 保存 HTML 供调试
html_path = OUTPUT_DIR / "USER_GUIDE.html"
with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_doc)
print(f"✅ 已生成 HTML: {html_path}")

# 生成 PDF
pdf_path = OUTPUT_DIR / "VIP仿真验证系统_使用说明书.pdf"
HTML(string=html_doc).write_pdf(str(pdf_path))
print(f"✅ PDF 已生成: {pdf_path}")
