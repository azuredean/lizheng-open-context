# 课代表立正 · Open Context

一个给人和 AI 都能读的公开知识底座：把课代表立正已经公开发表的文章、视频索引、可授权字幕、核心主张与《真本事》完整框架参考，整理成可检索、可引用、可继续开发的开放仓库。

它不是一个替你模仿“立正口吻”的人格提示词，也不宣称能替本人回答。它更像一套有来源、有时间、有边界的公共材料：你可以用它做搜索、问答、视频推荐、研究索引，或开发自己的课代表 skill / agent。

## 这里有什么

| 层 | 内容 | 开放方式 |
|---|---|---|
| `context/` | 当前核心主张、公开简介、Public Axioms V1、《真本事》完整框架与阅读地图 | 立正原创内容，CC BY 4.0 |
| `corpus/knowledge-bank/` | Knowledge Bank 中由 YZ｜立正本人公开发表的文章 | 全文、来源链接、发布日期，CC BY 4.0 |
| `catalog/knowledge-bank.jsonl` | Knowledge Bank 的公开文章目录 | 所有作者只列公开元数据；仅立正文稿进入全文语料 |
| `catalog/videos.jsonl` | 课代表立正 YouTube 公开常规视频目录 | 标题、日期、链接、字幕状态、权利范围 |
| `corpus/videos/` | 通过 V1 正向说话人/权利 allowlist 的本人主讲字幕 | 带 YouTube 时间码；嘉宾、多人及未确认内容不复制全文 |
| `docs/` | 数据边界、回答协议、建 agent 指南 | 可直接作为开发规范 |
| `scripts/` | 导出、搜索与发布前检查 | MIT |

准确数量和每个文件的哈希见 [`release-manifest.json`](release-manifest.json)。

## 30 秒开始

无需向量数据库，先用仓库自带的本地搜索：

```bash
python3 scripts/search.py "如何找到适合写在简历里的项目" --top 8
python3 scripts/search.py "fake work" --type knowledge-bank
python3 scripts/search.py "做出代表作" --type video
```

搜索结果会给出标题、日期、原始链接、命中片段；视频结果尽可能给到可点击的时间码。

想先看这套材料如何真正回答社区提出的问题，可以读[“如何找到适合写在简历里的项目，并复盘它”示例](examples/resume-projects.md)。示例明确标出了直接来源与仓库综合，避免把新生成的方法冒充成原话。

如果要接入 LLM，建议先读：

1. [`docs/answering-contract.md`](docs/answering-contract.md)：回答时怎样区分原文、综合判断和推断；
2. [`docs/build-your-own-agent.md`](docs/build-your-own-agent.md)：最小可用的检索与推荐流程；
3. [`docs/source-model.md`](docs/source-model.md)：来源优先级、时间与字段；
4. [`AGENTS.md`](AGENTS.md)：可直接交给 coding agent 的行为说明。

## 已有参考实现

[`sunyuzheng/zhenbenshi-advisor`](https://github.com/sunyuzheng/zhenbenshi-advisor) 是一个已经公开、聚焦《真本事》职业与价值框架的轻量 skill。它适合直接参考“怎样把一本书做成建议流程”；本仓库不复制或替代它，而是提供更广的公共来源层，让开发者可以同时使用《真本事》、Knowledge Bank、YouTube 与当前 thesis，并保留出处和时间语义。

## 这套材料主张什么

当前最核心的一句话是：

> **MAKE WHAT LASTS.**<br>
> **做点真东西。**

它和《真本事》之间的桥是：

> **学点真本事，做点真东西。**

`做出你的代表作` 是更长程的愿望：把逐渐挣来的理解与手艺，做成自己愿意长期负责、世界也愿意继续选择的作品。它不是一套成功保证，也不是要求每件工作都必须成为资产。

完整版本见 [`context/core-thesis.md`](context/core-thesis.md)。

## 为什么不直接发布一个“课代表 skill”

一个固定 skill 很快会把新的判断冻结成旧规则，也容易把“像他说话”误当成“理解他说过什么”。公开底座让不同的人可以做不同产品，同时保留三个更重要的能力：

- 回到原始出处，而不是只继承二手总结；
- 看见观点何时发表，以及后来是否变化；
- 明确区分本人原话、跨材料综合和开发者自己的推断。

仓库仍提供一套最小回答协议，但不垄断最终交互形式。

## 明确不在这里的内容

- 微信、短信、邮件、私信、私人聊天与未公开会议；
- 付费会员或私密社区空间的原文、评论和成员资料；
- 学员、客户、合作方的非公开信息；
- 合同、财务、定价策略、内部运营、路线图和商业机密；
- 未发布选题、草稿、课程内容、会员视频与私有媒体；
- 凭证、token、Cookie、环境变量、日志和本地绝对路径；
- 《真本事》出版社版式、插图、扫描件，以及不是由立正拥有权利的第三方素材；
- 付费课程的原始视频与逐字转录（框架内容已经以作者自有版本完整开放）；
- 已知嘉宾访谈的完整逐字稿。

视频字幕采用正向 allowlist：新视频不会因为“暂时没发现嘉宾”就自动获得全文许可，必须先明确加入 `config/video-transcript-allowlist.txt`；任何与嘉宾索引或人工排除表冲突的 ID 会让导出直接失败。

公开可见不等于可以无条件再授权。完整边界见 [`docs/privacy-and-rights.md`](docs/privacy-and-rights.md) 与 [`LICENSE-CONTENT.md`](LICENSE-CONTENT.md)。

## 更新与纠错

这个仓库是版本化快照，不是假装永远最新的“数字分身”。每次发布会记录来源日期、筛选规则、数量和哈希。发现错字、归属错误、断链或隐私问题，请开 issue；涉及移除请求时，请只描述目标文件和原因，不要在 issue 里再次粘贴敏感内容。

## License

- 程序与开发文档：MIT，见 [`LICENSE`](LICENSE)。
- 明确标注为立正原创的公开内容：CC BY 4.0，见 [`LICENSE-CONTENT.md`](LICENSE-CONTENT.md)。
- 公开元数据：CC0 1.0。
- 第三方引文、链接、姓名、商标和嘉宾内容不因进入本仓库而被重新授权。
