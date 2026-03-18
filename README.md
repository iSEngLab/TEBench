# 测试演化数据集构建工具

用于从Java Maven项目的Git历史中自动构建测试演化数据集的工具。

## 功能特性

### 1. 项目分析 (analysis.py) 【新增】
分析Java项目，筛选和分类过时测试用例：
- ✅ 筛选同时修改测试代码和源代码的commits
- ✅ 对commits进行三种类型分类：
  - **Type1 (执行出错)**: V-0.5编译或测试失败
- **Type2 (覆盖率差距)**: V0变更方法覆盖率（行/分支）相比V-0.5提升（旧测试覆盖不足）
  - **Type3 (适应性调整)**: 不属于Type1和Type2
- ✅ 支持并发处理和断点续传
- ✅ 生成详细的JSON和Markdown报告
- ✅ 使用临时worktree，不污染原始仓库

### 2. 初始筛选 (main.py)
从Git历史中筛选符合条件的commits：
- ✅ 同时修改测试代码和源代码
- ✅ 方法级别的变更检测
- ✅ 构建成功验证
- ✅ 覆盖率阈值过滤 (≥50%)
- ✅ 支持并行处理和断点续传

### 3. 过滤版本生成 (generate_filtered_versions.py)
为每个合格的commit生成 V-0.5 和 T-0.5 版本：
- ✅ V-0.5：过滤掉测试代码变更，仅保留源代码变更
- ✅ T-0.5：过滤掉源代码变更，仅保留测试代码变更
- ✅ 自动创建Git分支（`filtered/*` 与 `test-only/*`）
- ✅ 编译验证
- ✅ 同时模拟"缺少测试更新"和"仅测试更新"的真实场景

### 4. 识别评估 (identify_evaluation/) 【新增】
评估过时测试用例识别方法的效果：
- ✅ 从GT commit中提取测试变更（新增/修改/删除）
- ✅ 方法级别的精确识别
- ✅ 与识别方法结果对比，计算Precision/Recall/F1
- ✅ 按项目和类型统计分析
- ✅ 生成详细的比较报告

### 5. 更新评估 (update_evaluation/) 【原 evaluation/】
评估过时测试用例更新方法的效果：
- ✅ 创建隔离的评估worktree
- ✅ 可执行性评估（编译、测试通过率）
- ✅ 覆盖增量重合度评估
- ✅ 改动量评估（修改的测试方法数）
- ✅ 综合得分计算
- ✅ 批量评估支持

## 版本关系

每个成功处理的commit包含4个版本：

```
V-1 (父commit)
  ├──> V-0.5 (仅源代码变更)
  └──> T-0.5 (仅测试代码变更)
                 └──> V0 (完整版本)
```

- **V-1**: 父commit，作为基准版本
- **V-0.5**: 过滤版本，只包含源代码变更（测试代码未更新）
- **T-0.5**: 测试版本，只包含测试代码变更（源代码未更新）
- **V0**: 完整版本，包含所有变更（源代码+测试代码）

## 分析工具使用 (analysis.py)

### 基本用法

```bash
# 分析单个项目
python analysis.py --project /path/to/commons-csv

# 分析多个项目
python analysis.py --projects-dir /path/to/defects4j-projects

# 指定输出目录和并发数
python analysis.py --project /path/to/project --output ./output --workers 8

# 快速扫描模式（只做文件级筛选）
python analysis.py --project /path/to/project --phase quick

# 方法分析模式（到方法级分析，不执行测试）
python analysis.py --project /path/to/project --phase method

# 完整分析模式（默认）
python analysis.py --project /path/to/project --phase full

# 断点续传
python analysis.py --project /path/to/project --resume

# 日期过滤
python analysis.py --project /path/to/project --since 2020-01-01

# 采样分析（快速测试）
python analysis.py --project /path/to/project --sample 10
```

### 输出结构

