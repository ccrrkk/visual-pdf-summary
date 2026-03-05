import os
import urllib.request
import urllib.parse
import urllib.error
import hashlib
import markdown
import pdfkit
import platform
import pathlib
import re
import shutil
import subprocess

def _inject_ld_library_path(lib_dir: str):
    """Prepend lib_dir to LD_LIBRARY_PATH so child processes (wkhtmltopdf) can find .so files."""
    current = os.environ.get("LD_LIBRARY_PATH", "")
    if lib_dir not in current:
        os.environ["LD_LIBRARY_PATH"] = lib_dir + (":" + current if current else "")
        print(f">>> LD_LIBRARY_PATH set to: {os.environ['LD_LIBRARY_PATH']}")


def _fix_libjpeg():
    """Ensure libjpeg.so.8 is accessible. Creates symlink in /tmp (no root needed).
    Returns the directory containing the symlink, or None if not needed."""
    import glob

    # Already available system-wide — nothing to do
    if glob.glob("/usr/lib/x86_64-linux-gnu/libjpeg.so.8"):
        return None

    tmp_lib = "/tmp/libjpeg8_lib"
    symlink = os.path.join(tmp_lib, "libjpeg.so.8")

    if os.path.exists(symlink):
        return tmp_lib  # already set up from a previous call

    os.makedirs(tmp_lib, exist_ok=True)

    # Try to symlink from the modern libjpeg.so.62 (available on Debian/Ubuntu)
    candidates = (
        glob.glob("/usr/lib/x86_64-linux-gnu/libjpeg.so.62*")
        + glob.glob("/usr/lib/x86_64-linux-gnu/libjpeg.so.62")
        + glob.glob("/usr/lib/*/libjpeg.so.62*")
    )
    if candidates:
        try:
            os.symlink(candidates[0], symlink)
            print(f">>> Created libjpeg symlink in /tmp: {symlink} -> {candidates[0]}")
            return tmp_lib
        except FileExistsError:
            return tmp_lib

    # Last resort: download libjpeg8 .deb and extract the .so
    print(">>> libjpeg.so.62 not found, attempting to download libjpeg8...")
    deb_url = "http://archive.ubuntu.com/ubuntu/pool/main/libj/libjpeg8/libjpeg8_8c-2ubuntu8_amd64.deb"
    deb_path = "/tmp/libjpeg8.deb"
    extract_dir = "/tmp/libjpeg8_extract"
    try:
        result = subprocess.run(
            ["wget", "-q", "-O", deb_path, deb_url],
            capture_output=True, timeout=60
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["curl", "-sL", "-o", deb_path, deb_url],
                capture_output=True, timeout=60
            )
        if result.returncode == 0:
            os.makedirs(extract_dir, exist_ok=True)
            subprocess.run(["dpkg", "-x", deb_path, extract_dir], check=True, capture_output=True)
            found = glob.glob(f"{extract_dir}/**/libjpeg.so.8*", recursive=True)
            if found:
                os.symlink(found[0], symlink)
                print(f">>> Extracted and linked libjpeg.so.8 from .deb")
                return tmp_lib
    except Exception as e:
        print(f">>> Could not obtain libjpeg.so.8: {e}")

    return None


