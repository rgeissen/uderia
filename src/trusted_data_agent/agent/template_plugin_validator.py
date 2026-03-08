"""
Template Plugin Validator: Security and validation checks for template plugins.

This module provides validation for template plugins including:
- Manifest validation
- Template schema validation  
- Security scanning
- Permission checking
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger("template_validator")


class TemplatePluginValidator:
    """Validates template plugins for security and correctness."""
    
    # Patterns that might indicate malicious code
    SUSPICIOUS_PATTERNS = [
        r'exec\s*\(',
        r'eval\s*\(',
        r'__import__\s*\(',
        r'compile\s*\(',
        r'open\s*\([^)]*[\'"]w',  # File write operations
        r'subprocess\.',
        r'os\.system',
        r'os\.popen',
        r'__builtins__',
    ]
    
    # Required manifest fields
    REQUIRED_MANIFEST_FIELDS = [
        "name",
        "version",
        "template_id",
        "display_name",
        "author"
    ]
    
    # Required template fields  
    REQUIRED_TEMPLATE_FIELDS = [
        "template_id",
        "template_name",
        "template_type",
        "input_variables",
        "output_configuration",
        "strategy_template"
    ]
    
    # Valid permissions
    VALID_PERMISSIONS = [
        "database_access",
        "mcp_tools",
        "file_system",
        "network"
    ]
    
    def __init__(self):
        self.validation_errors: List[str] = []
        self.validation_warnings: List[str] = []
    
    def validate_plugin(self, plugin_path: Path) -> Tuple[bool, List[str], List[str]]:
        """
        Validate a complete plugin package.
        
        Args:
            plugin_path: Path to plugin directory
            
        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        self.validation_errors = []
        self.validation_warnings = []
        
        # Check manifest exists
        manifest_file = plugin_path / "manifest.json"
        if not manifest_file.exists():
            self.validation_errors.append("manifest.json not found")
            return False, self.validation_errors, self.validation_warnings
        
        # Load and validate manifest
        try:
            with open(manifest_file, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except Exception as e:
            self.validation_errors.append(f"Failed to parse manifest.json: {e}")
            return False, self.validation_errors, self.validation_warnings
        
        self._validate_manifest(manifest, plugin_path)
        
        # If manifest is invalid, stop here
        if self.validation_errors:
            return False, self.validation_errors, self.validation_warnings
        
        # Validate template file
        template_file_path = manifest.get("files", {}).get("template")
        if template_file_path:
            template_path = plugin_path / template_file_path
            if template_path.exists():
                self._validate_template_file(template_path)
            else:
                self.validation_errors.append(f"Template file not found: {template_file_path}")
        
        # Scan for security issues
        self._scan_security(plugin_path, manifest)
        
        is_valid = len(self.validation_errors) == 0
        return is_valid, self.validation_errors, self.validation_warnings
    
    def _validate_manifest(self, manifest: Dict[str, Any], plugin_path: Path):
        """Validate manifest structure and content."""
        
        # Check required fields
        for field in self.REQUIRED_MANIFEST_FIELDS:
            if field not in manifest:
                self.validation_errors.append(f"Missing required manifest field: {field}")
        
        # Validate version format
        version = manifest.get("version", "")
        if not re.match(r'^\d+\.\d+\.\d+$', version):
            self.validation_errors.append(f"Invalid version format: {version} (expected X.Y.Z)")
        
        # Validate template_id format
        template_id = manifest.get("template_id", "")
        if not re.match(r'^[a-z0-9_]+_v\d+$', template_id):
            self.validation_errors.append(
                f"Invalid template_id format: {template_id} (expected lowercase_with_underscores_v1)"
            )
        
        # Validate name format
        name = manifest.get("name", "")
        if not re.match(r'^[a-z0-9-]+$', name):
            self.validation_errors.append(
                f"Invalid name format: {name} (expected lowercase-with-hyphens)"
            )
        
        # Validate permissions
        permissions = manifest.get("permissions", [])
        for perm in permissions:
            if perm not in self.VALID_PERMISSIONS:
                self.validation_errors.append(f"Invalid permission: {perm}")
        
        # Check that declared files exist
        files = manifest.get("files", {})
        for file_type, file_path in files.items():
            if file_path:
                full_path = plugin_path / file_path
                if not full_path.exists():
                    self.validation_errors.append(f"Declared {file_type} file not found: {file_path}")
        
        # Validate compatibility versions
        compat = manifest.get("compatibility", {})
        if compat:
            min_ver = compat.get("min_app_version", "")
            max_ver = compat.get("max_app_version", "")
            if min_ver and not self._is_valid_version_constraint(min_ver):
                self.validation_warnings.append(f"Invalid min_app_version: {min_ver}")
            if max_ver and not self._is_valid_version_constraint(max_ver):
                self.validation_warnings.append(f"Invalid max_app_version: {max_ver}")
    
    def _validate_template_file(self, template_path: Path):
        """Validate template JSON structure."""
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template = json.load(f)
        except Exception as e:
            self.validation_errors.append(f"Failed to parse template file: {e}")
            return
        
        # Check required fields
        for field in self.REQUIRED_TEMPLATE_FIELDS:
            if field not in template:
                self.validation_errors.append(f"Missing required template field: {field}")
        
        # Validate strategy_template structure
        strategy = template.get("strategy_template", {})
        if not isinstance(strategy, dict):
            self.validation_errors.append("strategy_template must be an object")
            return
        
        if "phases" not in strategy:
            self.validation_errors.append("strategy_template must have 'phases' array")
        else:
            phases = strategy["phases"]
            if not isinstance(phases, list) or len(phases) == 0:
                self.validation_errors.append("strategy_template.phases must be a non-empty array")
    
    def _scan_security(self, plugin_path: Path, manifest: Dict[str, Any]):
        """Scan plugin files for potential security issues."""
        
        # Check if plugin requests dangerous permissions
        permissions = manifest.get("permissions", [])
        if "file_system" in permissions:
            self.validation_warnings.append(
                "Plugin requests file_system permission - ensure this is necessary"
            )
        if "network" in permissions:
            self.validation_warnings.append(
                "Plugin requests network permission - ensure this is necessary"
            )
        
        # Scan Python validator files for suspicious patterns
        validator_file = manifest.get("files", {}).get("validator")
        if validator_file:
            validator_path = plugin_path / validator_file
            if validator_path.exists():
                self._scan_python_file(validator_path)
        
        # Scan JavaScript UI files
        ui_script = manifest.get("files", {}).get("ui_script")
        if ui_script:
            script_path = plugin_path / ui_script
            if script_path.exists():
                self._scan_javascript_file(script_path)
    
    def _scan_python_file(self, file_path: Path):
        """Scan Python file for suspicious patterns."""
        try:
            content = file_path.read_text(encoding='utf-8')
            
            for pattern in self.SUSPICIOUS_PATTERNS:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    line_num = content[:match.start()].count('\n') + 1
                    self.validation_warnings.append(
                        f"Suspicious pattern in {file_path.name} line {line_num}: {match.group()}"
                    )
        except Exception as e:
            self.validation_warnings.append(f"Failed to scan {file_path.name}: {e}")
    
    def _scan_javascript_file(self, file_path: Path):
        """Scan JavaScript file for suspicious patterns."""
        try:
            content = file_path.read_text(encoding='utf-8')
            
            # JavaScript-specific patterns
            js_patterns = [
                r'eval\s*\(',
                r'Function\s*\(',
                r'localStorage\.',
                r'sessionStorage\.',
                r'document\.cookie',
            ]
            
            for pattern in js_patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    line_num = content[:match.start()].count('\n') + 1
                    self.validation_warnings.append(
                        f"Potentially unsafe in {file_path.name} line {line_num}: {match.group()}"
                    )
        except Exception as e:
            self.validation_warnings.append(f"Failed to scan {file_path.name}: {e}")
    
    def _is_valid_version_constraint(self, version: str) -> bool:
        """Check if version constraint is valid."""
        # Allow X.Y.Z, X.Y.x, X.x.x patterns
        return bool(re.match(r'^\d+\.\d+\.\d+$|^\d+\.\d+\.x$|^\d+\.x\.x$', version))


def validate_plugin_package(plugin_path: Path) -> Tuple[bool, List[str], List[str]]:
    """
    Convenience function to validate a plugin package.
    
    Args:
        plugin_path: Path to plugin directory
        
    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    validator = TemplatePluginValidator()
    return validator.validate_plugin(plugin_path)