```
output/analysis/
├── {project_name}/
│   ├── analysis_result.json    # 完整分析结果
│   ├── summary.md              # Markdown报告
│   └── commits/                # 每个commit的详细信息
│       ├── {commit_hash}.json
│       ├── {commit_hash}/       # 可视化辅助文件
│       │   ├── summary.md        # commit级摘要（执行/覆盖率）
│       │   ├── full.diff         # 完整diff
│       │   ├── source_only.diff  # 仅源代码diff
│       │   └── test_only.diff    # 仅测试diff
│       └── ...
└── global_summary/             # 全局汇总（多项目时）
    ├── all_projects_stats.json
    └── analysis_report.md
```

### 三种类型分类

| 类型 | 检测条件 | 含义 |
|------|----------|------|
| Type1 (执行出错) | V-0.5编译失败或测试失败 | 旧测试无法在新代码上正常执行 |
| Type2 (覆盖率差距) | V0变更方法覆盖率（行/分支）比V-0.5提升 | 旧测试对新代码的覆盖不足 |
| Type3 (适应性调整) | 不属于Type1和Type2 | 测试需要适应性修改 |

### 场景矩阵

| 场景 | V-0.5 | T-0.5 | 典型分类 |
|------|-------|-------|----------|
| A | ❌失败 | ❌失败 | Type1 (高置信度) |
| B | ❌失败 | ✅通过 | Type1 (中置信度) |
| C | ✅通过 | ❌失败 | Type2/Type3 |
| D | ✅通过 | ✅通过 | Type2/Type3 |

## 数据集统计

### Commons-CSV项目（示例）
- 统计以 `output/filtered_dataset.json` 中的 `metadata` 为准
- 元数据将分别统计 `source_only`（V-0.5）与 `test_only`（T-0.5）

### 成功案例示例

**案例 1: d93c4940（hash 以实际输出为准）**
```
V-1:  c36d6cde
V-0.5: ab0f7745 (分支: filtered/d93c4940)
T-0.5: 5e5d1c2a (分支: test-only/d93c4940)
V0:   d93c4940
日期: 2025-03-15
消息: CSVParser.parse(*) methods with a null Charset maps to...
```

## 目录结构

```
TUBench/
├── config.py                           # 配置文件
├── main.py                             # 初始筛选流程
├── analysis.py                         # 项目分析入口【新增】
├── generate_filtered_versions.py      # 生成V-0.5/T-0.5
├── evaluate.py                         # 更新评估入口【新增】
├── extract_gt_changes.py               # GT测试变更提取【新增】
├── compare_identification.py           # 识别结果比较【新增】
├── test_diff_filter.py                 # 测试diff过滤功能
├── requirements.txt                    # Python依赖
├── modules/                            # 核心模块
│   ├── git_analyzer.py                 # Git操作
│   ├── code_analyzer.py                # Java代码解析
│   ├── change_detector.py              # 变更检测
│   ├── maven_executor.py               # Maven执行
│   ├── coverage_analyzer.py            # 覆盖率分析
│   ├── commit_filter.py                # Commit过滤
│   ├── dataset_generator.py            # 数据集生成
│   ├── diff_filter.py                  # Diff过滤
│   ├── filtered_version_generator.py   # 过滤/测试版本生成
│   ├── isolated_executor.py            # 隔离执行器【新增】
│   └── commit_classifier.py            # Commit分类器【新增】
├── analysis/                           # 分析模块【新增】
│   ├── __init__.py
│   ├── project_analyzer.py             # 项目���分析
│   ├── commit_analyzer.py              # Commit级分析
│   ├── cache_manager.py                # 缓存管理
│   └── report_generator.py             # 报告生成
├── identify_evaluation/                # 识别评估模块【新增】
│   ├── __init__.py
│   ├── gt_extractor.py                 # GT测试变更提取器
│   ├── README.md                       # 模块文档
│   ├── example_predicted_format.json   # 识别结果格式示例
│   └── gt_changes_all.json             # GT变更数据（生成）
├── update_evaluation/                  # 更新评估模块【原evaluation/】
│   ├── __init__.py
│   ├── evaluation_orchestrator.py      # 评估编排器
│   ├── worktree_manager.py             # Worktree管理
│   ├── executability_evaluator.py      # 可执行性评估
│   ├── coverage_increment_analyzer.py  # 覆盖增量分析
│   ├── changed_method_extractor.py     # 变更方法提取
│   └── modification_effort_calculator.py # 改动量计算
├── utils/                              # 工具模块
│   └── logger.py                       # 日志工具
├── docs/                               # 文档【新增】
│   └── ANALYSIS_TOOL_SPEC.md           # 分析工具需求文档
└── output/                             # 输出目录
    ├── dataset.json                    # 初始筛选结果
    ├── filtered_dataset.json           # 最终数据集（含V-0.5/T-0.5）
    ├── analysis/                       # 分析结果【新增】
    └── *.log                            # 日志文件
```

