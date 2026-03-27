"""
TUBench Analysis Tool - main entry point for the analysis tool
Used to analyze test evolution data in Java projects, filter and classify qualifying commits
"""

import sys
import os
import argparse
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

# Add project root directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config, AnalysisConfig
from utils.logger import setup_logger, get_logger
from analysis.project_analyzer import ProjectAnalyzer
from analysis.report_generator import ReportGenerator


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description='TUBench Analysis Tool - test evolution dataset analysis tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Analyze a single project
  python analysis.py --project /path/to/commons-csv

  # Analyze all projects in a directory
  python analysis.py --projects-dir /path/to/defects4j-projects

  # Specify output directory and number of workers
  python analysis.py --project /path/to/project --output ./output --workers 8

  # Quick scan mode (file-level filtering only)
  python analysis.py --project /path/to/project --phase quick

  # Resume from checkpoint
  python analysis.py --project /path/to/project --resume

  # Analyze a specific commit
  python analysis.py --project /path/to/project --commit abc123
        '''
    )

    # Project path (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--project', '-p', type=str,
                       help='Path to a single project')
    group.add_argument('--projects-dir', '-d', type=str,
                       help='Path to a directory containing multiple projects')

    # Output configuration
    parser.add_argument('--output', '-o', type=str,
                        default=None,
                        help='Output directory (default: ./output/analysis/<project>_<YYYY-MM-DD>)')

    # Execution configuration
    parser.add_argument('--workers', '-w', type=int,
                        default=4,
                        help='Number of concurrent workers (default: 4)')
    parser.add_argument('--phase', type=str,
                        choices=['quick', 'method', 'full'],
                        default='full',
                        help='Execution phase: quick (quick scan), method (method analysis), full (complete analysis)')

    # Filter configuration
    parser.add_argument('--since', type=str,
                        default='2016-01-01',
                        help='Only analyze commits after this date (default: 2016-01-01)')
    parser.add_argument('--sample', type=int,
                        help='Sample size for quick testing')
    parser.add_argument('--commit', type=str,
                        help='Only analyze the specified commit')

    # Other options
    parser.add_argument('--resume', action='store_true',
                        help='Resume from checkpoint, skip already-analyzed commits')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose logging output')
    parser.add_argument('--no-cache', action='store_true',
                        help='Disable cache')

    return parser.parse_args()


def validate_project_path(path: str) -> bool:
    """Validate project path"""
    if not os.path.exists(path):
        return False

    # Check if it's a Git repository
    git_dir = os.path.join(path, '.git')
    if not os.path.exists(git_dir):
        return False

    # Check if it has pom.xml (Maven project)
    pom_file = os.path.join(path, 'pom.xml')
    if not os.path.exists(pom_file):
        return False

    return True


def get_project_list(args) -> list:
    """Get the list of projects to analyze"""
    projects = []

    if args.project:
        # Single project
        if validate_project_path(args.project):
            projects.append(args.project)
        else:
            raise ValueError(f"Invalid project path: {args.project}")

    elif args.projects_dir:
        # Multiple projects
        if not os.path.exists(args.projects_dir):
            raise ValueError(f"Directory does not exist: {args.projects_dir}")

        for name in sorted(os.listdir(args.projects_dir)):
            path = os.path.join(args.projects_dir, name)
            if os.path.isdir(path) and validate_project_path(path):
                projects.append(path)

        if not projects:
            raise ValueError(f"No valid Maven projects found in {args.projects_dir}")

    return projects


def _get_output_dir(args, project_name: str) -> str:
    """Generate project output directory (default: ./output/analysis/<project>_<YYYY-MM-DD_HH-MM-SS>)"""
    if args.output:
        return os.path.join(args.output, project_name)
    date_str = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    return os.path.join('./output/analysis', f"{project_name}_{date_str}")


def analyze_single_project(project_path: str, args, logger) -> dict:
    """Analyze a single project"""
    project_name = os.path.basename(project_path)
    logger.info(f"\n{'='*60}")
    logger.info(f"Starting analysis of project: {project_name}")
    logger.info(f"Path: {project_path}")
    logger.info(f"{'='*60}")

    # Create project analyzer
    output_dir = _get_output_dir(args, project_name)
    analyzer = ProjectAnalyzer(
        project_path=project_path,
        output_dir=output_dir,
        workers=args.workers,
        resume=args.resume,
        enable_cache=not args.no_cache,
        verbose=args.verbose
    )

    # Execute analysis
    try:
        result = analyzer.analyze(
            since_date=args.since,
            sample=args.sample,
            phase=args.phase,
            single_commit=args.commit
        )

        logger.info(f"\nProject {project_name} analysis complete!")
        logger.info(f"  Qualified commits: {len(result.qualified_commits)}")
        logger.info(f"  Type1 (execution error): {result.type_statistics.get('type1_execution_error', {}).get('count', 0)}")
        logger.info(f"  Type2 (coverage gap): {result.type_statistics.get('type2_coverage_decrease', {}).get('count', 0)}")
        logger.info(f"  Type3 (adaptive change): {result.type_statistics.get('type3_adaptive_change', {}).get('count', 0)}")

        return {
            'project': project_name,
            'success': True,
            'result': result
        }

    except Exception as e:
        logger.error(f"Project {project_name} analysis failed: {e}", exc_info=args.verbose)
        return {
            'project': project_name,
            'success': False,
            'error': str(e)
        }


def main():
    """Main function"""
    # Parse arguments
    args = parse_args()

    # Set up logging
    log_level = 'DEBUG' if args.verbose else 'INFO'
    setup_logger(level=log_level)
    logger = get_logger()

    logger.info("="*60)
    logger.info("TUBench Analysis Tool")
    logger.info(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)

    try:
        # Get project list
        projects = get_project_list(args)
        logger.info(f"Found {len(projects)} projects to analyze")

        # Create output directory
        base_output = args.output if args.output else './output/analysis'
        os.makedirs(base_output, exist_ok=True)

        # Analyze each project
        all_results = []
        for i, project_path in enumerate(projects):
            logger.info(f"\n[{i+1}/{len(projects)}] Processing project...")
            result = analyze_single_project(project_path, args, logger)
            all_results.append(result)

        # Generate global summary report (if there are multiple projects)
        if len(projects) > 1:
            logger.info("\nGenerating global summary report...")
            report_generator = ReportGenerator(base_output)
            successful_results = [r['result'] for r in all_results if r['success']]
            if successful_results:
                report_generator.generate_global_summary(
                    successful_results,
                    os.path.join(base_output, 'global_summary')
                )

        # Output summary
        logger.info("\n" + "="*60)
        logger.info("Analysis complete!")
        logger.info("="*60)

        successful = sum(1 for r in all_results if r['success'])
        failed = sum(1 for r in all_results if not r['success'])

        logger.info(f"Succeeded: {successful} projects")
        if failed > 0:
            logger.info(f"Failed: {failed} projects")
            for r in all_results:
                if not r['success']:
                    logger.info(f"  - {r['project']}: {r['error']}")

        logger.info(f"\nOutput directory: {args.output}")

    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
