"""
Test evolution dataset construction tool - main program
"""

import sys
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from config import Config
from utils.logger import setup_logger, get_logger
from modules import (
    GitAnalyzer,
    CodeAnalyzer,
    ChangeDetector,
    MavenExecutor,
    CoverageAnalyzer,
    CommitFilter,
    DatasetGenerator
)

# Set up logging
setup_logger()
logger = get_logger()


class DatasetBuilder:
    """Main class for the dataset builder"""

    def __init__(self, repo_path):
        """
        Initialize the dataset builder

        Args:
            repo_path: Git repository path
        """
        self.repo_path = repo_path
        self.git_analyzer = GitAnalyzer(repo_path)
        self.code_analyzer = CodeAnalyzer()
        self.change_detector = ChangeDetector()
        self.commit_filter = CommitFilter()
        self.dataset_generator = DatasetGenerator(
            Config.get_output_path(Config.OUTPUT_FILE)
        )

    def run(self):
        """Run the dataset building process"""
        logger.info("=" * 80)
        logger.info("Test Evolution Dataset Construction Tool")
        logger.info("=" * 80)

        try:
            # Phase 1: Get all commits
            logger.info("\n[Phase 1] Fetching commits...")
            commits = self.git_analyzer.get_all_commits(
                since_date=Config.get_date_filter()
            )

            if not commits:
                logger.error("No commits matching the criteria were found")
                return

            logger.info(f"Found {len(commits)} commits to process")

            # Load already-processed commits (supports checkpoint resume)
            if Config.SAVE_INTERMEDIATE:
                processed_hashes = self.dataset_generator.load_intermediate_results(
                    Config.get_output_path(Config.INTERMEDIATE_FILE)
                )
                commits = [c for c in commits if c.hexsha not in processed_hashes]
                logger.info(f"Skipping already-processed commits, {len(commits)} remaining")

            # Phase 2: Quick pre-filtering
            logger.info("\n[Phase 2] Quick pre-filtering...")
            filtered_commits = self.pre_filter_commits(commits)
            logger.info(f"{len(filtered_commits)} commits remaining after pre-filtering")

            if not filtered_commits:
                logger.warning("No commits passed pre-filtering")
                return

            # Phase 3: Detailed analysis (parallel processing)
            logger.info("\n[Phase 3] Detailed analysis (parallel processing)...")
            self.process_commits_parallel(filtered_commits)

            # Save the final dataset
            logger.info("\n[Phase 4] Saving dataset...")
            self.dataset_generator.save_dataset()

            # Output statistics
            stats = self.dataset_generator.get_statistics()
            logger.info("\n" + "=" * 80)
            logger.info("Build complete! Statistics:")
            logger.info(f"  Total processed: {stats['total_commits']} commits")
            logger.info(f"  Qualified: {stats['qualified_commits']} commits")
            logger.info(f"  Qualification rate: {stats['qualification_rate']:.2%}")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"Build failed: {e}", exc_info=True)

    def pre_filter_commits(self, commits):
        """
        Quick pre-filtering of commits (without switching versions)

        Args:
            commits: list of commit objects

        Returns:
            list: commits that passed pre-filtering
        """
        filtered = []

        for i, commit in enumerate(commits):
            logger.info(f"Pre-filtering [{i+1}/{len(commits)}]: {commit.hexsha[:8]}")

            # Get changed files
            changed_files = self.git_analyzer.get_changed_files(commit)

            # Must modify both test files and source code files
            if self.commit_filter.filter_by_file_changes(changed_files):
                filtered.append(commit)
                logger.debug(f"  ✓ Passed pre-filtering")
            else:
                logger.debug(f"  ✗ Did not pass pre-filtering")

        return filtered

    def process_commits_parallel(self, commits):
        """
        Process commits in parallel

        Args:
            commits: list of commit objects
        """
        # Convert commit objects to serializable data
        commit_hashes = [c.hexsha for c in commits]

        with ProcessPoolExecutor(max_workers=Config.PARALLEL_WORKERS) as executor:
            futures = {
                executor.submit(
                    process_single_commit_worker,
                    self.repo_path,
                    commit_hash
                ): commit_hash
                for commit_hash in commit_hashes
            }

            completed = 0
            for future in as_completed(futures):
                commit_hash = futures[future]
                completed += 1

                try:
                    result = future.result()

                    if result:
                        formatted_data = self.dataset_generator.format_commit_data(result)
                        self.dataset_generator.add_commit(formatted_data)

                        status = "✓ qualified" if result.get('qualified') else "✗ not qualified"
                        logger.info(f"[{completed}/{len(commits)}] {commit_hash[:8]} - {status}")

                    # Periodically save intermediate results
                    if Config.SAVE_INTERMEDIATE and completed % Config.SAVE_INTERVAL == 0:
                        self.dataset_generator.save_intermediate_results(
                            Config.get_output_path(Config.INTERMEDIATE_FILE)
                        )

                except Exception as e:
                    logger.error(f"Failed to process commit [{commit_hash[:8]}]: {e}")

        # Final save of intermediate results
        if Config.SAVE_INTERMEDIATE:
            self.dataset_generator.save_intermediate_results(
                Config.get_output_path(Config.INTERMEDIATE_FILE)
            )


