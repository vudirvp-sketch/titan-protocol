#!/usr/bin/env python3
"""
TITAN FUSE Protocol - Config Migration Script
Migrates configuration from v3.2.0 to v3.2.1

Usage:
    python scripts/migrate_config_v320_to_v321.py [--dry-run]
"""

import argparse
import json
import shutil
from pathlib import Path
from datetime import datetime
import yaml


def load_yaml(path: Path) -> dict:
    """Load YAML file."""
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def save_yaml(path: Path, data: dict, backup: bool = True) -> None:
    """Save YAML file with optional backup."""
    if backup and path.exists():
        backup_path = path.with_suffix(f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        shutil.copy(path, backup_path)
    
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def load_json(path: Path) -> dict:
    """Load JSON file."""
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict, backup: bool = True) -> None:
    """Save JSON file with optional backup."""
    if backup and path.exists():
        backup_path = path.with_suffix(f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        shutil.copy(path, backup_path)
    
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def migrate_config_yaml(repo_root: Path, dry_run: bool = False) -> dict:
    """
    Migrate config.yaml from v3.2.0 to v3.2.1.
    
    Adds:
    - mode section
    - intent_classifier section
    - anomaly_detection section
    - model_fallback section
    """
    config_path = repo_root / "config.yaml"
    config = load_yaml(config_path)
    
    changes = []
    
    # Add mode section
    if "mode" not in config:
        config["mode"] = {
            "current": "direct",
            "presets_dir": "presets/"
        }
        changes.append("Added 'mode' section")
    
    # Add intent_classifier section
    if "intent_classifier" not in config:
        config["intent_classifier"] = {
            "enabled": False,
            "method": "rule_based",
            "confidence_threshold": 0.7,
            "log_all": True
        }
        changes.append("Added 'intent_classifier' section")
    
    # Add anomaly_detection section
    if "anomaly_detection" not in config:
        config["anomaly_detection"] = {
            "enabled": False,
            "baseline_sessions": 10,
            "threshold_multiplier": 3,
            "action": "warn"
        }
        changes.append("Added 'anomaly_detection' section")
    
    # Add model_fallback section
    if "model_fallback" not in config:
        config["model_fallback"] = {
            "enabled": False,
            "chain": ["secondary-frontier", "local-high-end"],
            "degradation_mode": "reduced_capability"
        }
        changes.append("Added 'model_fallback' section")
    
    # Update protocol version in comments if present
    if "# Version: 3.2.0" in config_path.read_text() if config_path.exists() else False:
        changes.append("Note: Version comment should be updated to 3.2.1")
    
    if not dry_run and changes:
        save_yaml(config_path, config)
    
    return {"file": str(config_path), "changes": changes}


def migrate_session_json(repo_root: Path, dry_run: bool = False) -> dict:
    """
    Migrate sessions/current.json from v3.2.0 to v3.2.1.
    
    Adds:
    - mode fields
    - intent classification fields
    - extended gates
    - anomaly detection baseline fields
    """
    session_path = repo_root / "sessions" / "current.json"
    session = load_json(session_path)
    
    if not session:
        return {"file": str(session_path), "changes": ["No session file to migrate"]}
    
    changes = []
    
    # Update protocol version
    if session.get("protocol_version") == "3.2.0":
        session["protocol_version"] = "3.2.1"
        changes.append("Updated protocol_version to 3.2.1")
    
    # Add mode fields
    if "mode" not in session:
        session["mode"] = "direct"
        session["preset_name"] = None
        session["mode_config_source"] = "default"
        changes.append("Added mode fields")
    
    # Add intent classification fields
    if "intent_classification" not in session:
        session["intent_classification"] = None
        session["intent_confidence"] = 0.0
        session["intent_hash"] = None
        session["secondary_intents"] = []
        session["success_criteria"] = []
        session["domain_volatility"] = "medium"
        changes.append("Added intent classification fields")
    
    # Add extended gates
    gates = session.get("gates", {})
    extended_gates = ["GATE-INTENT", "GATE-PLAN", "GATE-SKILL", "GATE-SECURITY", "GATE-EXEC"]
    for gate_id in extended_gates:
        if gate_id not in gates:
            gates[gate_id] = {
                "gate_id": gate_id,
                "status": "PENDING",
                "timestamp": None,
                "details": {}
            }
            changes.append(f"Added {gate_id}")
    session["gates"] = gates
    
    # Add gate_intents_passed
    if "gate_intents_passed" not in session:
        session["gate_intents_passed"] = []
        changes.append("Added gate_intents_passed")
    
    # Add anomaly detection baseline fields
    if "baseline_p50_tokens" not in session:
        session["baseline_p50_tokens"] = 0.0
        session["baseline_p95_tokens"] = 0.0
        session["baseline_sessions_count"] = 0
        session["anomaly_detected"] = False
        changes.append("Added anomaly detection baseline fields")
    
    if not dry_run and changes:
        save_json(session_path, session)
    
    return {"file": str(session_path), "changes": changes}


def create_mode_config(repo_root: Path, dry_run: bool = False) -> dict:
    """
    Create MODE-CONFIG.yaml if it doesn't exist.
    """
    mode_config_path = repo_root / "MODE-CONFIG.yaml"
    
    if mode_config_path.exists():
        return {"file": str(mode_config_path), "changes": ["File already exists"]}
    
    mode_config = {
        "protocol_version": "3.2.1",
        "mode": "direct",
        "direct": {
            "description": "Standard phase pipeline without intent classification",
            "pipeline": "PHASE_-1 → PHASE_0 → PHASE_1 → PHASE_2 → PHASE_3 → PHASE_4 → PHASE_5",
            "backward_compatible": True,
            "features": {
                "intent_detection": False,
                "skill_auto_generation": False,
                "template_caching": False
            }
        },
        "auto": {
            "description": "Intent detection → planning → execution with verification",
            "pipeline": "TIER_-2 → PHASE_-1 → INTENT_CLASSIFICATION → DYNAMIC_PIPELINE",
            "features": {
                "intent_detection": True,
                "skill_auto_generation": False,
                "template_caching": False
            }
        },
        "fallback": {
            "mode": "direct"
        }
    }
    
    if not dry_run:
        save_yaml(mode_config_path, mode_config, backup=False)
    
    return {"file": str(mode_config_path), "changes": ["Created MODE-CONFIG.yaml"]}


def main():
    parser = argparse.ArgumentParser(description="Migrate TITAN FUSE config from v3.2.0 to v3.2.1")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root directory")
    args = parser.parse_args()
    
    print("=" * 60)
    print("TITAN FUSE Protocol - Config Migration v3.2.0 → v3.2.1")
    print("=" * 60)
    if args.dry_run:
        print("[DRY RUN - No changes will be applied]")
    print()
    
    results = []
    
    # Run migrations
    results.append(migrate_config_yaml(args.repo_root, args.dry_run))
    results.append(migrate_session_json(args.repo_root, args.dry_run))
    results.append(create_mode_config(args.repo_root, args.dry_run))
    
    # Print results
    for result in results:
        print(f"\n📄 {result['file']}")
        for change in result['changes']:
            print(f"   • {change}")
    
    print("\n" + "=" * 60)
    if args.dry_run:
        print("DRY RUN COMPLETE - No files were modified")
    else:
        print("MIGRATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