def _get_wkhtmltopdf_path():
    """Return wkhtmltopdf binary path. On Linux, downloads a pre-built binary if not found in PATH."""
    wk_path = shutil.which("wkhtmltopdf")
    if wk_path:
        return wk_path

    if platform.system() == "Windows":
        default_path = r'D:\wkhtmltopdf\bin\wkhtmltopdf.exe'
        return default_path if os.path.exists(default_path) else None

    # Use the bookworm build: links against libssl3 + libjpeg.so.62 — matches modern Debian/Ubuntu
    # (focal build needs libssl1.1 which is absent on Ubuntu 22.04+ / Debian bookworm)
    _WKHTML_DEB_URL = "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-2/wkhtmltox_0.12.6.1-2.bookworm_amd64.deb"
    _WKHTML_DEB_ID  = "bookworm-0.12.6.1-2"   # bump this string to force re-download
    bin_path    = "/tmp/wkhtmltox/usr/local/bin/wkhtmltopdf"
    marker_path = "/tmp/wkhtmltox/.deb_id"

    # Check whether the cached binary matches the expected build
    cached_id = ""
    if os.path.exists(marker_path):
        with open(marker_path) as _f:
            cached_id = _f.read().strip()

    if os.path.exists(bin_path) and cached_id == _WKHTML_DEB_ID:
        # Cached binary is up-to-date; re-apply libjpeg fix in case /tmp was partially cleared
        lib_dir = _fix_libjpeg()
        if lib_dir:
            _inject_ld_library_path(lib_dir)
        return bin_path

    # Need to (re-)download: wrong version cached, or first run
    if os.path.exists(bin_path):
        print(f">>> Cached wkhtmltopdf build '{cached_id}' is outdated, re-downloading '{_WKHTML_DEB_ID}'...")
        shutil.rmtree("/tmp/wkhtmltox", ignore_errors=True)

    print(f">>> Downloading wkhtmltopdf ({_WKHTML_DEB_ID})...")
    deb_path = "/tmp/wkhtmltox.deb"
    try:
        os.makedirs("/tmp/wkhtmltox", exist_ok=True)
        dl_result = subprocess.run(
            ["wget", "-q", "-O", deb_path, _WKHTML_DEB_URL],
            capture_output=True, timeout=120
        )
        if dl_result.returncode != 0:
            dl_result = subprocess.run(
                ["curl", "-L", "-o", deb_path, _WKHTML_DEB_URL],
                capture_output=True, timeout=120
            )
        if dl_result.returncode != 0:
            raise RuntimeError(f"Download failed: {dl_result.stderr.decode()}")
        subprocess.run(["dpkg", "-x", deb_path, "/tmp/wkhtmltox"], check=True, capture_output=True)
        os.chmod(bin_path, 0o755)
        # Write marker so we don't re-download on next call
        with open(marker_path, "w") as _f:
            _f.write(_WKHTML_DEB_ID)
        # bookworm build uses libjpeg.so.62 natively; _fix_libjpeg() is a no-op on bookworm
        # but kept as a safety net for other environments
        lib_dir = _fix_libjpeg()
        if lib_dir:
            _inject_ld_library_path(lib_dir)
        print(f">>> wkhtmltopdf ready: {bin_path}")
        return bin_path
    except Exception as e:
        print(f">>> Failed to download wkhtmltopdf: {e}")
        return None

