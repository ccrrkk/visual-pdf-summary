# Visual PDF Summary

Visual PDF Summary 是一个基于多模态大模型的科研论文智能简报生成工具。

不同于传统的仅基于文本摘要的工具，本项目能够深入理解 PDF 的版面结构，**自动提取论文中的插图和表格**，结合视觉大模型的能力，生成一份图文并茂、逻辑清晰的学术研报。

## ✨ 核心特性

- **🖼️ 智能视觉提取**: 也就是不仅仅是截图。内置基于 `Shapely` 和 `PyMuPDF` 的几何算法，自动检测并裁剪论文中的图片、图表和关键区域，去除干扰元素。
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
python reporter.py --pdf_path path/to/your/paper.pdf --output_dir output --language en
```

- `--pdf_path`: 输入 PDF 文件路径（必填）
- `--output_dir`: 输出目录，默认为 `output`
- `--language`: 简报语言，支持 `zh`（中文）和 `en`（英文），默认为 `en`

### 4. 修改prompt(可选)

如果需要自定义提示词，可以在 `prompt.py` 中修改 `cn_prompt` 和 `en_prompt` 变量。

## 💾 输出结果

尝试对论文["Attention Is All You Need"](https://arxiv.org/abs/1706.03762)生成简报，输出结果可以查看[report](example/attention_is_all_your_need/report.pdf),节选如下：

<center class="half">
    <img src="pic/1.png" width="200"/><img src="pic/2.png" width="200"/>
</center>

## 致敬

本文件有关pdf解析的代码部分参考自 https://github.com/CosmosShadow/gptpdf ,并在此基础上做了改进了图像提取的算法. 
