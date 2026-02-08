# Visual PDF Summary

Visual PDF Summary 是一个基于多模态.模型的科研论文智能简报生成工具。

不同于传统的仅基于文本摘要的工具，本项目能够深入理解 PDF 的版面结构，**自动提取论文中的插图和表格**，结合视觉大模型的能力，生成一份图文并茂、逻辑清晰的学术研报。

## 🚀 在线体验

无需本地安装，直接在浏览器中体验 Visual PDF Summary：

👉 [https://visual-pdf-summary.streamlit.app/](https://visual-pdf-summary.streamlit.app/)

上传你的 PDF，即可一键生成图文简报！

## ✨ 核心特性

- **🖼️ 智能视觉提取**: 程序基于微调后的 yolov26n 检测模型，自动检测并裁剪论文中的图片、图表和关键区域，去除干扰元素，提升检测准确率。
- **🧠 多模态深度理解**: 利用大模型的视觉理解能力，读取论文截图，结合提取的插图，生成比纯文本更准确的解读。
- **📊 图文并茂的报告**: 生成的报告自动按引用位置插入论文原图，不再是干瘪的文字。

## 🛠️ 使用方法

### 1. Python 依赖
请确保安装了 Python 3.8+，并安装以下依赖：

```bash
git clone https://github.com/ccrrkk/visual-pdf-summary.git
cd visual-pdf-summary
pip install -r requirements.txt
```

### 2. 获取API Key
需要一个有效的大模型 API Key 以调用大模型接口。可以在对应大模型服务提供商的官网获取。

获取到 Key 后，请在项目根目录创建一个 `.env` 文件，内容如下：

```env
api_key=你的API_KEY 
base_url=你的API_BASE_URL  
model=gpt-4o               
```

### 3. 运行程序

运行以下命令生成论文简报：

```bash
python reporter.py --pdf_path path/to/your/paper.pdf --output_dir output --language en --max_retries 3
```

- `--pdf_path`: 输入 PDF 文件路径（必填）
- `--output_dir`: 输出目录，默认为 `output`
- `--language`: 简报语言，支持 `zh`（中文）和 `en`（英文），默认为 `en`
- `--max_retries`: 最大重试次数，默认为3次

### 4. 运行前端界面

运行以下命令启动前端界面：

```bash
streamlit run app.py
```

随后在浏览器中打开 `http://localhost:8501` 即可使用。你可以在前端页面上轻松的调整相关配置.

### 5. 修改prompt(可选)

如果需要自定义提示词，可以在 `prompt.py` 中修改 `cn_prompt` 和 `en_prompt` 变量。

## 💾 输出结果

尝试对论文["Attention Is All You Need"](https://arxiv.org/abs/1706.03762)生成简报，输出结果可以查看[report](example/attention_is_all_your_need/report.pdf),节选如下：

<center class="half">
    <img src="pic/1.png" width="200"/><img src="pic/2.png" width="200"/>
</center>



## 致敬

本文件部分pdf解析方法的参考自 https://github.com/CosmosShadow/gptpdf ,并在此基础上做了重写了图像提取的方法.
