"""md2pdf.py — Markdown 转 HTML（中文字体优化），再用 Edge headless 转 PDF"""
import sys
import os
import markdown

def md_to_html(md_path, html_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    html_body = markdown.markdown(md_text, extensions=['tables', 'fenced_code'])

    html_full = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: "Microsoft YaHei", "微软雅黑", "SimHei", "黑体", "Noto Sans CJK SC", sans-serif;
    font-size: 14px;
    line-height: 1.8;
    margin: 2cm 2.5cm;
    color: #333;
  }}
  h1 {{
    font-size: 24px;
    border-bottom: 2px solid #333;
    padding-bottom: 8px;
    margin-top: 2em;
  }}
  h2 {{
    font-size: 19px;
    border-bottom: 1px solid #aaa;
    padding-bottom: 4px;
    margin-top: 1.8em;
  }}
  h3 {{
    font-size: 16px;
    margin-top: 1.4em;
  }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 13px;
  }}
  th, td {{
    border: 1px solid #bbb;
    padding: 6px 10px;
    text-align: left;
  }}
  th {{
    background-color: #e8e8e8;
    font-weight: bold;
  }}
  tr:nth-child(even) {{
    background-color: #f8f8f8;
  }}
  code {{
    background-color: #f0f0f0;
    padding: 2px 6px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 13px;
    border-radius: 3px;
  }}
  pre {{
    background-color: #f5f5f5;
    padding: 12px;
    border-radius: 5px;
    overflow-x: auto;
    line-height: 1.5;
  }}
  pre code {{
    background: none;
    padding: 0;
  }}
  blockquote {{
    border-left: 4px solid #4a90d9;
    margin: 1em 0;
    padding: 0.5em 1em;
    color: #666;
    background-color: #f9f9f9;
  }}
  a {{
    color: #4a90d9;
    text-decoration: none;
  }}
  hr {{
    border: none;
    border-top: 1px solid #ccc;
    margin: 2em 0;
  }}
  @page {{
    margin: 1.5cm;
  }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_full)
    print(f"HTML: {html_path}")

if __name__ == '__main__':
    md_path = sys.argv[1]
    html_path = os.path.splitext(md_path)[0] + '.html'
    md_to_html(md_path, html_path)
