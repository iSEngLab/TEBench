"""
Configuration file - test evolution dataset construction tool
"""

import os
from datetime import datetime


class AnalysisConfig:
    """Analysis tool configuration"""

    # ========== Analysis output configuration ==========
    # Analysis output directory
    ANALYSIS_OUTPUT_DIR = "./output/analysis"

    # Temporary worktree directory
    ANALYSIS_WORKTREE_DIR = "/tmp/tubench_analysis_worktrees"

    # ========== Concurrent configuration ==========
    # Number of concurrent commits within a single project
    ANALYSIS_WORKERS = 4

    # Whether to execute 4 versions in parallel when running a single version
    PARALLEL_VERSION_EXECUTION = True

    # ========== Timeout configuration ==========
    # Single compilation timeout (seconds)
    COMPILE_TIMEOUT = 300  # 5 minutes

    # Single test timeout (seconds)
    TEST_TIMEOUT = 900  # 15 minutes

    # Total timeout per commit (seconds)
    COMMIT_TIMEOUT = 1800  # 30 minutes

    # ========== Coverage configuration ==========
    # Coverage decrease threshold (below this value classified as Type2)
    COVERAGE_DECREASE_THRESHOLD = 0.02  # 2%
    # Branch coverage increase threshold (above this value classified as Type2-branch)
    BRANCH_COVERAGE_INCREASE_THRESHOLD = 0.02  # 2%

    # ========== Cache configuration ==========
    # Whether to enable cache
    ENABLE_CACHE = True

    # Cache directory
    CACHE_DIR = "./cache/analysis"

    # ========== Logging configuration ==========
    # Analysis log file
    ANALYSIS_LOG_FILE = "analysis.log"

    # ========== Version compatibility configuration ==========
    # Java version (set JAVA_HOME environment variable path, None means use system default)
    # Example: "/usr/lib/jvm/java-8-openjdk-amd64"
    JAVA_HOME = None

    # Maven executable path (None means use mvn from PATH)
    # Example: "/opt/maven-3.6.3/bin/mvn"
    MAVEN_EXECUTABLE = None

    # Extra Maven arguments (used to resolve compatibility issues)
    # Example: "-Dmaven.compiler.source=1.8 -Dmaven.compiler.target=1.8"
    MAVEN_EXTRA_ARGS = ""

    # Whether to skip commits when encountering compatibility issues (instead of marking as failed)
    SKIP_INCOMPATIBLE_COMMITS = False

    # Whether to attempt automatic fixing of common compatibility issues
    # Currently supported: auto-adjust source/target version
    AUTO_FIX_COMPATIBILITY = False


class Config:
    """Global configuration"""

    # ========== Basic configuration ==========
    # Git repository path (must be specified by user)
    REPO_PATH = "/Users/mac/Desktop/java-project/tu/temp/commons-csv"

    # Output directory
    OUTPUT_DIR = "./output"
    OUTPUT_FILE = "dataset.json"
    INTERMEDIATE_FILE = "intermediate_results.json"
    LOG_FILE = "dataset_builder.log"

    # ========== Filter conditions ==========
    # Only process commits after this date (format: YYYY-MM-DD)
    DATE_FILTER = "2016-01-01"

    # Coverage threshold (50% of test cases need to cover the changed production functions)
    COVERAGE_THRESHOLD = 0.5

    # ========== Path recognition rules ==========
    # Test code path patterns
    TEST_PATH_PATTERNS = ["src/test/java", "test/java", "src/test"]

    # Source code path patterns
    SOURCE_PATH_PATTERNS = ["src/main/java", "main/java", "src/main"]

    # ========== Maven configuration ==========
    # Maven command
    MAVEN_CMD = "mvn"

    # Maven timeout (seconds)
    MAVEN_TIMEOUT = 300

    # Maven options
    MAVEN_OPTS = "-DskipTests=false -Dmaven.test.failure.ignore=true"

    # ========== JaCoCo configuration ==========
    JACOCO_VERSION = "0.8.11"
    JACOCO_REPORT_PATH = "target/site/jacoco/jacoco.xml"

    # ========== Parallel processing configuration ==========
    # Number of parallel workers
    PARALLEL_WORKERS = 10

    # Single commit processing timeout (seconds)
    PROCESS_TIMEOUT = 900

    # ========== Advanced options ==========
    # Whether to save intermediate results (supports checkpoint resume)
    SAVE_INTERMEDIATE = True

    # Intermediate result save interval (save after processing this many commits)
    SAVE_INTERVAL = 10

    # Whether to enable verbose logging
    VERBOSE = True

    # Temporary worktree directory prefix
    WORKTREE_PREFIX = "/tmp/test_evolution_worktree_"

    @classmethod
    def validate(cls):
        """Validate configuration"""
        if not cls.REPO_PATH:
            raise ValueError("REPO_PATH is not set! Please specify the Git repository path.")

        if not os.path.exists(cls.REPO_PATH):
            raise ValueError(f"Git repository path does not exist: {cls.REPO_PATH}")

        # Create output directory
        os.makedirs(cls.OUTPUT_DIR, exist_ok=True)

        return True

    @classmethod
    def get_output_path(cls, filename):
        """Get the full path of an output file"""
        return os.path.join(cls.OUTPUT_DIR, filename)

    @classmethod
    def get_date_filter(cls):
        """Get the datetime object for the date filter"""
        try:
            return datetime.strptime(cls.DATE_FILTER, "%Y-%m-%d")
        except:
            return None
