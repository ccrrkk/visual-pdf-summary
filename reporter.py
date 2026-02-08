import os
import re
import base64
from typing import List, Tuple, Optional, Dict
import fitz
import shapely.geometry as sg
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity
import concurrent.futures
import logging
from openai import OpenAI
import pypandoc
from os import getenv
from dotenv import load_dotenv
import time
from utils_yolo import extract_pdf_images
from prompt import cn_prompt, en_prompt, cn_reviewer_promt, en_reviewer_promt
import argparse
import shutil
import pathlib 
from PIL import Image  
import io 
import markdown
import pdfkit
import platform
import shutil
import os
import re
import urllib.request
import urllib.parse
import hashlib

def _remove_markdown_backticks(content: str) -> str:
    """
    删除markdown中的```字符串.
    """
    if '```markdown' in content:
        content = content.replace('```markdown\n', '')
        last_backticks_pos = content.rfind('```')
        if last_backticks_pos != -1:
            content = content[:last_backticks_pos] + content[last_backticks_pos + 3:]
    return content

# markdown转pdf独立函数
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
            img_src = pathlib.Path(abs_path).as_uri()
        else:
            # 图片下载失败 fallback
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

    print(">>> 正在本地化处理数学公式 (HD Mode)...")
    
    # 正则替换数学公式
    md_text = re.sub(r'\$\$([\s\S]*?)\$\$', lambda m: process_latex(m, is_block=True), md_text)
    md_text = re.sub(r'(?<!\\)\$([^\$\n]+?)(?<!\\)\$', lambda m: process_latex(m, is_block=False), md_text)

    # 将 ![说明](图片) 转换为 <figure><figcaption> 结构
    def convert_image_to_figure(match):
        alt_text = match.group(1).strip()
        img_src = match.group(2).strip()
        
        # 如果没有说明文字，只返回普通图片标签
        if not alt_text:
            return f'<img src="{img_src}" />'
        
        # 有说明文字时，生成 figure 结构
        return f'''<figure>
    <img src="{img_src}" />
    <figcaption>{alt_text}</figcaption>
</figure>'''
    
    # 在转换为HTML前先处理图片
    md_text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', convert_image_to_figure, md_text)
    
    # 转 HTML
    html_body = markdown.markdown(md_text, extensions=[
        'extra', 'tables', 'fenced_code', 'attr_list'
    ])
    
    html = f"""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ 
                font-family: '{font}', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC', sans-serif; 
                margin: 2.5cm; 
                line-height: 1.8; 
                font-size: 20px; /* 调节此处来将字号调大 */
                color: #2c3e50;
            }}
            h1 {{ font-size: 46px; margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
            h2 {{ font-size: 32px; margin-top: 30px; }}
            table {{ border-collapse: collapse; width: 100%; margin: 25px 0; }}
            th, td {{ 
                border: 1px solid #e2e8f0; 
                padding: 12px 15px; 
                text-align: left; 
                font-size: 20px; /* 表格字号同步调大 */
                vertical-align: middle;
            }}
            th {{ background-color: #f8fafc; font-weight: bold; }}
            p {{ margin-bottom: 1.2em; }}
            li {{ margin-bottom: 0.5em; }}
            
            /* 图片样式 */
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
    
    config = None
    if platform.system() == "Windows":
        wk_path = shutil.which("wkhtmltopdf")
        if not wk_path:
            default_path = r'D:\wkhtmltopdf\bin\wkhtmltopdf.exe'
            if os.path.exists(default_path):
                wk_path = default_path
        if wk_path:
            config = pdfkit.configuration(wkhtmltopdf=wk_path)

    pdfkit.from_string(html, output_pdf, configuration=config, options=options)

def pdf_pages_to_base64_images(pdf_path: str) -> List[str]:
    """将PDF每一页转换为base64编码的图片，用于视觉审查"""
    doc = fitz.open(pdf_path)
    images = []
    for page_num in range(len(doc)):
        try:
            page = doc[page_num]
            # Matrix(1.5, 1.5) 用于提升清晰度，方便模型看清文字
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            img_data = pix.tobytes("jpeg")
            base64_str = base64.b64encode(img_data).decode("utf-8")
            images.append(f"data:image/jpeg;base64,{base64_str}")
        except Exception as e:
            print(f"Error converting page {page_num} to image: {e}")
    doc.close()
    return images

def report(
        pdf_path: str,
        img_dir: str = './',
        output_dir: str = './',
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = 'gpt-4o',
        language: str = 'en',
        max_retries: int = 3,
        font: str = 'Microsoft YaHei',
        compress_images: bool = True  
    ) -> Dict[str, str]:
    """
    生成论文简报
    Returns:
        Dict[str, str]: 包含生成文件路径的字典
            - 'md_path': Markdown文件路径
            - 'pdf_path': PDF文件路径
            - 'img_dir': 图片目录路径
    """
    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    client = OpenAI(
        api_key=api_key, # 使用传入的 api_key (main中已处理为优先读取env)
        base_url=base_url,
    )
    if language not in ['zh', 'en']:
        raise ValueError("Unsupported language. Supported languages are 'zh' and 'en'.")
    if language == 'zh':
        prompt = cn_prompt
    else:
        prompt = en_prompt
    
    # 提取论文标题
    import fitz
    doc = fitz.open(pdf_path)
    title = doc.metadata.get("title", "").strip()
    if not title:
        # 若元数据无标题，尝试用第一页大标题
        first_page = doc[0]
        blocks = first_page.get_text("blocks")
        # 取最靠上的大块文本作为标题
        blocks = sorted(blocks, key=lambda b: b[1])
        title = blocks[0][4].strip().replace('\n', ' ') if blocks else "untitled"
    # 清理标题为合法文件夹名
    safe_title = re.sub(r'[\\/:*?"<>|]', '_', title)
    
    paper_dir = os.path.join(output_dir, safe_title)
    if os.path.exists(paper_dir):
        shutil.rmtree(paper_dir)  # 先清空同名文件夹
    os.makedirs(paper_dir)
    
    img_dir = os.path.join(paper_dir, 'images')
    if not os.path.exists(img_dir):
        os.makedirs(img_dir)

    print(img_dir)
    start_time = time.time()

    extract_pdf_images(pdf_path, img_dir)

    after_extract_time = time.time()
    print("提取图片用时: {}秒".format(after_extract_time - start_time))

    for root, _, files in os.walk(img_dir):
        # 支持 .png 格式，兼容 x.png, Table_x_y.png, Fig_x_y.png
        images = [
            os.path.join(img_dir, f) 
            for f in files 
            if f.lower().endswith('.png') and (
                re.match(r'^\d+\.png$', f, re.IGNORECASE) or 
                re.match(r'^(?:Table|Fig|Unknown)_\d+_\d+\.png$', f, re.IGNORECASE) or
                re.match(r'^\d+_\d+\.png$', f, re.IGNORECASE)
            )
        ]
    
    def sort_key(x):
        filename = os.path.basename(x)
        name, ext = os.path.splitext(filename)
        parts = name.split('_')
        
        try:
            # Case A: 1.png -> (页码: 1, 索引: -1)
            if len(parts) == 1 and parts[0].isdigit():
                return (int(parts[0]), -1)
            
            # Case B: Table_1_0.png -> (页码: 1, 索引: 0)
            if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                return (int(parts[1]), int(parts[2]))
            
            # Case C: 1_0.png -> (页码: 1, 索引: 0)
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return (int(parts[0]), int(parts[1]))
                
            return (99999, 99999)
        except Exception:
            return (99999, 99999)

    images.sort(key=sort_key)

    def image_to_base64_data_url(image_path: str, compress: bool) -> str:
        """根据配置决定是否压缩并转换为 Base64"""
        if not compress:
            with open(image_path, "rb") as f:
                data = f.read()
                return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")
        
        try:
            with Image.open(image_path) as img:
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                
                max_side = 1024
                if max(img.size) > max_side:
                    scale = max_side / max(img.size)
                    new_size = (int(img.width * scale), int(img.height * scale))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                
                buffered = io.BytesIO()
                img.save(buffered, format="JPEG", quality=80) 
                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                return f"data:image/jpeg;base64,{img_str}"
        except Exception as e:
            return "data:image/png;base64," + base64.b64encode(open(image_path, "rb").read()).decode("utf-8")
    
    base64_urls = [image_to_base64_data_url(img, compress_images) for img in images]

    # 将 replace_image_paths 移动到此处，以便 report 函数内随处可用
    def replace_image_paths(content: str, target_img_dir: str, is_pdf: bool = False) -> str:
        """
        统一处理图片路径：
        - Markdown 模式：使用相对路径 'images/xxx.png'
        - PDF 模式：使用绝对路径 'file:///D:/path/to/images/xxx.png'
        """
        abs_img_dir = os.path.abspath(target_img_dir).replace('\\', '/')
        
        # 处理 Markdown 图片语法 ![alt](path)
        def repl_md(match):
            alt = match.group(1)
            img_name = match.group(2)
            # 提取纯文件名，防止大模型给出的路径包含多余层级
            filename = os.path.basename(img_name)
            
            if is_pdf:
                # Windows
                full_path = f"file:///{abs_img_dir}/{filename}"
            else:
                full_path = f"images/{filename}"
                
            return f"![{alt}]({full_path})"
        
        # 处理 HTML <img> 标签 src="xxx.png"
        def repl_html(match):
            before = match.group(1)  # src=" 之前的部分
            img_name = match.group(2)  # 文件名
            after = match.group(3)   # " 之后的部分
            filename = os.path.basename(img_name)
            
            if is_pdf:
                full_path = f"file:///{abs_img_dir}/{filename}"
            else:
                full_path = f"images/{filename}"
            
            return f'{before}src="{full_path}"{after}'
        
        # 先处理 Markdown 语法
        content = re.sub(r'!\[([^\]]*)\]\(([^)]+\.png)\)', repl_md, content)
        # 再处理 HTML <img> 标签
        content = re.sub(r'(<img\s[^>]*?)src="([^"]+\.png)"([^>]*>)', repl_html, content)
        
        return content

    llm_start_time = time.time()

    print("base64编码用时: {}秒".format(llm_start_time - after_extract_time))

    current_try = 0
    content = ""
    quality_pass = False

    # 初始化对话历史，第一条消息包含图片和初始提示
    messages = [
        {
            "role": "user",
            "content": [
                *[
                    {
                        "type": "image_url",
                        "image_url": {"url": url}
                    }
                    for url in base64_urls
                ],
                {"type": "text", "text": prompt},
            ],
        },
    ]

    while current_try < max_retries and not quality_pass:
        print(f"尝试生成报告 (第 {current_try + 1}/{max_retries} 次)...")
        
        # 只保留最近一轮的消息（图片+prompt，上一轮assistant，最新user）
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
        )
        # print(completion)
        content = completion.choices[0].message.content
        
        # --- 质量自检环节：生成临时PDF并截图 ---
        print("正在生成临时PDF进行视觉质量自检...")
        
        # 1. 清理当前生成的文本
        temp_content_clean = _remove_markdown_backticks(content)
        # 简单清理分隔符
        temp_content_clean = temp_content_clean.replace('\n---\n', '\n').replace('\n---\r\n', '\n').replace('---\n', '').replace('---\r\n', '')
        
        # 2. 转换为PDF所需的格式（绝对路径图片）
        pdf_review_content = replace_image_paths(temp_content_clean, img_dir, is_pdf=True)
        
        # 3. 生成临时文件
        temp_review_md = os.path.join(paper_dir, f'review_temp_{current_try}.md')
        temp_review_pdf = os.path.join(paper_dir, f'review_temp_{current_try}.pdf')
        
        pdf_gen_success = False
        review_pdf_images = []

        try:
            with open(temp_review_md, 'w', encoding='utf-8') as f:
                f.write(pdf_review_content)
            
            # 使用现有函数生成PDF
            markdown_to_pdf(temp_review_md, temp_review_pdf, font=font)
            
            # 转换PDF为图片
            if os.path.exists(temp_review_pdf):
                review_pdf_images = pdf_pages_to_base64_images(temp_review_pdf)
                if review_pdf_images:
                    pdf_gen_success = True
                    print(f"临时PDF生成成功，共 {len(review_pdf_images)} 页。")
        except Exception as e:
            print(f"临时PDF生成失败，将回退到纯文本审查: {e}")

        # 构造审稿内容
        print("正在调用模型进行质量评估...")
        if language == 'zh':
            check_system_prompt = cn_reviewer_promt
        else:
            check_system_prompt = en_reviewer_promt

        # 组装消息：原始图片 -> (PDF截图 或 警告) -> 指令与Markdown文本
        check_user_content = []
        check_user_content.append({"type": "text", "text": "## Original Source Images"})
        check_user_content.extend([{"type": "image_url", "image_url": {"url": url}} for url in base64_urls])
        
        if pdf_gen_success:
            check_user_content.append({"type": "text", "text": "## Generated Report PDF Pages (For detailed visual inspection)"})
            check_user_content.extend([{"type": "image_url", "image_url": {"url": url}} for url in review_pdf_images])
        else:
            check_user_content.append({"type": "text", "text": "**WARNING: Could not generate PDF preview. Please review based on text only.**"})

        # check_user_content.append({"type": "text", "text": f"{review_instruction}\n\n## Markdown Source\n{content}"})

        # 构造审稿人的消息
        check_messages = [
            {"role": "system", "content": check_system_prompt},
            {
                "role": "user", 
                "content": check_user_content
            } 
        ]

        check_completion = client.chat.completions.create(
            model=model,
            messages=check_messages 
        )
        check_result = check_completion.choices[0].message.content.strip()

        # 清理临时文件
        if os.path.exists(temp_review_md):
            os.remove(temp_review_md)
        if os.path.exists(temp_review_pdf):
            os.remove(temp_review_pdf)

        box_match = re.search(r'\\box(?:ed)?\{(.*?)\}', check_result, re.IGNORECASE)
        box_content = box_match.group(1).strip() if box_match else ""
        if box_content.lower() == "pass":
            print(">>> 质量检测通过。")
            quality_pass = True
        else:
            print(f">>> 质量检测未通过。")
            # 提取审稿意见
            critique = check_result.replace("FAIL", "").strip()
            print(f"审稿意见: {critique[:2000]}..." if len(critique) > 2000 else f"审稿意见: {critique}")
            
            # 只有当PDF生成成功时，才将PDF截图加入对话历史，否则只加文字
            # 注意：将大量的PDF截图放入对话历史可能会导致token过长
            # 这里我们选择只保留文字版critique进入下一轮生成，
            # 这里的 check_messages 是一次性的，不放入 main messages loop
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        *[
                            {
                                "type": "image_url",
                                "image_url": {"url": url}
                            }
                            for url in base64_urls
                        ],
                        {"type": "text", "text": prompt},
                    ],
                },
                {"role": "assistant", "content": content},
            ]
            if language == 'zh':
                retry_prompt = f"上一版本的报告未通过视觉审查，审稿人意见如下（基于PDF渲染效果）：\n\n{critique}\n\n请你参考意见，修复图片引用错误、公式错误或内容问题，重新生成报告。"
            else:
                retry_prompt = f"The previous report failed the visual review. Reviewer critique (based on PDF rendering): \n\n{critique}\n\nPlease fix image references, formula errors, or content issues and regenerate the report."
            messages.append({"role": "user", "content": retry_prompt})

            current_try += 1

    if not quality_pass:
        print("达到最大尝试次数，使用最后一次生成的结果。")

    llm_end_time = time.time()
    print(f"LLM调用时间 (含自检): {llm_end_time - llm_start_time}秒")

    # # 生成附录
    # content += "\n\n## 附录：所有提取图表\n\n"
    # appendix_images = [img for img in images if "_" in os.path.basename(img)]
    
    # # 直接用 HTML <img> 标签
    # for i, img_path in enumerate(appendix_images):
    #     fname = os.path.basename(img_path)
    #     # 使用 HTML img 标签，inline-block 布局
    #     content += f'<img src="{fname}" alt="{fname}" style="width:45%; height:auto; display:inline-block; margin:0.5em; vertical-align:top;" /> '
    #     if (i + 1) % 2 == 0:
    #         content += "\n"
    # content += "\n"

    content = _remove_markdown_backticks(content)

    # 去除所有 markdown 分割线 '---'
    content = content.replace('\n---\n', '\n')
    content = content.replace('\n---\r\n', '\n')
    content = content.replace('---\n', '')
    content = content.replace('---\r\n', '')
    
    # 分别生成 Markdown 内容和 PDF 内容
    md_content = replace_image_paths(content, img_dir, is_pdf=False)
    # PDF 用的图片目录就是上面创建的 img_dir
    pdf_content = replace_image_paths(content, img_dir, is_pdf=True)

    # 保存解析后的markdown文件
    md_output_path = os.path.join(paper_dir, 'report.md')
    with open(md_output_path, 'w', encoding='utf-8') as f:
        f.write(md_content)

    tmp_md_path = os.path.join(paper_dir, 'temp_report.md')
    with open(tmp_md_path, 'w', encoding='utf-8') as f:
        f.write(pdf_content)

    pdf_output_path = os.path.join(paper_dir, 'report.pdf')
    # 使用修改后的独立函数
    markdown_to_pdf(tmp_md_path, pdf_output_path, font=font)

    # 删除临时文件
    if os.path.exists(tmp_md_path):
        os.remove(tmp_md_path)

    end_time = time.time()
    print("markdown转pdf用时: {}秒".format(end_time - llm_end_time))
    print(f"总用时: {end_time - llm_start_time}秒")
    
    # 返回生成的文件路径
    return {
        'md_path': md_output_path,
        'pdf_path': pdf_output_path,
        'img_dir': img_dir
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成论文简报")
    parser.add_argument('--pdf_path', type=str, required=True, help='input pdf file path')
    parser.add_argument('--output_dir', type=str, default='output', help='output directory')
    parser.add_argument('--language', type=str, default='en', choices=['zh', 'en'], help='language: zh(Chinese) 或 en(English)')
    parser.add_argument('--api_key', type=str, default=None, help='OpenAI API Key')
    parser.add_argument('--base_url', type=str, default=None, help='OpenAI Base URL')
    parser.add_argument('--model', type=str, default=None, help='model name')
    parser.add_argument('--max_retries', type=int, default=3, help='Max retries for quality check loop')
    parser.add_argument('--compress', action='store_true', default=True, help='是否开启图片压缩以减小请求体积')
    parser.add_argument('--no-compress', action='store_false', dest='compress', help='关闭图片压缩')
    
    parser.add_argument('--font', type=str, default='Microsoft YaHei', 
                        choices=['Microsoft YaHei', 'SimSun', 'KaiTi', 'SimHei'], 
                        help='Font for PDF generation: Microsoft YaHei(微软雅黑), SimSun(宋体), KaiTi(楷体), SimHei(黑体)')
    
    args = parser.parse_args()

    load_dotenv()  

    api_key = getenv("api_key") if args.api_key is None else args.api_key
    base_url = getenv("base_url") if args.base_url is None else args.base_url
    model = getenv("model") if args.model is None else args.model

    report(
        pdf_path=args.pdf_path,
        output_dir=args.output_dir,
        api_key=api_key,
        base_url=base_url,
        model=model,
        language=args.language,
        max_retries=args.max_retries,
        font=args.font,
        compress_images=args.compress
    )





