#!/usr/bin/env python3
"""
测试脚本 - 验证Batch OpenCode Runner的设置和功能

使用方法:
python test_batch_opencode.py
"""

import os
import sys
import json

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from baseline.opencode.scripts.prompts import get_prompt_for_type, format_task_prompt


def test_prompt_generation():
    """测试prompt生成"""
    print("="*60)
    print("测试1: Prompt生成")
    print("="*60)

    # 测试Type1 prompt
    print("\n--- Type1 Prompt ---")
    type1_prompt = get_prompt_for_type('type1')
    print(f"Length: {len(type1_prompt)} characters")
    print(f"First 200 chars:\n{type1_prompt[:200]}...")

    # 测试Type2 prompt
    print("\n--- Type2 Prompt ---")
    type2_prompt = get_prompt_for_type('type2')
    print(f"Length: {len(type2_prompt)} characters")
    print(f"First 200 chars:\n{type2_prompt[:200]}...")

    # 测试完整格式化
    print("\n--- Formatted Prompt ---")
    formatted = format_task_prompt(
        commit_type='type1',
        project_name='commons-csv',
        additional_context='Test context'
    )
    print(f"Length: {len(formatted)} characters")
    print(f"First 300 chars:\n{formatted[:300]}...")

    print("\n✓ Prompt生成测试通过")


def test_opencode_availability():
    """测试OpenCode是否可用"""
    print("\n" + "="*60)
    print("测试2: OpenCode可用性")
    print("="*60)

    import subprocess

    try:
        result = subprocess.run(
            ['which', 'opencode'],
            capture_output=True,
            text=True,
            check=True
        )
        opencode_path = result.stdout.strip()
        print(f"✓ OpenCode found at: {opencode_path}")

        # 尝试获取版本
        try:
            version_result = subprocess.run(
                [opencode_path, '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            print(f"Version info: {version_result.stdout.strip()}")
        except:
            print("(Version info not available)")

        return True

    except subprocess.CalledProcessError:
        print("✗ OpenCode not found in PATH")
        print("Please install OpenCode or specify path with --opencode-path")
        return False


def test_pandas_availability():
    """测试pandas是否可用"""
    print("\n" + "="*60)
    print("测试3: Pandas可用性")
    print("="*60)

    try:
        import pandas as pd
        import openpyxl
        print(f"✓ pandas version: {pd.__version__}")
        print(f"✓ openpyxl version: {openpyxl.__version__}")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        print("Please install: pip install pandas openpyxl")
        return False


def test_worktree_records_file():
    """测试worktree_records.xlsx是否存在"""
    print("\n" + "="*60)
    print("测试4: Worktree Records文件")
    print("="*60)

    test_path = "/Users/mac/Desktop/TestUpdate/TUDataset/worktree_records.xlsx"

    if os.path.exists(test_path):
        print(f"✓ File exists: {test_path}")

        try:
            import pandas as pd
            df = pd.read_excel(test_path)
            print(f"✓ File readable, {len(df)} records")
            print(f"Columns: {df.columns.tolist()}")

            # 显示前几条记录
            print("\nFirst 3 records:")
            for idx, row in df.head(3).iterrows():
                print(f"  Task {row.get('task_id', idx+1)}: "
                      f"{row.get('project', 'N/A')} - "
                      f"{row.get('type', 'N/A')} - "
                      f"{row.get('status', 'N/A')}")

            # 统计
            print(f"\nStatus distribution:")
            for status, count in df['status'].value_counts().items():
                print(f"  {status}: {count}")

            return True

        except Exception as e:
            print(f"✗ Failed to read file: {e}")
            return False
    else:
        print(f"✗ File not found: {test_path}")
        print("Please run batch_worktree_builder.py first")
        return False


def test_worktree_directories():
    """测试worktree目录是否存在"""
    print("\n" + "="*60)
    print("测试5: Worktree目录")
    print("="*60)

    test_dir = "/Users/mac/Desktop/TestUpdate/TUDataset/worktrees"

    if os.path.exists(test_dir):
        print(f"✓ Directory exists: {test_dir}")

        # 列出前几个worktree
        worktrees = sorted([d for d in os.listdir(test_dir) if d.endswith('_eval')])
        print(f"✓ Found {len(worktrees)} worktrees")

        if worktrees:
            print("\nFirst 5 worktrees:")
            for wt in worktrees[:5]:
                wt_path = os.path.join(test_dir, wt)
                # 检查是否有pom.xml
                has_pom = os.path.exists(os.path.join(wt_path, 'pom.xml'))
                print(f"  {wt} {'(has pom.xml)' if has_pom else '(no pom.xml)'}")

        return True
    else:
        print(f"✗ Directory not found: {test_dir}")
        return False


def test_output_directory():
    """测试输出目录是否可创建"""
    print("\n" + "="*60)
    print("测试6: 输出目录")
    print("="*60)

    test_output = "/Users/mac/Desktop/TestUpdate/TUDataset/opencode_results_test"

    try:
        os.makedirs(test_output, exist_ok=True)
        os.makedirs(os.path.join(test_output, 'logs'), exist_ok=True)
        os.makedirs(os.path.join(test_output, 'prompts'), exist_ok=True)
        os.makedirs(os.path.join(test_output, 'results'), exist_ok=True)

        print(f"✓ Output directory created: {test_output}")
        print("✓ Subdirectories created: logs, prompts, results")

        # 清理测试目录
        import shutil
        shutil.rmtree(test_output)
        print("✓ Test directory cleaned up")

        return True

    except Exception as e:
        print(f"✗ Failed to create output directory: {e}")
        return False


def test_sample_task():
    """测试生成一个示例任务"""
    print("\n" + "="*60)
    print("测试7: 示例任务生成")
    print("="*60)

    # 模拟一个worktree记录
    sample_record = {
        'task_id': 1,
        'project': 'commons-csv',
        'worktree_path': '/Users/mac/Desktop/TestUpdate/TUDataset/worktrees/commons-csv-task_001_eval',
        'v_minus_1_commit': 'abc123',
        'v_0_5_commit': 'def456',
        'v_0_commit': 'ghi789',
        'type': 'type1',
        'status': 'ready'
    }

    print("Sample record:")
    print(json.dumps(sample_record, indent=2))

    # 生成prompt
    from baseline.opencode.scripts.batch_opencode_runner import OpenCodeRunner

    try:
        # 创建临时runner（不需要真实文件）
        runner = OpenCodeRunner(
            input_excel="dummy.xlsx",
            output_dir="/tmp/test_output",
            workers=1
        )

        prompt = runner.generate_prompt(sample_record)

        print(f"\n✓ Generated prompt ({len(prompt)} characters)")
        print("\nFirst 500 characters:")
        print(prompt[:500])
        print("...")

        return True

    except Exception as e:
        print(f"✗ Failed to generate prompt: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("\n" + "="*60)
    print("Batch OpenCode Runner - 环境测试")
    print("="*60)

    tests = [
        ("Prompt生成", test_prompt_generation),
        ("OpenCode可用性", test_opencode_availability),
        ("Pandas可用性", test_pandas_availability),
        ("Worktree Records文件", test_worktree_records_file),
        ("Worktree目录", test_worktree_directories),
        ("输出目录", test_output_directory),
        ("示例任务生成", test_sample_task),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # 汇总
    print("\n" + "="*60)
    print("测试汇总")
    print("="*60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n✓ 所有测试通过！可以开始使用batch_opencode_runner.py")
        return 0
    else:
        print("\n✗ 部分测试失败，请检查上述错误信息")
        return 1


if __name__ == "__main__":
    sys.exit(main())
