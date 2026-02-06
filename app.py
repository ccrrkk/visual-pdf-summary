import streamlit as st
import os
from reporter import report
from dotenv import load_dotenv

st.set_page_config(page_title="论文可视化摘要", layout="wide")
st.title("📄 论文可视化摘要生成器")

load_dotenv()

# --- 侧边栏参数 ---
st.sidebar.header("参数设置")
language = st.sidebar.selectbox("选择语言", ["zh", "en"], index=0)
# use_rag = st.sidebar.checkbox("开启RAG切片总结模式", value=True) # 原代码中 reporter 似乎尚未实现 use_rag 参数，暂且保留或注释
use_rag = False 

st.sidebar.markdown("### 模型配置")
api_key = st.sidebar.text_input("OpenAI API Key", value=os.getenv("api_key") or "", type="password")
base_url = st.sidebar.text_input("OpenAI Base URL", value=os.getenv("base_url") or "")
model = st.sidebar.text_input("主模型 (如gpt-4o)", value=os.getenv("model") or "gpt-4o")

st.sidebar.markdown("### 生成配置")

# 1. 最大重试次数
max_retries = st.sidebar.slider("最大自检重试次数", min_value=1, max_value=5, value=3, help="如果模型生成质量不过关，自动重试的次数")

# 2. 字体选择与预览
st.sidebar.markdown("#### PDF字体选择")
# 字体映射：显示名称 -> (系统字体名, CSS通用名用于预览)
font_options = {
    "微软雅黑 (Modern)": ("Microsoft YaHei", "Microsoft YaHei, sans-serif"),
    "宋体 (Standard)": ("SimSun", "SimSun, serif"),
    "楷体 (Traditional)": ("KaiTi", "KaiTi, system-ui, serif"),
    "黑体 (Bold)": ("SimHei", "SimHei, sans-serif")
}

selected_font_label = st.sidebar.selectbox("选择字体", list(font_options.keys()), index=0)
selected_font_sys, selected_font_css = font_options[selected_font_label]

# 字体效果预览
st.sidebar.markdown(
    f"""
    <div style="padding: 10px; border: 1px solid #ddd; border-radius: 5px; background-color: #f9f9f9;">
        <p style="margin:0; font-size:12px; color:#666;">字体效果预览：</p>
        <p style="margin:5px 0 0 0; font-size:16px; font-family: {selected_font_css};">
            人工智能与论文摘要<br>
            AI Paper Summary
        </p>
    </div>
    """,
    unsafe_allow_html=True
)

output_dir = st.sidebar.text_input("输出目录", value="output")

st.sidebar.markdown("---")
st.sidebar.info("上传PDF，点击生成摘要")

# --- 主界面 ---
uploaded_file = st.file_uploader("上传论文PDF文件", type=["pdf"])

if uploaded_file is not None:
    # 确保文件名安全，或使用固定名，这里简单处理
    pdf_path = os.path.join(output_dir, uploaded_file.name)
    os.makedirs(output_dir, exist_ok=True)
    with open(pdf_path, "wb") as f:
        f.write(uploaded_file.read())

    if st.button("生成摘要"):
        with st.spinner("正在生成摘要，请稍候..."):
            try:
                # 调用 reporter
                result = report(
                    pdf_path=pdf_path,
                    output_dir=output_dir,
                    api_key=api_key if api_key else None,
                    base_url=base_url if base_url else None,
                    model=model,
                    language=language,
                    max_retries=max_retries,  # 传入新参数
                    font=selected_font_sys    # 传入系统字体名
                )
                
                st.success("摘要生成完成！")
                
                col1, col2 = st.columns([1, 1])
                
                with col1:
                    st.markdown("### 📥 下载文件")
                    with open(result['pdf_path'], "rb") as f:
                        st.download_button("下载PDF简报", f, file_name="report.pdf", mime="application/pdf")
                    
                    with open(result['md_path'], "r", encoding="utf-8") as f:
                        st.download_button("下载Markdown源码", f, file_name="report.md", mime="text/markdown")

                st.markdown("---")
                st.markdown("### 📄 摘要预览")
                
                # 读取并展示 markdown
                with open(result['md_path'], "r", encoding="utf-8") as f:
                    md_text = f.read()
                    st.markdown(md_text, unsafe_allow_html=True)

                st.markdown("---")
                st.markdown("### 🖼️ 提取的图表")
                imgs = os.listdir(result['img_dir'])
                # 简单过滤显示图片
                img_files = [f for f in imgs if f.endswith(".png")]
                if img_files:
                    st.image([os.path.join(result['img_dir'], img) for img in img_files[:10]], width=150, caption=img_files[:10])
                    if len(img_files) > 10:
                        st.info(f"还有 {len(img_files)-10} 张图片未显示...")

            except Exception as e:
                st.error(f"生成过程中发生错误: {str(e)}")
                # 打印详细堆栈以便调试
                import traceback
                st.code(traceback.format_exc())