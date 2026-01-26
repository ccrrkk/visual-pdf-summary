# Attention Is All You Need

**title**: "Attention Is All You Need"; **authors**: Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N. Gomez, Łukasz Kaiser, Illia Polosukhin; **affiliation**: Google Brain, Google Research, University of Toronto; **venue**: 31st Conference on Neural Information Processing Systems (NIPS 2017), Long Beach, CA, USA; **source**: arXiv:1706.03762v7 [cs.CL] 2 Aug 2023

---

## TL;DR

本文提出了**Transformer**，一种完全基于注意力机制（attention mechanism）的新型神经网络架构，摒弃了循环（RNN）和卷积（CNN）结构。其核心是**缩放点积注意力**（Scaled Dot-Product Attention）和**多头注意力**（Multi-Head Attention），通过并行计算实现了极高的训练效率。在机器翻译任务上，Transformer不仅取得了当时最优的BLEU分数（EN-DE: 28.4, EN-FR: 41.8），而且训练时间大幅缩短（仅需3.5天）。更重要的是，该模型展现出强大的泛化能力，在英语句法依存分析等非翻译任务上也取得了突破性成果，为后续大模型时代奠定了基石。

---

## 引言

传统的序列建模与转导模型（如机器翻译）主要依赖于循环神经网络（RNN）或卷积神经网络（CNN）作为编码器-解码器结构的核心组件。然而，这些模型存在固有缺陷：
1.  **顺序计算**：RNN的递归特性使其难以并行化，训练速度慢，尤其在长序列上受限于内存带宽。
2.  **长距离依赖建模困难**：尽管LSTM/GRU等门控机制有所改善，但信号仍需逐层传递，导致远距离位置间的依赖关系建模效率低下。

为解决上述问题，本文提出了一种全新的架构——**Transformer**。其核心思想是：**完全摒弃递归与卷积，仅依靠自注意力（Self-Attention）机制来建模输入与输出序列中任意两个位置之间的全局依赖关系**。这使得模型能够并行处理所有位置，极大地提升了计算效率，并从根本上解决了长距离依赖问题。

---

## 方法

### 核心架构

Transformer的整体架构如图1所示，由堆叠的编码器（Encoder）和解码器（Decoder）组成，两者均由N=6个相同的层构成。

![Figure 1: The Transformer - model architecture.](images\2_0.png)

*   **编码器（Encoder）**：每一层包含两个子层：
    1.  **多头自注意力机制**（Multi-Head Self-Attention）：用于捕获输入序列内部的依赖关系。
    2.  **前馈神经网络**（Feed-Forward Network）：一个简单的全连接前馈网络。
    每个子层后都接有**残差连接**（Residual Connection）和**层归一化**（Layer Normalization）。

*   **解码器（Decoder）**：每一层包含三个子层：
    1.  **掩码多头自注意力机制**（Masked Multi-Head Self-Attention）：防止当前位置关注到未来的位置，以维持自回归属性。
    2.  **多头注意力机制**（Multi-Head Attention）：其`Query`来自解码器的前一层，而`Key`和`Value`则来自编码器的输出，实现对编码器信息的“交叉注意”。
    3.  **前馈神经网络**（Feed-Forward Network）。
    同样，每个子层后均有残差连接和层归一化.

### 关键组件详解

#### 1. 缩放点积注意力（Scaled Dot-Product Attention）

这是Transformer中最基础的注意力计算单元，如图2（左）所示。给定查询（Query）矩阵 $Q$、键（Key）矩阵 $K$ 和值（Value）矩阵 $V$，其计算公式为：

$$
\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V
$$

其中，$d_k$ 是键向量的维度。引入 $\frac{1}{\sqrt{d_k}}$ 的缩放因子是为了防止点积结果过大，导致 softmax 函数进入梯度极小的饱和区，从而影响训练稳定性。

![Figure 2: (left) Scaled Dot-Product Attention. (right) Multi-Head Attention consists of several attention layers running in parallel.](images\3_0.png)

#### 2. 多头注意力（Multi-Head Attention）

为了使模型能够同时关注来自不同表示子空间的信息，Transformer采用了多头机制。它将输入线性投影到 $h$ 个不同的子空间，然后在每个子空间上并行地执行缩放点积注意力，最后将结果拼接并再次线性投影。其公式为：

$$
\text{MultiHead}(Q, K, V) = \text{Concat}(\text{head}_1, ..., \text{head}_h)W^O
$$
$$
\text{where } \text{head}_i = \text{Attention}(QW_i^Q, KW_i^K, VW_i^V)
$$

文中采用 $h=8$ 个头，且为保持总计算量不变，每个头的维度 $d_k = d_v = d_{model}/h = 64$。

#### 3. 位置编码（Positional Encoding）

由于模型本身不具备对序列顺序的感知能力，作者引入了**正弦/余弦函数**构成的位置编码（Positional Encoding）来注入位置信息：

$$
PE_{(pos, 2i)} = \sin(pos / 10000^{2i/d_{model}})
$$
$$
PE_{(pos, 2i+1)} = \cos(pos / 10000^{2i/d_{model}})
$$

其中，$pos$ 是位置，$i$ 是维度。这种设计允许模型通过线性变换轻松学习到相对位置关系。

#### 4. 前馈网络与嵌入

每个位置的前馈网络（FFN）是一个两层的全连接网络，中间使用ReLU激活：

$$
\text{FFN}(x) = \max(0, xW_1 + b_1)W_2 + b_2
$$

输入和输出的词嵌入（Embedding）维度为 $d_{model}=512$，并与位置编码相加后输入模型。最终的输出通过一个线性变换和Softmax得到词表上的概率分布。

### 模型复杂度分析

