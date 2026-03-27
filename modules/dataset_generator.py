"""
Dataset generator - responsible for generating the final JSON format dataset
"""

import json
import os
from datetime import datetime
from utils.logger import get_logger

logger = get_logger()


class DatasetGenerator:
    """Dataset generator"""

    def __init__(self, output_path):
        """
        Initialize the dataset generator

        Args:
            output_path: output file path
        """
        self.output_path = output_path
        self.dataset = []

    def add_commit(self, commit_data):
        """
        Add a commit to the dataset

        Args:
            commit_data: commit data dictionary
        """
        self.dataset.append(commit_data)

    def save_dataset(self):
        """
        Save the dataset to a file

        Returns:
            bool: whether the save was successful
        """
        try:
            # Create output directory
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

            # Add metadata
            output_data = {
                'metadata': {
                    'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'total_commits': len(self.dataset),
                    'qualified_commits': len([c for c in self.dataset if c.get('qualified', False)])
                },
                'commits': self.dataset
            }

            # Save JSON file
            with open(self.output_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            logger.info(f"Dataset saved: {self.output_path}")
            logger.info(f"Total: {len(self.dataset)} commits, qualified: {output_data['metadata']['qualified_commits']} commits")

            return True

        except Exception as e:
            logger.error(f"Failed to save dataset: {e}")
            return False

    def load_intermediate_results(self, intermediate_path):
        """
        Load intermediate results (supports checkpoint resume)

        Args:
            intermediate_path: path to the intermediate results file

        Returns:
            list: list of already processed commit hashes
        """
        try:
            if os.path.exists(intermediate_path):
                with open(intermediate_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.dataset = data.get('commits', [])
                    processed_hashes = [c['commit_hash'] for c in self.dataset]
                    logger.info(f"Loaded intermediate results: {len(processed_hashes)} commits")
                    return processed_hashes
        except Exception as e:
            logger.warning(f"Failed to load intermediate results: {e}")

        return []

    def save_intermediate_results(self, intermediate_path):
        """
        Save intermediate results

        Args:
            intermediate_path: path to the intermediate results file
        """
        try:
            os.makedirs(os.path.dirname(intermediate_path), exist_ok=True)

            output_data = {
                'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'commits': self.dataset
            }

            with open(intermediate_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Intermediate results saved: {len(self.dataset)} commits")

        except Exception as e:
            logger.warning(f"Failed to save intermediate results: {e}")
    
    def format_commit_data(self, commit_info):
        """
        Format commit data to ensure a consistent output format

        Args:
            commit_info: commit information dictionary

        Returns:
            dict: formatted commit data
        """
        return {
            'commit_hash': commit_info.get('commit_hash', ''),
            'parent_hash': commit_info.get('parent_hash', ''),
            'author': commit_info.get('author', ''),
            'date': commit_info.get('date', ''),
            'message': commit_info.get('message', ''),
            'changed_files': commit_info.get('changed_files', {}),
            'changed_methods': {
                'test_methods': [
                    {
                        'class': m.get('class', ''),
                        'method': m.get('method', ''),
                        'line_range': [m.get('start_line', 0), m.get('end_line', 0)]
                    }
                    for m in commit_info.get('changed_methods', {}).get('test_methods', [])
                ],
                'source_methods': [
                    {
                        'class': m.get('class', ''),
                        'method': m.get('method', ''),
                        'line_range': [m.get('start_line', 0), m.get('end_line', 0)]
                    }
                    for m in commit_info.get('changed_methods', {}).get('source_methods', [])
                ]
            },
            'coverage_analysis': commit_info.get('coverage_analysis', {}),
            'build_status': commit_info.get('build_status', {}),
            'qualified': commit_info.get('qualified', False),
            'filter_reasons': commit_info.get('filter_reasons', [])
        }
    
    def get_statistics(self):
        """
        Get dataset statistics

        Returns:
            dict: statistics information
        """
        total = len(self.dataset)
        qualified = len([c for c in self.dataset if c.get('qualified', False)])
        
        return {
            'total_commits': total,
            'qualified_commits': qualified,
            'qualification_rate': qualified / total if total > 0 else 0.0
        }