## 使用方法

### 1. 配置

编辑 `config.py` 设置仓库路径和过滤条件：

```python
class Config:
    # Git仓库路径
    REPO_PATH = "/path/to/your/java-project"
    
    # 日期过滤
    DATE_FILTER = "2016-01-01"
    
    # 覆盖率阈值（50%）
    COVERAGE_THRESHOLD = 0.5
```

### 2. 初始筛选

```bash
python main.py
```

生成 `output/dataset.json`，包含所有符合条件的commits。

### 3. 生成过滤版本

```bash
python generate_filtered_versions.py output/dataset.json output/filtered_dataset.json
```

为每个合格的commit生成 V-0.5 和 T-0.5 版本，保存到 `output/filtered_dataset.json`。

### 4. 项目分析（新增）

```bash
# 分析单个项目
python analysis.py --project /path/to/commons-csv

# 分析defects4j所有项目
python analysis.py --projects-dir /path/to/defects4j-projects --workers 4
```

分析项目并分类commits，生成 `output/analysis/` 下的报告。

### 5. 识别评估（新增）

```bash
# 提取Ground Truth测试变更
python extract_gt_changes.py \
  --input /path/to/worktree_records.csv \
  --output identify_evaluation/gt_changes_all.json

# 比较识别方法结果与GT
python compare_identification.py \
  --gt identify_evaluation/gt_changes_all.json \
  --predicted your_method_results.json \
  --output identify_evaluation/comparison_results.json

python evaluate_user_identification.py \
  --input /Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.csv \
  --gt identify_evaluation/gt_changes_all.json \
  --output identify_evaluation/user_identification_results.json
```

详细使用说明见 `identify_evaluation/README.md`

### 6. 更新评估（新增）

```bash
# 准备评估环境
python evaluate.py prepare \
  --project /path/to/commons-csv \
  --commit abc123

# 执行评估
python evaluate.py run \
  --worktree /path/to/worktree \
  --gt-commit abc123 \
  --output results.json

# 批量评估
python evaluate.py run-batch \
  --input eval_tasks.json \
  --output eval_results.json
```

### 7. 测试diff过滤功能

```bash
python test_diff_filter.py
```

### 8. 查看结果

```bash
# 查看生成的Git分支
cd /path/to/your/java-project
git branch | grep "filtered/"
git branch | grep "test-only/"

# 查看某个过滤分支
git log filtered/d93c4940
git log test-only/d93c4940

# 对比V-0.5和V0的差异（应主要是测试变更）
git diff ab0f7745 d93c4940

# 对比V-1和T-0.5的差异（应主要是测试变更）
git diff c36d6cde 5e5d1c2a

# 对比T-0.5和V0的差异（应主要是源代码变更）
git diff 5e5d1c2a d93c4940
```

## 数据集格式

### filtered_dataset.json 结构（示例，数值仅示意）

```json
{
  "metadata": {
    "source_dataset": "output/dataset.json",
    "total_processed": 130,
    "source_only": {
      "successful": 125,
      "failed": {"apply_patch": 0, "compilation": 5, "other": 0},
      "success_rate": "96.15%"
    },
    "test_only": {
      "successful": 123,
      "failed": {"apply_patch": 0, "compilation": 7, "other": 0},
      "success_rate": "94.62%"
    }
  },
  "commits": [
    {
      "original_commit": "d93c4940...",
      "parent_commit": "c36d6cde...",
      "author": "Gary Gregory",
      "date": "2025-03-15 04:29:53",
      "message": "...",
      "changed_files": {
        "test_files": ["..."],
        "source_files": ["..."],
        "other_files": []
      },
      "changed_methods": {
        "test_methods": [...],
        "source_methods": [...]
      },
      "coverage_analysis": {...},
      "filtered_version": {
        "success": true,
        "filtered_commit_hash": "ab0f7745...",
        "branch_name": "filtered/d93c4940"
      },
      "test_only_version": {
        "success": true,
        "test_only_commit_hash": "5e5d1c2a...",
        "branch_name": "test-only/d93c4940"
      }
    }
  ]
}
```