如表1所示，Transformer的自注意力层具有 $O(n^2 \cdot d)$ 的计算复杂度，但其**最大路径长度仅为 $O(1)$**，这意味着任意两个位置间的依赖关系都可以一步建立，这是其能高效建模长距离依赖的关键。相比之下，RNN的最大路径长度为 $O(n)$，CNN为 $O(\log_k(n))$。

| Layer Type           | Complexity per Layer | Sequential Operations | Maximum Path Length |
| :------------------- | :------------------- | :-------------------- | :------------------ |
| Self-Attention       | $O(n^2 \cdot d)$     | $O(1)$                | $O(1)$              |
| Recurrent            | $O(n \cdot d^2)$     | $O(n)$                | $O(n)$              |
| Convolutional        | $O(k \cdot n \cdot d^2)$ | $O(1)$             | $O(\log_k(n))$      |
| Self-Attention (restricted) | $O(r \cdot n \cdot d)$ | $O(1)$          | $O(n/r)$            |

---

## 实验

### 实验设置

*   **数据集**：WMT 2014 英德（EN-DE）和英法（EN-FR）翻译任务。
*   **硬件**：8块NVIDIA P100 GPU。
*   **优化器**：Adam优化器，$\beta_1=0.9, \beta_2=0.98, \epsilon=10^{-9}$。
*   **训练策略**：采用带预热（warmup）的学习率调度策略。

### 主要结果

#### 1. 机器翻译性能（Table 2）

Transformer在两个翻译任务上均显著超越了当时的SOTA模型，且训练成本更低。

| Model                      | EN-DE BLEU | EN-FR BLEU | Training Cost (FLOPs) |
| :------------------------- | :--------- | :--------- | :-------------------- |
| **Transformer (big)**      | **28.4**   | **41.8**   | $2.3 \cdot 10^{19}$   |
| ConvS2S Ensemble [9]       | 26.36      | 41.29      | $1.2 \cdot 10^{21}$   |
| GNMT + RL Ensemble [38]    | 26.30      | 41.16      | $1.1 \cdot 10^{21}$   |

*   **关键结论**：Transformer (big) 在EN-FR任务上达到了41.8的BLEU分数，刷新了记录；其训练成本仅为之前最佳集成模型的约1/50。

#### 2. 架构消融实验（Table 3）

表3系统地验证了各超参数的影响：
*   **头数（h）**：8头为最优，过少（1, 4）或过多（16, 32）都会导致性能下降。
*   **维度（$d_k$, $d_v$）**：减小维度会损害模型质量，印证了点积注意力的兼容性函数需要足够维度才能有效工作。
*   **Dropout**：加入dropout（0.1）能有效防止过拟合，提升泛化性能。
*   **位置编码**：将正弦位置编码替换为可学习的编码，效果几乎相同，说明其设计是合理的。

#### 3. 泛化能力验证：英语句法依存分析（Table 4）

为证明Transformer的通用性，作者将其应用于**英语句法依存分析**（English Constituency Parsing）任务。

| Model                     | WSJ 23 F1 |
| :------------------------ | :-------- |
| **Transformer (4 layers)** | **92.7**  |
| Luong et al. (2015) [23]  | 93.0      |
| Dyer et al. (2016) [8]    | 93.3      |

*   **关键结论**：即使只用4层、仅在40K句子的小规模数据集上进行**无监督预训练**（WSJ only, discriminative），Transformer也取得了91.3的F1分数，接近甚至超过了当时最先进的RNN模型。这强有力地证明了其强大的特征提取能力和模型泛化能力。

#### 4. 注意力可视化

论文通过多个图例（Figures 3, 4, 5）直观展示了注意力机制的工作原理：
*   **Figure 3**：展示了对动词“making”的长距离依赖捕捉，多个注意力头都聚焦于其宾语“registration”。
*   **Figure 4 & 5**：揭示了不同注意力头会学习到不同的语言学功能，例如有的头专注于句法结构（如解析“The Law”），有的头则负责指代消解（如解析“its”）。

![Figure 3: An example of the attention mechanism following long-distance dependencies...](images\12_0.png)
![Figure 4: Two attention heads... apparently involved in anaphora resolution.](images\13_0.png)
![Figure 5: Many of the attention heads exhibit behaviour that seems related to the structure of the sentence.](images\14_0.png)

---

## 总结与讨论

### 总结

本文提出的Transformer架构是深度学习领域的一项里程碑式工作。它通过纯粹的注意力机制，成功地解决了RNN/CNN在序列建模中的核心瓶颈——并行化与长距离依赖。其简洁而强大的设计不仅在机器翻译任务上取得了卓越成绩，更在句法分析等下游任务上展现了惊人的泛化能力，彻底改变了自然语言处理的研究范式。

### 局限性与未来工作

*   **计算与内存开销**：自注意力的 $O(n^2)$ 复杂度在处理超长序列（如整篇文档、视频帧）时会成为瓶颈。论文在第11页也提及了这一点，并计划未来研究限制注意力范围（如只关注局部邻域）的方法。
*   **对归纳偏置的削弱**：完全放弃卷积和循环结构，意味着模型失去了对局部性（CNN）和顺序性（RNN）的先验知识，这可能在某些特定任务上需要更多数据来弥补。
*   **未来方向**：正如论文结论所述，作者计划将Transformer扩展到图像、音频等多模态任务，并探索更高效的注意力变体（如稀疏注意力、线性注意力）以处理更大规模的输入。后续的BERT、GPT等模型正是沿着这一方向发展的直接产物。

总而言之，"Attention Is All You Need" 不仅是一篇提出新模型的论文，更是一份宣告新时代来临的宣言书，其影响深远，至今仍是大语言模型（LLM）架构的基石。