def markdown_to_pdf(input_md: str, output_pdf: str, font: str = 'Microsoft YaHei'):

    base_dir = os.path.dirname(os.path.abspath(input_md))
    math_img_dir = os.path.join(base_dir, "math_images")
    os.makedirs(math_img_dir, exist_ok=True)

    def process_latex(match, is_block=False):
        tex = match.group(1).strip()
        if not tex: return ""
        
        file_hash = hashlib.md5(tex.encode('utf-8')).hexdigest()
        local_filename = os.path.join(math_img_dir, f"{file_hash}.png")
        
        if not os.path.exists(local_filename):
            try:
                query = urllib.parse.quote(f"\\dpi{{300}} {tex}")
                url = f"https://latex.codecogs.com/png.image?{query}"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Referer': 'https://latex.codecogs.com/'
                }
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as response:
                    data = response.read()
                    if len(data) > 0:
                        with open(local_filename, 'wb') as f:
                            f.write(data)
                    else:
                        print(f"Warning: Empty response for latex: {tex}")
            except Exception as e:
                print(f"Latex download failed: {e}")
                return f'<span style="color:red; font-size: 0.8em;">(Formula Error: {tex})</span>'

        if os.path.exists(local_filename):
            abs_path = os.path.abspath(local_filename)
            # ✅ 同步修复：清除路径中的 NBSP 再编码
            clean_path = abs_path.replace('\\', '/').replace('\u00a0', ' ')
            img_src = 'file:///' + urllib.parse.quote(clean_path, safe='/:')
        else:
            return f'<span style="color:red">$${tex}$$</span>'
        
        # 1. 块级公式：zoom: 0.6 将300DPI图片缩小约一半显示，max-width: 100% 覆盖全局的60%限制
        # 2. 行内公式：zoom: 0.6 保持同比例，vertical-align 对齐
        if is_block:
            style = (
                "display: block; "
                "margin: 1em auto; "
                "max-width: 100%; "   
                "height: auto; "      
                "width: auto; "       
                "zoom: 0.4; "         
            )
        else:
            style = (
                "display: inline; "   # 强制设为行内元素，覆盖全局的 display: block
                "margin: 0 2px; "     # 覆盖全局的 margin，只留左右微小间距
                "max-width: 100%; "
                "height: auto; "
                "width: auto; "
                "vertical-align: -0.3em; " 
                "zoom: 0.4; "         # 行内公式保持同样的缩放比例
            )

        return f'<img src="{img_src}" style="{style}" />'

    # 读取 Markdown
    with open(input_md, 'r', encoding='utf-8') as f:
        md_text = f.read()

    def fix_list_indentation(text: str) -> str:
        """
        Python-Markdown 默认要求 4 空格缩进才能识别嵌套列表。
        许多编辑器/LLM 生成的 Markdown 使用 2 空格缩进，导致嵌套层级丢失。
        本函数将列表项前的 2 空格倍数缩进统一扩展为 4 空格倍数。
        """
        lines = text.split('\n')
        result = []
        # 匹配列表项：可选缩进 + (- 或 * 或 + 或 数字.) + 空格 + 内容
        list_item_re = re.compile(r'^(\s*)([-*+]|\d+\.)\s')
        # 匹配列表项续行（缩进但不是新列表项）
        for line in lines:
            m = list_item_re.match(line)
            if m:
                indent = m.group(1)
                indent_len = len(indent)
                # 只处理纯空格缩进，且是 2 的倍数但不是 4 的倍数的情况
                if indent_len > 0 and indent_len % 2 == 0:
                    # 计算当前是几个 2-空格层级
                    levels = indent_len // 2
                    # 替换为 4 空格 * 层级数
                    new_indent = '    ' * levels
                    line = new_indent + line.lstrip()
            result.append(line)
        return '\n'.join(result)

    md_text = fix_list_indentation(md_text)

    def normalize_markdown_lists(text: str) -> str:
        """
        归一化 Markdown 列表，提升 Python-Markdown 对中文报告的稳定解析：
        1) 将 tab / 全角空格 转为普通空格
        2) 列表项缩进统一到 4 空格层级
        3) 识别“父级 li 下看似子项但未规范缩进”的行，自动提升为子列表
        """
        lines = text.split('\n')

        # 标准列表项：缩进 + marker + 空格 + 内容
        list_item_re = re.compile(r'^(\s*)([-*+]|\d+\.)\s+(.+?)\s*$')
        # 宽松子项：至少有缩进 + marker + 空格 + 内容（用于纠偏）
        loose_list_re = re.compile(r'^(\s{2,})([-*+]|\d+\.)\s+(.+?)\s*$')

        normalized = []
        in_code_fence = False

        prev_is_list_item = False
        prev_list_indent_spaces = 0

        for raw in lines:
            line = raw

            # 代码块内不处理
            if line.strip().startswith("```"):
                in_code_fence = not in_code_fence
                normalized.append(line)
                continue
            if in_code_fence:
                normalized.append(line)
                continue

            # 统一空白
            line = line.replace('\u3000', '  ')   # 全角空格 -> 2半角
            line = line.replace('\t', '    ')     # tab -> 4空格

            m = list_item_re.match(line)
            if m:
                indent = m.group(1)
                marker = m.group(2)
                content = m.group(3)

                indent_len = len(indent)
                # 统一为 4 空格层级（向上取整到最近层级）
                level = 0 if indent_len == 0 else max(1, (indent_len + 3) // 4)
                new_indent = '    ' * level
                new_line = f"{new_indent}{marker} {content}"

                normalized.append(new_line)
                prev_is_list_item = True
                prev_list_indent_spaces = len(new_indent)
                continue

            # 纠偏：上一行是列表项，当前行像“子列表项”但缩进混乱
            lm = loose_list_re.match(line)
            if lm and prev_is_list_item:
                marker = lm.group(2)
                content = lm.group(3)
                child_indent = ' ' * (prev_list_indent_spaces + 4)
                normalized.append(f"{child_indent}{marker} {content}")
                prev_is_list_item = True
                prev_list_indent_spaces = len(child_indent)
                continue

            # 空行保持，但不重置太多状态（允许列表中夹空行）
            if line.strip() == "":
                normalized.append(line)
                continue

            normalized.append(line)
            prev_is_list_item = False

        return '\n'.join(normalized)

    md_text = normalize_markdown_lists(md_text)

    print(">>> 正在本地化处理数学公式 (HD Mode)...")
    
    # 正则替换数学公式
    md_text = re.sub(r'\$\$([\s\S]*?)\$\$', lambda m: process_latex(m, is_block=True), md_text)
    md_text = re.sub(r'(?<!\\)\$([^\$\n]+?)(?<!\\)\$', lambda m: process_latex(m, is_block=False), md_text)

    # 将 ![说明](图片) 转换为 <figure><figcaption> 结构
    def convert_image_to_figure(match):
        alt_text = match.group(1).strip()
        img_src = match.group(2).strip()
        
        if not img_src.startswith(('http://', 'https://', 'file://', 'data:')):
            abs_img_path = os.path.join(base_dir, img_src)
            abs_img_path = os.path.abspath(abs_img_path)
            # ✅ 修复：先将路径中所有非断行空格（U+00A0）替换为普通空格，再做 URL 编码
            clean_path = abs_img_path.replace('\\', '/').replace('\u00a0', ' ')
            img_src = 'file:///' + urllib.parse.quote(clean_path, safe='/:')
        
        if not alt_text:
            return f'<img src="{img_src}" />'
        
        return f'''<figure>
    <img src="{img_src}" />
    <figcaption>{alt_text}</figcaption>
</figure>'''
    
    # 在转换为HTML前先处理图片
    md_text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', convert_image_to_figure, md_text)
    
    # 转 HTML
    md_instance = markdown.Markdown(
        extensions=['extra', 'tables', 'fenced_code', 'attr_list', 'sane_lists'],
        tab_length=4
    )
    html_body = md_instance.convert(md_text)

    # ====== 调试：保存中间 HTML 文件 ======
    debug_html_path = output_pdf.replace('.pdf', '_debug.html')

    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ 
                font-family: '{font}', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC', sans-serif; 
                margin: 2.5cm; 
                line-height: 1.8; 
                font-size: 20px;
                color: #2c3e50;
            }}
            h1 {{ font-size: 46px; margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
            h2 {{ font-size: 32px; margin-top: 30px; }}
            table {{ border-collapse: collapse; width: 100%; margin: 25px 0; }}
            th, td {{ 
                border: 1px solid #e2e8f0; 
                padding: 12px 15px; 
                text-align: left; 
                font-size: 20px;
                vertical-align: middle;
            }}
            th {{ background-color: #f8fafc; font-weight: bold; }}
            p {{ margin-bottom: 1.2em; }}
            
            /* 修复列表渲染问题 */
            ul, ol {{
                padding-left: 2em;
                margin-top: 0.5em;
                margin-bottom: 0.5em;
            }}
            li {{
                margin-bottom: 0.5em;
                padding-left: 0.2em; 
            }}
            
            /* 图片样式 - 移除 zoom，改用 transform */
            img {{ 
                max-width: 60%; /* 限制最大宽度为页面的 80%，可按需调为 70% 或 75% */
                height: auto; 
                display: block; 
                margin: 1.5em auto; 
            }}
            
            /* figure 和 figcaption 样式 */
            figure {{
                text-align: center;
                margin: 2em auto;
                max-width: 80%;
            }}
            
            figure img {{
                max-width: 100%;
                height: auto;
                display: block;
                margin: 0 auto 0.8em auto;
            }}
            
            figcaption {{
                font-size: 18px;
                color: #555;
                font-style: italic;
                text-align: center;
                margin-top: 0.5em;
                line-height: 1.6;
            }}
        </style>
    </head>
    <body>{html_body}</body>
    </html>
    """
    
    # 保存调试用 HTML
    with open(debug_html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f">>> 调试 HTML 已保存: {debug_html_path}")

    options = {
        'encoding': "UTF-8",
        'enable-local-file-access': None,
        'quiet': '',
        'disable-javascript': None,
        'load-error-handling': 'ignore',
        # 增加打印精度
        'image-dpi': '300',
        'image-quality': '94'
    }
    
    wk_path = _get_wkhtmltopdf_path()
    config = pdfkit.configuration(wkhtmltopdf=wk_path) if wk_path else None
    pdfkit.from_string(html, output_pdf, configuration=config, options=options)