### analysis_result.json 结构（新增）

```json
{
  "project_name": "commons-csv",
  "analysis_time": "2025-01-15T10:30:00",
  "statistics": {
    "total_commits": 1500,
    "qualified_commits": 120,
    "type1_count": 45,
    "type2_count": 30,
    "type3_count": 45
  },
  "commits": [
    {
      "commit_hash": "abc123...",
      "parent_hash": "def456...",
      "classification": {
        "type": "type1",
        "confidence": "high",
        "scenario": "B",
        "details": {
          "v_half_result": {"compile": false, "error": "..."},
          "t_half_result": {"compile": true, "test_pass": true}
        }
      }
    }
  ]
}
```

## 技术实现

### Diff过滤算法

使用正则表达式解析Git diff：

1. 按文件分割diff（通过 `diff --git` 标记）
2. 根据文件路径判断是否为测试文件
3. 分离源代码diff和测试代码diff
4. 生成只包含源代码变更 / 只包含测试代码变更的patch

### 版本生成流程

1. 从父commit创建新分支
2. 应用过滤后的patch（只含源代码变更 / 只含测试代码变更）
3. 提交变更，生成 V-0.5 / T-0.5 版本
4. 编译验证
5. 记录分支信息和commit hash

### 分析流程（新增）

1. **快速扫描阶段**: 扫描Git历史，筛选同时修改测试和源代码的commits
2. **方法分析阶段**: 解析Java代码，检测方法级变更
3. **执行阶段**: 在隔离worktree中构建和测试各版本
4. **分类阶段**: 根据执行结果分类commits
5. **报告阶段**: 生成JSON和Markdown报告

## 依赖项

```
GitPython==3.1.40
javalang==0.13.0
lxml==5.1.0
```

注：已移除 `unidiff` 依赖，改用自定义正则表达式解析。

## 注意事项

1. **仓库状态**: 运行前确保Git仓库clean（无未提交的变更）
2. **JDK版本**: 确保安装了兼容的JDK版本
3. **Maven**: 需要Maven构建工具
4. **磁盘空间**: 生成的分支会占用额外空间
5. **并行处理**: main.py支持并行，generate_filtered_versions.py串行处理
6. **Worktree**: analysis.py使用临时worktree，自动清理，不污染原仓库

## 失败处理

### 编译失败的原因

常见编译失败原因：
- JDK版本不兼容（如项目需要Java 6，但系统只有Java 8+）
- Maven clean失败（文件被占用）
- 依赖下载失败

失败的commits会被跳过，不影响其他commits的处理。

### 清理分支

如需清理生成的分支：

```bash
cd /path/to/your/java-project
git branch | grep "filtered/" | xargs git branch -D
git branch | grep "test-only/" | xargs git branch -D
```

## 实验场景

此数据集可用于以下研究：

1. **测试演化研究**: 研究测试用例如何随源代码演化
2. **测试生成**: 基于V-0.5生成测试，与V0对比
3. **测试修复**: 检测和修复不完整的测试更新
4. **覆盖率分析**: 分析代码变更对覆盖率的影响
5. **过时测试分类**: 分析三种类型过时测试的分布和特征
6. **过时测试识别**: 评估识别过时测试用例的方法效果【新增】
7. **过时测试更新**: 评估自动更新过时测试用例的方法效果【新增】

## 项目状态

✅ **已完成**
- 初始筛选流程
- Diff过滤功能
- 过滤/测试版本生成
- 编译验证
- 数据集导出
- 项目分析工具（新增）
- 三种类型分类（新增）

🎉 **测试结果**: 成功率以 `filtered_dataset.json` 的 `metadata` 为准

## 作者

测试演化数据集构建工具 - 2025
