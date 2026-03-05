import streamlit as st
import os
import base64
from reporter import report
from dotenv import load_dotenv

st.set_page_config(page_title="论文可视化摘要", layout="wide")
st.title("📄 论文可视化摘要生成器")

load_dotenv()

# 初始化 session state 用于人工审查
if 'review_status' not in st.session_state:
    st.session_state.review_status = None  # None, 'pending', 'satisfied', 'unsatisfied'
if 'human_feedback' not in st.session_state:
    st.session_state.human_feedback = ''
if 'last_report_result' not in st.session_state:
    st.session_state.last_report_result = None
if 'last_report_content' not in st.session_state:
    st.session_state.last_report_content = None
if 'regenerate_count' not in st.session_state:
    st.session_state.regenerate_count = 0

# --- 侧边栏参数 ---
st.sidebar.header("参数设置")
language = st.sidebar.selectbox("选择语言", ["zh", "en"], index=0)
# use_rag = st.sidebar.checkbox("开启RAG切片总结模式", value=True) # 原代码中 reporter 似乎尚未实现 use_rag 参数，暂且保留或注释
use_rag = False 

st.sidebar.markdown("### 模型配置")
api_key = st.sidebar.text_input("OpenAI style API Key", value=os.getenv("api_key") or "", type="password")
base_url = st.sidebar.text_input("OpenAI  style Base URL", value=os.getenv("base_url") or "")
model = st.sidebar.text_input("主模型 (如gpt-5)", value=os.getenv("model") or "gpt-5")

st.sidebar.markdown("### 生成配置")

# 1. 最大重试次数
max_retries = st.sidebar.slider("最大自检重试次数", min_value=1, max_value=5, value=3, help="如果模型生成质量不过关，自动重试的次数")

