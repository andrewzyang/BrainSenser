"""
Application Configuration for iEEG BrainSense App.

This module provides centralized configuration settings for the application,
including preprocessing options, UI preferences, and system settings.

Author: iEEG BrainSense Development Team
Last Updated: 2025-10-02
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from src.core.path_resolver import default_app_data_dir

logger = logging.getLogger(__name__)


class AppConfig:
    """
    Application configuration manager.

    Manages application settings with support for:
    - Default values
    - User preferences
    - Configuration persistence
    - Runtime modification

    Settings are stored in ~/.brainsense_data/config.json
    """

    # Default configuration values
    DEFAULT_CONFIG = {
        'preprocessing': {
            'overvoltage_removal': {
                'enabled': True,
                'threshold': 71582788,  # ~71.58M (2^32-1/60)
                'method': 'OvER',
                'reference': 'Hanish et al. 2025'
            }
        },
        'ui': {
            'theme': 'light',
            'default_page': 'patient_selection',
            'show_preprocessing_notifications': True,
            'show_upload_progress': True
        },
        'data': {
            'auto_backup': False,
            'backup_interval_days': 7,
            'max_file_size_mb': 500
        },
        'analysis': {
            'enable_outlier_detection': True,
            'outlier_threshold_sigma': 3.0,
            'enable_trend_analysis': True
        },
        'export': {
            'default_format': 'csv',
            'include_metadata': True,
            'compress_exports': False
        }
    }

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize AppConfig.

        Args:
            config_path: Optional path to config file.
                        Defaults to ~/.brainsense_data/config.json
        """
        # Determine config file location
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Shared resolver: dev → ~/.brainsense_data; frozen macOS →
            # ~/Library/Application Support/BrainSenser (outside the read-only bundle).
            self.config_path = default_app_data_dir() / 'config.json'

        # Ensure config directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load configuration
        self.config = self._load_config()

        logger.info(f"AppConfig initialized from {self.config_path}")

    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file or create with defaults.

        Returns:
            Dict containing configuration settings
        """
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)

                # Merge user config with defaults (user config takes precedence)
                config = self._deep_merge(self.DEFAULT_CONFIG.copy(), user_config)
                logger.info("Loaded user configuration")
                return config

            except Exception as e:
                logger.error(f"Failed to load config file: {e}")
                logger.info("Using default configuration")
                return self.DEFAULT_CONFIG.copy()
        else:
            # Create config file with defaults
            self._save_config(self.DEFAULT_CONFIG)
            logger.info("Created new configuration file with defaults")
            return self.DEFAULT_CONFIG.copy()

    def _deep_merge(self, base: Dict, updates: Dict) -> Dict:
        """
        Deep merge two dictionaries.

        Args:
            base: Base dictionary
            updates: Dictionary with updates

        Returns:
            Merged dictionary
        """
        result = base.copy()

        for key, value in updates.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def _save_config(self, config: Optional[Dict] = None) -> bool:
        """
        Save configuration to file.

        Args:
            config: Configuration to save (uses self.config if None)

        Returns:
            bool: True if successful
        """
        try:
            config_to_save = config if config is not None else self.config

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config_to_save, f, indent=2)

            logger.info(f"Configuration saved to {self.config_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")
            return False

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.

        Args:
            key_path: Dot-separated path (e.g., 'preprocessing.overvoltage_removal.enabled')
            default: Default value if key not found

        Returns:
            Configuration value or default

        Example:
            >>> config = AppConfig()
            >>> enabled = config.get('preprocessing.overvoltage_removal.enabled')
            >>> print(f"OvER preprocessing: {enabled}")
        """
        keys = key_path.split('.')
        value = self.config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def set(self, key_path: str, value: Any, save: bool = True) -> bool:
        """
        Set configuration value using dot notation.

        Args:
            key_path: Dot-separated path
            value: Value to set
            save: Whether to save to file immediately

        Returns:
            bool: True if successful

        Example:
            >>> config = AppConfig()
            >>> config.set('preprocessing.overvoltage_removal.enabled', False)
        """
        keys = key_path.split('.')
        target = self.config

        # Navigate to parent of target key
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]

        # Set the value
        target[keys[-1]] = value

        # Save if requested
        if save:
            return self._save_config()

        return True

    def reset_to_defaults(self, save: bool = True) -> bool:
        """
        Reset configuration to default values.

        Args:
            save: Whether to save immediately

        Returns:
            bool: True if successful
        """
        self.config = self.DEFAULT_CONFIG.copy()

        if save:
            return self._save_config()

        return True

    def is_overvoltage_preprocessing_enabled(self) -> bool:
        """
        Check if overvoltage preprocessing is enabled.

        Returns:
            bool: True if OvER preprocessing is enabled
        """
        return self.get('preprocessing.overvoltage_removal.enabled', True)

    def get_overvoltage_threshold(self) -> float:
        """
        Get overvoltage detection threshold.

        Returns:
            float: Threshold value for overvoltage detection
        """
        return self.get('preprocessing.overvoltage_removal.threshold', 71582788)

    def enable_overvoltage_preprocessing(self, enabled: bool = True) -> bool:
        """
        Enable or disable overvoltage preprocessing.

        Args:
            enabled: Whether to enable preprocessing

        Returns:
            bool: True if successful
        """
        return self.set('preprocessing.overvoltage_removal.enabled', enabled)

    def export_config(self, path: Path) -> bool:
        """
        Export configuration to a file.

        Args:
            path: Path to export file

        Returns:
            bool: True if successful
        """
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
            logger.info(f"Configuration exported to {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export configuration: {e}")
            return False

    def import_config(self, path: Path, save: bool = True) -> bool:
        """
        Import configuration from a file.

        Args:
            path: Path to import file
            save: Whether to save immediately

        Returns:
            bool: True if successful
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                imported_config = json.load(f)

            # Merge with defaults to ensure all keys exist
            self.config = self._deep_merge(self.DEFAULT_CONFIG.copy(), imported_config)

            if save:
                return self._save_config()

            logger.info(f"Configuration imported from {path}")
            return True

        except Exception as e:
            logger.error(f"Failed to import configuration: {e}")
            return False


# Global configuration instance (singleton pattern)
_app_config_instance: Optional[AppConfig] = None


def get_app_config() -> AppConfig:
    """
    Get global AppConfig instance (singleton).

    Returns:
        AppConfig: Global configuration instance

    Example:
        >>> from src.core.app_config import get_app_config
        >>> config = get_app_config()
        >>> if config.is_overvoltage_preprocessing_enabled():
        ...     print("OvER preprocessing is enabled")
    """
    global _app_config_instance

    if _app_config_instance is None:
        _app_config_instance = AppConfig()

    return _app_config_instance