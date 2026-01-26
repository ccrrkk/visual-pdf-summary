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
from prompt import cn_prompt, en_prompt
import argparse

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

def report(
        pdf_path: str,
        img_dir: str = './',
        output_dir: str = './',
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = 'gpt-4o',
        language: str = 'en'
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
        api_key=api_key,
        base_url=base_url,
    )
    if language not in ['zh', 'en']:
        raise ValueError("Unsupported language. Supported languages are 'zh' and 'en'.")
    if language == 'zh':
        prompt = cn_prompt
    else:
        prompt = en_prompt
    img_dir = os.path.join(output_dir, 'images')
    print(img_dir)
    start_time = time.time()

    extract_pdf_images(pdf_path, img_dir)

    after_extract_time = time.time()
    print("提取图片用时: {}秒".format(after_extract_time - start_time))

    for root, _, files in os.walk(img_dir):
        images = [os.path.join(img_dir, f) for f in files if f.endswith('.png') and re.match(r'\d+\.png', f)]
    
    def image_to_base64_data_url(image_path: str) -> str:
        with open(image_path, "rb") as f:
            data = f.read()
            return "data:image/png;base64," + base64.b64encode(data).decode("utf-8")
    
    base64_urls = [image_to_base64_data_url(img) for img in images]

    llm_start_time = time.time()

    print("base64编码用时: {}秒".format(llm_start_time - after_extract_time))

    completion = client.chat.completions.create(
        model=model,
        messages=[
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
        ],
    )
    content = completion.choices[0].message.content

    llm_end_time = time.time()
    print(f"LLM调用时间: {llm_end_time - llm_start_time}秒")

    content = _remove_markdown_backticks(content)

    # with open(os.path.join(output_dir, 'raw_report.md'), 'w', encoding='utf-8') as f:
    #     f.write(content)

    # 替换大模型输出的图片路径，如![<说明>](0_0.png) -> ![<说明>](img_dir/0_0.png)
    # 注意markdown和pdf对路径的要求不一样
    def replace_image_paths(content: str, img_dir: str) -> str:
        # 只替换形如 ![xxx](0_0.png) 的图片路径
        def repl(match):
            alt, path = match.group(1), match.group(2)
            # 如果已经有目录前缀就不重复加
            if path.startswith(img_dir):
                return f"![{alt}]({path})"
            return f"![{alt}]({os.path.join(img_dir, path)})"
        # 正则匹配 ![xxx](xxx.png)
        return re.sub(r'!\[([^\]]*)\]\(([\w\-_\.]+\.png)\)', repl, content)
    
    md_content = replace_image_paths(content, "images") # markdown的图像路径必须是markdown文件相对于图片的路径
    pdf_content = replace_image_paths(content, img_dir) # 而pdf的图像路径是代码运行目录相对于图片的路径

    # 保存解析后的markdown文件
    md_output_path = os.path.join(output_dir, 'report.md')
    with open(md_output_path, 'w', encoding='utf-8') as f:
        f.write(md_content)

    tmp_md_path = os.path.join(output_dir, 'temp_report.md')
    with open(tmp_md_path, 'w', encoding='utf-8') as f:
        f.write(pdf_content)

    # markdown->pdf
    def markdown_to_pdf(input: str,output) -> str:
        output = pypandoc.convert_file(input, 'pdf', outputfile=output,
                              extra_args=['--pdf-engine=xelatex', 
                                          '-V', 'CJKmainfont=SimSun'])
    
    pdf_output_path = os.path.join(output_dir, 'report.pdf')
    markdown_to_pdf(tmp_md_path, pdf_output_path)

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
    args = parser.parse_args()

    load_dotenv()  

    api_key = getenv("api_key") if args.api_key is None else args.api_key
    base_url = getenv("base_url") if args.base_url is None else args.base_url
    model = getenv("model") if args.model is None else args.model
    img_dir = os.path.join(args.output_dir, 'images')

    report(
        pdf_path=args.pdf_path,
        img_dir=img_dir,
        output_dir=args.output_dir,
        api_key=api_key,
        base_url=base_url,
        model=model,
        language=args.language
    )