def process_single_commit_worker(repo_path, commit_hash):
    """
    Worker function: process a single commit (runs in a separate process)

    Args:
        repo_path: Git repository path
        commit_hash: commit hash value

    Returns:
        dict: commit processing result
    """
    # Re-initialize in the worker process
    git_analyzer = GitAnalyzer(repo_path)
    code_analyzer = CodeAnalyzer()
    change_detector = ChangeDetector()
    maven_executor = None
    coverage_analyzer = CoverageAnalyzer()
    commit_filter = CommitFilter()

    commit = git_analyzer.repo.commit(commit_hash)

    # Get basic information
    commit_info = git_analyzer.get_commit_info(commit)
    commit_info['changed_files'] = git_analyzer.get_changed_files(commit)
    commit_info['changed_methods'] = {'test_methods': [], 'source_methods': []}
    commit_info['coverage_analysis'] = {}
    commit_info['build_status'] = {'parent_success': False, 'child_success': False}

    try:
        # Analyze changed methods
        for test_file in commit_info['changed_files']['test_files']:
            diff_text = git_analyzer.get_file_diff(commit, test_file)
            file_content = git_analyzer.get_file_content(commit.hexsha, test_file)

            if file_content:
                changed_methods = change_detector.detect_changed_methods(
                    file_content, diff_text, code_analyzer
                )
                # Add package information
                package = code_analyzer.get_package_name(file_content)
                for method in changed_methods:
                    method['package'] = package
                    method['file'] = test_file
                commit_info['changed_methods']['test_methods'].extend(changed_methods)

        for source_file in commit_info['changed_files']['source_files']:
            diff_text = git_analyzer.get_file_diff(commit, source_file)
            file_content = git_analyzer.get_file_content(commit.hexsha, source_file)

            if file_content:
                changed_methods = change_detector.detect_changed_methods(
                    file_content, diff_text, code_analyzer
                )
                # Add package information
                package = code_analyzer.get_package_name(file_content)
                for method in changed_methods:
                    method['package'] = package
                    method['file'] = source_file
                commit_info['changed_methods']['source_methods'].extend(changed_methods)

        # Check if there are method-level changes
        if not commit_filter.filter_by_method_changes(commit_info['changed_methods']):
            commit_info['qualified'] = False
            commit_info['filter_reasons'] = ['Method changes do not meet requirements']
            return commit_info

        # Create worktree for build and test
        worktree_path = Config.WORKTREE_PREFIX + commit_hash

        # Process parent commit
        if commit.parents:
            parent_hash = commit.parents[0].hexsha
            if git_analyzer.create_worktree(parent_hash, worktree_path):
                maven_executor = MavenExecutor(worktree_path)

                if maven_executor.has_pom():
                    # Run tests and collect coverage
                    test_result = maven_executor.test_with_jacoco()
                    commit_info['build_status']['parent_success'] = test_result['success']

                    if test_result['success'] and test_result['jacoco_report']:
                        coverage_data = coverage_analyzer.parse_jacoco_report(
                            test_result['jacoco_report']
                        )

                        if coverage_data:
                            commit_info['coverage_analysis']['parent_commit'] = \
                                coverage_analyzer.analyze_test_coverage_for_changes(
                                    coverage_data,
                                    commit_info['changed_methods']['test_methods'],
                                    commit_info['changed_methods']['source_methods']
                                )

                git_analyzer.remove_worktree(worktree_path)

        # Process child commit
        if git_analyzer.create_worktree(commit_hash, worktree_path):
            maven_executor = MavenExecutor(worktree_path)

            if maven_executor.has_pom():
                test_result = maven_executor.test_with_jacoco()
                commit_info['build_status']['child_success'] = test_result['success']

                if test_result['success'] and test_result['jacoco_report']:
                    coverage_data = coverage_analyzer.parse_jacoco_report(
                        test_result['jacoco_report']
                    )

                    if coverage_data:
                        commit_info['coverage_analysis']['child_commit'] = \
                            coverage_analyzer.analyze_test_coverage_for_changes(
                                coverage_data,
                                commit_info['changed_methods']['test_methods'],
                                commit_info['changed_methods']['source_methods']
                            )

            git_analyzer.remove_worktree(worktree_path)

        # Apply all filter conditions
        qualified, reasons = commit_filter.apply_all_filters(
            commit_info,
            threshold=Config.COVERAGE_THRESHOLD
        )

        commit_info['qualified'] = qualified
        commit_info['filter_reasons'] = reasons

    except Exception as e:
        logger.error(f"Exception while processing commit [{commit_hash[:8]}]: {e}")
        commit_info['qualified'] = False
        commit_info['filter_reasons'] = [f'Processing exception: {str(e)}']

    return commit_info


def main():
    """Main function"""
    # Check configuration
    if len(sys.argv) > 1:
        Config.REPO_PATH = sys.argv[1]

    try:
        Config.validate()
    except ValueError as e:
        logger.error(str(e))
        logger.info("\nUsage: python main.py <git_repo_path>")
        logger.info("Or set REPO_PATH in config.py")
        sys.exit(1)

    # Build dataset
    builder = DatasetBuilder(Config.REPO_PATH)
    builder.run()


if __name__ == "__main__":
    main()
