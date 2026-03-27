"""
Test evolution dataset post-processing tool - generate filtered versions
Used to generate versions that hide test changes from the initially filtered dataset
"""

import sys
import json
import os
from config import Config
from utils.logger import setup_logger, get_logger
from modules import GitAnalyzer, FilteredVersionGenerator

setup_logger()
logger = get_logger()


def load_qualified_commits(dataset_file):
    """
    Load qualified commits

    Args:
        dataset_file: path to the dataset file

    Returns:
        list: list of qualified commit information
    """
    try:
        with open(dataset_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            commits = data.get('commits', [])
            # Only select commits where qualified=True
            qualified = [c for c in commits if c.get('qualified', False)]
            logger.info(f"Loaded {len(qualified)} qualified commits (total: {len(commits)})")
            return qualified
    except Exception as e:
        logger.error(f"Failed to load dataset: {e}")
        return []


def generate_filtered_versions(repo_path, dataset_file, output_file):
    """
    Generate filtered versions for all qualified commits

    Args:
        repo_path: Git repository path
        dataset_file: input dataset file
        output_file: output dataset file
    """
    logger.info("=" * 80)
    logger.info("Test Evolution Dataset - Generating Filtered Versions")
    logger.info("=" * 80)

    # Load qualified commits
    qualified_commits = load_qualified_commits(dataset_file)
    if not qualified_commits:
        logger.error("No qualified commits found")
        return

    # Initialize tools
    git_analyzer = GitAnalyzer(repo_path)
    version_generator = FilteredVersionGenerator(git_analyzer)

    # Statistics
    stats = {
        'total': len(qualified_commits),
        'source_only': {
            'success': 0,
            'failed_apply': 0,
            'failed_compile': 0,
            'failed_other': 0
        },
        'test_only': {
            'success': 0,
            'failed_apply': 0,
            'failed_compile': 0,
            'failed_other': 0
        }
    }

    # Processing results
    results = []

    try:
        for i, commit_info in enumerate(qualified_commits):
            commit_hash = commit_info['commit_hash']
            logger.info(f"\nProcessing [{i+1}/{len(qualified_commits)}]: {commit_hash[:8]}")

            # Generate filtered version (source code changes only)
            source_result = version_generator.generate_filtered_version(commit_info)
            # Generate test version (test code changes only)
            test_result = version_generator.generate_test_only_version(commit_info)

            # Build output data
            output_data = {
                'original_commit': commit_hash,
                'parent_commit': commit_info['parent_hash'],
                'author': commit_info['author'],
                'date': commit_info['date'],
                'message': commit_info['message'],
                'changed_files': commit_info['changed_files'],
                'changed_methods': commit_info['changed_methods'],
                'coverage_analysis': commit_info.get('coverage_analysis', {}),
                'filtered_version': {
                    'success': source_result['success'],
                    'filtered_commit_hash': source_result.get('filtered_commit_hash'),
                    'branch_name': source_result.get('branch_name'),
                    'test_changes_hidden': source_result.get('test_changes_hidden', {}),
                    'filter_stats': source_result.get('stats', {}),
                    'error': source_result.get('error')
                },
                'test_only_version': {
                    'success': test_result['success'],
                    'test_only_commit_hash': test_result.get('test_only_commit_hash'),
                    'branch_name': test_result.get('branch_name'),
                    'source_changes_hidden': test_result.get('source_changes_hidden', {}),
                    'filter_stats': test_result.get('stats', {}),
                    'error': test_result.get('error')
                }
            }

            # Update statistics - source code version
            if source_result['success']:
                stats['source_only']['success'] += 1
                logger.info(
                    f"  ✓ Source code version succeeded: {source_result['filtered_commit_hash'][:8]} "
                    f"(branch: {source_result['branch_name']})"
                )
            else:
                error_msg = source_result.get('error', 'Unknown error')
                if 'apply' in error_msg.lower() or 'patch' in error_msg.lower():
                    stats['source_only']['failed_apply'] += 1
                elif 'compile' in error_msg.lower() or 'compilation' in error_msg:
                    stats['source_only']['failed_compile'] += 1
                else:
                    stats['source_only']['failed_other'] += 1
                logger.warning(f"  ✗ Source code version failed: {error_msg}")

            # Update statistics - test version
            if test_result['success']:
                stats['test_only']['success'] += 1
                logger.info(
                    f"  ✓ Test version succeeded: {test_result['test_only_commit_hash'][:8]} "
                    f"(branch: {test_result['branch_name']})"
                )
            else:
                error_msg = test_result.get('error', 'Unknown error')
                if 'apply' in error_msg.lower() or 'patch' in error_msg.lower():
                    stats['test_only']['failed_apply'] += 1
                elif 'compile' in error_msg.lower() or 'compilation' in error_msg:
                    stats['test_only']['failed_compile'] += 1
                else:
                    stats['test_only']['failed_other'] += 1
                logger.warning(f"  ✗ Test version failed: {error_msg}")

            results.append(output_data)

        # Save results
        def _success_rate(success, total):
            return f"{(success / total * 100):.2f}%" if total else "0.00%"

        output_data = {
            'metadata': {
                'source_dataset': dataset_file,
                'total_processed': stats['total'],
                'source_only': {
                    'successful': stats['source_only']['success'],
                    'failed': {
                        'apply_patch': stats['source_only']['failed_apply'],
                        'compilation': stats['source_only']['failed_compile'],
                        'other': stats['source_only']['failed_other']
                    },
                    'success_rate': _success_rate(stats['source_only']['success'], stats['total'])
                },
                'test_only': {
                    'successful': stats['test_only']['success'],
                    'failed': {
                        'apply_patch': stats['test_only']['failed_apply'],
                        'compilation': stats['test_only']['failed_compile'],
                        'other': stats['test_only']['failed_other']
                    },
                    'success_rate': _success_rate(stats['test_only']['success'], stats['total'])
                }
            },
            'commits': results
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        logger.info("\n" + "=" * 80)
        logger.info("Processing complete!")
        logger.info(f"Total: {stats['total']}")
        logger.info(
            f"Source code version succeeded: {stats['source_only']['success']} "
            f"({_success_rate(stats['source_only']['success'], stats['total'])})"
        )
        logger.info(
            f"Test version succeeded: {stats['test_only']['success']} "
            f"({_success_rate(stats['test_only']['success'], stats['total'])})"
        )
        logger.info("Source code version failures:")
        logger.info(f"  - Patch apply failed: {stats['source_only']['failed_apply']}")
        logger.info(f"  - Compilation failed: {stats['source_only']['failed_compile']}")
        logger.info(f"  - Other errors: {stats['source_only']['failed_other']}")
        logger.info("Test version failures:")
        logger.info(f"  - Patch apply failed: {stats['test_only']['failed_apply']}")
        logger.info(f"  - Compilation failed: {stats['test_only']['failed_compile']}")
        logger.info(f"  - Other errors: {stats['test_only']['failed_other']}")
        logger.info(f"\nResults saved to: {output_file}")
        logger.info("=" * 80)

    finally:
        # Restore original state
        version_generator.restore_original_branch()


def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python generate_filtered_versions.py <dataset.json> [output.json]")
        print("\nArguments:")
        print("  dataset.json - path to the initially filtered dataset file")
        print("  output.json  - output file path (optional, defaults to filtered_dataset.json)")
        print("\nExample:")
        print("  python generate_filtered_versions.py output/dataset.json output/filtered_dataset.json")
        sys.exit(1)

    dataset_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "output/filtered_dataset.json"

    # Validate input file
    if not os.path.exists(dataset_file):
        logger.error(f"Dataset file does not exist: {dataset_file}")
        sys.exit(1)

    # Use repository path from configuration
    if not Config.REPO_PATH:
        logger.error("Please set REPO_PATH in config.py")
        sys.exit(1)

    try:
        Config.validate()
        generate_filtered_versions(Config.REPO_PATH, dataset_file, output_file)
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
