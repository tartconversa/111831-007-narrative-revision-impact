# 叙事分类趋势分析

这个 Python 项目整理与“叙事分类趋势分析”有关的来源观察，并生成供研究人员复核的统计摘要。

分类口径按版本管理：观察记录其录入时的口径版本，口径调整通过相邻版本间的显式映射投影，拆分后的子类归属必须逐条复核，证据不足的观察保持“未决”并在比较结果与报告中披露缺口。详见 [docs/analysis-notes.md](docs/analysis-notes.md) 与 [docs/taxonomy-guide.md](docs/taxonomy-guide.md)。

## 开发

需要 Python 3.11 或更高版本。安装开发依赖：`python -m pip install -e .`。

运行测试：`python -m unittest discover -s tests -v`。
构建发行包：`python -m build`。
