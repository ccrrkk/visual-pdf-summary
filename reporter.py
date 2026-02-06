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
from utils import extract_pdf_images
from prompt import cn_prompt, en_prompt, cn_reviewer_promt, en_reviewer_promt
import argparse
import shutil

def _remove_markdown_backticks(content: str) -> str:
    """
    删除markdown中的```字符串。
    """
    if '```markdown' in content:
        content = content.replace('```markdown\n', '')
        last_backticks_pos = content.rfind('```')
        if last_backticks_pos != -1:
            content = content[:last_backticks_pos] + content[last_backticks_pos + 3:]
    return content

# markdown转pdf独立函数
def markdown_to_pdf(input_md: str, output_pdf: str, font: str = 'Microsoft YaHei'):
    import markdown
    import pdfkit
    import platform
    import shutil
    import os
    import re
    import urllib.request
    import urllib.parse
    import hashlib

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
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    with open(local_filename, 'wb') as f:
                        f.write(response.read())
            except Exception:
                return f'<span style="color:red">$${tex}$$</span>'

        abs_path = local_filename.replace('\\', '/')
        
        if is_block:
            # 块级公式：字号比正文略大
            style = (
                "display: block; "
                "margin: 3em auto; "
                "height: 3em; "   
                "max-width: 95%; "
            )
        else:
            # 行内公式：字号略大于正文
            style = (
                "height: 1.2em; "   
                "vertical-align: -0.2em; "
                "margin: 0 4px; "
            )

        return f'<img src="file:///{abs_path}" style="{style}" />'

    # 3. 读取 Markdown
    with open(input_md, 'r', encoding='utf-8') as f:
        md_text = f.read()

    print(">>> 正在本地化处理数学公式 (HD Mode)...")
    
    # 4. 正则替换
    md_text = re.sub(r'\$\$([\s\S]*?)\$\$', lambda m: process_latex(m, is_block=True), md_text)
    md_text = re.sub(r'(?<!\\)\$([^\$\n]+?)(?<!\\)\$', lambda m: process_latex(m, is_block=False), md_text)

    # 5. 转 HTML
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
                font-size: 20px; /* --- 将测试用的 100px 改回 24px，现在它会生效了 --- */
                color: #2c3e50;
            }}
            h1 {{ font-size: 38px; margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
            h2 {{ font-size: 32px; margin-top: 30px; }}
            
            /* 表格文字同步调大 */
            table {{ border-collapse: collapse; width: 100%; margin: 25px 0; }}
            th, td {{ 
                border: 1px solid #e2e8f0; 
                padding: 12px 15px; 
                text-align: left; 
                font-size: 20px; /* 表格字号适配 */
                vertical-align: middle;
            }}
            th {{ background-color: #f8fafc; font-weight: bold; }}
            
            p {{ margin-bottom: 1.2em; }}
            li {{ margin-bottom: 0.5em; }}
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

def report(
        pdf_path: str,
        img_dir: str = './',
        output_dir: str = './',
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = 'gpt-4o',
        language: str = 'en',
        max_retries: int = 3,
        font: str = 'Microsoft YaHei'
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
    # 1. 提取论文标题
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
    # 2. 在output_dir下新建以标题命名的文件夹
    paper_dir = os.path.join(output_dir, safe_title)
    if os.path.exists(paper_dir):
        shutil.rmtree(paper_dir)  # 先清空同名文件夹
    os.makedirs(paper_dir)
    # 3. img_dir为此文件夹下images
    img_dir = os.path.join(paper_dir, 'images')
    if not os.path.exists(img_dir):
        os.makedirs(img_dir)

    print(img_dir)
    start_time = time.time()

    extract_pdf_images(pdf_path, img_dir)

    after_extract_time = time.time()
    print("提取图片用时: {}秒".format(after_extract_time - start_time))

    for root, _, files in os.walk(img_dir):
        # 修改正则以支持 x.png 和 x_y.png
        images = [os.path.join(img_dir, f) for f in files if f.endswith('.png') and re.match(r'\d+(?:_\d+)?\.png', f)]
    
    # 修改排序逻辑，处理 0.png 和 0_0.png 的情况
    def sort_key(x):
        name = os.path.basename(x).split('.')[0]
        parts = name.split('_')
        page = int(parts[0])
        # 如果是 x.png，index 设为 -1，排在 x_0.png 之前
        idx = int(parts[1]) if len(parts) > 1 else -1
        return (page, idx)

    images.sort(key=sort_key)

    def image_to_base64_data_url(image_path: str) -> str:
        with open(image_path, "rb") as f:
            data = f.read()
            return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")
    
    base64_urls = [image_to_base64_data_url(img) for img in images]

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
        
        # 自检环节
        print("正在进行质量自检...")
        if language == 'zh':
            check_system_prompt = cn_reviewer_promt
        else:
            check_system_prompt = en_reviewer_promt

        # 构造审稿人的消息，必须包含原始图片，否则审稿人无法核对图片编号是否正确
        check_messages = [
            {"role": "system", "content": check_system_prompt},
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
                    {"type": "text", "text": f"Review this report content:\n\n{content}"}
                ]
            } 
        ]

        check_completion = client.chat.completions.create(
            model=model,
            messages=check_messages # 使用包含图片的消息列表
        )
        check_result = check_completion.choices[0].message.content.strip()

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
            
            # 只保留图片+prompt、上一轮assistant、最新user
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
                retry_prompt = f"上一版本的报告质量未达标，审稿人意见如下：\n\n{critique}\n\n请你参考原始图片内容和上述审稿意见，重新生成一份更详细、逻辑更严密的报告。"
            else:
                retry_prompt = f"The previous report was rejected. Reviewer critique:\n\n{critique}\n\nPlease regenerate the report, strictly following the original images and addressing the reviewer's feedback above."
            messages.append({"role": "user", "content": retry_prompt})

            current_try += 1

    if not quality_pass:
        print("达到最大尝试次数，使用最后一次生成的结果。")

    llm_end_time = time.time()
    print(f"LLM调用时间 (含自检): {llm_end_time - llm_start_time}秒")

    # --- 新增：生成附录 (Appendix) ---
    content += "\n\n## 附录：所有提取图表\n\n"
    # 筛选出 x_y.png 格式的图片 (通常是提取的插图/表格)
    appendix_images = [img for img in images if "_" in os.path.basename(img)]
    
    # 使用 Pandoc 兼容的 Markdown 语法 ({width=45%}) 来替代 HTML
    # 注意: f-string 中输出花括号需要双写 {{ }}
    for i, img_path in enumerate(appendix_images):
        fname = os.path.basename(img_path)
        # 用空格连接，尽量让 pandoc 排在一行（如果宽度允许）
        content += f"![{fname}]({fname}){{ width=45% }} " 
        # 每两张图强制换行，增加可读性
        if (i + 1) % 2 == 0:
            content += "\n"
    content += "\n"
    # -------------------------------

    content = _remove_markdown_backticks(content)

    # 去除所有 markdown 分割线 '---'
    content = content.replace('\n---\n', '\n')
    content = content.replace('\n---\r\n', '\n')
    content = content.replace('---\n', '')
    content = content.replace('---\r\n', '')

    # with open(os.path.join(output_dir, 'raw_report.md'), 'w', encoding='utf-8') as f:
    #     f.write(content)

    # --- 修正：更完善的路径替换逻辑 ---
    def replace_image_paths(content: str, target_img_dir: str, is_pdf: bool = False) -> str:
        """
        统一处理图片路径：
        - Markdown 模式：使用相对路径 'images/xxx.png'
        - PDF 模式：使用绝对路径 'file:///D:/path/to/images/xxx.png'
        """
        abs_img_dir = os.path.abspath(target_img_dir).replace('\\', '/')
        
        def repl_md(match):
            alt = match.group(1)
            img_name = match.group(2)
            # 提取纯文件名，防止大模型给出的路径包含多余层级
            filename = os.path.basename(img_name)
            
            if is_pdf:
                # 对于 Windows，file:/// + 绝对路径是最稳妥的
                full_path = f"file:///{abs_img_dir}/{filename}"
            else:
                full_path = f"images/{filename}"
                
            return f"![{alt}]({full_path})"

        # 正则匹配 ![alt](path)
        return re.sub(r'!\[([^\]]*)\]\(([^)]+\.png)\)', repl_md, content)
    
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
        font=args.font
    )





