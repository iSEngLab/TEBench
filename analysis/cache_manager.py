"""
Cache manager - manages cache of analysis results
"""

import os
import json
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any

from utils.logger import get_logger

logger = get_logger()


class CacheManager:
    """Cache manager - supports checkpoint resume and result reuse"""

    def __init__(self, cache_dir: str, enabled: bool = True):
        """
        Initialize the cache manager

        Args:
            cache_dir: cache directory
            enabled: whether to enable cache
        """
        self.cache_dir = cache_dir
        self.enabled = enabled

        if enabled:
            os.makedirs(cache_dir, exist_ok=True)

    def _get_cache_key(self, project: str, commit_hash: str, phase: str) -> str:
        """Generate cache key"""
        return f"{project}_{commit_hash}_{phase}"

    def _get_cache_path(self, cache_key: str) -> str:
        """Get cache file path"""
        return os.path.join(self.cache_dir, f"{cache_key}.json")

    def has_cache(self, project: str, commit_hash: str, phase: str) -> bool:
        """Check whether cache exists"""
        if not self.enabled:
            return False

        cache_key = self._get_cache_key(project, commit_hash, phase)
        cache_path = self._get_cache_path(cache_key)
        return os.path.exists(cache_path)

    def get_cache(self, project: str, commit_hash: str, phase: str) -> Optional[Dict[str, Any]]:
        """Get cached data"""
        if not self.enabled:
            return None

        cache_key = self._get_cache_key(project, commit_hash, phase)
        cache_path = self._get_cache_path(cache_key)

        if not os.path.exists(cache_path):
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.debug(f"Loaded from cache: {cache_key}")
                return data
        except Exception as e:
            logger.warning(f"Failed to read cache {cache_key}: {e}")
            return None

    def set_cache(self, project: str, commit_hash: str, phase: str, data: Dict[str, Any]):
        """Set cached data"""
        if not self.enabled:
            return

        cache_key = self._get_cache_key(project, commit_hash, phase)
        cache_path = self._get_cache_path(cache_key)

        try:
            # Add cache metadata
            cache_data = {
                'cache_key': cache_key,
                'cached_at': datetime.now().isoformat(),
                'project': project,
                'commit_hash': commit_hash,
                'phase': phase,
                'data': data
            }

            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)

            logger.debug(f"Cache saved: {cache_key}")
        except Exception as e:
            logger.warning(f"Failed to save cache {cache_key}: {e}")

    def clear_cache(self, project: str = None, commit_hash: str = None):
        """Clear cache"""
        if not self.enabled or not os.path.exists(self.cache_dir):
            return

        count = 0
        for filename in os.listdir(self.cache_dir):
            if not filename.endswith('.json'):
                continue

            should_delete = True
            if project and not filename.startswith(f"{project}_"):
                should_delete = False
            if commit_hash and commit_hash not in filename:
                should_delete = False

            if should_delete:
                try:
                    os.remove(os.path.join(self.cache_dir, filename))
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete cache {filename}: {e}")

        logger.info(f"Cleared {count} cache files")

    def get_cached_commits(self, project: str, phase: str) -> set:
        """Get list of cached commits"""
        if not self.enabled or not os.path.exists(self.cache_dir):
            return set()

        cached = set()
        prefix = f"{project}_"
        suffix = f"_{phase}.json"

        for filename in os.listdir(self.cache_dir):
            if filename.startswith(prefix) and filename.endswith(suffix):
                # Extract commit hash
                commit_hash = filename[len(prefix):-len(suffix)]
                cached.add(commit_hash)

        return cached

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        if not self.enabled or not os.path.exists(self.cache_dir):
            return {'enabled': False, 'count': 0, 'size_mb': 0}

        count = 0
        total_size = 0

        for filename in os.listdir(self.cache_dir):
            if filename.endswith('.json'):
                count += 1
                filepath = os.path.join(self.cache_dir, filename)
                total_size += os.path.getsize(filepath)

        return {
            'enabled': True,
            'count': count,
            'size_mb': round(total_size / (1024 * 1024), 2)
        }
