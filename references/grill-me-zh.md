# 反向质询：grill-me 中文方法参考

在需求契约和方案选择中，用持续访谈把问题、决策依赖和关键取舍问清楚，再形成共同理解。

本参考采用 Matt Pocock 的通用设计质询原作，作中文转述与 dot 场景适配。

## 原作核心方法（中文转述）

1. 将想法、计划或设计梳理成设计树：每项决定带出后续决定，标明彼此依赖。
2. 提问前逐项核对依赖，只把前置条件已确定的问题放入本轮，覆盖当前全部可回答的独立决策。依赖尚未回答问题的下游追问，留到后续轮次。
3. 给本轮每题编号，提供推荐答案及理由，让用户确认、修正、反驳或补充自己的选择。
4. 用户回答后重新检查设计树，继承已确定的决定，更新依赖，再提出下一轮问题。
5. 可查事实由助手调查，目标与价值取舍由用户决定。事实调查进行中，只暂停依赖它的分支，其余独立问题继续。
6. 持续探索与目标相关的全部分支，直到本轮再无待决定的问题、双方的假设均已说明。用户明确确认共同理解后，进入执行。

该固定版本采用分轮提问，用户也可指定逐题方式。

## dot 的中文适配

以下是本工作流的呈现与闭环约定：

- 手机每批最多5个独立问题，这是单批上限。当前可答问题较多时，先问最影响结果的几项，收到答案后重新检查依赖，再继续追问。
- 每题给明确选项、推荐和取舍，允许自由回答。推荐依据已有目标与真实证据，未定阈值交由用户决定。
- 同层独立问题可同批；有依赖的先问上游。答案含糊、回避取舍或矛盾时，沿原编号继续问具体缺口；新证据只重开受影响分支。
- 合并问题前检查其他未答题的可能答案：若某个答案会使本题暂时无法回答或选项失效，把本题安排在后续轮次。事实未查清时，先推进其余独立分支。
- 在需求入口问清使用者、场景、目标结果、验收、范围、约束、授权与责任；在方案入口问清可行方向、代价、依赖、失败恢复和关键取舍。
- 同时质询模型自己的推荐：找出最强可信失败案例、承重假设和推翻它的观察，比较更简单、可逆的选择。可实验的假设用最小安全实验补证。
- 关键信息充分时，整理简洁需求契约与推荐方案，由用户本人明确确认开动，可合并一轮。已明确确认的内容直接复用。
- 原作是无状态访谈；持续承诺由 dot 按用户批准的范围复用原有任务记录，普通小请求在当前对话闭环。
- 事实调查与交流按当前有效权限推进。用户最新明确反馈优先，新增权限、敏感分享和用户亲验按各自要求落实。

## 手机提问示例

🔵 待决策

1. 第一版最先要让谁完成什么动作？
A 推荐：先跑通一个真实使用者的完整流程，便于验收
B 先搭基础能力，再选择业务流程
也可以直接描述最近一次实际使用场景

若用户只回答“好用就行”，沿1继续：
“1. 想先改善哪个具体动作？例如更快完成、减少遗漏，或更容易确认结果。你给一个实际例子，我们再定成功标准。”

## 收敛与确认

以证据和用户决定解决关键分支，用实验或明确风险处理覆盖仍需验证的假设。整理目标、验收、范围、重要取舍与待决事项，等用户明确确认后执行；复杂度较低、结果已明确的小请求直接完成并检查。

## 原源与版本

原作者：Matt Pocock
固定提交：c665c5559e8be56a12271a620ae44aa1ada535ed（2026-10-06）

- [grill-me 入口](https://github.com/mattpocock/skills/blob/c665c5559e8be56a12271a620ae44aa1ada535ed/skills/productivity/grill-me/SKILL.md)
- [grilling 核心方法](https://github.com/mattpocock/skills/blob/c665c5559e8be56a12271a620ae44aa1ada535ed/skills/productivity/grilling/SKILL.md)
- [原仓使用说明](https://github.com/mattpocock/skills/blob/c665c5559e8be56a12271a620ae44aa1ada535ed/docs/productivity/grill-me.md)
- [原仓许可](https://github.com/mattpocock/skills/blob/c665c5559e8be56a12271a620ae44aa1ada535ed/LICENSE)

该版本的 grill-me 是调用 grilling 的入口。本参考汉化核心方法，手机批次、稳定编号、反例验真、契约结构与任务记录属于 dot 适配。方法正文使用中文，下列原始许可保留版权及许可声明。

## 上游许可原文

MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