# 👈 新增：图片压缩选项
compress_images = st.sidebar.checkbox("开启图片压缩", value=True, help="减小图片体积，防止 API 报错 413 或连接中断")

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
    # 修正 1：不要直接把上传的 PDF 放在 output_dir 根目录，
    # 否则 reporter 里的 shutil.rmtree(paper_dir) 可能会影响到它。
    # 我们可以先存在临时目录。
    temp_dir = os.path.join(output_dir, "temp_uploads")
    os.makedirs(temp_dir, exist_ok=True)
    pdf_path = os.path.join(temp_dir, uploaded_file.name)
    
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
                    max_retries=max_retries,
                    font=selected_font_sys,
                    compress_images=compress_images
                )

                # 存储结果到 session state
                st.session_state.last_report_result = result
                st.session_state.review_status = 'pending'
                st.session_state.human_feedback = ''
                st.session_state.regenerate_count = 0
                # 读取生成的markdown内容
                try:
                    with open(result['md_path'], 'r', encoding='utf-8') as f:
                        st.session_state.last_report_content = f.read()
                except Exception as e:
                    print(f"无法读取markdown内容: {e}")
                    st.session_state.last_report_content = None

                st.success("摘要生成完成！")

            except OSError as e:
                if "wkhtmltopdf" in str(e):
                    st.error("❌ 未找到 PDF 生成引擎 (wkhtmltopdf)。")
                    st.info("请确保服务器已安装 wkhtmltopdf。本地运行请下载安装并加入 PATH。")
                else:
                    st.error(f"系统错误: {str(e)}")
            except Exception as e:
                st.error(f"生成过程中发生错误: {str(e)}")
                import traceback
                st.code(traceback.format_exc())

    # 显示生成的报告和人工审查界面
    if st.session_state.last_report_result is not None:
        result = st.session_state.last_report_result

        col1, col2 = st.columns([1, 1])

        with col1:
            st.markdown("### 📥 下载文件")
            with open(result['pdf_path'], "rb") as f:
                st.download_button("下载PDF简报", f, file_name="report.pdf", mime="application/pdf")

            with open(result['md_path'], "rb") as f:
                st.download_button("下载Markdown源码", f, file_name="report.md", mime="text/markdown")

        # st.markdown("---")
        # st.markdown("### 📄 摘要预览")

        # # 修正 2：处理 Streamlit 预览中的图片路径
        # # Streamlit 不支持直接读取相对路径的本地图片
        # with open(result['md_path'], "r", encoding="utf-8") as f:
        #     md_text = f.read()

        #     # 将 markdown 中的 images/ 替换为绝对路径，方便预览（Streamlit 特殊处理）
        #     preview_img_dir = os.path.abspath(result['img_dir']).replace('\\', '/')
        #     # 将 ![alt](images/xx.png) 替换为直接使用图片文件（Streamlit 较难直接在 markdown 里渲染本地绝对路径图片）
        #     # 更好的办法是：在内容渲染前，先把文本按段拆开，遇到图片用 st.image()

        #     # 简单粗暴法：Streamlit 只有在 images 文件夹在当前运行目录下时才能显示。
        #     # 或者我们可以解析 md，手动渲染文本和图片：
        #     import re
        #     parts = re.split(r'(!\[.*?\]\(.*?\))', md_text)
        #     for part in parts:
        #         img_match = re.search(r'!\[(.*?)\]\((.*?)\)', part)
        #         if img_match:
        #             img_filename = os.path.basename(img_match.group(2))
        #             st.image(os.path.join(result['img_dir'], img_filename), caption=img_match.group(1))
        #         else:
        #             st.markdown(part, unsafe_allow_html=True)

        # st.markdown("---")
        # st.markdown("### 🖼️ 提取的图表")
        # imgs = os.listdir(result['img_dir'])
        # # 简单过滤显示图片
        # img_files = [f for f in imgs if f.endswith(".png")]
        # if img_files:
        #     st.image([os.path.join(result['img_dir'], img) for img in img_files[:10]], width=150, caption=img_files[:10])
        #     if len(img_files) > 10:
        #         st.info(f"还有 {len(img_files)-10} 张图片未显示...")

        # 人工审查界面
        st.markdown("---")
        st.markdown("### 👤 人工审查")

        if st.session_state.review_status == 'pending':
            satisfaction = st.radio("您对生成的报告是否满意？", ["满意", "不满意"], index=None)

            if satisfaction == "满意":
                st.session_state.review_status = 'satisfied'
                st.success("感谢您的认可！")
            elif satisfaction == "不满意":
                st.session_state.review_status = 'unsatisfied'
                # 继续显示反馈输入框

        if st.session_state.review_status == 'unsatisfied':
            feedback = st.text_area("请提供具体的改进意见：", value=st.session_state.human_feedback, height=150)
            st.session_state.human_feedback = feedback

            # 上传反馈图片，帮助更精准地定位问题
            feedback_images = st.file_uploader(
                "上传参考图片（可选，帮助定位问题）",
                type=["png", "jpg", "jpeg"],
                accept_multiple_files=True,
                key="feedback_images"
            )

            if st.button("重新生成报告"):
                if feedback.strip():
                    # 将反馈图片转换为 base64 data URLs
                    feedback_image_urls = []
                    if feedback_images:
                        for img_file in feedback_images:
                            img_bytes = img_file.read()
                            b64 = base64.b64encode(img_bytes).decode("utf-8")
                            mime = "image/png" if img_file.name.endswith(".png") else "image/jpeg"
                            feedback_image_urls.append(f"data:{mime};base64,{b64}")

                    with st.spinner("正在根据您的反馈重新生成报告..."):
                        try:
                            new_result = report(
                                pdf_path=pdf_path,
                                output_dir=output_dir,
                                api_key=api_key if api_key else None,
                                base_url=base_url if base_url else None,
                                model=model,
                                language=language,
                                max_retries=max_retries,
                                font=selected_font_sys,
                                compress_images=compress_images,
                                human_feedback=feedback,
                                previous_content=st.session_state.last_report_content,
                                skip_image_extraction=True,
                                feedback_images=feedback_image_urls
                            )
                            # 更新结果
                            st.session_state.last_report_result = new_result
                            st.session_state.review_status = 'pending'
                            st.session_state.regenerate_count += 1
                            # 读取新生成的markdown内容
                            try:
                                with open(new_result['md_path'], 'r', encoding='utf-8') as f:
                                    st.session_state.last_report_content = f.read()
                            except Exception as e:
                                print(f"无法读取新生成的markdown内容: {e}")
                                st.session_state.last_report_content = None
                            st.success("报告已重新生成！请查看更新后的报告。")
                            # 清空反馈
                            st.session_state.human_feedback = ''
                            st.rerun()
                        except Exception as e:
                            st.error(f"重新生成过程中发生错误: {str(e)}")
                else:
                    st.warning("请输入改进意见后再点击重新生成。")
        elif st.session_state.review_status == 'satisfied':
            st.info("审查完成，报告已定稿。")