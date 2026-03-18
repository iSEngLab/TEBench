"""
评估协调器 - 协调整个评估流程
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

from git import Repo

from config import AnalysisConfig
from utils.logger import get_logger
from .worktree_manager import WorktreeManager
from .changed_method_extractor import ChangedMethodExtractor
from .executability_evaluator import ExecutabilityEvaluator
from .coverage_increment_analyzer import CoverageIncrementAnalyzer
from .modification_effort_calculator import ModificationEffortCalculator

logger = get_logger()


class EvaluationOrchestrator:
    """评估协调器 - 协调整个评估流程"""

    def __init__(self, repo_path: str, cache_dir: str = None):
        """
        初始化评估协调器

        Args:
            repo_path: 仓库路径
            cache_dir: 缓存目录（用于读取分析结果）
        """
        self.repo_path = repo_path
        self.project_name = os.path.basename(repo_path)
        self.repo = Repo(repo_path)
        self.cache_dir = cache_dir or AnalysisConfig.CACHE_DIR

        # 初始化各个组件
        self.worktree_manager = WorktreeManager(repo_path)
        self.method_extractor = ChangedMethodExtractor(repo_path)
        self.executability_evaluator = ExecutabilityEvaluator()
        self.coverage_analyzer = CoverageIncrementAnalyzer()
        self.effort_calculator = ModificationEffortCalculator(repo_path)

    def prepare_evaluation(self, gt_commit: str) -> Dict[str, Any]:
        """
        准备评估环境

        Args:
            gt_commit: GT commit hash

        Returns:
            dict: 准备结果
        """
        return self.worktree_manager.prepare_evaluation_worktree(
            gt_commit, self.cache_dir
        )

    def run_evaluation(self, worktree_path: str, gt_commit: str) -> Dict[str, Any]:
        """
        执行评估（只读操作，不修改git状态）

        Args:
            worktree_path: 用户修改后的worktree路径
            gt_commit: GT commit hash

        Returns:
            dict: 评估结果
        """
        result = {
            'success': False,
            'project': self.project_name,
            'gt_commit': gt_commit,
            'evaluation': {
                'executability': {},
                'coverage_analysis': {},
                'coverage_overlap': {},
                'modification_effort': {}
            },
            'error': None,
            'timestamp': datetime.now().isoformat()
        }

        try:
            # 1. 获取worktree信息（从git解析）
            metadata = self.worktree_manager.get_worktree_info(worktree_path)
            if not metadata:
                result['error'] = "无法获取worktree信息"
                return result

            v05_commit = metadata.get('v05_commit')
            result['v05_commit'] = v05_commit
            result['task_id'] = metadata.get('task_id')

            # 2. 分析用户的修改（不提交，只分析）
            user_changes = self._analyze_user_changes(worktree_path, v05_commit, gt_commit)
            result['user_changes'] = user_changes

            if not user_changes.get('has_changes'):
                result['error'] = "没有检测到任何修改"
                return result

            # 3. 可执行性评估
            logger.info("执行可执行性评估...")

            # 计算 User 和 GT 修改的测试方法的并集
            user_test_methods = user_changes.get('test_methods', [])
            gt_test_methods = user_changes.get('gt_test_methods', [])
            all_test_methods = self._merge_test_methods(user_test_methods, gt_test_methods)

            logger.debug(f"User修改测试方法: {len(user_test_methods)}, GT修改测试方法: {len(gt_test_methods)}, 并集: {len(all_test_methods)}")

            executability = self.executability_evaluator.evaluate(
                worktree_path,
                all_test_methods  # 使用并集
            )
            result['evaluation']['executability'] = executability

            # 如果编译失败，跳过后续评估
            if not executability.get('compile_success'):
                result['error'] = "编译失败，跳过覆盖率和改动量评估"
                return result

            # 4. 覆盖率分析（支持两种模式）
            logger.info("执行覆盖率分析...")
            source_methods = user_changes.get('gt_source_methods', [])

            # 覆盖率评估模式切换：
            # - 'increment': 原有覆盖增量逻辑（V-0.5 / User / GT 三版本）
            # - 'direct': 新逻辑（仅执行 User 和 GT 的变更测试，并比较变更被测函数覆盖）
            coverage_mode = 'direct'

            coverage_result = self._analyze_coverage_with_worktrees(
                v05_commit,
                gt_commit,
                worktree_path,
                source_methods,
                all_test_methods,
                mode=coverage_mode
            )
            # 新字段（推荐）
            result['evaluation']['coverage_analysis'] = coverage_result
            # 兼容旧字段（避免外部脚本断裂）
            result['evaluation']['coverage_overlap'] = coverage_result
            result['coverage_mode'] = coverage_mode

            # 5. 改动量计算（支持两种模式）
            logger.info("计算改动量...")
            effort_result = self._calculate_modification_effort(
                worktree_path,
                gt_commit,
                v05_commit,
                all_test_methods,
                metric='direction'  # 当前使用最小改动模式；如需方向一致性评估，可改为 metric='direction'
            )
            result['evaluation']['modification_effort'] = effort_result

            # 6. 计算综合分数
            result['scores'] = self._calculate_scores(result['evaluation'])

            result['success'] = True

        except Exception as e:
            logger.error(f"评估失败: {e}")
            result['error'] = str(e)

        return result

    def _analyze_user_changes(self, worktree_path: str, v05_commit: str, gt_commit: str) -> Dict[str, Any]:
        """
        分析用户的修改（不提交，只分析working tree中的改动）

        Returns:
            dict: {
                'has_changes': bool,
                'changed_files': list,
                'test_methods': list,  # 用户修改的测试方法
                'gt_source_methods': list,  # GT中变更的源代码方法
                'common_methods': list  # 用户和GT都修改的测试方法
            }
        """
        from git import Repo

        result = {
            'has_changes': False,
            'changed_files': [],
            'test_methods': [],
            'gt_source_methods': [],
            'common_methods': []
        }

        try:
            worktree_repo = Repo(worktree_path)

            # 检查是否有修改（staged + unstaged + untracked）
            changed_files = []

            # staged changes
            for item in worktree_repo.index.diff('HEAD'):
                changed_files.append(item.a_path or item.b_path)

            # unstaged changes
            for item in worktree_repo.index.diff(None):
                if item.a_path not in changed_files:
                    changed_files.append(item.a_path)

            # untracked files
            for f in worktree_repo.untracked_files:
                if f not in changed_files:
                    changed_files.append(f)

            result['changed_files'] = changed_files
            result['has_changes'] = len(changed_files) > 0

            if not result['has_changes']:
                return result

            # 提取用户修改的测试方法（从working tree分析）
            user_test_methods = self._extract_user_test_methods(worktree_path, v05_commit)
            result['test_methods'] = user_test_methods

            # 提取GT的源代码方法和测试方法
            # 注意：源代码变更应该相对于 V-0.5 的 parent（即原始版本），而不是 V-0.5 本身
            # 因为 V-0.5 已经包含了源代码变更
            v05_parent = self.repo.commit(v05_commit).parents[0].hexsha if self.repo.commit(v05_commit).parents else v05_commit
            gt_source_methods = self.method_extractor._extract_changed_source_methods(gt_commit, v05_parent)
            gt_test_methods = self.method_extractor._extract_changed_test_methods(gt_commit, v05_commit)
            result['gt_source_methods'] = gt_source_methods
            result['gt_test_methods'] = gt_test_methods  # 保存GT测试方法用于可执行性评估

            logger.debug(f"GT源代码变更方法: {len(gt_source_methods)} 个 (相对于 {v05_parent[:8]})")
            for m in gt_source_methods:
                logger.debug(f"  - {m.get('class')}.{m.get('method')} ({m.get('file')}:{m.get('start_line')}-{m.get('end_line')})")

            # 计算共同修改的测试方法
            user_keys = {(m.get('file'), m.get('class'), m.get('method')) for m in user_test_methods}
            gt_keys = {(m.get('file'), m.get('class'), m.get('method')) for m in gt_test_methods}
            common_keys = user_keys & gt_keys

            # 构建common_methods，包含两边的行号信息
            user_methods_map = {(m.get('file'), m.get('class'), m.get('method')): m for m in user_test_methods}
            gt_methods_map = {(m.get('file'), m.get('class'), m.get('method')): m for m in gt_test_methods}

            for key in common_keys:
                user_m = user_methods_map.get(key)
                gt_m = gt_methods_map.get(key)
                if user_m and gt_m:
                    result['common_methods'].append({
                        'file': key[0],
                        'class': key[1],
                        'method': key[2],
                        'package': user_m.get('package', ''),
                        'user_start_line': user_m.get('start_line'),
                        'user_end_line': user_m.get('end_line'),
                        'gt_start_line': gt_m.get('start_line'),
                        'gt_end_line': gt_m.get('end_line')
                    })

            logger.debug(f"用户修改: {len(changed_files)} 文件, {len(user_test_methods)} 测试方法, "
                        f"{len(result['common_methods'])} 共同方法")

        except Exception as e:
            logger.error(f"分析用户修改失败: {e}")

        return result

    def _merge_test_methods(self, user_methods: List[Dict], gt_methods: List[Dict]) -> List[Dict]:
        """
        合并 User 和 GT 修改的测试方法（并集）

        Args:
            user_methods: User 修改的测试方法
            gt_methods: GT 修改的测试方法

        Returns:
            list: 合并后的测试方法列表（去重）
        """
        merged = {}

        # 添加 User 方法
        for m in user_methods:
            key = (m.get('file'), m.get('class'), m.get('method'))
            merged[key] = m

        # 添加 GT 方法（如果不存在）
        for m in gt_methods:
            key = (m.get('file'), m.get('class'), m.get('method'))
            if key not in merged:
                merged[key] = m

        return list(merged.values())

    def _extract_user_test_methods(self, worktree_path: str, v05_commit: str) -> List[Dict]:
        """
        从worktree的working tree中提取用户修改的测试方法
        """
        from git import Repo
        from modules.code_analyzer import CodeAnalyzer
        from modules.change_detector import ChangeDetector
        from config import Config

        methods = []
        code_analyzer = CodeAnalyzer()
        change_detector = ChangeDetector()

        try:
            worktree_repo = Repo(worktree_path)

            # 获取相对于HEAD的diff（包含staged和unstaged）
            diff_text = worktree_repo.git.diff('HEAD')

            if not diff_text:
                return methods

            # 解析diff
            parsed = change_detector.parse_diff(diff_text)

            for entry in parsed:
                file_path = entry.get('file')
                if not file_path or not file_path.endswith('.java'):
                    continue

                # 只处理测试文件
                if not any(pattern in file_path for pattern in Config.TEST_PATH_PATTERNS):
                    continue

                # 读取当前working tree中的文件内容
                full_path = os.path.join(worktree_path, file_path)
                if not os.path.exists(full_path):
                    continue

                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # 解析方法
                classes_info = code_analyzer.parse_java_file(content)
                package = code_analyzer.get_package_name(content)

                all_methods = []
                for cls in classes_info.get('classes', []):
                    for m in cls.get('methods', []):
                        all_methods.append({
                            'class': cls.get('name'),
                            'method': m.get('name'),
                            'parameters': m.get('parameters', []),
                            'start_line': m.get('start_line', 0),
                            'end_line': m.get('end_line', 0),
                            'package': package,
                            'file': file_path
                        })

                # 找出变更的方法
                for change in entry.get('changes', []):
                    for line_no in change.get('added_lines', []):
                        for m in all_methods:
                            if m['start_line'] <= line_no <= m['end_line']:
                                key = (m['file'], m['class'], m['method'])
                                if not any((em['file'], em['class'], em['method']) == key for em in methods):
                                    methods.append(m)
                                break

            # 解析数据提供方法（@MethodSource 引用的方法）→ 替换为实际的参数化测试方法
            content_map = {}
            for m in methods:
                fp = m.get('file', '')
                if fp and fp not in content_map:
                    full_path = os.path.join(worktree_path, fp)
                    if os.path.exists(full_path):
                        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f_:
                            content_map[fp] = f_.read()
            methods = self.method_extractor._resolve_data_providers(methods, content_map)

        except Exception as e:
            logger.debug(f"提取用户测试方法失败: {e}")

        return methods

    def _find_method_in_commit(self, commit_hash: str, file_path: str,
                               class_name: str, method_name: str) -> Optional[Dict]:
        """
        在指定commit中按方法名查找方法（返回该commit中的正确行号）

        Args:
            commit_hash: commit hash
            file_path: 文件路径
            class_name: 类名
            method_name: 方法名

        Returns:
            dict: 方法信息（含正确行号），未找到返回 None
        """
        try:
            content = self.method_extractor._get_file_content(commit_hash, file_path)
            if not content:
                return None

            all_methods = self.method_extractor._extract_all_methods(content, file_path)
            for m in all_methods:
                if m.get('class') == class_name and m.get('method') == method_name:
                    return m
            return None
        except Exception as e:
            logger.debug(f"在commit {commit_hash[:8]} 中查找方法 {class_name}.{method_name} 失败: {e}")
            return None

    def _find_method_in_worktree(self, worktree_path: str, file_path: str,
                                  class_name: str, method_name: str) -> Optional[Dict]:
        """
        在worktree文件系统中按方法名查找方法（返回正确行号）

        Args:
            worktree_path: worktree路径
            file_path: 相对文件路径
            class_name: 类名
            method_name: 方法名

        Returns:
            dict: 方法信息（含正确行号），未找到返回 None
        """
        try:
            full_path = os.path.join(worktree_path, file_path)
            if not os.path.exists(full_path):
                return None

            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            all_methods = self.method_extractor._extract_all_methods(content, file_path)
            for m in all_methods:
                if m.get('class') == class_name and m.get('method') == method_name:
                    return m
            return None
        except Exception as e:
            logger.debug(f"在worktree中查找方法 {class_name}.{method_name} 失败: {e}")
            return None

    def _calculate_modification_effort(self,
                                        worktree_path: str,
                                        gt_commit: str,
                                        v05_commit: str,
                                        all_test_methods: List[Dict],
                                        metric: str = 'direction') -> Dict[str, Any]:
        """
        计算改动量得分（支持两种评估方式）

        基于 User+GT 测试方法并集计算。
        对每个方法按名称分别在 worktree（User版本）和目标基准 commit 中查找并提取代码，
        然后计算 token Jaccard。

        metric='direction':
            direction_score = Jaccard(User_tokens, GT_tokens)
            得分越高表示越接近 GT。

        metric='effort':
            effort_score = Jaccard(V05_tokens, User_tokens)
            得分越高表示改动越少（越接近 V-0.5）。

        说明：统一返回 average_score，供 _calculate_scores 读取。
        """
        if metric not in ('direction', 'effort'):
            logger.warning(f"未知改动量评估模式: {metric}，回退为 direction")
            metric = 'direction'

        result = {
            'method_details': [],
            'metric': metric,
            'average_score': 0.0,
            'direction_score': 0.0,
            'effort_score': 0.0,
            'total_methods': len(all_test_methods),
            'error': None
        }

        if not all_test_methods:
            # 空方法集合时，direction 与 effort 都按 0.0 处理
            result['average_score'] = 0.0
            return result

        try:
            score_sum = 0.0
            valid_count = 0

            for method in all_test_methods:
                file_path = method.get('file')
                class_name = method.get('class')
                method_name = method.get('method')

                # 按方法名在 worktree 中查找用户版本
                user_method = self._find_method_in_worktree(
                    worktree_path, file_path, class_name, method_name
                )
                if user_method:
                    full_path = os.path.join(worktree_path, file_path)
                    with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    lines = content.split('\n')
                    start = user_method.get('start_line', 0)
                    end = user_method.get('end_line', 0)
                    if start > 0 and end > 0 and end <= len(lines):
                        user_code = '\n'.join(lines[start-1:end])
                    else:
                        user_code = ""
                else:
                    user_code = ""

                # 根据评估模式选择基准代码
                user_tokens = self.effort_calculator._tokenize(user_code) if user_code else []
                gt_tokens = []
                v05_tokens = []

                if metric == 'direction':
                    gt_method = self._find_method_in_commit(
                        gt_commit, file_path, class_name, method_name
                    )
                    if gt_method:
                        gt_code = self.effort_calculator._extract_method_code(
                            gt_commit, file_path,
                            gt_method.get('start_line'),
                            gt_method.get('end_line')
                        ) or ""
                    else:
                        gt_code = ""

                    gt_tokens = self.effort_calculator._tokenize(gt_code) if gt_code else []
                    score = self.effort_calculator._jaccard_similarity(user_tokens, gt_tokens)

                    logger.debug(f"方向得分计算 - {class_name}.{method_name}: {score:.4f}")
                else:
                    v05_method = self._find_method_in_commit(
                        v05_commit, file_path, class_name, method_name
                    )
                    if v05_method:
                        v05_code = self.effort_calculator._extract_method_code(
                            v05_commit, file_path,
                            v05_method.get('start_line'),
                            v05_method.get('end_line')
                        ) or ""
                    else:
                        v05_code = ""

                    v05_tokens = self.effort_calculator._tokenize(v05_code) if v05_code else []
                    score = self.effort_calculator._jaccard_similarity(v05_tokens, user_tokens)

                    logger.debug(f"改动量得分计算 - {class_name}.{method_name}: {score:.4f}")

                result['method_details'].append({
                    'class': class_name,
                    'method': method_name,
                    'file': file_path,
                    'metric': metric,
                    'v05_tokens': len(v05_tokens),
                    'gt_tokens': len(gt_tokens),
                    'user_tokens': len(user_tokens),
                    'in_user': user_method is not None,
                    'score': score
                })

                score_sum += score
                valid_count += 1

            if valid_count > 0:
                result['average_score'] = score_sum / valid_count

            # 兼容输出：按当前模式同步到对应字段
            if metric == 'direction':
                result['direction_score'] = result['average_score']
            else:
                result['effort_score'] = result['average_score']

        except Exception as e:
            logger.error(f"计算改动量得分失败: {e}")
            result['error'] = str(e)

        return result

    def _calculate_scores(self, evaluation: Dict) -> Dict[str, float]:
        """
        计算综合分数

        公式：
        - 如果不可执行: score = 0
        - 如果GT无覆盖增量: score = 改动量得分（不计入覆盖率）
        - 否则: score = 0.6 × 覆盖增量重合度 + 0.4 × 改动量得分
        """
        scores = {
            'executability': 0.0,
            'coverage_overlap': 0.0,
            'modification_score': 0.0,
            'overall': 0.0
        }

        # 可执行性（门槛条件）
        exec_eval = evaluation.get('executability', {})
        if exec_eval.get('compile_success'):
            scores['executability'] = 0.5
            if exec_eval.get('test_success'):
                scores['executability'] = 1.0

        # 覆盖率得分（优先读取新字段，兼容旧字段）
        cov_eval = evaluation.get('coverage_analysis') or evaluation.get('coverage_overlap', {})
        line_overlap = cov_eval.get('line_overlap_ratio', 0)
        branch_overlap = cov_eval.get('branch_overlap_ratio', 0)
        gt_line_count = cov_eval.get('gt_increment_lines', 0)
        gt_branch_count = cov_eval.get('gt_increment_branches', 0)

        overlap_values = []
        if gt_line_count > 0:
            overlap_values.append(line_overlap)
        if gt_branch_count > 0:
            overlap_values.append(branch_overlap)

        if overlap_values:
            scores['coverage_overlap'] = sum(overlap_values) / len(overlap_values)
        else:
            scores['coverage_overlap'] = 0.0

        # 改动量得分（Jaccard(V05, User)，越高越好）
        effort_eval = evaluation.get('modification_effort', {})
        scores['modification_score'] = effort_eval.get('average_score', 0)

        # GT是否有覆盖增量
        gt_has_increment = cov_eval.get('gt_has_increment', True)

        # 综合分数
        # 不可执行则为0
        if scores['executability'] < 1.0:
            scores['overall'] = 0.0
        elif not gt_has_increment:
            # GT无覆盖增量，综合得分只用改动量
            scores['overall'] = scores['modification_score']
            logger.debug("GT无覆盖增量，综合得分仅使用改动量得分")
        else:
            scores['overall'] = (
                0.6 * scores['coverage_overlap'] +
                0.4 * scores['modification_score']
            )

        return scores

    def _analyze_coverage_with_worktrees(self,
                                         v05_commit: str,
                                         gt_commit: str,
                                         user_worktree: str,
                                         source_methods: List[Dict],
                                         test_methods: List[Dict] = None,
                                         mode: str = 'increment') -> Dict[str, Any]:
        """
        覆盖率分析调度入口。

        Args:
            mode:
                - 'increment': 使用覆盖增量分析（V-0.5 / User / GT）
                - 'direct': 使用GT基准直接比较（仅User / GT）
        """
        if mode == 'direct':
            return self._analyze_coverage_direct_with_worktrees(
                gt_commit, user_worktree, source_methods, test_methods
            )
        return self._analyze_coverage_increment_with_worktrees(
            v05_commit, gt_commit, user_worktree, source_methods, test_methods
        )

    def _analyze_coverage_increment_with_worktrees(self,
                                                   v05_commit: str,
                                                   gt_commit: str,
                                                   user_worktree: str,
                                                   source_methods: List[Dict],
                                                   test_methods: List[Dict] = None) -> Dict[str, Any]:
        """使用临时worktree执行覆盖增量分析（旧逻辑）。"""
        result = {
            'mode': 'increment',
            'line_overlap_ratio': 0.0,
            'branch_overlap_ratio': 0.0,
            'gt_increment_lines': 0,
            'gt_increment_branches': 0,
            'user_increment_lines': 0,
            'common_increment_lines': 0,
            'gt_has_increment': False,
            'error': None
        }

        v05_worktree = None
        gt_worktree = None

        try:
            # 创建V-0.5 worktree（直接基于 v05_commit，无需再应用 patch）
            v05_worktree = os.path.join(
                self.worktree_manager.eval_dir,
                f"{self.project_name}_v05_temp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
            self.repo.git.worktree('add', '--detach', v05_worktree, v05_commit)

            # 创建GT worktree
            gt_worktree = os.path.join(
                self.worktree_manager.eval_dir,
                f"{self.project_name}_gt_temp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
            self.repo.git.worktree('add', '--detach', gt_worktree, gt_commit)

            # 分析覆盖增量
            coverage_result = self.coverage_analyzer.analyze(
                v05_worktree, user_worktree, gt_worktree, source_methods, test_methods
            )

            result['line_overlap_ratio'] = coverage_result['overlap_ratio']['line']
            result['branch_overlap_ratio'] = coverage_result['overlap_ratio']['branch']
            result['gt_increment_lines'] = len(coverage_result['gt_increment']['lines'])
            result['gt_increment_branches'] = len(coverage_result['gt_increment']['branches'])
            result['user_increment_lines'] = len(coverage_result['user_increment']['lines'])
            result['common_increment_lines'] = len(
                coverage_result['gt_increment']['lines'] &
                coverage_result['user_increment']['lines']
            )
            result['gt_has_increment'] = coverage_result.get('gt_has_increment', False)

        except Exception as e:
            logger.error(f"覆盖增量分析失败: {e}")
            result['error'] = str(e)

        finally:
            # 清理临时worktree
            for wt in [v05_worktree, gt_worktree]:
                if wt and os.path.exists(wt):
                    try:
                        self.repo.git.worktree('remove', '--force', wt)
                    except:
                        import shutil
                        shutil.rmtree(wt, ignore_errors=True)

        return result

    def _analyze_coverage_direct_with_worktrees(self,
                                                gt_commit: str,
                                                user_worktree: str,
                                                source_methods: List[Dict],
                                                test_methods: List[Dict] = None) -> Dict[str, Any]:
        """
        使用临时worktree执行覆盖率直接比较（新逻辑）。

        特点：
        1. 不执行 V-0.5 测试
        2. 只在 User 与 GT 上执行变更测试方法
        3. 只统计本次 diff 中变更被测函数上的行/分支覆盖
        """
        result = {
            'mode': 'direct',
            'line_overlap_ratio': 0.0,
            'branch_overlap_ratio': 0.0,
            # 为兼容现有评分逻辑，沿用这些字段名，语义改为 GT 基准覆盖集合规模
            'gt_increment_lines': 0,
            'gt_increment_branches': 0,
            'user_increment_lines': 0,
            'common_increment_lines': 0,
            'gt_has_increment': False,
            'error': None
        }

        gt_worktree = None

        try:
            gt_worktree = os.path.join(
                self.worktree_manager.eval_dir,
                f"{self.project_name}_gt_temp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
            self.repo.git.worktree('add', '--detach', gt_worktree, gt_commit)

            coverage_result = self.coverage_analyzer.analyze_gt_baseline(
                user_worktree=user_worktree,
                gt_worktree=gt_worktree,
                source_methods=source_methods,
                test_methods=test_methods
            )

            result['line_overlap_ratio'] = coverage_result['overlap_ratio']['line']
            result['branch_overlap_ratio'] = coverage_result['overlap_ratio']['branch']
            result['gt_increment_lines'] = len(coverage_result['gt_reference']['lines'])
            result['gt_increment_branches'] = len(coverage_result['gt_reference']['branches'])
            result['user_increment_lines'] = len(coverage_result['user_covered']['lines'])
            result['common_increment_lines'] = len(
                coverage_result['gt_reference']['lines'] &
                coverage_result['user_covered']['lines']
            )
            result['gt_has_increment'] = coverage_result.get('gt_has_reference', False)

        except Exception as e:
            logger.error(f"覆盖率直接比较失败: {e}")
            result['error'] = str(e)

        finally:
            if gt_worktree and os.path.exists(gt_worktree):
                try:
                    self.repo.git.worktree('remove', '--force', gt_worktree)
                except:
                    import shutil
                    shutil.rmtree(gt_worktree, ignore_errors=True)

        return result

    def run_batch_evaluation(self,
                              tasks: List[Dict],
                              output_file: str = None) -> Dict[str, Any]:
        """
        批量执行评估

        Args:
            tasks: 评估任务列表 [{'project': str, 'gt_commit': str, 'user_worktree': str}]
            output_file: 输出文件路径

        Returns:
            dict: 批量评估结果
        """
        results = {
            'metadata': {
                'evaluation_time': datetime.now().isoformat(),
                'total_tasks': len(tasks),
                'successful': 0,
                'failed': 0
            },
            'results': []
        }

        for i, task in enumerate(tasks):
            logger.info(f"[{i+1}/{len(tasks)}] 评估任务...")

            try:
                worktree_path = task.get('user_worktree')
                gt_commit = task.get('gt_commit')

                if not worktree_path or not os.path.exists(worktree_path):
                    results['results'].append({
                        'gt_commit': gt_commit,
                        'status': 'failed',
                        'error': 'Worktree not found'
                    })
                    results['metadata']['failed'] += 1
                    continue

                if not gt_commit:
                    results['results'].append({
                        'status': 'failed',
                        'error': 'GT commit not specified'
                    })
                    results['metadata']['failed'] += 1
                    continue

                eval_result = self.run_evaluation(worktree_path, gt_commit)

                if eval_result.get('success'):
                    results['metadata']['successful'] += 1
                    eval_result['status'] = 'success'
                else:
                    results['metadata']['failed'] += 1
                    eval_result['status'] = 'failed'

                results['results'].append(eval_result)

            except Exception as e:
                logger.error(f"评估任务失败: {e}")
                results['results'].append({
                    'gt_commit': task.get('gt_commit'),
                    'status': 'failed',
                    'error': str(e)
                })
                results['metadata']['failed'] += 1

        # 保存结果
        if output_file:
            self._save_results(results, output_file)

        return results

    def _save_results(self, results: Dict, output_file: str):
        """保存评估结果"""
        # 转换set为list以便JSON序列化
        def convert_sets(obj):
            if isinstance(obj, set):
                return list(obj)
            elif isinstance(obj, dict):
                return {k: convert_sets(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_sets(item) for item in obj]
            return obj

        results = convert_sets(results)

        os.makedirs(os.path.dirname(output_file) or '.', exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        logger.info(f"评估结果已保存到: {output_file}")

    def cleanup(self, worktree_path: str = None, cleanup_all: bool = False):
        """
        清理worktree

        Args:
            worktree_path: 指定的worktree路径
            cleanup_all: 是否清理所有评估worktree
        """
        if cleanup_all:
            self.worktree_manager.cleanup_all_worktrees()
        elif worktree_path:
            self.worktree_manager.cleanup_worktree(worktree_path)
